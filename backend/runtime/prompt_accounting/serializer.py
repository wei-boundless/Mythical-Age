from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from .cache_planner import stable_text_hash
from .models import PromptSegment, PromptSegmentMap
from .token_counter import TokenCounterRegistry


def canonical_json(value: Any) -> str:
    return json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_messages(messages: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in list(messages or []):
        normalized.append(_normalize_message(message))
    return normalized


class CanonicalPromptSerializer:
    def __init__(self, token_counter: TokenCounterRegistry | None = None) -> None:
        self.token_counter = token_counter or TokenCounterRegistry()

    def build_segment_map(
        self,
        *,
        request_id: str,
        messages: list[Any],
        tools: list[Any] | None = None,
        provider: str = "",
        model: str = "",
        task_run_id: str = "",
        session_id: str = "",
        created_at: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PromptSegmentMap:
        timestamp = time.time() if created_at is None else float(created_at or 0.0)
        normalized_messages = normalize_messages(messages)
        normalized_tools = normalize_tools(list(tools or []))
        request_payload = {
            "messages": normalized_messages,
            "tools": normalized_tools,
            "metadata": dict(metadata or {}),
        }
        canonical = canonical_json(request_payload)
        segments: list[PromptSegment] = []
        ordinal = 0
        for index, message in enumerate(normalized_messages):
            ordinal += 1
            segment_payload = canonical_json(message)
            kind = _message_segment_kind(message, index=index, total=len(normalized_messages))
            cache_role = _cache_role_for_message(kind=kind, message=message, index=index)
            compression_role = _compression_role_for_kind(kind)
            token_count = self.token_counter.count_text(segment_payload, provider=provider, model=model)
            segments.append(
                PromptSegment(
                    segment_id=_segment_id(request_id, ordinal, kind, segment_payload),
                    request_id=request_id,
                    task_run_id=str(task_run_id or ""),
                    session_id=str(session_id or ""),
                    kind=kind,
                    ordinal=ordinal,
                    role=str(message.get("role") or ""),
                    content_hash=stable_text_hash(segment_payload),
                    byte_length=len(segment_payload.encode("utf-8", errors="ignore")),
                    predicted_tokens=token_count.tokens,
                    cache_role=cache_role,
                    compression_role=compression_role,
                    source=str(message.get("source") or "message"),
                    created_at=timestamp,
                    metadata={"token_count_mode": token_count.mode},
                )
            )
        if normalized_tools:
            ordinal += 1
            segment_payload = canonical_json({"tools": normalized_tools})
            token_count = self.token_counter.count_text(segment_payload, provider=provider, model=model)
            segments.append(
                PromptSegment(
                    segment_id=_segment_id(request_id, ordinal, "tool_schema", segment_payload),
                    request_id=request_id,
                    task_run_id=str(task_run_id or ""),
                    session_id=str(session_id or ""),
                    kind="tool_schema",
                    ordinal=ordinal,
                    role="tool_schema",
                    content_hash=stable_text_hash(segment_payload),
                    byte_length=len(segment_payload.encode("utf-8", errors="ignore")),
                    predicted_tokens=token_count.tokens,
                    cache_role="cacheable_prefix",
                    compression_role="preserve",
                    source="model_request.tools",
                    created_at=timestamp,
                    metadata={"tool_count": len(normalized_tools), "token_count_mode": token_count.mode},
                )
            )
        return PromptSegmentMap(
            request_id=request_id,
            task_run_id=str(task_run_id or ""),
            session_id=str(session_id or ""),
            provider=str(provider or ""),
            model=str(model or ""),
            segments=tuple(segments),
            canonical_hash=stable_text_hash(canonical),
            byte_length=len(canonical.encode("utf-8", errors="ignore")),
            predicted_prompt_tokens=sum(int(segment.predicted_tokens or 0) for segment in segments),
            created_at=timestamp,
            metadata=dict(metadata or {}),
        )


def normalize_tools(tools: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for tool in list(tools or []):
        name = str(getattr(tool, "name", "") or getattr(tool, "__name__", "") or type(tool).__name__)
        description = str(getattr(tool, "description", "") or "")
        schema = _tool_schema(tool)
        normalized.append(
            {
                "name": name,
                "description": description,
                "schema": schema,
            }
        )
    return sorted(normalized, key=lambda item: str(item.get("name") or ""))


def _normalize_message(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        role = str(message.get("role") or message.get("type") or "user")
        content = _stringify_content(message.get("content"))
        payload = {
            "role": role,
            "content": content,
        }
        for key in ("name", "tool_call_id"):
            if message.get(key):
                payload[key] = str(message.get(key) or "")
        if message.get("tool_calls"):
            payload["tool_calls"] = _json_stable(message.get("tool_calls"))
        return payload
    role = str(getattr(message, "type", "") or getattr(message, "role", "") or message.__class__.__name__).lower()
    payload = {
        "role": role,
        "content": _stringify_content(getattr(message, "content", "")),
    }
    for key in ("name", "tool_call_id"):
        value = getattr(message, key, None)
        if value:
            payload[key] = str(value)
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        payload["tool_calls"] = _json_stable(tool_calls)
    additional_kwargs = getattr(message, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict) and additional_kwargs.get("reasoning_content"):
        payload["reasoning_content_present"] = True
    return payload


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            else:
                parts.append(canonical_json(block))
        return "".join(parts)
    return str(content or "")


def _tool_schema(tool: Any) -> Any:
    for attr_name in ("args_schema", "schema", "input_schema"):
        value = getattr(tool, attr_name, None)
        if value is None:
            continue
        if callable(getattr(value, "model_json_schema", None)):
            try:
                return value.model_json_schema()
            except Exception:
                continue
        if callable(value):
            continue
        return _json_stable(value)
    for method_name in ("tool_call_schema", "get_input_schema"):
        method = getattr(tool, method_name, None)
        if not callable(method):
            continue
        try:
            result = method()
        except Exception:
            continue
        if callable(getattr(result, "model_json_schema", None)):
            try:
                return result.model_json_schema()
            except Exception:
                continue
        return _json_stable(result)
    return {}


def _message_segment_kind(message: dict[str, Any], *, index: int, total: int) -> str:
    role = str(message.get("role") or "").lower()
    content = str(message.get("content") or "")
    if role == "tool":
        return "tool_observations"
    if role == "system":
        if "Runtime Context Package" in content or "当前情境" in content:
            return "memory_context"
        if "当前 Agent 工作契约" in content or "Runtime Execution Facts" in content:
            return "task_contract"
        return "system_static" if index == 0 else "system_session"
    if role == "user" and index >= max(0, total - 1):
        return "volatile_turn"
    if role == "assistant" and message.get("tool_calls"):
        return "tool_observations"
    return "conversation_recent"


def _cache_role_for_message(*, kind: str, message: dict[str, Any], index: int) -> str:
    if kind == "system_static" and index == 0 and not _contains_volatile_fact(str(message.get("content") or "")):
        return "cacheable_prefix"
    if kind in {"system_session", "task_contract"}:
        return "session_stable"
    if kind == "memory_context":
        return "volatile"
    return "volatile"


def _compression_role_for_kind(kind: str) -> str:
    if kind in {"system_static", "tool_schema", "task_contract"}:
        return "preserve"
    if kind in {"tool_observations", "artifact_summaries"}:
        return "ref_only"
    if kind == "conversation_recent":
        return "summarize"
    return "summarize"


def _contains_volatile_fact(content: str) -> bool:
    lowered = content.lower()
    return any(marker in lowered for marker in ("current time", "当前时间", "local_time", "runtime execution facts"))


def _segment_id(request_id: str, ordinal: int, kind: str, payload: str) -> str:
    digest = hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"seg:{request_id}:{ordinal}:{kind}:{digest}"


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
