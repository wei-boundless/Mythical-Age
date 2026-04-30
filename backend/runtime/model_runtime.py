from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, convert_to_messages
from langchain_openai import ChatOpenAI

try:
    from langchain_deepseek import ChatDeepSeek
except ImportError:  # pragma: no cover - optional dependency at runtime
    ChatDeepSeek = None

from agents.models import AgentDefinition
from config import LLM_PROVIDER_DEFAULTS
from runtime.settings import AppSettingsService

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
        ):
            yield item


class ModelRuntime:
    def __init__(self, settings_service: AppSettingsService) -> None:
        self.settings_service = settings_service
        static = settings_service.static
        self.request_timeout_seconds = max(
            0.01,
            float(getattr(static, "llm_timeout_seconds", 45.0) or 45.0),
        )
        self.max_retries = max(0, int(getattr(static, "llm_max_retries", 2) or 2))

    def build_chat_model(self):
        return self._build_chat_model_for_spec(self._candidate_specs()[0])

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

    async def invoke_messages(self, messages: list[dict[str, str]]) -> Any:
        last_error: ModelRuntimeError | None = None
        candidates = self._candidate_specs()
        for spec_index, spec in enumerate(candidates):
            for attempt in range(1, self.max_retries + 2):
                model = self._build_chat_model_for_spec(spec)
                try:
                    return await asyncio.wait_for(
                        model.ainvoke(messages),
                        timeout=self.request_timeout_seconds,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    last_error = self._map_error(exc, spec)
                    if attempt <= self.max_retries and last_error.retryable:
                        logger.warning(
                            "Retrying model invoke after %s (%s/%s): %s",
                            last_error.code,
                            attempt,
                            self.max_retries,
                            last_error.detail,
                        )
                        await asyncio.sleep(min(0.5, 0.1 * attempt))
                        continue
                    break
                finally:
                    await self._aclose_chat_model(model)
            if last_error is None:
                continue
            if spec_index < len(candidates) - 1:
                logger.warning(
                    "Switching model candidate after %s on %s/%s",
                    last_error.code,
                    spec.provider,
                    spec.model,
                )
                continue
            raise last_error
        raise RuntimeError("No model candidates available")

    async def invoke_messages_with_tools(self, messages: list[Any], tools: list[Any]) -> Any:
        last_error: ModelRuntimeError | None = None
        candidates = self._candidate_specs()
        for spec_index, spec in enumerate(candidates):
            for attempt in range(1, self.max_retries + 2):
                model = self._build_chat_model_for_spec(spec)
                try:
                    bound_model = model.bind_tools(tools) if tools else model
                    return await asyncio.wait_for(
                        bound_model.ainvoke(messages),
                        timeout=self.request_timeout_seconds,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    last_error = self._map_error(exc, spec)
                    if attempt <= self.max_retries and last_error.retryable:
                        logger.warning(
                            "Retrying tool-enabled model invoke after %s (%s/%s): %s",
                            last_error.code,
                            attempt,
                            self.max_retries,
                            last_error.detail,
                        )
                        await asyncio.sleep(min(0.5, 0.1 * attempt))
                        continue
                    break
                finally:
                    await self._aclose_chat_model(model)
            if last_error is None:
                continue
            if spec_index < len(candidates) - 1:
                logger.warning(
                    "Switching tool-enabled model candidate after %s on %s/%s",
                    last_error.code,
                    spec.provider,
                    spec.model,
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
    ):
        last_error: ModelRuntimeError | None = None
        candidates = self._candidate_specs()
        for spec_index, spec in enumerate(candidates):
            for attempt in range(1, self.max_retries + 2):
                emitted = False
                model = self._build_chat_model_for_spec(spec)
                agent = self._create_raw_agent(
                    system_prompt=system_prompt,
                    tools=tools,
                    agent_definition=agent_definition,
                    model=model,
                )
                try:
                    stream = agent.astream(payload, stream_mode=stream_mode)
                    async for item in self._iterate_with_timeout(stream):
                        emitted = True
                        yield item
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    last_error = self._map_error(exc, spec)
                    if emitted:
                        raise last_error from exc
                    if attempt <= self.max_retries and last_error.retryable:
                        logger.warning(
                            "Retrying model stream after %s (%s/%s): %s",
                            last_error.code,
                            attempt,
                            self.max_retries,
                            last_error.detail,
                        )
                        await asyncio.sleep(min(0.5, 0.1 * attempt))
                        continue
                    break
                finally:
                    await self._aclose_chat_model(model)
            if last_error is None:
                continue
            if spec_index < len(candidates) - 1:
                logger.warning(
                    "Switching stream model candidate after %s on %s/%s",
                    last_error.code,
                    spec.provider,
                    spec.model,
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

    def _candidate_specs(self) -> list[ModelSpec]:
        settings = self.settings_service.static
        primary = ModelSpec(
            provider=settings.llm_provider,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
        default_model = LLM_PROVIDER_DEFAULTS.get(primary.provider, {}).get("model")
        specs = [primary]
        if default_model and default_model != primary.model:
            specs.append(
                ModelSpec(
                    provider=primary.provider,
                    model=default_model,
                    api_key=primary.api_key,
                    base_url=primary.base_url,
                )
            )
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
        if spec.provider == "deepseek":
            if ChatDeepSeek is None:
                raise RuntimeError("langchain-deepseek is not installed")
            if not spec.api_key:
                raise RuntimeError("Missing API key for provider deepseek")
            return _DeepSeekReasoningCompatChatModel(
                model=spec.model,
                api_key=spec.api_key,
                base_url=spec.base_url,
                temperature=0,
            )

        if not spec.api_key:
            raise RuntimeError(f"Missing API key for provider {spec.provider}")

        return ChatOpenAI(
            model=spec.model,
            api_key=spec.api_key,
            base_url=spec.base_url,
            temperature=0,
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

    async def _iterate_with_timeout(self, stream):
        while True:
            try:
                item = await asyncio.wait_for(
                    stream.__anext__(),
                    timeout=self.request_timeout_seconds,
                )
            except StopAsyncIteration:
                return
            yield item

    def _map_error(self, exc: Exception, spec: ModelSpec) -> ModelRuntimeError:
        if isinstance(exc, ModelRuntimeError):
            return exc

        detail = str(exc) or exc.__class__.__name__
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
