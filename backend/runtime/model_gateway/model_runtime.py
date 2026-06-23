from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import os
import time
import uuid
from dataclasses import dataclass, is_dataclass, replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from bootstrap.settings import AppSettingsService
from config import LLM_PROVIDER_DEFAULTS
from harness.runtime.prompt_segment_plan import build_prompt_segment_plan
from prompt_library import SESSION_TITLE_GENERATION_PROMPT
from runtime.prompt_accounting import (
    CanonicalPromptSerializer,
    ModelTokenUsageRecord,
    PromptAccountingLedger,
    PromptCacheBaselineTracker,
    PromptCacheBreakRecord,
    PromptCacheBreakDetector,
    PromptCachePlanner,
    PromptStabilityReporter,
    extract_provider_usage,
)
from runtime.tool_runtime.tool_call_policy import ToolCallBindingOptions

from .lightweight_chat_model import LightweightChatModel, LightweightConversationAgent
from .model_request import ModelRequestBuilder
from .providers import ProviderRequestProfile, build_provider_adapter_result

if TYPE_CHECKING:
    from agent_system.a2a.models import AgentDefinition
    from agent_system.models.model_profile_models import ResolvedModelSpec

logger = logging.getLogger(__name__)

_UTILITY_PROMPT_REFS_BY_PURPOSE: dict[str, tuple[str, ...]] = {
    "utility.generate_title": ("utility.title_generation.session",),
    "utility.rag_answer_finalizer": ("utility.finalizer.rag_answer",),
    "memory.durable_recall_selector": ("utility.memory.durable_recall_selector",),
    "memory.maintenance_after_commit": ("agent.memory_system_agent.memory_maintenance.work_role",),
}

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
    response_format: dict[str, Any] | None = None
    structured_output: str | None = None
    provider_extensions: dict[str, Any] | None = None
    completion_profile: dict[str, Any] | None = None
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
        self._prompt_cache_baseline_tracker = PromptCacheBaselineTracker()
        self._prompt_cache_break_detector = PromptCacheBreakDetector()
        self._prompt_stability_reporter = PromptStabilityReporter()
        self._model_request_builder = ModelRequestBuilder()
        self.runtime_observability: Any | None = None

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
        return str(getattr(static, "llm_reasoning_effort", "") or "").strip().lower()

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

    def attach_runtime_observability(self, observability: Any | None) -> None:
        self.runtime_observability = observability

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
                effective_spec = _spec_with_chat_prefix_endpoint(spec)
                effective_messages = _messages_with_chat_prefix_protocol(messages, spec=effective_spec)
                model = self._get_chat_model_for_spec(effective_spec)
                accounting = self._begin_prompt_accounting(
                    effective_messages,
                    tools=None,
                    spec=effective_spec,
                    accounting_context=accounting_context,
                    attempt=attempt,
                    call_kind="invoke_messages",
                )
                try:
                    response = await asyncio.wait_for(
                        model.ainvoke(effective_messages),
                        timeout=self._model_call_timeout_seconds_for_spec(effective_spec),
                    )
                    self._finish_prompt_accounting(accounting, response=response)
                    return response
                except asyncio.CancelledError as exc:
                    self._finish_prompt_accounting(accounting, response=None, error=exc)
                    raise
                except Exception as exc:
                    self._finish_prompt_accounting(accounting, response=None, error=exc)
                    last_error = self._map_error(exc, effective_spec)
                    await self._invalidate_chat_model_for_spec(effective_spec)
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
                effective_spec = _spec_with_chat_prefix_endpoint(spec)
                effective_messages = _messages_with_chat_prefix_protocol(messages, spec=effective_spec)
                model = self._get_chat_model_for_spec(effective_spec)
                accounting = self._begin_prompt_accounting(
                    effective_messages,
                    tools=tools,
                    spec=effective_spec,
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
                            spec=effective_spec,
                            thinking_mode=self._thinking_mode_for_spec(effective_spec),
                        )
                        if tools
                        else model
                    )
                    response = await asyncio.wait_for(
                        bound_model.ainvoke(effective_messages),
                        timeout=self._model_call_timeout_seconds_for_spec(effective_spec),
                    )
                    self._finish_prompt_accounting(accounting, response=response)
                    return response
                except asyncio.CancelledError as exc:
                    self._finish_prompt_accounting(accounting, response=None, error=exc)
                    raise
                except Exception as exc:
                    self._finish_prompt_accounting(accounting, response=None, error=exc)
                    last_error = self._map_error(exc, effective_spec)
                    await self._invalidate_chat_model_for_spec(effective_spec)
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
                effective_spec = _spec_with_chat_prefix_endpoint(spec)
                effective_messages = _messages_with_chat_prefix_protocol(messages, spec=effective_spec)
                model = self._get_chat_model_for_spec(effective_spec)
                accounting = self._begin_prompt_accounting(
                    effective_messages,
                    tools=None,
                    spec=effective_spec,
                    accounting_context=accounting_context,
                    attempt=attempt,
                    call_kind="astream_messages",
                )
                aggregated_chunk = None
                try:
                    stream = model.astream(effective_messages)
                    async for chunk in self._iterate_with_timeout(stream, spec=effective_spec):
                        emitted = True
                        try:
                            aggregated_chunk = chunk if aggregated_chunk is None else aggregated_chunk + chunk
                        except Exception:
                            aggregated_chunk = chunk
                        yield chunk
                    self._finish_prompt_accounting(accounting, response=aggregated_chunk)
                    return
                except asyncio.CancelledError as exc:
                    self._finish_prompt_accounting(accounting, response=None, error=exc)
                    raise
                except Exception as exc:
                    self._finish_prompt_accounting(accounting, response=None, error=exc)
                    last_error = self._map_error(exc, effective_spec)
                    await self._invalidate_chat_model_for_spec(effective_spec)
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
                effective_spec = _spec_with_chat_prefix_endpoint(spec)
                effective_messages = _messages_with_chat_prefix_protocol(messages, spec=effective_spec)
                model = self._get_chat_model_for_spec(effective_spec)
                accounting = self._begin_prompt_accounting(
                    effective_messages,
                    tools=tools,
                    spec=effective_spec,
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
                            spec=effective_spec,
                            thinking_mode=self._thinking_mode_for_spec(effective_spec),
                        )
                        if tools
                        else model
                    )
                    stream = bound_model.astream(effective_messages)
                    async for chunk in self._iterate_with_timeout(stream, spec=effective_spec):
                        emitted = True
                        try:
                            aggregated_chunk = chunk if aggregated_chunk is None else aggregated_chunk + chunk
                        except Exception:
                            aggregated_chunk = chunk
                        yield chunk
                    self._finish_prompt_accounting(accounting, response=aggregated_chunk)
                    return
                except asyncio.CancelledError as exc:
                    self._finish_prompt_accounting(accounting, response=None, error=exc)
                    raise
                except Exception as exc:
                    self._finish_prompt_accounting(accounting, response=None, error=exc)
                    last_error = self._map_error(exc, effective_spec)
                    await self._invalidate_chat_model_for_spec(effective_spec)
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
                except asyncio.CancelledError as exc:
                    self._finish_prompt_accounting(accounting, response=None, error=exc)
                    raise
                except Exception as exc:
                    self._finish_prompt_accounting(accounting, response=None, error=exc)
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
        try:
            messages = [
                {"role": "system", "content": SESSION_TITLE_GENERATION_PROMPT},
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
        provider_adapter = self._provider_adapter_result_for_spec(spec)
        effective_base_url = str(provider_adapter.effective_base_url or spec.base_url)
        provider = str(spec.provider or "").strip().lower()
        if provider == "deepseek":
            self._validate_deepseek_mode_for_spec(spec)
            if not spec.api_key:
                raise RuntimeError("Missing API key for provider deepseek")
            thinking_enabled = self._thinking_enabled_for_spec(spec)
            return LightweightChatModel(
                provider=provider,
                model=spec.model,
                api_key=spec.api_key,
                base_url=effective_base_url,
                timeout_seconds=timeout_seconds,
                max_output_tokens=max_output_tokens,
                output_token_parameter="max_tokens",
                temperature=None if thinking_enabled else temperature,
                reasoning_effort=self._reasoning_effort_for_spec(spec) if thinking_enabled else "",
                **_lightweight_model_provider_kwargs(provider_adapter.model_kwargs),
            )

        if not spec.api_key and provider != "ollama":
            raise RuntimeError(f"Missing API key for provider {spec.provider}")
        return LightweightChatModel(
            provider=provider,
            model=spec.model,
            api_key=spec.api_key,
            base_url=effective_base_url,
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens,
            output_token_parameter=_output_token_parameter_for_provider(provider),
            temperature=temperature,
            reasoning_effort=self._chat_openai_reasoning_effort_for_spec(spec) or "",
            **_lightweight_model_provider_kwargs(provider_adapter.model_kwargs),
        )

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
                self._provider_adapter_result_for_spec(spec).pool_key_hash(),
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
        return LightweightConversationAgent(model=model, tools=tools, system_prompt=system_prompt)

    async def _aclose_chat_model(self, model: Any) -> None:
        close_targets = [model]
        for attr_name in ("root_async_client", "root_client", "http_async_client", "http_client"):
            target = getattr(model, attr_name, None)
            if target is None:
                continue
            if any(existing is target for existing in close_targets):
                continue
            close_targets.append(target)

        for target in close_targets:
            close_method = getattr(target, "aclose", None) or getattr(target, "close", None)
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
                response_format=dict(override.get("response_format") or {}),
                structured_output=str(override.get("structured_output") or "").strip() or None,
                provider_extensions=dict(override.get("provider_extensions") or {}),
                completion_profile=dict(override.get("completion_profile") or {}),
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
            response_format=dict(getattr(override, "response_format", {}) or {}),
            structured_output=str(getattr(override, "structured_output", "") or "").strip() or None,
            provider_extensions=dict(getattr(override, "provider_extensions", {}) or {}),
            completion_profile=dict(getattr(override, "completion_profile", {}) or {}),
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
        local_prediction_usage_id = f"tokuse:{request_id}:local_prediction"
        model_request = None
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
        except Exception:
            logger.debug("Failed to build model request accounting projection", exc_info=True)
        trace_span_context = self._start_model_trace_span(
            context=context,
            request_id=request_id,
            run_id=run_id,
            task_run_id=task_run_id,
            session_id=session_id,
            provider=spec.provider,
            model=spec.model,
            call_kind=call_kind,
            attempt=attempt,
            packet_ref=str(context.get("packet_ref") or ""),
            usage_id=local_prediction_usage_id,
            message_count=len(list(messages or [])),
            tool_count=len(list(tools or [])),
        )
        base_accounting = {
            "request_id": request_id,
            "run_id": run_id,
            "task_run_id": task_run_id,
            "session_id": session_id,
            "provider": spec.provider,
            "model": spec.model,
            "started_at": created_at,
            "trace_span_context": trace_span_context,
        }
        if model_request is not None:
            base_accounting["model_request"] = model_request
        if ledger is None or model_request is None:
            return base_accounting
        try:
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
                usage_id=local_prediction_usage_id,
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
                model_request=model_request,
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
                "model_request_provider_payload_prefix_hash": model_request.provider_payload_prefix_hash,
                "model_request_provider_payload_provider_global_prefix_hash": model_request.provider_payload_provider_global_prefix_hash,
                "model_request_provider_payload_session_prefix_hash": model_request.provider_payload_session_prefix_hash,
                "model_request_provider_payload_task_prefix_hash": model_request.provider_payload_task_prefix_hash,
                "model_request_tool_catalog_hash": model_request.tool_catalog_hash,
                "model_request_stable_tool_catalog_hash": model_request.stable_tool_catalog_hash,
                "model_request_cache_sensitive_params_hash": model_request.cache_sensitive_params_hash,
                "model_request_provider_transport_payload": dict(
                    model_request_diagnostics.get("provider_transport_payload") or {}
                ),
                "prefix_hash_matches_model_request": prefix_hash_matches_model_request,
                "unplanned_message_count": int(model_request_diagnostics.get("unplanned_message_count") or 0),
                "bound_segment_count": int(model_request_diagnostics.get("bound_segment_count") or 0),
                "planned_segment_count": int(model_request_diagnostics.get("planned_segment_count") or 0),
            }
            if cache_policy.mode == "disabled" and cache_record.status != "bypassed":
                cache_record = replace(
                    cache_record,
                    scope="none",
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
            previous_stability_reports = _previous_prompt_stability_reports(
                ledger,
                run_id=run_id,
                task_run_id=task_run_id,
                session_id=session_id,
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
            previous_baselines = _previous_prompt_cache_baselines(
                ledger,
                run_id=run_id,
                task_run_id=task_run_id,
                session_id=session_id,
            )
            baseline_record = self._prompt_cache_baseline_tracker.build_active_record(
                segment_map=segment_map,
                model_request=model_request,
                previous_records=previous_baselines,
                created_at=created_at,
            )
            ledger.record_prompt_cache_baseline(baseline_record)
            return {
                **base_accounting,
                "cache_record": cache_record,
                "model_request": model_request,
                "segment_map": segment_map,
                "stability_report": stability_report,
                "cache_baseline_record": baseline_record,
            }
        except Exception:
            logger.debug("Failed to record prompt accounting prediction", exc_info=True)
            return base_accounting

    def _finish_prompt_accounting(self, accounting: dict[str, Any], *, response: Any, error: BaseException | None = None) -> None:
        ledger = self.prompt_accounting_ledger
        request_id = str(dict(accounting or {}).get("request_id") or "")
        if error is not None:
            self._finish_model_trace_span(accounting, provider_usage=None, error=error)
            return
        if ledger is None or not request_id:
            self._finish_model_trace_span(accounting, provider_usage=None, error=None)
            return
        provider_usage = None
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
            previous_cache_records = _previous_prompt_cache_records(
                ledger,
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
                        "provider_payload_prefix_hash": str(getattr(model_request, "provider_payload_prefix_hash", "") or ""),
                        "provider_payload_provider_global_prefix_hash": str(getattr(model_request, "provider_payload_provider_global_prefix_hash", "") or ""),
                        "provider_payload_session_prefix_hash": str(getattr(model_request, "provider_payload_session_prefix_hash", "") or ""),
                        "provider_payload_task_prefix_hash": str(getattr(model_request, "provider_payload_task_prefix_hash", "") or ""),
                        "tool_catalog_hash": str(getattr(model_request, "tool_catalog_hash", "") or ""),
                        "stable_tool_catalog_hash": str(getattr(model_request, "stable_tool_catalog_hash", "") or ""),
                        "cache_sensitive_params_hash": str(getattr(model_request, "cache_sensitive_params_hash", "") or ""),
                        "duration_seconds": duration_seconds,
                    },
                )
            ledger.record_token_usage(provider_usage)
            if cache_record is not None:
                updated_cache_record = self._prompt_cache_planner.with_provider_usage(cache_record, provider_usage)
                stable_prefix_predicted_tokens = int(
                    dict(updated_cache_record.diagnostics or {}).get("provider_payload_prefix_predicted_tokens")
                    or dict(updated_cache_record.diagnostics or {}).get("stable_prefix_predicted_tokens")
                    or 0
                )
                cached_tokens = max(int(provider_usage.cached_tokens or 0), int(provider_usage.cache_read_tokens or 0))
                cache_miss_tokens = int(provider_usage.cache_miss_tokens or 0)
                provider_returned_cache_hit_rate = (
                    round(cached_tokens / (cached_tokens + cache_miss_tokens), 4)
                    if (cached_tokens + cache_miss_tokens) > 0
                    and str(dict(provider_usage.diagnostics or {}).get("provider_cache_hit_rate_source") or "")
                    == "provider_hit_miss_tokens"
                    else None
                )
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
                        "provider_cache_miss_tokens": cache_miss_tokens,
                        "provider_returned_cache_hit_rate": provider_returned_cache_hit_rate,
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
        finally:
            self._finish_model_trace_span(accounting, provider_usage=provider_usage, error=None)

    def _start_model_trace_span(
        self,
        *,
        context: dict[str, Any],
        request_id: str,
        run_id: str,
        task_run_id: str,
        session_id: str,
        provider: str,
        model: str,
        call_kind: str,
        attempt: int,
        packet_ref: str,
        usage_id: str,
        message_count: int,
        tool_count: int,
    ) -> Any | None:
        observability = self.runtime_observability
        start_span = getattr(observability, "start_span", None)
        if not callable(start_span):
            return None
        parent_context: Any | None = dict(context or {})
        try:
            return start_span(
                parent_context,
                name=f"model.{call_kind}",
                span_kind="model",
                refs={
                    "usage_id": usage_id,
                    "prompt_request_id": request_id,
                    "packet_ref": packet_ref,
                    **({"task_run_id": task_run_id} if task_run_id else {}),
                    **({"run_id": run_id} if run_id else {}),
                },
                attributes={
                    "provider": provider,
                    "model": model,
                    "call_kind": call_kind,
                    "attempt": attempt,
                    "message_count": message_count,
                    "tool_count": tool_count,
                    "session_id": session_id,
                },
                idempotency_key=f"model:{request_id}",
            )
        except Exception:
            logger.debug("Failed to start model trace span", exc_info=True)
            return None

    def _finish_model_trace_span(
        self,
        accounting: dict[str, Any],
        *,
        provider_usage: ModelTokenUsageRecord | None,
        error: BaseException | None,
    ) -> None:
        observability = self.runtime_observability
        span_context = dict(accounting or {}).get("trace_span_context")
        if span_context is None:
            return
        record_event = getattr(observability, "record_event", None)
        finish_span = getattr(observability, "finish_span", None)
        if not callable(finish_span):
            return
        attributes: dict[str, Any] = {}
        if provider_usage is not None:
            attributes.update(
                {
                    "provider_usage_id": provider_usage.usage_id,
                    "provider_prompt_tokens": int(provider_usage.prompt_tokens or 0),
                    "provider_completion_tokens": int(provider_usage.completion_tokens or 0),
                    "provider_total_tokens": int(provider_usage.total_tokens or 0),
                    "provider_cached_tokens": max(
                        int(provider_usage.cached_tokens or 0),
                        int(provider_usage.cache_read_tokens or 0),
                    ),
                }
            )
            try:
                if callable(record_event):
                    record_event(
                        span_context,
                        name="model.provider_usage_recorded",
                        refs={"usage_id": provider_usage.usage_id},
                        attributes={
                            "provider": provider_usage.provider,
                            "model": provider_usage.model,
                            "prompt_tokens": int(provider_usage.prompt_tokens or 0),
                            "completion_tokens": int(provider_usage.completion_tokens or 0),
                            "total_tokens": int(provider_usage.total_tokens or 0),
                        },
                        idempotency_key=f"model-provider-usage:{provider_usage.usage_id}",
                    )
            except Exception:
                logger.debug("Failed to record model provider usage trace event", exc_info=True)
        try:
            finish_span(
                span_context,
                status="error" if error is not None else "ok",
                error=error,
                attributes=attributes,
            )
        except Exception:
            logger.debug("Failed to finish model trace span", exc_info=True)

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
        value = str(spec.reasoning_effort or self.reasoning_effort or "").strip().lower()
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

    def _provider_adapter_result_for_spec(self, spec: ModelSpec):
        return build_provider_adapter_result(
            ProviderRequestProfile(
                provider=str(spec.provider or ""),
                model=str(spec.model or ""),
                base_url=str(spec.base_url or ""),
                max_output_tokens=self._max_output_tokens_for_spec(spec),
                temperature=self._temperature_for_spec(spec),
                thinking_mode=self._thinking_mode_for_spec(spec),
                reasoning_effort=self._reasoning_effort_for_spec(spec),
                stream_policy=dict(spec.stream_policy or {}),
                response_format=dict(spec.response_format or {}),
                structured_output=str(spec.structured_output or ""),
                completion_profile=dict(spec.completion_profile or {}),
                provider_extensions=dict(spec.provider_extensions or {}),
            )
        )

    def _cache_relevant_params_for_spec(
        self,
        spec: ModelSpec,
        *,
        call_kind: str,
        tool_count: int,
        tool_call_options: ToolCallBindingOptions | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        adapter_result = self._provider_adapter_result_for_spec(spec)
        return {
            "provider": str(spec.provider or ""),
            "model": str(spec.model or ""),
            "base_url": _cache_relevant_base_url(adapter_result.effective_base_url or spec.base_url),
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
            **dict(adapter_result.request_params_for_accounting or {}),
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

        detail = _compact_error_detail(_exception_chain_text(exc), limit=1000)
        lowered = detail.lower()

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
        if any(
            token in lowered
            for token in (
                "insufficient balance",
                "insufficient quota",
                "insufficient_quota",
                "quota exceeded",
                "exceeded your current quota",
                "payment required",
                "billing hard limit",
                "out of credits",
                "no credits",
                "credit balance",
                "402",
                "余额不足",
            )
        ):
            return ModelRuntimeError(
                code="insufficient_balance",
                provider=spec.provider,
                model=spec.model,
                detail=detail,
                retryable=False,
                user_message="模型服务余额不足，请检查模型提供商账户余额或更换可用模型。",
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


def _lightweight_model_provider_kwargs(model_kwargs: dict[str, Any]) -> dict[str, Any]:
    payload = dict(model_kwargs or {})
    nested_model_kwargs = dict(payload.pop("model_kwargs", {}) or {})
    extra_body = dict(payload.pop("extra_body", {}) or {})
    response_format = dict(nested_model_kwargs.pop("response_format", {}) or {})
    if nested_model_kwargs:
        extra_body.update(nested_model_kwargs)
    if payload:
        extra_body.update(payload)
    return {
        "extra_body": extra_body,
        "response_format": response_format,
    }


def _output_token_parameter_for_provider(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized == "openai":
        return "max_completion_tokens"
    return "max_tokens"


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
    if tools and kwargs.get("strict") is None and _response_format_requires_strict_tools(spec):
        kwargs["strict"] = True
    return model.bind_tools(tools, **kwargs)


def _response_format_requires_strict_tools(spec: ModelSpec | None) -> bool:
    if spec is None:
        return False
    if dict(spec.response_format or {}):
        return True
    return str(spec.structured_output or "").strip().lower() in {"json_object", "json_schema", "structured"}


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


def _previous_prompt_cache_baselines(ledger: Any, *, run_id: str, task_run_id: str, session_id: str) -> list[Any]:
    filters = _previous_stability_report_filter(run_id=run_id, task_run_id=task_run_id, session_id=session_id)
    list_recent = getattr(ledger, "list_recent_prompt_cache_baselines", None)
    use_recent = _prompt_accounting_scoped_reads_are_expensive(ledger) and callable(list_recent)
    if use_recent:
        records = list(list_recent(**filters, limit=128))
        if session_id and (filters.get("task_run_id") or filters.get("run_id")):
            records.extend(list_recent(session_id=session_id, limit=128))
    else:
        records = list(ledger.list_prompt_cache_baselines(**filters))
        if session_id and filters.get("task_run_id"):
            records.extend(ledger.list_prompt_cache_baselines(session_id=session_id))
        if session_id and filters.get("run_id"):
            records.extend(ledger.list_prompt_cache_baselines(session_id=session_id))
    deduped: dict[str, Any] = {}
    for record in records:
        key = str(getattr(record, "baseline_id", "") or f"{getattr(record, 'request_id', '')}:{getattr(record, 'created_at', '')}")
        previous = deduped.get(key)
        if previous is None or float(getattr(record, "created_at", 0.0) or 0.0) >= float(getattr(previous, "created_at", 0.0) or 0.0):
            deduped[key] = record
    return sorted(deduped.values(), key=lambda item: float(getattr(item, "created_at", 0.0) or 0.0))


def _previous_prompt_stability_reports(ledger: Any, *, run_id: str, task_run_id: str, session_id: str) -> list[Any]:
    filters = _previous_stability_report_filter(run_id=run_id, task_run_id=task_run_id, session_id=session_id)
    list_recent = getattr(ledger, "list_recent_prompt_stability", None)
    use_recent = _prompt_accounting_scoped_reads_are_expensive(ledger) and callable(list_recent)
    if use_recent:
        records = list(list_recent(**filters, limit=128))
        if session_id and (filters.get("task_run_id") or filters.get("run_id")):
            records.extend(list_recent(session_id=session_id, limit=128))
    else:
        records = list(ledger.list_prompt_stability(**filters))
        if session_id and filters.get("task_run_id"):
            records.extend(ledger.list_prompt_stability(session_id=session_id))
        if session_id and filters.get("run_id"):
            records.extend(ledger.list_prompt_stability(session_id=session_id))
    deduped: dict[str, Any] = {}
    for record in records:
        key = str(getattr(record, "report_id", "") or f"{getattr(record, 'request_id', '')}:{getattr(record, 'created_at', '')}")
        previous = deduped.get(key)
        if previous is None or float(getattr(record, "created_at", 0.0) or 0.0) >= float(getattr(previous, "created_at", 0.0) or 0.0):
            deduped[key] = record
    return sorted(deduped.values(), key=lambda item: float(getattr(item, "created_at", 0.0) or 0.0))


def _previous_prompt_cache_records(ledger: Any, *, run_id: str, task_run_id: str, session_id: str) -> list[Any]:
    list_recent = getattr(ledger, "list_recent_prompt_cache", None)
    if callable(list_recent):
        try:
            return list(
                list_recent(
                    run_id=run_id,
                    task_run_id=task_run_id,
                    session_id=session_id,
                    limit=128,
                )
                or []
            )
        except Exception:
            logger.debug("Failed to read recent prompt cache records.", exc_info=True)
            return []
    if _prompt_accounting_scoped_reads_are_expensive(ledger):
        return []
    list_prompt_cache = getattr(ledger, "list_prompt_cache", None)
    if not callable(list_prompt_cache):
        return []
    try:
        return list(
            list_prompt_cache(
                run_id=run_id,
                task_run_id=task_run_id,
                session_id=session_id,
            )
            or []
        )
    except Exception:
        logger.debug("Failed to read prompt cache records.", exc_info=True)
        return []


def _prompt_accounting_scoped_reads_are_expensive(ledger: Any) -> bool:
    scoped_reads_are_expensive = getattr(ledger, "scoped_reads_are_expensive", None)
    if not callable(scoped_reads_are_expensive):
        return False
    try:
        return bool(scoped_reads_are_expensive())
    except Exception:
        return True


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
        return str(getattr(model_request, "provider_payload_task_prefix_hash", "") or getattr(model_request, "task_prefix_hash", "") or "")
    if tier == "session":
        return str(getattr(model_request, "provider_payload_session_prefix_hash", "") or getattr(model_request, "session_prefix_hash", "") or "")
    if tier == "provider_global":
        return str(getattr(model_request, "provider_payload_provider_global_prefix_hash", "") or getattr(model_request, "provider_global_prefix_hash", "") or "")
    if tier in {"stable", "provider_payload"}:
        return str(getattr(model_request, "provider_payload_prefix_hash", "") or getattr(model_request, "stable_prefix_hash", "") or "")
    return ""


def _spec_with_chat_prefix_endpoint(spec: ModelSpec | Any) -> ModelSpec | Any:
    profile = dict(_spec_attr(spec, "completion_profile") or {})
    if str(profile.get("mode") or "").strip() != "chat_prefix":
        return spec
    if str(profile.get("provider_mode") or "").strip() != "deepseek_chat_prefix":
        return spec
    if str(_spec_attr(spec, "provider") or "").strip().lower() != "deepseek":
        return spec
    base_url = str(_spec_attr(spec, "base_url") or "").rstrip("/")
    if not base_url or base_url.endswith("/beta"):
        return spec
    return _copy_spec_with_base_url(spec, f"{base_url}/beta")


def _copy_spec_with_base_url(spec: Any, base_url: str) -> Any:
    if is_dataclass(spec):
        try:
            return replace(spec, base_url=base_url)
        except TypeError:
            pass
    if isinstance(spec, dict):
        return {**spec, "base_url": base_url}
    payload = {
        key: getattr(spec, key)
        for key in (
            "provider",
            "model",
            "api_key",
            "base_url",
            "max_output_tokens",
            "timeout_seconds",
            "long_output_timeout_seconds",
            "max_retries",
            "temperature",
            "thinking_mode",
            "reasoning_effort",
            "stream_policy",
            "response_format",
            "structured_output",
            "provider_extensions",
            "completion_profile",
            "diagnostics",
        )
        if hasattr(spec, key)
    }
    payload["base_url"] = base_url
    return SimpleNamespace(**payload)


def _spec_attr(spec: Any, key: str) -> Any:
    if isinstance(spec, dict):
        return spec.get(key)
    return getattr(spec, key, None)


def _messages_with_chat_prefix_protocol(messages: list[Any], *, spec: ModelSpec | Any) -> list[Any]:
    profile = dict(_spec_attr(spec, "completion_profile") or {})
    if str(profile.get("mode") or "").strip() != "chat_prefix":
        return messages
    if str(profile.get("provider_mode") or "").strip() != "deepseek_chat_prefix":
        return messages
    if str(_spec_attr(spec, "provider") or "").strip().lower() != "deepseek":
        return messages
    prepared = [dict(item) if isinstance(item, dict) else item for item in list(messages or [])]
    for index in range(len(prepared) - 1, -1, -1):
        item = prepared[index]
        if not isinstance(item, dict):
            continue
        if str(item.get("role") or "").strip() != "assistant":
            continue
        if not str(item.get("content") or "").strip():
            continue
        raw_additional_kwargs = item.get("additional_kwargs")
        explicit_prefix = item.get("prefix") is True or (
            isinstance(raw_additional_kwargs, dict) and raw_additional_kwargs.get("prefix") is True
        )
        if not explicit_prefix:
            continue
        item["prefix"] = True
        additional_kwargs = dict(item.get("additional_kwargs") or {})
        additional_kwargs["prefix"] = True
        item["additional_kwargs"] = additional_kwargs
        return prepared
    return messages


def _utility_accounting_context(
    *,
    source: str,
    messages: list[dict[str, Any]],
    purpose: str,
    stable_message_count: int = 1,
    message_cache_plan: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> dict[str, Any]:
    stable_count = max(1, int(stable_message_count or 1))
    prompt_refs = _utility_prompt_refs_for_purpose(purpose)
    primary_prompt_ref = prompt_refs[0] if prompt_refs else ""
    cache_plan = [dict(item) for item in list(message_cache_plan or []) if isinstance(item, dict)]
    segment_plan = build_prompt_segment_plan(
        packet_id=f"utility:{purpose}:{uuid.uuid4().hex[:8]}",
        invocation_kind="utility_model_call",
        message_specs=_utility_message_specs(
            messages=list(messages or []),
            purpose=purpose,
            primary_prompt_ref=primary_prompt_ref,
            stable_count=stable_count,
            message_cache_plan=cache_plan,
        ),
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
            "primary_prompt_ref": primary_prompt_ref,
            "prompt_refs": list(prompt_refs),
            "segment_plan_ref": segment_plan.get("segment_plan_id", ""),
        },
    }


def _utility_prompt_refs_for_purpose(purpose: str) -> tuple[str, ...]:
    normalized = str(purpose or "").strip()
    return tuple(_UTILITY_PROMPT_REFS_BY_PURPOSE.get(normalized, ()))


def utility_accounting_context(
    *,
    source: str,
    messages: list[dict[str, Any]],
    purpose: str,
    cache_metric_scope: str = "utility_minimal_plan",
    session_id: str = "",
    run_id: str = "",
    task_run_id: str = "",
    stable_message_count: int = 1,
    message_cache_plan: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> dict[str, Any]:
    context = _utility_accounting_context(
        source=source,
        messages=messages,
        purpose=purpose,
        stable_message_count=stable_message_count,
        message_cache_plan=message_cache_plan,
    )
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


def _utility_message_specs(
    *,
    messages: list[dict[str, Any]],
    purpose: str,
    primary_prompt_ref: str,
    stable_count: int,
    message_cache_plan: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for index, message in enumerate(list(messages or [])):
        plan = dict(message_cache_plan[index]) if index < len(message_cache_plan) else {}
        default = _default_utility_message_spec(
            index=index,
            message=message,
            purpose=purpose,
            primary_prompt_ref=primary_prompt_ref,
            stable_count=stable_count,
        )
        specs.append(
            {
                **default,
                **{
                    key: value
                    for key, value in plan.items()
                    if key
                    in {
                        "kind",
                        "source_ref",
                        "cache_scope",
                        "cache_role",
                        "prefix_tier",
                        "compression_role",
                        "metadata",
                    }
                },
                "role": str(message.get("role") or default["role"] or "user"),
                "content": str(message.get("content") or ""),
            }
        )
    return specs


def _default_utility_message_spec(
    *,
    index: int,
    message: dict[str, Any],
    purpose: str,
    primary_prompt_ref: str,
    stable_count: int,
) -> dict[str, Any]:
    stable = index < stable_count
    return {
        "role": str(message.get("role") or "user"),
        "content": str(message.get("content") or ""),
        "kind": "utility_static" if index == 0 else ("utility_stable" if stable else "utility_volatile"),
        "source_ref": primary_prompt_ref if index == 0 and primary_prompt_ref else purpose,
        "cache_scope": "global" if index == 0 else ("session" if stable else "none"),
        "cache_role": "cacheable_prefix" if index == 0 else ("session_stable" if stable else "volatile"),
        "prefix_tier": "provider_global" if index == 0 else ("session" if stable else "volatile"),
        "compression_role": "preserve" if stable else "summarize",
    }


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
