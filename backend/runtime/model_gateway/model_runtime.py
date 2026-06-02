from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import os
import time
import uuid
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, convert_to_messages
from langchain_openai import ChatOpenAI

try:
    from langchain_deepseek import ChatDeepSeek
except ImportError:  # pragma: no cover - optional dependency at runtime
    ChatDeepSeek = None

from bootstrap.settings import AppSettingsService
from config import LLM_PROVIDER_DEFAULTS
from harness.runtime.prompt_segment_plan import build_prompt_segment_plan
from runtime.prompt_accounting import (
    CanonicalPromptSerializer,
    ModelTokenUsageRecord,
    PromptAccountingLedger,
    PromptCacheBreakRecord,
    PromptCacheBreakDetector,
    PromptCachePlanner,
    PromptStabilityReporter,
    extract_provider_usage,
)
from runtime.tool_runtime.tool_call_policy import ToolCallBindingOptions

from .model_request import ModelRequestBuilder

if TYPE_CHECKING:
    from agent_system.a2a.models import AgentDefinition
    from agent_system.models.model_profile_models import ResolvedModelSpec

logger = logging.getLogger(__name__)


class _DeepSeekReasoningCompatChatModel(ChatDeepSeek):
    """Preserve DeepSeek native thinking payload across tool-call round trips.

    DeepSeek thinking mode requires the previous assistant tool-call message to
    replay its `reasoning_content` on the next request. LangChain stores that
    field in `AIMessage.additional_kwargs`, but the default OpenAI-compatible
    message serializer drops it for chat/completions payloads. This is protocol
    state for DeepSeek API replay, not a public progress note or generated
    application-side chain of thought.
    """

    def _get_request_payload(
        self,
        input_: Any,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, list):
            return payload
        try:
            original_messages = convert_to_messages(input_)
        except Exception:
            return payload

        raw_input_messages = list(input_) if isinstance(input_, list) else []
        for index, (original_message, serialized_message) in enumerate(zip(original_messages, raw_messages)):
            if not isinstance(original_message, AIMessage):
                continue
            if not isinstance(serialized_message, dict):
                continue
            if str(serialized_message.get("role", "") or "").strip() != "assistant":
                continue

            raw_message = raw_input_messages[index] if index < len(raw_input_messages) else None
            reasoning_content = _deepseek_reasoning_content_from_message(original_message, raw_message)
            if reasoning_content:
                serialized_message["reasoning_content"] = reasoning_content

        return payload


def stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content or "")


def _deepseek_reasoning_content_from_message(message: Any, raw_message: Any = None) -> str:
    candidates: list[Any] = []
    additional_kwargs = getattr(message, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        candidates.append(additional_kwargs.get("reasoning_content"))
    if isinstance(raw_message, dict):
        candidates.append(raw_message.get("reasoning_content"))
        raw_additional_kwargs = raw_message.get("additional_kwargs")
        if isinstance(raw_additional_kwargs, dict):
            candidates.append(raw_additional_kwargs.get("reasoning_content"))
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


@dataclass(frozen=True, slots=True)
class ModelSpec:
    provider: str
    model: str
    api_key: str | None
    base_url: str
    max_output_tokens: int | None = None
    timeout_seconds: float | None = None
    long_output_timeout_seconds: float | None = None
    max_retries: int | None = None
    temperature: float | None = None
    thinking_mode: str | None = None
    reasoning_effort: str | None = None
    stream_policy: dict[str, Any] | None = None
    diagnostics: dict[str, Any] | None = None


class ModelRuntimeError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        provider: str,
        model: str,
        detail: str,
        retryable: bool,
        user_message: str,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.provider = provider
        self.model = model
        self.detail = detail
        self.retryable = retryable
        self.user_message = user_message


class RuntimeConversationAgent:
    def __init__(
        self,
        runtime: "ModelRuntime",
        *,
        system_prompt: str,
        tools: list[Any],
        agent_definition: AgentDefinition,
    ) -> None:
        self.runtime = runtime
        self.system_prompt = system_prompt
        self.tools = tools
        self.agent_definition = agent_definition

    async def astream(self, payload: dict[str, Any], *, stream_mode: list[str]):
        async for item in self.runtime.astream_conversation(
            system_prompt=self.system_prompt,
            tools=self.tools,
            agent_definition=self.agent_definition,
            payload=payload,
            stream_mode=stream_mode,
            model_spec=None,
        ):
            yield item


class ModelRuntime:
    def __init__(
        self,
        settings_service: AppSettingsService,
        *,
        prompt_accounting_ledger: PromptAccountingLedger | None = None,
    ) -> None:
        self.settings_service = settings_service
        self._chat_model_pool: dict[str, Any] = {}
        self.prompt_accounting_ledger = prompt_accounting_ledger
        self._prompt_serializer = CanonicalPromptSerializer()
        self._prompt_cache_planner = PromptCachePlanner()
        self._prompt_cache_break_detector = PromptCacheBreakDetector()
        self._prompt_stability_reporter = PromptStabilityReporter()
        self._model_request_builder = ModelRequestBuilder()

    @property
    def request_timeout_seconds(self) -> float:
        static = self.settings_service.static
        return max(0.01, float(getattr(static, "llm_timeout_seconds", 45.0) or 45.0))

    @property
    def max_retries(self) -> int:
        static = self.settings_service.static
        value = getattr(static, "llm_max_retries", 2)
        if value in {None, ""}:
            value = 2
        return max(0, int(value))

    @property
    def max_output_tokens(self) -> int:
        static = self.settings_service.static
        return max(1, int(getattr(static, "llm_max_output_tokens", 65536) or 65536))

    @property
    def long_output_timeout_seconds(self) -> float:
        static = self.settings_service.static
        return max(
            self.request_timeout_seconds,
            float(getattr(static, "llm_long_output_timeout_seconds", 180.0) or 180.0),
        )

    @property
    def model_call_timeout_seconds(self) -> float:
        if self.max_output_tokens >= 16384:
            return self.long_output_timeout_seconds
        return self.request_timeout_seconds

    @property
    def thinking_mode(self) -> str:
        static = self.settings_service.static
        return str(getattr(static, "llm_thinking_mode", "disabled") or "disabled").strip().lower()

    @property
    def reasoning_effort(self) -> str:
        static = self.settings_service.static
        return str(getattr(static, "llm_reasoning_effort", "auto") or "auto").strip().lower()

    def build_chat_model(self):
        return self._get_chat_model_for_spec(self._candidate_specs()[0])

    def create_conversation_agent(
        self,
        *,
        system_prompt: str,
        tools: list[Any],
        agent_definition: AgentDefinition,
    ):
        return RuntimeConversationAgent(
            self,
            system_prompt=system_prompt,
            tools=tools,
            agent_definition=agent_definition,
        )

    def attach_prompt_accounting_ledger(self, ledger: PromptAccountingLedger | None) -> None:
        self.prompt_accounting_ledger = ledger

    async def invoke_messages(
        self,
        messages: list[dict[str, str]],
        *,
        model_spec: ModelSpec | "ResolvedModelSpec" | None = None,
        accounting_context: dict[str, Any] | None = None,
    ) -> Any:
        last_error: ModelRuntimeError | None = None
        candidates = self._candidate_specs(model_spec=model_spec)
        for spec_index, spec in enumerate(candidates):
            for attempt in range(1, self._max_retries_for_spec(spec) + 2):
                model = self._get_chat_model_for_spec(spec)
                accounting = self._begin_prompt_accounting(
                    messages,
                    tools=None,
                    spec=spec,
                    accounting_context=accounting_context,
                    attempt=attempt,
                    call_kind="invoke_messages",
                )
                try:
                    response = await asyncio.wait_for(
                        model.ainvoke(messages),
                        timeout=self._model_call_timeout_seconds_for_spec(spec),
                    )
                    self._finish_prompt_accounting(accounting, response=response)
                    return response
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    last_error = self._map_error(exc, spec)
                    await self._invalidate_chat_model_for_spec(spec)
                    if attempt <= self._max_retries_for_spec(spec) and last_error.retryable:
                        logger.warning(
                            "Retrying model invoke after %s (%s/%s): %s",
                            last_error.code,
                            attempt,
                            self._max_retries_for_spec(spec),
                            last_error.detail,
                        )
                        await asyncio.sleep(min(0.5, 0.1 * attempt))
                        continue
                    break
            if last_error is None:
                continue
            if spec_index < len(candidates) - 1:
                self._record_model_candidate_switch(
                    accounting_context=accounting_context,
                    from_spec=spec,
                    to_spec=candidates[spec_index + 1],
                    attempt=self._max_retries_for_spec(spec) + 1,
                    call_kind="invoke_messages",
                    error=last_error,
                )
                logger.warning(
                    "Switching model candidate after %s on %s/%s: %s",
                    last_error.code,
                    spec.provider,
                    spec.model,
                    _compact_error_detail(last_error.detail),
                )
                continue
            raise last_error
        raise RuntimeError("No model candidates available")

    async def invoke_messages_with_tools(
        self,
        messages: list[Any],
        tools: list[Any],
        *,
        model_spec: ModelSpec | "ResolvedModelSpec" | None = None,
        tool_call_options: ToolCallBindingOptions | dict[str, Any] | None = None,
        accounting_context: dict[str, Any] | None = None,
    ) -> Any:
        last_error: ModelRuntimeError | None = None
        candidates = self._candidate_specs(model_spec=model_spec)
        for spec_index, spec in enumerate(candidates):
            for attempt in range(1, self._max_retries_for_spec(spec) + 2):
                model = self._get_chat_model_for_spec(spec)
                accounting = self._begin_prompt_accounting(
                    messages,
                    tools=tools,
                    spec=spec,
                    accounting_context=accounting_context,
                    attempt=attempt,
                    call_kind="invoke_messages_with_tools",
                    tool_call_options=tool_call_options,
                )
                try:
                    bound_model = (
                        _bind_tools_with_options(
                            model,
                            tools,
                            tool_call_options=tool_call_options,
                            spec=spec,
                            thinking_mode=self._thinking_mode_for_spec(spec),
                        )
                        if tools
                        else model
                    )
                    response = await asyncio.wait_for(
                        bound_model.ainvoke(messages),
                        timeout=self._model_call_timeout_seconds_for_spec(spec),
                    )
                    self._finish_prompt_accounting(accounting, response=response)
                    return response
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    last_error = self._map_error(exc, spec)
                    await self._invalidate_chat_model_for_spec(spec)
                    if attempt <= self._max_retries_for_spec(spec) and last_error.retryable:
                        logger.warning(
                            "Retrying tool-enabled model invoke after %s (%s/%s): %s",
                            last_error.code,
                            attempt,
                            self._max_retries_for_spec(spec),
                            last_error.detail,
                        )
                        await asyncio.sleep(min(0.5, 0.1 * attempt))
                        continue
                    break
            if last_error is None:
                continue
            if spec_index < len(candidates) - 1:
                self._record_model_candidate_switch(
                    accounting_context=accounting_context,
                    from_spec=spec,
                    to_spec=candidates[spec_index + 1],
                    attempt=self._max_retries_for_spec(spec) + 1,
                    call_kind="invoke_messages_with_tools",
                    error=last_error,
                )
                logger.warning(
                    "Switching tool-enabled model candidate after %s on %s/%s: %s",
                    last_error.code,
                    spec.provider,
                    spec.model,
                    _compact_error_detail(last_error.detail),
                )
                continue
            raise last_error
        raise RuntimeError("No model candidates available")

    async def astream_messages(
        self,
        messages: list[Any],
        *,
        model_spec: ModelSpec | "ResolvedModelSpec" | None = None,
        accounting_context: dict[str, Any] | None = None,
    ):
        last_error: ModelRuntimeError | None = None
        candidates = self._candidate_specs(model_spec=model_spec)
        for spec_index, spec in enumerate(candidates):
            for attempt in range(1, self._max_retries_for_spec(spec) + 2):
                emitted = False
                model = self._get_chat_model_for_spec(spec)
                accounting = self._begin_prompt_accounting(
                    messages,
                    tools=None,
                    spec=spec,
                    accounting_context=accounting_context,
                    attempt=attempt,
                    call_kind="astream_messages",
                )
                aggregated_chunk = None
                try:
                    stream = model.astream(messages)
                    async for chunk in self._iterate_with_timeout(stream, spec=spec):
                        emitted = True
                        try:
                            aggregated_chunk = chunk if aggregated_chunk is None else aggregated_chunk + chunk
                        except Exception:
                            aggregated_chunk = chunk
                        yield chunk
                    self._finish_prompt_accounting(accounting, response=aggregated_chunk)
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    last_error = self._map_error(exc, spec)
                    await self._invalidate_chat_model_for_spec(spec)
                    if emitted:
                        raise last_error from exc
                    if attempt <= self._max_retries_for_spec(spec) and last_error.retryable:
                        logger.warning(
                            "Retrying model stream after %s (%s/%s): %s",
                            last_error.code,
                            attempt,
                            self._max_retries_for_spec(spec),
                            last_error.detail,
                        )
                        await asyncio.sleep(min(0.5, 0.1 * attempt))
                        continue
                    break
            if last_error is None:
                continue
            if spec_index < len(candidates) - 1:
                self._record_model_candidate_switch(
                    accounting_context=accounting_context,
                    from_spec=spec,
                    to_spec=candidates[spec_index + 1],
                    attempt=self._max_retries_for_spec(spec) + 1,
                    call_kind="astream_messages",
                    error=last_error,
                )
                logger.warning(
                    "Switching stream model candidate after %s on %s/%s: %s",
                    last_error.code,
                    spec.provider,
                    spec.model,
                    _compact_error_detail(last_error.detail),
                )
                continue
            raise last_error
        raise RuntimeError("No model candidates available")

    async def astream_messages_with_tools(
        self,
        messages: list[Any],
        tools: list[Any],
        *,
        model_spec: ModelSpec | "ResolvedModelSpec" | None = None,
        tool_call_options: ToolCallBindingOptions | dict[str, Any] | None = None,
        accounting_context: dict[str, Any] | None = None,
    ):
        last_error: ModelRuntimeError | None = None
        candidates = self._candidate_specs(model_spec=model_spec)
        for spec_index, spec in enumerate(candidates):
            for attempt in range(1, self._max_retries_for_spec(spec) + 2):
                emitted = False
                model = self._get_chat_model_for_spec(spec)
                accounting = self._begin_prompt_accounting(
                    messages,
                    tools=tools,
                    spec=spec,
                    accounting_context=accounting_context,
                    attempt=attempt,
                    call_kind="astream_messages_with_tools",
                    tool_call_options=tool_call_options,
                )
                aggregated_chunk = None
                try:
                    bound_model = (
                        _bind_tools_with_options(
                            model,
                            tools,
                            tool_call_options=tool_call_options,
                            spec=spec,
                            thinking_mode=self._thinking_mode_for_spec(spec),
                        )
                        if tools
                        else model
                    )
                    stream = bound_model.astream(messages)
                    async for chunk in self._iterate_with_timeout(stream, spec=spec):
                        emitted = True
                        try:
                            aggregated_chunk = chunk if aggregated_chunk is None else aggregated_chunk + chunk
                        except Exception:
                            aggregated_chunk = chunk
                        yield chunk
                    self._finish_prompt_accounting(accounting, response=aggregated_chunk)
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    last_error = self._map_error(exc, spec)
                    await self._invalidate_chat_model_for_spec(spec)
                    if emitted:
                        raise last_error from exc
                    if attempt <= self._max_retries_for_spec(spec) and last_error.retryable:
                        logger.warning(
                            "Retrying tool-enabled model stream after %s (%s/%s): %s",
                            last_error.code,
                            attempt,
                            self._max_retries_for_spec(spec),
                            last_error.detail,
                        )
                        await asyncio.sleep(min(0.5, 0.1 * attempt))
                        continue
                    break
            if last_error is None:
                continue
            if spec_index < len(candidates) - 1:
                self._record_model_candidate_switch(
                    accounting_context=accounting_context,
                    from_spec=spec,
                    to_spec=candidates[spec_index + 1],
                    attempt=self._max_retries_for_spec(spec) + 1,
                    call_kind="astream_messages_with_tools",
                    error=last_error,
                )
                logger.warning(
                    "Switching tool-enabled stream model candidate after %s on %s/%s: %s",
                    last_error.code,
                    spec.provider,
                    spec.model,
                    _compact_error_detail(last_error.detail),
                )
                continue
            raise last_error
        raise RuntimeError("No model candidates available")

    async def astream_conversation(
        self,
        *,
        system_prompt: str,
        tools: list[Any],
        agent_definition: AgentDefinition,
        payload: dict[str, Any],
        stream_mode: list[str],
        model_spec: ModelSpec | "ResolvedModelSpec" | None = None,
        accounting_context: dict[str, Any] | None = None,
    ):
        last_error: ModelRuntimeError | None = None
        candidates = self._candidate_specs(model_spec=model_spec)
        for spec_index, spec in enumerate(candidates):
            for attempt in range(1, self._max_retries_for_spec(spec) + 2):
                emitted = False
                model = self._get_chat_model_for_spec(spec)
                accounting_messages = [
                    {"role": "system", "content": system_prompt},
                    *list(dict(payload or {}).get("messages") or []),
                ]
                accounting = self._begin_prompt_accounting(
                    accounting_messages,
                    tools=tools,
                    spec=spec,
                    accounting_context=accounting_context,
                    attempt=attempt,
                    call_kind="astream_conversation",
                )
                last_item = None
                agent = self._create_raw_agent(
                    system_prompt=system_prompt,
                    tools=tools,
                    agent_definition=agent_definition,
                    model=model,
                )
                try:
                    stream = agent.astream(payload, stream_mode=stream_mode)
                    async for item in self._iterate_with_timeout(stream, spec=spec):
                        emitted = True
                        last_item = item
                        yield item
                    self._finish_prompt_accounting(accounting, response=last_item)
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    last_error = self._map_error(exc, spec)
                    await self._invalidate_chat_model_for_spec(spec)
                    if emitted:
                        raise last_error from exc
                    if attempt <= self._max_retries_for_spec(spec) and last_error.retryable:
                        logger.warning(
                            "Retrying model stream after %s (%s/%s): %s",
                            last_error.code,
                            attempt,
                            self._max_retries_for_spec(spec),
                            last_error.detail,
                        )
                        await asyncio.sleep(min(0.5, 0.1 * attempt))
                        continue
                    break
            if last_error is None:
                continue
            if spec_index < len(candidates) - 1:
                self._record_model_candidate_switch(
                    accounting_context=accounting_context,
                    from_spec=spec,
                    to_spec=candidates[spec_index + 1],
                    attempt=self._max_retries_for_spec(spec) + 1,
                    call_kind="astream_conversation",
                    error=last_error,
                )
                logger.warning(
                    "Switching stream model candidate after %s on %s/%s: %s",
                    last_error.code,
                    spec.provider,
                    spec.model,
                    _compact_error_detail(last_error.detail),
                )
                continue
            raise last_error
        raise RuntimeError("No model candidates available")

    async def generate_title(self, first_user_message: str) -> str:
        prompt = (
            "请根据用户的第一条消息生成一个中文会话标题。"
            "要求不超过 10 个汉字，不要带引号，不要解释。"
        )
        try:
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": first_user_message},
            ]
            response = await self.invoke_messages(
                messages,
                accounting_context=_utility_accounting_context(
                    source="model_runtime.generate_title",
                    messages=messages,
                    purpose="utility.generate_title",
                ),
            )
            title = stringify_content(getattr(response, "content", "")).strip()
            return title[:10] or "新会话"
        except ModelRuntimeError:
            return (first_user_message.strip() or "新会话")[:10]
        except Exception:
            return (first_user_message.strip() or "新会话")[:10]

    async def summarize_history(self, messages: list[dict[str, Any]]) -> str:
        prompt = (
            "你是一名上下文压缩员。"
            "你只负责把已有运行历史整理成后续模型可以继续工作的恢复点。"
            "你不能引入新事实，不能搜索，不能修改文件，不能替主 Agent 继续执行任务。"
            "请输出中文 handoff summary，保留用户目标、当前约束、已验证事实、产物引用、未解决问题、最近纠错和下一步恢复提示。"
            "丢弃重复寒暄、旧工具原文、大段 JSON/表格原文、过期状态和已被后续消息否定的信息。"
            "控制在 900 字以内，不要解释压缩过程。"
        )
        transcript_lines: list[str] = []
        for item in messages:
            role = item.get("role", "assistant")
            content = str(item.get("content", "") or "")
            if content:
                transcript_lines.append(f"{role}: {content}")
        transcript = "\n".join(transcript_lines)

        try:
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": transcript},
            ]
            response = await self.invoke_messages(
                messages,
                accounting_context=_utility_accounting_context(
                    source="model_runtime.summarize_history",
                    messages=messages,
                    purpose="utility.summarize_history",
                ),
            )
            summary = stringify_content(getattr(response, "content", "")).strip()
            return summary[:500]
        except ModelRuntimeError:
            return transcript[:500]
        except Exception:
            return transcript[:500]

    def _candidate_specs(self, *, model_spec: ModelSpec | "ResolvedModelSpec" | None = None) -> list[ModelSpec]:
        if model_spec is not None:
            return [self._model_spec_from_override(model_spec)]
        settings = self.settings_service.static
        primary = ModelSpec(
            provider=settings.llm_provider,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
        specs = [primary]
        fallback_provider = getattr(settings, "llm_fallback_provider", None)
        fallback_model = getattr(settings, "llm_fallback_model", None)
        fallback_api_key = getattr(settings, "llm_fallback_api_key", None)
        fallback_base_url = getattr(settings, "llm_fallback_base_url", None)
        if fallback_provider and fallback_model and fallback_base_url:
            specs.append(
                ModelSpec(
                    provider=fallback_provider,
                    model=fallback_model,
                    api_key=fallback_api_key,
                    base_url=fallback_base_url,
                )
            )

        deduped: list[ModelSpec] = []
        seen: set[tuple[str, str, str | None, str]] = set()
        for spec in specs:
            key = (spec.provider, spec.model, spec.api_key, spec.base_url)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(spec)
        return deduped

    def _build_chat_model_for_spec(self, spec: ModelSpec):
        timeout_seconds = self._model_call_timeout_seconds_for_spec(spec)
        max_output_tokens = self._max_output_tokens_for_spec(spec)
        temperature = self._temperature_for_spec(spec)
        if spec.provider == "deepseek":
            self._validate_deepseek_mode_for_spec(spec)
            if ChatDeepSeek is None:
                raise RuntimeError("langchain-deepseek is not installed")
            if not spec.api_key:
                raise RuntimeError("Missing API key for provider deepseek")
            thinking_enabled = self._thinking_enabled_for_spec(spec)
            extra_body: dict[str, Any] = {
                "thinking": {
                    "type": "enabled" if thinking_enabled else "disabled"
                }
            }
            model_kwargs: dict[str, Any] = {
                "model": spec.model,
                "api_key": spec.api_key,
                "base_url": spec.base_url,
                "timeout": timeout_seconds,
                "max_retries": 0,
                "max_tokens": max_output_tokens,
                "extra_body": extra_body,
            }
            if thinking_enabled:
                reasoning_effort = self._reasoning_effort_for_spec(spec)
                if reasoning_effort:
                    model_kwargs["reasoning_effort"] = reasoning_effort
            else:
                model_kwargs["temperature"] = temperature
            return _DeepSeekReasoningCompatChatModel(**model_kwargs)

        if not spec.api_key:
            raise RuntimeError(f"Missing API key for provider {spec.provider}")

        model_kwargs: dict[str, Any] = {
            "model": spec.model,
            "api_key": spec.api_key,
            "base_url": spec.base_url,
            "temperature": temperature,
            "timeout": timeout_seconds,
            "max_retries": 0,
            "max_completion_tokens": max_output_tokens,
        }
        reasoning_effort = self._chat_openai_reasoning_effort_for_spec(spec)
        if reasoning_effort:
            model_kwargs["reasoning_effort"] = reasoning_effort
        return ChatOpenAI(**model_kwargs)

    def _get_chat_model_for_spec(self, spec: ModelSpec):
        key = self._chat_model_pool_key(spec)
        model = self._chat_model_pool.get(key)
        if model is None:
            model = self._build_chat_model_for_spec(spec)
            self._chat_model_pool[key] = model
        return model

    async def _invalidate_chat_model_for_spec(self, spec: ModelSpec) -> None:
        key = self._chat_model_pool_key(spec)
        model = self._chat_model_pool.pop(key, None)
        if model is not None:
            await self._aclose_chat_model(model)

    async def close(self) -> None:
        models = list(self._chat_model_pool.values())
        self._chat_model_pool.clear()
        for model in models:
            await self._aclose_chat_model(model)

    def _chat_model_pool_key(self, spec: ModelSpec) -> str:
        api_key = str(spec.api_key or "")
        api_key_fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16] if api_key else ""
        return "|".join(
            [
                str(spec.provider or ""),
                str(spec.model or ""),
                str(spec.base_url or ""),
                api_key_fingerprint,
                str(self._max_output_tokens_for_spec(spec)),
                str(self._model_call_timeout_seconds_for_spec(spec)),
                str(self._temperature_for_spec(spec)),
                str(self._thinking_mode_for_spec(spec)),
                str(self._reasoning_effort_for_spec(spec)),
            ]
        )

    def _create_raw_agent(
        self,
        *,
        system_prompt: str,
        tools: list[Any],
        agent_definition: AgentDefinition,
        model: Any,
    ):
        return create_agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
        )

    async def _aclose_chat_model(self, model: Any) -> None:
        close_targets = []
        for attr_name in ("root_async_client", "root_client", "http_async_client", "http_client"):
            target = getattr(model, attr_name, None)
            if target is None:
                continue
            if any(existing is target for existing in close_targets):
                continue
            close_targets.append(target)

        for target in close_targets:
            close_method = getattr(target, "close", None)
            if not callable(close_method):
                continue
            try:
                result = close_method()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.debug("Failed to close model runtime client", exc_info=True)

    async def _iterate_with_timeout(self, stream, *, spec: ModelSpec | None = None):
        while True:
            try:
                item = await asyncio.wait_for(
                    stream.__anext__(),
                    timeout=self._model_call_timeout_seconds_for_spec(spec) if spec is not None else self.model_call_timeout_seconds,
                )
            except StopAsyncIteration:
                return
            yield item

    def _model_spec_from_override(self, override: ModelSpec | "ResolvedModelSpec" | dict[str, Any]) -> ModelSpec:
        if isinstance(override, ModelSpec):
            return override
        if isinstance(override, dict):
            settings = self.settings_service.static
            system_provider = str(getattr(settings, "llm_provider", "") or "").strip().lower()
            provider = str(override.get("provider") or system_provider).strip().lower()
            provider_defaults = dict(LLM_PROVIDER_DEFAULTS.get(provider) or {})
            system_model = str(getattr(settings, "llm_model", "") or "").strip()
            system_base_url = str(getattr(settings, "llm_base_url", "") or "").strip()
            model = str(
                override.get("model")
                or (system_model if provider == system_provider else "")
                or provider_defaults.get("model")
                or ""
            ).strip()
            base_url = str(
                override.get("base_url")
                or (system_base_url if provider == system_provider else "")
                or provider_defaults.get("base_url")
                or ""
            ).strip()
            credential_ref = str(override.get("credential_ref") or "").strip()
            api_key = override.get("api_key")
            if not api_key:
                api_key = self._api_key_from_credential_ref(credential_ref=credential_ref, provider=provider)
            return ModelSpec(
                provider=provider,
                model=model,
                api_key=str(api_key).strip() if api_key else None,
                base_url=base_url,
                max_output_tokens=_optional_int(override.get("max_output_tokens")),
                timeout_seconds=_optional_float(override.get("timeout_seconds")),
                long_output_timeout_seconds=_optional_float(override.get("long_output_timeout_seconds")),
                max_retries=_optional_int(override.get("max_retries")),
                temperature=_optional_float(override.get("temperature")),
                thinking_mode=str(override.get("thinking_mode") or "").strip() or None,
                reasoning_effort=str(override.get("reasoning_effort") or "").strip() or None,
                stream_policy=dict(override.get("stream_policy") or {}),
                diagnostics=dict(override.get("diagnostics") or {}),
            )
        return ModelSpec(
            provider=str(getattr(override, "provider", "") or "").strip(),
            model=str(getattr(override, "model", "") or "").strip(),
            api_key=getattr(override, "api_key", None),
            base_url=str(getattr(override, "base_url", "") or "").strip(),
            max_output_tokens=getattr(override, "max_output_tokens", None),
            timeout_seconds=getattr(override, "timeout_seconds", None),
            long_output_timeout_seconds=getattr(override, "long_output_timeout_seconds", None),
            max_retries=getattr(override, "max_retries", None),
            temperature=getattr(override, "temperature", None),
            thinking_mode=getattr(override, "thinking_mode", None),
            reasoning_effort=getattr(override, "reasoning_effort", None),
            stream_policy=dict(getattr(override, "stream_policy", {}) or {}),
            diagnostics=dict(getattr(override, "diagnostics", {}) or {}),
        )

    def _api_key_from_credential_ref(self, *, credential_ref: str, provider: str) -> str | None:
        settings = self.settings_service.static
        normalized_provider = str(provider or "").strip().lower()
        ref = str(credential_ref or "").strip()
        if not normalized_provider:
            return None
        if ref in {"", f"provider:{normalized_provider}:primary"}:
            if str(getattr(settings, "llm_provider", "") or "").strip().lower() == normalized_provider:
                return getattr(settings, "llm_api_key", None)
            return _first_configured_env_for_provider(normalized_provider)
        if ref == f"provider:{normalized_provider}:fallback":
            if str(getattr(settings, "llm_fallback_provider", "") or "").strip().lower() == normalized_provider:
                return getattr(settings, "llm_fallback_api_key", None)
            return _first_configured_env_for_provider(normalized_provider)
        if ref == "system:llm:primary":
            return getattr(settings, "llm_api_key", None)
        if ref == "system:llm:fallback":
            return getattr(settings, "llm_fallback_api_key", None)
        if ref.startswith("provider:"):
            parts = ref.split(":")
            ref_provider = str(parts[1] if len(parts) >= 2 else normalized_provider).strip().lower()
            ref_slot = str(parts[2] if len(parts) >= 3 else "primary").strip().lower()
            if ref_slot == "fallback" and str(getattr(settings, "llm_fallback_provider", "") or "").strip().lower() == ref_provider:
                return getattr(settings, "llm_fallback_api_key", None)
            if str(getattr(settings, "llm_provider", "") or "").strip().lower() == ref_provider:
                return getattr(settings, "llm_api_key", None)
            return _first_configured_env_for_provider(ref_provider)
        if ref.startswith("env:"):
            env_name = ref.removeprefix("env:").strip()
            allowed = set(LLM_PROVIDER_DEFAULTS.get(normalized_provider, {}).get("credential_envs") or ())
            return os.getenv(env_name) if env_name in allowed else None
        return None

    def _begin_prompt_accounting(
        self,
        messages: list[Any],
        *,
        tools: list[Any] | None,
        spec: ModelSpec,
        accounting_context: dict[str, Any] | None,
        attempt: int,
        call_kind: str,
        tool_call_options: ToolCallBindingOptions | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ledger = self.prompt_accounting_ledger
        if ledger is None:
            return {}
        context = dict(accounting_context or {})
        context, unplanned_reason = _normalize_accounting_context_for_prompt_plan(
            context,
            call_kind=call_kind,
            message_count=len(list(messages or [])),
            tool_count=len(list(tools or [])),
        )
        request_id = str(context.get("request_id") or "").strip()
        if not request_id:
            request_id = f"modelreq:{uuid.uuid4().hex}"
        if attempt > 1:
            request_id = f"{request_id}:attempt:{attempt}"
        raw_run_id = str(context.get("run_id") or context.get("task_run_id") or "").strip()
        task_run_id = _formal_task_run_id(context.get("task_run_id") or raw_run_id)
        run_id = raw_run_id or task_run_id
        session_id = str(context.get("session_id") or "")
        created_at = time.time()
        metadata = {
            "source": str(context.get("source") or call_kind),
            "call_kind": call_kind,
            "attempt": attempt,
            "packet_ref": str(context.get("packet_ref") or ""),
            "turn_id": str(context.get("turn_id") or ""),
            "invocation_index": context.get("invocation_index"),
            "call_purpose": str(context.get("call_purpose") or ""),
            "cache_metric_scope": str(context.get("cache_metric_scope") or "agent_runtime"),
            "prompt_manifest": dict(context.get("prompt_manifest") or {}),
            "cache_relevant_params": self._cache_relevant_params_for_spec(
                spec,
                call_kind=call_kind,
                tool_count=len(list(tools or [])),
                tool_call_options=tool_call_options,
            ),
        }
        segment_plan = dict(context.get("segment_plan") or {})
        try:
            model_request = self._model_request_builder.build(
                request_id=request_id,
                messages=list(messages or []),
                tools=list(tools or []),
                provider=spec.provider,
                model=spec.model,
                base_url=spec.base_url,
                segment_plan=segment_plan,
                metadata=metadata,
            )
            cache_policy = model_request.cache_policy
            segment_map = self._prompt_serializer.build_segment_map(
                request_id=request_id,
                messages=list(messages or []),
                tools=list(tools or []),
                provider=spec.provider,
                model=spec.model,
                run_id=run_id,
                task_run_id=task_run_id,
                session_id=session_id,
                created_at=created_at,
                metadata={
                    **metadata,
                    "model_request_ref": model_request.request_id,
                    "provider_cache_policy": cache_policy.to_dict(),
                    "stable_prefix_hash": model_request.stable_prefix_hash,
                    "provider_global_prefix_hash": model_request.provider_global_prefix_hash,
                    "session_prefix_hash": model_request.session_prefix_hash,
                    "task_prefix_hash": model_request.task_prefix_hash,
                },
                segment_plan=segment_plan,
                model_request=model_request,
            )
            ledger.record_segment_map(segment_map)
            prediction = ModelTokenUsageRecord(
                usage_id=f"tokuse:{request_id}:local_prediction",
                request_id=request_id,
                run_id=run_id,
                task_run_id=task_run_id,
                session_id=session_id,
                provider=spec.provider,
                model=spec.model,
                source="local_prediction",
                prompt_tokens=segment_map.predicted_prompt_tokens,
                total_tokens=segment_map.predicted_prompt_tokens,
                created_at=created_at,
                diagnostics={
                    "segment_count": len(segment_map.segments),
                    "canonical_hash": segment_map.canonical_hash,
                    "model_request_canonical_hash": model_request.canonical_hash,
                    "stable_prefix_hash": model_request.stable_prefix_hash,
                    "provider_global_prefix_hash": model_request.provider_global_prefix_hash,
                    "session_prefix_hash": model_request.session_prefix_hash,
                    "task_prefix_hash": model_request.task_prefix_hash,
                    "provider_cache_policy": cache_policy.to_dict(),
                    **metadata,
                },
            )
            ledger.record_token_usage(prediction)
            cache_record = self._prompt_cache_planner.plan(
                segment_map,
                provider=spec.provider,
                model=spec.model,
                created_at=created_at,
            )
            model_request_diagnostics = dict(model_request.diagnostics or {})
            prefix_key_tier = str(dict(cache_record.diagnostics or {}).get("prefix_key_tier") or "")
            expected_prefix_hash = _model_request_prefix_hash_for_tier(
                model_request,
                prefix_key_tier=prefix_key_tier,
            )
            prefix_hash_matches_model_request = bool(cache_record.prefix_hash) and cache_record.prefix_hash == expected_prefix_hash
            cache_record_diagnostics = {
                **dict(cache_record.diagnostics or {}),
                "provider_cache_policy": cache_policy.to_dict(),
                "model_request_prefix_key_tier": prefix_key_tier,
                "model_request_selected_prefix_hash": expected_prefix_hash,
                "model_request_stable_prefix_hash": model_request.stable_prefix_hash,
                "model_request_provider_global_prefix_hash": model_request.provider_global_prefix_hash,
                "model_request_session_prefix_hash": model_request.session_prefix_hash,
                "model_request_task_prefix_hash": model_request.task_prefix_hash,
                "prefix_hash_matches_model_request": prefix_hash_matches_model_request,
                "unplanned_message_count": int(model_request_diagnostics.get("unplanned_message_count") or 0),
                "bound_segment_count": int(model_request_diagnostics.get("bound_segment_count") or 0),
                "planned_segment_count": int(model_request_diagnostics.get("planned_segment_count") or 0),
            }
            if cache_policy.mode == "disabled" and cache_record.status != "bypassed":
                cache_record = replace(
                    cache_record,
                    scope="none",
                    ttl_seconds=0,
                    status="bypassed",
                    cache_safety_reasons=(
                        *tuple(cache_record.cache_safety_reasons or ()),
                        cache_policy.reason or "provider_cache_disabled",
                    ),
                    diagnostics=cache_record_diagnostics,
                )
            else:
                cache_record = replace(
                    cache_record,
                    diagnostics=cache_record_diagnostics,
                )
            ledger.record_prompt_cache(cache_record)
            if unplanned_reason:
                ledger.record_prompt_cache_break(
                    PromptCacheBreakRecord(
                        break_id=f"pcbreak:{request_id}:unplanned:{uuid.uuid4().hex[:8]}",
                        request_id=request_id,
                        run_id=run_id,
                        task_run_id=task_run_id,
                        session_id=session_id,
                        provider=spec.provider,
                        model=spec.model,
                        cache_key=cache_record.cache_key,
                        prefix_hash=cache_record.prefix_hash,
                        reason="unplanned_model_call",
                        created_at=created_at,
                        diagnostics={
                            "severity": "high" if _agent_runtime_like_call(call_kind=call_kind, context=context) else "medium",
                            "call_kind": call_kind,
                            "source": str(context.get("source") or ""),
                            "cache_metric_scope": str(metadata.get("cache_metric_scope") or ""),
                            "message_count": len(list(messages or [])),
                            "tool_count": len(list(tools or [])),
                            "unplanned_reason": unplanned_reason,
                        },
                    )
                )
            previous_stability_reports = ledger.list_prompt_stability(
                **_previous_stability_report_filter(
                    run_id=run_id,
                    task_run_id=task_run_id,
                    session_id=session_id,
                )
            )
            previous_stability_report = _previous_stability_report(
                previous_stability_reports,
                invocation_kind=str(metadata.get("source") or metadata.get("call_kind") or ""),
                provider=spec.provider,
                model=spec.model,
            )
            stability_report = self._prompt_stability_reporter.build(
                segment_map=segment_map,
                previous_report=previous_stability_report,
                model_request=model_request,
                cache_record=cache_record,
                created_at=created_at,
            )
            ledger.record_prompt_stability(stability_report)
            return {
                "request_id": request_id,
                "run_id": run_id,
                "task_run_id": task_run_id,
                "session_id": session_id,
                "provider": spec.provider,
                "model": spec.model,
                "cache_record": cache_record,
                "model_request": model_request,
                "segment_map": segment_map,
                "stability_report": stability_report,
                "started_at": created_at,
            }
        except Exception:
            logger.debug("Failed to record prompt accounting prediction", exc_info=True)
            return {}

    def _finish_prompt_accounting(self, accounting: dict[str, Any], *, response: Any) -> None:
        ledger = self.prompt_accounting_ledger
        request_id = str(dict(accounting or {}).get("request_id") or "")
        if ledger is None or not request_id:
            return
        try:
            provider_usage = extract_provider_usage(
                response,
                request_id=request_id,
                provider=str(accounting.get("provider") or ""),
                model=str(accounting.get("model") or ""),
                run_id=str(accounting.get("run_id") or accounting.get("task_run_id") or ""),
                task_run_id=str(accounting.get("task_run_id") or ""),
                session_id=str(accounting.get("session_id") or ""),
            )
            if provider_usage is None:
                return
            cache_record = accounting.get("cache_record")
            finished_at = time.time()
            started_at = float(accounting.get("started_at") or finished_at)
            duration_seconds = max(0.0, finished_at - started_at)
            previous_cache_records = ledger.list_prompt_cache(
                run_id=str(accounting.get("run_id") or accounting.get("task_run_id") or ""),
                task_run_id=str(accounting.get("task_run_id") or ""),
                session_id=str(accounting.get("session_id") or ""),
            )
            model_request = accounting.get("model_request")
            cache_policy = getattr(model_request, "cache_policy", None)
            if cache_policy is not None:
                provider_usage = replace(
                    provider_usage,
                    diagnostics={
                        **dict(provider_usage.diagnostics or {}),
                        "provider_cache_policy": cache_policy.to_dict(),
                        "model_request_ref": str(getattr(model_request, "request_id", "") or ""),
                        "stable_prefix_hash": str(getattr(model_request, "stable_prefix_hash", "") or ""),
                        "provider_global_prefix_hash": str(getattr(model_request, "provider_global_prefix_hash", "") or ""),
                        "session_prefix_hash": str(getattr(model_request, "session_prefix_hash", "") or ""),
                        "task_prefix_hash": str(getattr(model_request, "task_prefix_hash", "") or ""),
                        "duration_seconds": duration_seconds,
                    },
                )
            ledger.record_token_usage(provider_usage)
            if cache_record is not None:
                updated_cache_record = self._prompt_cache_planner.with_provider_usage(cache_record, provider_usage)
                stable_prefix_predicted_tokens = int(
                    dict(updated_cache_record.diagnostics or {}).get("provider_global_prefix_predicted_tokens")
                    or dict(updated_cache_record.diagnostics or {}).get("stable_prefix_predicted_tokens")
                    or 0
                )
                cached_tokens = max(int(provider_usage.cached_tokens or 0), int(provider_usage.cache_read_tokens or 0))
                cache_efficiency = (
                    round(cached_tokens / stable_prefix_predicted_tokens, 4)
                    if stable_prefix_predicted_tokens > 0
                    else 0.0
                )
                updated_cache_record = replace(
                    updated_cache_record,
                    diagnostics={
                        **dict(updated_cache_record.diagnostics or {}),
                        "duration_seconds": duration_seconds,
                        "provider_prompt_tokens": int(provider_usage.prompt_tokens or 0),
                        "provider_total_tokens": int(provider_usage.total_tokens or 0),
                        "provider_cached_tokens": cached_tokens,
                        "cache_efficiency": cache_efficiency,
                    },
                )
                ledger.record_prompt_cache(updated_cache_record)
                break_record = self._prompt_cache_break_detector.detect(
                    cache_record=updated_cache_record,
                    provider_usage=provider_usage,
                    previous_cache_records=previous_cache_records,
                    created_at=time.time(),
                )
                if break_record is not None:
                    ledger.record_prompt_cache_break(break_record)
            stability_report = accounting.get("stability_report")
            if stability_report is not None:
                updated_stability_report = self._prompt_stability_reporter.with_provider_usage(
                    stability_report,
                    provider_usage,
                )
                ledger.record_prompt_stability(updated_stability_report)
        except Exception:
            logger.debug("Failed to record provider token usage", exc_info=True)

    def _max_output_tokens_for_spec(self, spec: ModelSpec) -> int:
        if spec.max_output_tokens is not None:
            return max(1, int(spec.max_output_tokens or 1))
        return self.max_output_tokens

    def _timeout_seconds_for_spec(self, spec: ModelSpec) -> float:
        if spec.timeout_seconds is not None:
            return max(0.01, float(spec.timeout_seconds or 0.01))
        return self.request_timeout_seconds

    def _long_output_timeout_seconds_for_spec(self, spec: ModelSpec) -> float:
        timeout = self._timeout_seconds_for_spec(spec)
        if spec.long_output_timeout_seconds is not None:
            return max(timeout, float(spec.long_output_timeout_seconds or timeout))
        return max(timeout, self.long_output_timeout_seconds)

    def _model_call_timeout_seconds_for_spec(self, spec: ModelSpec) -> float:
        if self._max_output_tokens_for_spec(spec) >= 16384:
            return self._long_output_timeout_seconds_for_spec(spec)
        return self._timeout_seconds_for_spec(spec)

    def _max_retries_for_spec(self, spec: ModelSpec) -> int:
        if spec.max_retries is not None:
            return max(0, int(spec.max_retries or 0))
        return self.max_retries

    def _temperature_for_spec(self, spec: ModelSpec) -> float:
        if spec.temperature is None:
            return 0.0
        try:
            return float(spec.temperature)
        except (TypeError, ValueError):
            return 0.0

    def _thinking_mode_for_spec(self, spec: ModelSpec) -> str:
        return str(spec.thinking_mode or self.thinking_mode or "disabled").strip().lower()

    def _thinking_enabled_for_spec(self, spec: ModelSpec) -> bool:
        return self._thinking_mode_for_spec(spec) == "enabled"

    def _reasoning_effort_for_spec(self, spec: ModelSpec) -> str:
        value = str(spec.reasoning_effort or self.reasoning_effort or "auto").strip().lower()
        if value in {"", "auto", "default", "adaptive"}:
            return ""
        if value in {"max", "xhigh"}:
            return "max"
        return "high"

    def _validate_deepseek_mode_for_spec(self, spec: ModelSpec) -> None:
        if str(spec.provider or "").strip().lower() != "deepseek":
            return
        thinking_mode = self._thinking_mode_for_spec(spec)
        reasoning_effort = self._reasoning_effort_for_spec(spec)
        if reasoning_effort != "max" or thinking_mode == "enabled":
            return
        raise ModelRuntimeError(
            code="configuration",
            provider=spec.provider,
            model=spec.model,
            detail=(
                "DeepSeek reasoning_effort=max requires thinking_mode=enabled; "
                "thinking_mode=disabled would run a non-thinking call."
            ),
            retryable=False,
            user_message="DeepSeek max 模式必须同时开启 thinking，不能在 thinking disabled 下运行。",
        )

    def _chat_openai_reasoning_effort_for_spec(self, spec: ModelSpec) -> str | None:
        if not self._thinking_enabled_for_spec(spec):
            return None
        if not _supports_chat_openai_reasoning_effort(spec):
            return None
        return _normalize_chat_openai_reasoning_effort(self._reasoning_effort_for_spec(spec))

    def _cache_relevant_params_for_spec(
        self,
        spec: ModelSpec,
        *,
        call_kind: str,
        tool_count: int,
        tool_call_options: ToolCallBindingOptions | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "provider": str(spec.provider or ""),
            "model": str(spec.model or ""),
            "base_url": _cache_relevant_base_url(spec.base_url),
            "call_kind": str(call_kind or ""),
            "tool_count": max(0, int(tool_count or 0)),
            "tool_call_options": _cache_relevant_tool_call_options(
                tool_call_options,
                spec=spec,
                thinking_mode=self._thinking_mode_for_spec(spec),
            ),
            "max_output_tokens": self._max_output_tokens_for_spec(spec),
            **(
                {}
                if _is_deepseek_thinking_spec(spec, thinking_mode=self._thinking_mode_for_spec(spec))
                else {"temperature": self._temperature_for_spec(spec)}
            ),
            "thinking_mode": self._thinking_mode_for_spec(spec),
            "reasoning_effort": self._reasoning_effort_for_spec(spec),
            "chat_openai_reasoning_effort": self._chat_openai_reasoning_effort_for_spec(spec) or "",
            "stream_policy": dict(spec.stream_policy or {}),
        }

    def _record_model_candidate_switch(
        self,
        *,
        accounting_context: dict[str, Any] | None,
        from_spec: ModelSpec,
        to_spec: ModelSpec,
        attempt: int,
        call_kind: str,
        error: ModelRuntimeError | None,
    ) -> None:
        ledger = self.prompt_accounting_ledger
        if ledger is None:
            return
        context = dict(accounting_context or {})
        request_id = str(context.get("request_id") or f"modelreq:{uuid.uuid4().hex}")
        timestamp = time.time()
        record = PromptCacheBreakRecord(
            break_id=f"pcbreak:{request_id}:candidate-switch:{uuid.uuid4().hex[:8]}",
            request_id=request_id,
            run_id=str(context.get("run_id") or context.get("task_run_id") or ""),
            task_run_id=str(context.get("task_run_id") or ""),
            session_id=str(context.get("session_id") or ""),
            provider=str(from_spec.provider or ""),
            model=str(from_spec.model or ""),
            cache_key="",
            prefix_hash="",
            reason="model_candidate_switch",
            diagnostics={
                "severity": "medium",
                "call_kind": str(call_kind or ""),
                "attempt": max(0, int(attempt or 0)),
                "from_provider": str(from_spec.provider or ""),
                "from_model": str(from_spec.model or ""),
                "from_base_url": _cache_relevant_base_url(from_spec.base_url),
                "to_provider": str(to_spec.provider or ""),
                "to_model": str(to_spec.model or ""),
                "to_base_url": _cache_relevant_base_url(to_spec.base_url),
                "error_code": str(getattr(error, "code", "") or ""),
                "error_detail": _compact_error_detail(str(getattr(error, "detail", "") or "")),
                "source": str(context.get("source") or ""),
            },
            created_at=timestamp,
        )
        ledger.record_prompt_cache_break(record)

    def _map_error(self, exc: Exception, spec: ModelSpec) -> ModelRuntimeError:
        if isinstance(exc, ModelRuntimeError):
            return exc

        detail = str(exc) or exc.__class__.__name__
        lowered = _exception_chain_text(exc).lower()

        if isinstance(exc, asyncio.TimeoutError) or any(
            token in lowered for token in ("timed out", "timeout", "deadline exceeded")
        ):
            return ModelRuntimeError(
                code="timeout",
                provider=spec.provider,
                model=spec.model,
                detail=detail,
                retryable=True,
                user_message="模型请求超时，请稍后重试。",
            )
        if any(token in lowered for token in ("rate limit", "too many requests", "429")):
            return ModelRuntimeError(
                code="rate_limit",
                provider=spec.provider,
                model=spec.model,
                detail=detail,
                retryable=True,
                user_message="模型请求触发限流，请稍后重试。",
            )
        if any(
            token in lowered
            for token in (
                "readerror",
                "read error",
                "remoteprotocolerror",
                "remote protocol error",
                "protocolerror",
                "protocol error",
                "incomplete read",
                "incomplete chunk",
                "chunked",
                "server disconnected",
                "peer closed",
                "httpcore",
                "httpx",
                "broken pipe",
                "ssl",
                "connection",
                "temporarily unavailable",
                "service unavailable",
                "unavailable",
                "connection reset",
                "network",
            )
        ):
            return ModelRuntimeError(
                code="provider_unavailable",
                provider=spec.provider,
                model=spec.model,
                detail=detail,
                retryable=True,
                user_message="模型服务暂时不可用，请稍后重试。",
            )
        if any(
            token in lowered
            for token in ("missing api key", "authentication", "unauthorized", "401", "403", "api key")
        ):
            return ModelRuntimeError(
                code="configuration",
                provider=spec.provider,
                model=spec.model,
                detail=detail,
                retryable=False,
                user_message="模型配置有误，请检查提供商和密钥设置。",
            )
        return ModelRuntimeError(
            code="provider_error",
            provider=spec.provider,
            model=spec.model,
            detail=detail,
            retryable=False,
            user_message="模型调用失败，请稍后重试。",
        )


def _compact_error_detail(detail: str, *, limit: int = 500) -> str:
    normalized = " ".join(str(detail or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _bind_tools_with_options(
    model: Any,
    tools: list[Any],
    *,
    tool_call_options: ToolCallBindingOptions | dict[str, Any] | None,
    spec: ModelSpec | None = None,
    thinking_mode: str = "",
) -> Any:
    options = _normalize_tool_call_options(tool_call_options)
    kwargs = options.bind_kwargs() if options is not None else {}
    return model.bind_tools(tools, **kwargs)


def _is_deepseek_thinking_spec(spec: ModelSpec | None, *, thinking_mode: str = "") -> bool:
    if spec is None:
        return False
    provider = str(spec.provider or "").strip().lower()
    effective_thinking_mode = str(thinking_mode or spec.thinking_mode or "disabled").strip().lower()
    return provider == "deepseek" and effective_thinking_mode == "enabled"


def _supports_chat_openai_reasoning_effort(spec: ModelSpec) -> bool:
    provider = str(spec.provider or "").strip().lower()
    if provider != "openai":
        return False
    defaults = dict(LLM_PROVIDER_DEFAULTS.get(provider) or {})
    tags = {str(tag or "").strip().lower() for tag in defaults.get("capability_tags") or []}
    return "reasoning" in tags and _is_openai_reasoning_model(spec.model)


def _is_openai_reasoning_model(model: str) -> bool:
    normalized = str(model or "").strip().lower()
    return normalized.startswith(("gpt-5", "o1", "o3", "o4"))


def _normalize_chat_openai_reasoning_effort(effort: str) -> str:
    normalized = str(effort or "").strip().lower()
    if normalized == "max":
        return "high"
    if normalized in {"minimal", "low", "medium", "high"}:
        return normalized
    return "high"


def _normalize_tool_call_options(
    tool_call_options: ToolCallBindingOptions | dict[str, Any] | None,
) -> ToolCallBindingOptions | None:
    if tool_call_options is None:
        return None
    if isinstance(tool_call_options, ToolCallBindingOptions):
        return tool_call_options
    if isinstance(tool_call_options, dict):
        return ToolCallBindingOptions(
            tool_choice=tool_call_options.get("tool_choice"),
            strict=tool_call_options.get("strict") if "strict" in tool_call_options else None,
            parallel_tool_calls=(
                tool_call_options.get("parallel_tool_calls")
                if "parallel_tool_calls" in tool_call_options
                else None
            ),
        )
    return None


def _optional_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _formal_task_run_id(value: Any) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized.startswith("taskrun:") else ""


def _cache_relevant_base_url(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if "api.deepseek.com" in text:
        return "https://api.deepseek.com"
    if "api.openai.com" in text:
        return "https://api.openai.com"
    if "api.openai.azure.com" in text:
        return "https://api.openai.azure.com"
    return text


def _cache_relevant_tool_call_options(
    tool_call_options: ToolCallBindingOptions | dict[str, Any] | None,
    *,
    spec: ModelSpec | None,
    thinking_mode: str = "",
) -> dict[str, Any]:
    options = _normalize_tool_call_options(tool_call_options)
    if options is None:
        return {}
    return options.bind_kwargs()


def _previous_stability_report_filter(*, run_id: str, task_run_id: str, session_id: str) -> dict[str, str]:
    if task_run_id:
        return {"task_run_id": task_run_id}
    if run_id:
        return {"run_id": run_id}
    if session_id:
        return {"session_id": session_id}
    return {}


def _previous_stability_report(
    reports: list[Any],
    *,
    invocation_kind: str,
    provider: str,
    model: str,
) -> Any | None:
    target_invocation = str(invocation_kind or "").strip()
    target_provider = str(provider or "").strip()
    target_model = str(model or "").strip()
    for report in reversed(list(reports or [])):
        if target_invocation and str(getattr(report, "invocation_kind", "") or "") != target_invocation:
            continue
        if target_provider and str(getattr(report, "provider", "") or "") != target_provider:
            continue
        if target_model and str(getattr(report, "model", "") or "") != target_model:
            continue
        return report
    return None


def _model_request_prefix_hash_for_tier(model_request: Any, *, prefix_key_tier: str) -> str:
    tier = str(prefix_key_tier or "").strip()
    if tier == "task":
        return str(getattr(model_request, "task_prefix_hash", "") or "")
    if tier == "session":
        return str(getattr(model_request, "session_prefix_hash", "") or "")
    if tier == "provider_global":
        return str(getattr(model_request, "provider_global_prefix_hash", "") or "")
    if tier == "stable":
        return str(getattr(model_request, "stable_prefix_hash", "") or "")
    return ""


def _utility_accounting_context(
    *,
    source: str,
    messages: list[dict[str, Any]],
    purpose: str,
) -> dict[str, Any]:
    segment_plan = build_prompt_segment_plan(
        packet_id=f"utility:{purpose}:{uuid.uuid4().hex[:8]}",
        invocation_kind="utility_model_call",
        message_specs=[
            {
                "role": str(message.get("role") or "user"),
                "content": str(message.get("content") or ""),
                "kind": "utility_static" if index == 0 else "utility_volatile",
                "source_ref": purpose,
                "cache_scope": "global" if index == 0 else "none",
                "cache_role": "cacheable_prefix" if index == 0 else "volatile",
                "prefix_tier": "provider_global" if index == 0 else "volatile",
                "compression_role": "preserve" if index == 0 else "summarize",
            }
            for index, message in enumerate(list(messages or []))
        ],
    ).to_dict()
    return {
        "source": source,
        "call_purpose": purpose,
        "cache_metric_scope": "utility_minimal_plan",
        "segment_plan": segment_plan,
        "prompt_manifest": {
            "invocation_kind": "utility_model_call",
            "cache_metric_scope": "utility_minimal_plan",
            "utility_purpose": purpose,
            "segment_plan_ref": segment_plan.get("segment_plan_id", ""),
        },
    }


def utility_accounting_context(
    *,
    source: str,
    messages: list[dict[str, Any]],
    purpose: str,
    cache_metric_scope: str = "utility_minimal_plan",
    session_id: str = "",
    run_id: str = "",
    task_run_id: str = "",
) -> dict[str, Any]:
    context = _utility_accounting_context(source=source, messages=messages, purpose=purpose)
    if cache_metric_scope:
        context["cache_metric_scope"] = str(cache_metric_scope)
        context.setdefault("prompt_manifest", {})["cache_metric_scope"] = str(cache_metric_scope)
    if session_id:
        context["session_id"] = str(session_id)
    if run_id:
        context["run_id"] = str(run_id)
    if task_run_id:
        context["task_run_id"] = str(task_run_id)
    return context


def _normalize_accounting_context_for_prompt_plan(
    context: dict[str, Any],
    *,
    call_kind: str,
    message_count: int,
    tool_count: int,
) -> tuple[dict[str, Any], str]:
    normalized = dict(context or {})
    segment_plan = dict(normalized.get("segment_plan") or {})
    if segment_plan.get("segments"):
        return normalized, ""
    scope = str(normalized.get("cache_metric_scope") or "").strip()
    if not scope:
        scope = "unplanned_model_call"
        normalized["cache_metric_scope"] = scope
    manifest = dict(normalized.get("prompt_manifest") or {})
    manifest.setdefault("cache_metric_scope", scope)
    manifest.setdefault("unplanned_model_call", True)
    manifest.setdefault("call_kind", str(call_kind or ""))
    manifest.setdefault("message_count", max(0, int(message_count or 0)))
    manifest.setdefault("tool_count", max(0, int(tool_count or 0)))
    normalized["prompt_manifest"] = manifest
    return normalized, "missing_segment_plan"


def _agent_runtime_like_call(*, call_kind: str, context: dict[str, Any]) -> bool:
    scope = str(dict(context or {}).get("cache_metric_scope") or "")
    if scope == "agent_runtime":
        return True
    source = str(dict(context or {}).get("source") or "")
    return source.startswith("harness.") or str(call_kind or "") in {
        "astream_conversation",
        "astream_messages",
        "astream_messages_with_tools",
    }


def _optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_configured_env_for_provider(provider: str) -> str | None:
    for env_name in LLM_PROVIDER_DEFAULTS.get(provider, {}).get("credential_envs") or ():
        value = os.getenv(str(env_name))
        if value and value.strip():
            return value.strip()
    return None


def _exception_chain_text(exc: Exception) -> str:
    parts: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(f"{current.__class__.__name__}: {current}")
        current = current.__cause__ or current.__context__
    return " | ".join(parts) or exc.__class__.__name__


