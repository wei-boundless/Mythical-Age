from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, convert_to_messages
from langchain_openai import ChatOpenAI

try:
    from langchain_deepseek import ChatDeepSeek
except ImportError:  # pragma: no cover - optional dependency at runtime
    ChatDeepSeek = None

from bootstrap.settings import AppSettingsService
from runtime.tool_runtime.tool_call_policy import ToolCallBindingOptions

if TYPE_CHECKING:
    from agent_system.a2a.models import AgentDefinition
    from agent_system.models.model_profile_models import ResolvedModelSpec

logger = logging.getLogger(__name__)


class _DeepSeekReasoningCompatChatModel(ChatDeepSeek):
    """Preserve DeepSeek thinking payload across tool-call round trips.

    DeepSeek thinking mode requires the previous assistant tool-call message to
    replay its `reasoning_content` on the next request. LangChain stores that
    field in `AIMessage.additional_kwargs`, but the default OpenAI-compatible
    message serializer drops it for chat/completions payloads. We patch the
    serialized assistant messages here so multi-turn tool loops can continue.
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

        for original_message, serialized_message in zip(original_messages, raw_messages):
            if not isinstance(original_message, AIMessage):
                continue
            if not isinstance(serialized_message, dict):
                continue
            if str(serialized_message.get("role", "") or "").strip() != "assistant":
                continue

            reasoning_content = str(original_message.additional_kwargs.get("reasoning_content", "") or "").strip()
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
    def __init__(self, settings_service: AppSettingsService) -> None:
        self.settings_service = settings_service
        self._chat_model_pool: dict[str, Any] = {}

    @property
    def request_timeout_seconds(self) -> float:
        static = self.settings_service.static
        return max(0.01, float(getattr(static, "llm_timeout_seconds", 45.0) or 45.0))

    @property
    def max_retries(self) -> int:
        static = self.settings_service.static
        return max(0, int(getattr(static, "llm_max_retries", 2) or 2))

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
        return str(getattr(static, "llm_reasoning_effort", "high") or "high").strip().lower()

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

    async def invoke_messages(self, messages: list[dict[str, str]], *, model_spec: ModelSpec | "ResolvedModelSpec" | None = None) -> Any:
        last_error: ModelRuntimeError | None = None
        candidates = self._candidate_specs(model_spec=model_spec)
        for spec_index, spec in enumerate(candidates):
            for attempt in range(1, self._max_retries_for_spec(spec) + 2):
                model = self._get_chat_model_for_spec(spec)
                try:
                    return await asyncio.wait_for(
                        model.ainvoke(messages),
                        timeout=self._model_call_timeout_seconds_for_spec(spec),
                    )
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
    ) -> Any:
        last_error: ModelRuntimeError | None = None
        candidates = self._candidate_specs(model_spec=model_spec)
        for spec_index, spec in enumerate(candidates):
            for attempt in range(1, self._max_retries_for_spec(spec) + 2):
                model = self._get_chat_model_for_spec(spec)
                try:
                    bound_model = (
                        _bind_tools_with_options(model, tools, tool_call_options=tool_call_options, spec=spec)
                        if tools
                        else model
                    )
                    return await asyncio.wait_for(
                        bound_model.ainvoke(messages),
                        timeout=self._model_call_timeout_seconds_for_spec(spec),
                    )
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

    async def astream_messages(self, messages: list[Any], *, model_spec: ModelSpec | "ResolvedModelSpec" | None = None):
        last_error: ModelRuntimeError | None = None
        candidates = self._candidate_specs(model_spec=model_spec)
        for spec_index, spec in enumerate(candidates):
            for attempt in range(1, self._max_retries_for_spec(spec) + 2):
                emitted = False
                model = self._get_chat_model_for_spec(spec)
                try:
                    stream = model.astream(messages)
                    async for chunk in self._iterate_with_timeout(stream, spec=spec):
                        emitted = True
                        yield chunk
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
    ):
        last_error: ModelRuntimeError | None = None
        candidates = self._candidate_specs(model_spec=model_spec)
        for spec_index, spec in enumerate(candidates):
            for attempt in range(1, self._max_retries_for_spec(spec) + 2):
                emitted = False
                model = self._get_chat_model_for_spec(spec)
                try:
                    bound_model = (
                        _bind_tools_with_options(model, tools, tool_call_options=tool_call_options, spec=spec)
                        if tools
                        else model
                    )
                    stream = bound_model.astream(messages)
                    async for chunk in self._iterate_with_timeout(stream, spec=spec):
                        emitted = True
                        yield chunk
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
    ):
        last_error: ModelRuntimeError | None = None
        candidates = self._candidate_specs(model_spec=model_spec)
        for spec_index, spec in enumerate(candidates):
            for attempt in range(1, self._max_retries_for_spec(spec) + 2):
                emitted = False
                model = self._get_chat_model_for_spec(spec)
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
                        yield item
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
            response = await self.invoke_messages(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": first_user_message},
                ]
            )
            title = stringify_content(getattr(response, "content", "")).strip()
            return title[:10] or "新会话"
        except ModelRuntimeError:
            return (first_user_message.strip() or "新会话")[:10]
        except Exception:
            return (first_user_message.strip() or "新会话")[:10]

    async def summarize_history(self, messages: list[dict[str, Any]]) -> str:
        prompt = (
            "请将以下对话压缩成中文摘要，控制在 500 字以内。"
            "重点保留用户目标、已完成步骤、重要结论和未解决事项。"
        )
        transcript_lines: list[str] = []
        for item in messages:
            role = item.get("role", "assistant")
            content = str(item.get("content", "") or "")
            if content:
                transcript_lines.append(f"{role}: {content}")
        transcript = "\n".join(transcript_lines)

        try:
            response = await self.invoke_messages(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": transcript},
                ]
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
            if ChatDeepSeek is None:
                raise RuntimeError("langchain-deepseek is not installed")
            if not spec.api_key:
                raise RuntimeError("Missing API key for provider deepseek")
            thinking_enabled = self._thinking_mode_for_spec(spec) == "enabled"
            extra_body: dict[str, Any] = {
                "thinking": {
                    "type": "enabled" if thinking_enabled else "disabled"
                }
            }
            model_kwargs: dict[str, Any] = {
                "model": spec.model,
                "api_key": spec.api_key,
                "base_url": spec.base_url,
                "temperature": temperature,
                "timeout": timeout_seconds,
                "max_retries": 0,
                "max_tokens": max_output_tokens,
                "extra_body": extra_body,
            }
            if thinking_enabled:
                model_kwargs["reasoning_effort"] = self._reasoning_effort_for_spec(spec)
            return _DeepSeekReasoningCompatChatModel(**model_kwargs)

        if not spec.api_key:
            raise RuntimeError(f"Missing API key for provider {spec.provider}")

        return ChatOpenAI(
            model=spec.model,
            api_key=spec.api_key,
            base_url=spec.base_url,
            temperature=temperature,
            timeout=timeout_seconds,
            max_retries=0,
            max_completion_tokens=max_output_tokens,
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

    def _model_spec_from_override(self, override: ModelSpec | "ResolvedModelSpec") -> ModelSpec:
        if isinstance(override, ModelSpec):
            return override
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

    def _reasoning_effort_for_spec(self, spec: ModelSpec) -> str:
        return str(spec.reasoning_effort or self.reasoning_effort or "high").strip().lower()

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
) -> Any:
    options = _normalize_tool_call_options(tool_call_options)
    kwargs = options.bind_kwargs() if options is not None else {}
    if _deepseek_thinking_disallows_tool_choice(spec):
        kwargs.pop("tool_choice", None)
    return model.bind_tools(tools, **kwargs)


def _deepseek_thinking_disallows_tool_choice(spec: ModelSpec | None) -> bool:
    if spec is None:
        return False
    provider = str(spec.provider or "").strip().lower()
    thinking_mode = str(spec.thinking_mode or "disabled").strip().lower()
    return provider == "deepseek" and thinking_mode == "enabled"


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


def _exception_chain_text(exc: Exception) -> str:
    parts: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(f"{current.__class__.__name__}: {current}")
        current = current.__cause__ or current.__context__
    return " | ".join(parts) or exc.__class__.__name__


