from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from .cache_planner import stable_text_hash
from .models import PromptSegment, PromptSegmentMap
from .token_counter import TokenCounterRegistry


REASONING_CONTENT_CHARS_PER_TOKEN_ESTIMATE = 4


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
        run_id: str = "",
        task_run_id: str = "",
        session_id: str = "",
        created_at: float | None = None,
        metadata: dict[str, Any] | None = None,
        segment_plan: dict[str, Any] | None = None,
        model_request: Any | None = None,
    ) -> PromptSegmentMap:
        timestamp = time.time() if created_at is None else float(created_at or 0.0)
        canonical_run_id = str(run_id or task_run_id or "")
        normalized_messages = _model_request_messages(model_request) or normalize_messages(messages)
        normalized_tools = _model_request_tools(model_request) or normalize_tools(list(tools or []))
        request_payload = {
            "messages": normalized_messages,
            "tools": normalized_tools,
        }
        canonical = canonical_json(request_payload)
        bindings = _model_request_bindings(model_request)
        plan = _model_request_segment_plan(model_request) or dict(segment_plan or {})
        planned_by_index = _bindings_by_message_index(bindings) if bindings else _plan_segments_by_message_index(plan)
        segments: list[PromptSegment] = []
        ordinal = 0
        for index, message in enumerate(normalized_messages):
            ordinal += 1
            segment_payload = canonical_json(message)
            planned = planned_by_index.get(index)
            kind = str(planned.get("kind") or "unknown_unplanned") if planned else "unknown_unplanned"
            cache_role = _cache_role(planned.get("cache_role")) if planned else "never_cache"
            prefix_tier = _prefix_tier(planned.get("prefix_tier"), cache_scope=str(planned.get("cache_scope") or "none"), cache_role=cache_role) if planned else "none"
            compression_role = _compression_role(planned.get("compression_role")) if planned else "summarize"
            authority_class = _authority_class(
                planned,
                message=message,
                kind=kind,
                compression_role=compression_role,
            )
            token_count = self.token_counter.count_text(segment_payload, provider=provider, model=model)
            reasoning_token_supplement = _reasoning_content_token_supplement(message)
            segments.append(
                PromptSegment(
                    segment_id=_segment_id(request_id, ordinal, kind, segment_payload),
                    request_id=request_id,
                    run_id=canonical_run_id,
                    task_run_id=str(task_run_id or ""),
                    session_id=str(session_id or ""),
                    kind=kind,
                    ordinal=ordinal,
                    role=str(message.get("role") or ""),
                    content_hash=stable_text_hash(segment_payload),
                    byte_length=len(segment_payload.encode("utf-8", errors="ignore")),
                    predicted_tokens=token_count.tokens + reasoning_token_supplement,
                    cache_role=cache_role,
                    prefix_tier=prefix_tier,
                    compression_role=compression_role,
                    authority_class=authority_class,
                    source=str(planned.get("source_ref") or "model_request.message") if planned else "model_request.unplanned_message",
                    created_at=timestamp,
                    metadata={
                        "token_count_mode": token_count.mode,
                        **(
                            {"reasoning_content_predicted_tokens": reasoning_token_supplement}
                            if reasoning_token_supplement
                            else {}
                        ),
                        **_planned_metadata(planned),
                    },
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
                    run_id=canonical_run_id,
                    task_run_id=str(task_run_id or ""),
                    session_id=str(session_id or ""),
                    kind="tool_schema",
                    ordinal=ordinal,
                    role="tool_schema",
                    content_hash=stable_text_hash(segment_payload),
                    byte_length=len(segment_payload.encode("utf-8", errors="ignore")),
                    predicted_tokens=token_count.tokens,
                    cache_role="never_cache",
                    compression_role="preserve",
                    authority_class="contract",
                    source="model_request.tools",
                    created_at=timestamp,
                    metadata={
                        "tool_count": len(normalized_tools),
                        "token_count_mode": token_count.mode,
                        "cache_note": "tool_schema_is_recorded_but_not_promoted_to_prefix_without_explicit_request_boundary",
                    },
                )
            )
        return PromptSegmentMap(
            request_id=request_id,
            run_id=canonical_run_id,
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
        _mark_reasoning_content(payload, message.get("reasoning_content"))
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
        _mark_reasoning_content(payload, additional_kwargs.get("reasoning_content"))
    return payload


def _mark_reasoning_content(payload: dict[str, Any], value: Any) -> None:
    reasoning_content = str(value or "")
    if not reasoning_content:
        return
    payload["reasoning_content_present"] = True
    payload["reasoning_content_chars"] = len(reasoning_content)
    payload["reasoning_content_estimated_tokens"] = _estimate_reasoning_content_tokens(len(reasoning_content))
    payload["reasoning_content_hash"] = stable_text_hash(reasoning_content)


def _estimate_reasoning_content_tokens(char_count: int) -> int:
    chars = max(0, int(char_count or 0))
    if chars <= 0:
        return 0
    return max(1, (chars + REASONING_CONTENT_CHARS_PER_TOKEN_ESTIMATE - 1) // REASONING_CONTENT_CHARS_PER_TOKEN_ESTIMATE)


def _reasoning_content_token_supplement(message: dict[str, Any]) -> int:
    if not bool(message.get("reasoning_content_present")):
        return 0
    return _estimate_reasoning_content_tokens(_int_value(message.get("reasoning_content_chars")))


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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


def _model_request_messages(model_request: Any | None) -> list[dict[str, Any]]:
    if model_request is None:
        return []
    value = getattr(model_request, "messages", None)
    if value is None and isinstance(model_request, dict):
        value = model_request.get("messages")
    return [dict(item) for item in list(value or []) if isinstance(item, dict)]


def _model_request_tools(model_request: Any | None) -> list[dict[str, Any]]:
    if model_request is None:
        return []
    value = getattr(model_request, "tools", None)
    if value is None and isinstance(model_request, dict):
        value = model_request.get("tools")
    return [dict(item) for item in list(value or []) if isinstance(item, dict)]


def _model_request_bindings(model_request: Any | None) -> list[dict[str, Any]]:
    if model_request is None:
        return []
    value = getattr(model_request, "segment_bindings", None)
    if value is None and isinstance(model_request, dict):
        value = model_request.get("segment_bindings")
    result: list[dict[str, Any]] = []
    for item in list(value or []):
        if hasattr(item, "to_dict"):
            result.append(dict(item.to_dict()))
        elif isinstance(item, dict):
            result.append(dict(item))
    return result


def _model_request_segment_plan(model_request: Any | None) -> dict[str, Any]:
    if model_request is None:
        return {}
    value = getattr(model_request, "segment_plan", None)
    if value is None and isinstance(model_request, dict):
        value = model_request.get("segment_plan")
    return dict(value or {}) if isinstance(value, dict) else {}


def _bindings_by_message_index(bindings: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for binding in bindings:
        index = _int(binding.get("model_message_index"), default=-1)
        if index < 0:
            continue
        result[index] = {
            "kind": str(binding.get("kind") or "unknown_unplanned"),
            "cache_role": _cache_role(binding.get("cache_role")),
            "prefix_tier": _prefix_tier(
                binding.get("prefix_tier"),
                cache_scope=str(binding.get("cache_scope") or "none"),
                cache_role=_cache_role(binding.get("cache_role")),
            ),
            "cache_scope": str(binding.get("cache_scope") or "none"),
            "compression_role": _compression_role(binding.get("compression_role")),
            "source_ref": str(binding.get("source_ref") or ""),
            "metadata": {
                "planned_segment_id": str(binding.get("planned_segment_id") or ""),
                "planned_content_hash": str(binding.get("planned_content_hash") or ""),
                "planned_model_message_hash": str(binding.get("planned_model_message_hash") or ""),
                "request_content_hash": str(binding.get("request_content_hash") or ""),
                **dict(binding.get("metadata") or {}),
            },
        }
    return result


def _plan_segments_by_message_index(segment_plan: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for segment in list(segment_plan.get("segments") or []):
        if not isinstance(segment, dict):
            continue
        index = _int(segment.get("model_message_index"), default=-1)
        if index < 0:
            continue
        result[index] = dict(segment)
    return result


def _planned_metadata(planned: dict[str, Any] | None) -> dict[str, Any]:
    if not planned:
        return {"planned": False}
    metadata = dict(planned.get("metadata") or {})
    return {
        "planned": True,
        "planned_segment_id": str(planned.get("segment_id") or planned.get("planned_segment_id") or ""),
        "planned_content_hash": str(planned.get("content_hash") or planned.get("planned_content_hash") or ""),
        **metadata,
    }


def _cache_role(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized in {"cacheable_prefix", "session_stable", "volatile", "never_cache"}:
        return normalized
    return "volatile"


def _prefix_tier(value: Any, *, cache_scope: str, cache_role: str) -> str:
    normalized = str(value or "").strip()
    if normalized in {"provider_global", "session", "task", "volatile", "none"}:
        return normalized
    if cache_role == "cacheable_prefix":
        return "provider_global"
    if cache_role == "session_stable":
        scope = str(cache_scope or "").strip()
        if scope == "task":
            return "task"
        if scope == "session":
            return "session"
        if scope == "global":
            return "provider_global"
        return "session"
    if cache_role == "volatile":
        return "volatile"
    return "none"


def _compression_role(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized in {"preserve", "summarize", "drop_if_cold", "ref_only"}:
        return normalized
    return "summarize"


def _authority_class(
    planned: dict[str, Any] | None,
    *,
    message: dict[str, Any],
    kind: str,
    compression_role: str,
) -> str:
    raw = ""
    if planned:
        raw = str(planned.get("authority_class") or dict(planned.get("metadata") or {}).get("authority_class") or "")
    if raw in {
        "contract",
        "permission",
        "current_user_intent",
        "runtime_state",
        "evidence_ref",
        "natural_history",
        "bulk_output",
        "unknown",
    }:
        return raw
    normalized_kind = str(kind or "").lower()
    if compression_role == "preserve":
        if "permission" in normalized_kind:
            return "permission"
        if "runtime" in normalized_kind or "state" in normalized_kind:
            return "runtime_state"
        return "contract"
    if str(message.get("role") or "") == "user":
        return "current_user_intent"
    if "tool" in normalized_kind or compression_role in {"drop_if_cold", "ref_only"}:
        return "bulk_output"
    if "retrieval" in normalized_kind or "evidence" in normalized_kind:
        return "evidence_ref"
    if "runtime" in normalized_kind or "state" in normalized_kind:
        return "runtime_state"
    return "natural_history"


def _int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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
