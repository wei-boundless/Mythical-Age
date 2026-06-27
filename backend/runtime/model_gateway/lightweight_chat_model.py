from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx


@dataclass(slots=True)
class LightweightChatMessage:
    content: Any = ""
    additional_kwargs: dict[str, Any] = field(default_factory=dict)
    response_metadata: dict[str, Any] = field(default_factory=dict)
    usage_metadata: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)

    @property
    def raw(self) -> dict[str, Any]:
        return self.raw_response


@dataclass(slots=True)
class LightweightChatChunk:
    content: Any = ""
    additional_kwargs: dict[str, Any] = field(default_factory=dict)
    response_metadata: dict[str, Any] = field(default_factory=dict)
    usage_metadata: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)
    raw_tool_call_chunks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def raw(self) -> dict[str, Any]:
        return self.raw_response

    def __add__(self, other: Any) -> "LightweightChatChunk":
        if not isinstance(other, LightweightChatChunk):
            return LightweightChatChunk(
                content=_stringify_content(self.content) + _stringify_content(getattr(other, "content", other)),
                additional_kwargs=dict(self.additional_kwargs),
                response_metadata=dict(self.response_metadata),
                usage_metadata=dict(self.usage_metadata),
                tool_calls=[dict(item) for item in self.tool_calls],
                provider=self.provider,
                model=self.model,
                raw_response=dict(self.raw_response),
                raw_tool_call_chunks=[dict(item) for item in self.raw_tool_call_chunks],
            )

        additional_kwargs = {**dict(self.additional_kwargs), **dict(other.additional_kwargs)}
        reasoning_content = _stringify_content(dict(self.additional_kwargs).get("reasoning_content")) + _stringify_content(
            dict(other.additional_kwargs).get("reasoning_content")
        )
        if reasoning_content:
            additional_kwargs["reasoning_content"] = reasoning_content

        raw_tool_call_chunks = _merge_tool_call_chunks(_chunk_fragments(self), _chunk_fragments(other))
        return LightweightChatChunk(
            content=_stringify_content(self.content) + _stringify_content(other.content),
            additional_kwargs=additional_kwargs,
            response_metadata={**dict(self.response_metadata), **dict(other.response_metadata)},
            usage_metadata={**dict(self.usage_metadata), **dict(other.usage_metadata)},
            tool_calls=_normalize_provider_tool_calls(raw_tool_call_chunks),
            provider=self.provider or other.provider,
            model=self.model or other.model,
            raw_response=dict(other.raw_response or self.raw_response),
            raw_tool_call_chunks=raw_tool_call_chunks,
        )


class LightweightChatModel:
    """Small OpenAI-compatible chat client used by ModelRuntime."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        api_key: str | None,
        base_url: str,
        timeout_seconds: float,
        max_output_tokens: int | None,
        output_token_parameter: str,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        extra_body: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        default_headers: dict[str, str] | None = None,
        tools: list[Any] | None = None,
        tool_bind_kwargs: dict[str, Any] | None = None,
        http_async_client: httpx.AsyncClient | None = None,
        owns_client: bool = True,
    ) -> None:
        self.provider = str(provider or "").strip().lower()
        self.model = str(model or "").strip()
        self.api_key = str(api_key or "").strip()
        self.base_url = str(base_url or "").strip()
        self.timeout_seconds = max(0.01, float(timeout_seconds or 0.01))
        self.max_output_tokens = max_output_tokens
        self.output_token_parameter = str(output_token_parameter or "max_tokens").strip() or "max_tokens"
        self.temperature = temperature
        self.reasoning_effort = str(reasoning_effort or "").strip()
        self.extra_body = dict(extra_body or {})
        self.response_format = dict(response_format or {})
        self.default_headers = dict(default_headers or {})
        self.tools = list(tools or [])
        self.tool_bind_kwargs = dict(tool_bind_kwargs or {})
        self.http_async_client = http_async_client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout_seconds, connect=min(20.0, self.timeout_seconds)),
            follow_redirects=True,
        )
        self._owns_client = bool(owns_client if http_async_client is None else owns_client)

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "LightweightChatModel":
        return LightweightChatModel(
            provider=self.provider,
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            timeout_seconds=self.timeout_seconds,
            max_output_tokens=self.max_output_tokens,
            output_token_parameter=self.output_token_parameter,
            temperature=self.temperature,
            reasoning_effort=self.reasoning_effort,
            extra_body=dict(self.extra_body),
            response_format=dict(self.response_format),
            default_headers=dict(self.default_headers),
            tools=list(tools or []),
            tool_bind_kwargs=dict(kwargs or {}),
            http_async_client=self.http_async_client,
            owns_client=False,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self.http_async_client.aclose()

    async def ainvoke(self, messages: list[Any]) -> LightweightChatMessage:
        body = self._request_body(messages, stream=False)
        response = await self.http_async_client.post(
            self._chat_completions_url(),
            headers=self._headers(),
            json=body,
        )
        await _raise_for_provider_status(response)
        data = response.json()
        return _message_from_completion_response(data, provider=self.provider, fallback_model=self.model)

    async def astream(self, messages: list[Any]) -> AsyncIterator[LightweightChatChunk]:
        body = self._request_body(messages, stream=True)
        async with self.http_async_client.stream(
            "POST",
            self._chat_completions_url(),
            headers=self._headers(),
            json=body,
        ) as response:
            await _raise_for_provider_status(response)
            async for line in response.aiter_lines():
                payload = _sse_payload_from_line(line)
                if payload is None:
                    continue
                if payload == "[DONE]":
                    return
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                chunk = _chunk_from_stream_response(data, provider=self.provider, fallback_model=self.model)
                if chunk is not None:
                    yield chunk

    def _request_body(self, messages: list[Any], *, stream: bool) -> dict[str, Any]:
        tool_payloads = provider_tool_payloads(self.tools, strict=self.tool_bind_kwargs.get("strict"))
        body: dict[str, Any] = {
            "model": self.model,
        }
        if self.max_output_tokens is not None:
            body[self.output_token_parameter] = max(1, int(self.max_output_tokens or 1))
        if self.temperature is not None:
            body["temperature"] = float(self.temperature)
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        if self.response_format:
            body["response_format"] = dict(self.response_format)
        if self.extra_body:
            body.update(copy.deepcopy(self.extra_body))
        body["stream"] = bool(stream)
        if stream:
            body["stream_options"] = {"include_usage": True}

        if tool_payloads:
            body["tools"] = tool_payloads
            for key in ("tool_choice", "parallel_tool_calls"):
                if key in self.tool_bind_kwargs and self.tool_bind_kwargs.get(key) is not None:
                    body[key] = self.tool_bind_kwargs[key]
        body["messages"] = [_message_to_provider_payload(message) for message in list(messages or [])]
        return body

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", **dict(self.default_headers)}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _chat_completions_url(self) -> str:
        base_url = self.base_url.rstrip("/")
        if not base_url:
            raise RuntimeError(f"Missing base_url for provider {self.provider}")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"


class LightweightConversationAgent:
    def __init__(self, *, model: Any, tools: list[Any], system_prompt: str) -> None:
        self.model = model
        self.tools = list(tools or [])
        self.system_prompt = str(system_prompt or "")

    async def astream(self, payload: dict[str, Any], *, stream_mode: list[str] | None = None) -> AsyncIterator[Any]:
        messages = [{"role": "system", "content": self.system_prompt}, *list(dict(payload or {}).get("messages") or [])]
        bound_model = self.model.bind_tools(self.tools) if self.tools else self.model
        async for chunk in bound_model.astream(messages):
            if stream_mode:
                yield {"messages": [chunk]}
            else:
                yield chunk


def provider_tool_payloads(tools: list[Any], *, strict: Any = None) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for tool in list(tools or []):
        name = _tool_name(tool)
        if not name:
            continue
        parameters = _tool_parameters_schema(tool)
        function_payload: dict[str, Any] = {
            "name": name,
            "description": _tool_description(tool, fallback=name),
            "parameters": parameters,
        }
        if strict is not None:
            function_payload["strict"] = bool(strict)
        payloads.append({"type": "function", "function": function_payload})
    return sorted(payloads, key=lambda item: str(dict(item.get("function") or {}).get("name") or ""))


def provider_message_payloads(messages: list[Any]) -> list[dict[str, Any]]:
    return [_message_to_provider_payload(message) for message in list(messages or [])]


def _message_from_completion_response(
    data: dict[str, Any],
    *,
    provider: str,
    fallback_model: str,
) -> LightweightChatMessage:
    choices = list(data.get("choices") or [])
    choice = dict(choices[0] or {}) if choices else {}
    message = dict(choice.get("message") or {})
    usage = dict(data.get("usage") or {})
    response_metadata = {
        "id": str(data.get("id") or ""),
        "model": str(data.get("model") or fallback_model),
        "model_name": str(data.get("model") or fallback_model),
        "finish_reason": str(choice.get("finish_reason") or ""),
        "token_usage": usage,
        "usage": usage,
    }
    additional_kwargs: dict[str, Any] = {"provider": provider}
    reasoning_content = _first_text_preserving_whitespace(
        message.get("reasoning_content"),
        message.get("reasoning"),
        dict(message.get("additional_kwargs") or {}).get("reasoning_content")
        if isinstance(message.get("additional_kwargs"), dict)
        else "",
    )
    if reasoning_content:
        additional_kwargs["reasoning_content"] = reasoning_content
    raw_tool_calls = list(message.get("tool_calls") or [])
    tool_calls = _normalize_provider_tool_calls(raw_tool_calls)
    if raw_tool_calls:
        additional_kwargs["tool_calls"] = copy.deepcopy(raw_tool_calls)
    return LightweightChatMessage(
        content=message.get("content") or "",
        additional_kwargs=additional_kwargs,
        response_metadata=response_metadata,
        usage_metadata=usage,
        tool_calls=tool_calls,
        provider=provider,
        model=str(data.get("model") or fallback_model),
        raw_response=dict(data),
    )


def _chunk_from_stream_response(
    data: dict[str, Any],
    *,
    provider: str,
    fallback_model: str,
) -> LightweightChatChunk | None:
    choices = list(data.get("choices") or [])
    usage = dict(data.get("usage") or {})
    if not choices and not usage:
        return None
    choice = dict(choices[0] or {}) if choices else {}
    delta = dict(choice.get("delta") or {})
    response_metadata = {
        "id": str(data.get("id") or ""),
        "model": str(data.get("model") or fallback_model),
        "model_name": str(data.get("model") or fallback_model),
        "finish_reason": str(choice.get("finish_reason") or ""),
        "token_usage": usage,
        "usage": usage,
    }
    additional_kwargs: dict[str, Any] = {"provider": provider}
    reasoning_content = _first_text_preserving_whitespace(delta.get("reasoning_content"), delta.get("reasoning"))
    if reasoning_content:
        additional_kwargs["reasoning_content"] = reasoning_content
    raw_tool_call_chunks = _provider_tool_call_chunks(delta.get("tool_calls"))
    if raw_tool_call_chunks:
        additional_kwargs["tool_calls"] = copy.deepcopy(raw_tool_call_chunks)
    return LightweightChatChunk(
        content=delta.get("content") or "",
        additional_kwargs=additional_kwargs,
        response_metadata=response_metadata,
        usage_metadata=usage,
        tool_calls=_normalize_provider_tool_calls(raw_tool_call_chunks),
        provider=provider,
        model=str(data.get("model") or fallback_model),
        raw_response=dict(data),
        raw_tool_call_chunks=raw_tool_call_chunks,
    )


def _message_to_provider_payload(message: Any) -> dict[str, Any]:
    item = dict(message) if isinstance(message, dict) else _object_message_payload(message)
    passthrough = _provider_payload_passthrough(item)
    if passthrough is not None:
        return passthrough
    role = _provider_role(item.get("role") or item.get("type") or item.get("message_type") or "")
    payload: dict[str, Any] = {
        "role": role,
        "content": _serializable_content(item.get("content")),
    }
    for key in ("name", "tool_call_id"):
        value = str(item.get(key) or "").strip()
        if value:
            payload[key] = value
    if role == "assistant":
        additional_kwargs = dict(item.get("additional_kwargs") or {}) if isinstance(item.get("additional_kwargs"), dict) else {}
        reasoning_content = _first_text_preserving_whitespace(
            item.get("reasoning_content"),
            additional_kwargs.get("reasoning_content"),
        )
        if reasoning_content:
            payload["reasoning_content"] = reasoning_content
        prefix = item.get("prefix")
        if prefix is None:
            prefix = additional_kwargs.get("prefix")
        if prefix is True or str(prefix or "").strip().lower() == "true":
            payload["prefix"] = True
        tool_calls = item.get("tool_calls")
        if tool_calls is None:
            tool_calls = additional_kwargs.get("tool_calls")
        provider_calls = _provider_tool_calls_from_normalized(tool_calls)
        if provider_calls:
            payload["tool_calls"] = provider_calls
    return payload


def _provider_payload_passthrough(item: dict[str, Any]) -> dict[str, Any] | None:
    role = str(item.get("role") or "").strip()
    if role not in {"system", "user", "assistant", "tool"}:
        return None
    if isinstance(item.get("additional_kwargs"), dict) and dict(item.get("additional_kwargs") or {}):
        return None
    tool_calls = item.get("tool_calls")
    if tool_calls and not _provider_shaped_tool_calls(tool_calls):
        return None
    payload: dict[str, Any] = {
        "role": role,
        "content": _serializable_content(item.get("content")),
    }
    for key in ("name", "tool_call_id"):
        value = str(item.get(key) or "").strip()
        if value:
            payload[key] = value
    if role == "assistant":
        reasoning_content = _first_text_preserving_whitespace(item.get("reasoning_content"))
        if reasoning_content:
            payload["reasoning_content"] = reasoning_content
        if item.get("prefix") is True or str(item.get("prefix") or "").strip().lower() == "true":
            payload["prefix"] = True
        if tool_calls:
            payload["tool_calls"] = [copy.deepcopy(dict(call)) for call in tool_calls if isinstance(call, dict)]
    return payload


def _provider_shaped_tool_calls(value: Any) -> bool:
    calls = _as_list(value)
    if not calls:
        return False
    for raw in calls:
        if not isinstance(raw, dict):
            return False
        item = dict(raw)
        function = item.get("function")
        if str(item.get("type") or "") != "function" or not isinstance(function, dict):
            return False
        if not str(item.get("id") or "").strip():
            return False
        if not str(function.get("name") or "").strip():
            return False
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            return False
    return True


def _object_message_payload(message: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in (
        "role",
        "type",
        "message_type",
        "content",
        "name",
        "tool_call_id",
        "tool_calls",
        "additional_kwargs",
        "reasoning_content",
        "prefix",
    ):
        value = getattr(message, key, None)
        if value is not None:
            payload[key] = value
    if "role" not in payload and "type" not in payload:
        payload["role"] = message.__class__.__name__
    return payload


def _provider_role(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"human", "humanmessage"}:
        return "user"
    if normalized in {"ai", "aimessage", "assistantmessage"}:
        return "assistant"
    if normalized in {"systemmessage"}:
        return "system"
    if normalized in {"toolmessage"}:
        return "tool"
    if normalized in {"system", "user", "assistant", "tool"}:
        return normalized
    return "user"


def _serializable_content(value: Any) -> Any:
    if isinstance(value, list):
        result: list[Any] = []
        for item in value:
            if isinstance(item, dict):
                result.append(copy.deepcopy(item))
            elif isinstance(item, str):
                result.append({"type": "text", "text": item})
        return result
    if isinstance(value, (str, int, float, bool)) or value is None:
        return "" if value is None else value
    return str(value)


def _tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        return str(tool.get("name") or tool.get("tool_name") or "").strip()
    return str(getattr(tool, "name", "") or "").strip()


def _tool_description(tool: Any, *, fallback: str) -> str:
    if isinstance(tool, dict):
        return str(tool.get("description") or tool.get("display_name") or fallback)
    capability_definition = getattr(tool, "capability_definition", None)
    return str(
        getattr(tool, "description", "")
        or getattr(capability_definition, "description", "")
        or getattr(capability_definition, "display_name", "")
        or fallback
    )


def _tool_parameters_schema(tool: Any) -> dict[str, Any]:
    if isinstance(tool, dict):
        schema = tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else tool.get("parameters")
        if isinstance(schema, dict) and schema:
            return _json_schema_object(schema)
        return _schema_from_contract(
            required_inputs=list(tool.get("required_inputs") or []),
            optional_inputs=list(tool.get("optional_inputs") or []),
        )

    for schema_source in (getattr(tool, "input_schema", None), getattr(tool, "args_schema", None)):
        schema = _schema_from_schema_source(schema_source)
        if schema:
            return _json_schema_object(schema)

    capability_definition = getattr(tool, "capability_definition", None)
    contract = getattr(capability_definition, "contract", None)
    return _schema_from_contract(
        required_inputs=list(getattr(contract, "required_inputs", []) or []),
        optional_inputs=list(getattr(contract, "optional_inputs", []) or []),
    )


def _schema_from_schema_source(schema_source: Any) -> dict[str, Any]:
    if schema_source is None:
        return {}
    if isinstance(schema_source, dict):
        return dict(schema_source)
    for method_name in ("model_json_schema", "schema"):
        method = getattr(schema_source, method_name, None)
        if callable(method):
            try:
                schema = method()
            except Exception:
                continue
            if isinstance(schema, dict):
                return dict(schema)
    return {}


def _schema_from_contract(*, required_inputs: list[Any], optional_inputs: list[Any]) -> dict[str, Any]:
    required = [str(item).strip() for item in required_inputs if str(item).strip()]
    optional = [str(item).strip() for item in optional_inputs if str(item).strip()]
    properties = {name: {"type": "string"} for name in [*required, *optional]}
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def _json_schema_object(schema: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(schema)
    payload.setdefault("type", "object")
    payload.setdefault("properties", {})
    if not isinstance(payload.get("properties"), dict):
        payload["properties"] = {}
    required = payload.get("required")
    payload["required"] = [str(item) for item in list(required or []) if str(item)]
    return payload


def _provider_tool_calls_from_normalized(tool_calls: Any) -> list[dict[str, Any]]:
    provider_calls: list[dict[str, Any]] = []
    for index, raw in enumerate(_as_list(tool_calls), start=1):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        function = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = str(item.get("name") or function.get("name") or "").strip()
        if not name:
            continue
        args = item.get("args")
        if args is None:
            args = item.get("arguments")
        if args is None:
            args = function.get("arguments")
        arguments = args if isinstance(args, str) else json.dumps(dict(args or {}), ensure_ascii=False)
        provider_calls.append(
            {
                "id": str(
                    item.get("id")
                    or item.get("call_id")
                    or _deterministic_provider_tool_call_id(
                        name=name,
                        arguments=arguments,
                        index=index,
                    )
                ),
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": arguments,
                },
            }
        )
    return provider_calls


def _provider_tool_call_chunks(raw_tool_calls: Any) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for index, raw in enumerate(_as_list(raw_tool_calls)):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        function = item.get("function") if isinstance(item.get("function"), dict) else {}
        chunks.append(
            {
                "index": int(item.get("index") if item.get("index") is not None else index),
                "id": str(item.get("id") or ""),
                "type": str(item.get("type") or "function"),
                "name": str(item.get("name") or function.get("name") or ""),
                "arguments": str(item.get("arguments") or function.get("arguments") or ""),
            }
        )
    return chunks


def _deterministic_provider_tool_call_id(*, name: str, arguments: str, index: int) -> str:
    seed = {
        "index": max(1, int(index or 1)),
        "name": str(name or ""),
        "arguments": _tool_call_arguments_identity(arguments),
    }
    digest = hashlib.sha256(
        json.dumps(seed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8",
            errors="ignore",
        )
    ).hexdigest()[:24]
    return f"call_{digest}"


def _tool_call_arguments_identity(arguments: Any) -> Any:
    if isinstance(arguments, str):
        text = arguments
        if text.strip():
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return text
            if isinstance(parsed, dict):
                return _json_stable(parsed)
        return text
    if isinstance(arguments, dict):
        return _json_stable(arguments)
    return str(arguments or "")


def _merge_tool_call_chunks(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    order: list[int] = []
    for raw in [*left, *right]:
        if not isinstance(raw, dict):
            continue
        index = int(raw.get("index") if raw.get("index") is not None else len(order))
        if index not in merged:
            merged[index] = {"index": index, "id": "", "type": "function", "name": "", "arguments": ""}
            order.append(index)
        current = merged[index]
        if raw.get("id"):
            current["id"] = str(raw.get("id") or current.get("id") or "")
        if raw.get("type"):
            current["type"] = str(raw.get("type") or current.get("type") or "function")
        if raw.get("name"):
            current["name"] = str(raw.get("name") or current.get("name") or "")
        if raw.get("arguments"):
            current["arguments"] = str(current.get("arguments") or "") + str(raw.get("arguments") or "")
    return [merged[index] for index in sorted(order)]


def _normalize_provider_tool_calls(raw_tool_calls: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for index, raw in enumerate(_as_list(raw_tool_calls), start=1):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        function = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = str(item.get("name") or function.get("name") or "").strip()
        args = item.get("args")
        if args is None:
            args = item.get("arguments")
        if args is None:
            args = function.get("arguments")
        if not name:
            name = str(function.get("name") or "").strip()
        if not name:
            continue
        calls.append(
            {
                "id": str(item.get("id") or item.get("call_id") or f"tool-call-{index}").strip(),
                "name": name,
                "args": _parse_args(args),
                "type": "tool_call",
            }
        )
    return calls


def _chunk_fragments(chunk: LightweightChatChunk) -> list[dict[str, Any]]:
    if chunk.raw_tool_call_chunks:
        return [dict(item) for item in chunk.raw_tool_call_chunks]
    return _tool_calls_to_chunks(chunk.tool_calls)


def _tool_calls_to_chunks(tool_calls: Any) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for index, call in enumerate(_as_list(tool_calls)):
        if not isinstance(call, dict):
            continue
        chunks.append(
            {
                "index": index,
                "id": str(call.get("id") or call.get("call_id") or ""),
                "type": "function",
                "name": str(call.get("name") or ""),
                "arguments": json.dumps(dict(call.get("args") or {}), ensure_ascii=False),
            }
        )
    return chunks


def _parse_args(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return [value]
    return []


def _sse_payload_from_line(line: str) -> str | None:
    text = str(line or "").strip()
    if not text:
        return None
    if text.startswith(":") or text.startswith("event:"):
        return None
    if text.startswith("data:"):
        return text.removeprefix("data:").strip()
    if text.startswith("{"):
        return text
    return None


async def _raise_for_provider_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    try:
        text = (await response.aread()).decode("utf-8", errors="replace")
    except Exception:
        text = ""
    detail = " ".join(text.split())[:1000]
    raise RuntimeError(f"Provider request failed with HTTP {response.status_code}: {detail}")


def _first_text(*values: Any) -> str:
    for value in values:
        text = _stringify_content(value).strip()
        if text:
            return text
    return ""


def _first_text_preserving_whitespace(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = _stringify_content(value)
        if text != "":
            return text
    return ""


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, dict) and block.get("text") is not None:
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return str(content or "")
