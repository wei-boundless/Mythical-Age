from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from prompt_cache_policy import is_cache_eligible_prefix, normalize_cache_role, normalize_compression_role, normalize_prefix_tier

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
        provider_payload_manifest = _model_request_provider_payload_manifest(model_request)
        provider_tool_segment = _provider_payload_tool_segment(provider_payload_manifest)
        tool_schema_profile = provider_tool_segment or _unmanifested_tool_schema_profile(
            normalized_tools=normalized_tools,
            has_provider_payload_manifest=bool(provider_payload_manifest),
        )
        tool_schema_inserted = False
        message_transport_prefix_open = True
        segments: list[PromptSegment] = []
        ordinal = 0

        def append_tool_schema_segment() -> None:
            nonlocal ordinal, tool_schema_inserted
            if tool_schema_inserted or not normalized_tools:
                return
            ordinal += 1
            segment_payload = canonical_json({"tools": normalized_tools})
            token_count = self.token_counter.count_text(segment_payload, provider=provider, model=model)
            tool_schema_metadata = dict(tool_schema_profile.get("metadata") or {})
            message_prefix_eligible_component = bool(
                normalized_tools
                and is_cache_eligible_prefix(
                    cache_role=str(tool_schema_profile.get("cache_role") or ""),
                    prefix_tier=str(tool_schema_profile.get("prefix_tier") or ""),
                )
            )
            stable_transport_contract = bool(
                tool_schema_metadata.get("stable_transport_contract")
                or str(tool_schema_metadata.get("transport_contract_role") or "") == "stable_transport_contract"
                or tool_schema_metadata.get("provider_payload_stable_component") is True
            )
            stable_tool_schema_component = bool(normalized_tools and (message_prefix_eligible_component or stable_transport_contract))
            tool_schema_prefix_component = bool(message_prefix_eligible_component and message_transport_prefix_open)
            segments.append(
                PromptSegment(
                    segment_id=_segment_id(request_id, ordinal, str(tool_schema_profile.get("kind") or "tool_schema_catalog"), segment_payload),
                    request_id=request_id,
                    run_id=canonical_run_id,
                    task_run_id=str(task_run_id or ""),
                    session_id=str(session_id or ""),
                    kind=str(tool_schema_profile.get("kind") or "tool_schema_catalog"),
                    ordinal=ordinal,
                    role="tool_schema",
                    content_hash=stable_text_hash(segment_payload),
                    byte_length=len(segment_payload.encode("utf-8", errors="ignore")),
                    predicted_tokens=token_count.tokens,
                    cache_role=str(tool_schema_profile.get("cache_role") or "never_cache"),
                    prefix_tier=str(tool_schema_profile.get("prefix_tier") or "none"),
                    compression_role="preserve",
                    authority_class="stable_transport_contract"
                    if stable_transport_contract and not tool_schema_prefix_component
                    else "contract",
                    source=str(tool_schema_profile.get("source") or "model_request.tools"),
                    created_at=timestamp,
                    metadata={
                        "tool_count": len(normalized_tools),
                        "token_count_mode": token_count.mode,
                        "provider_payload_transport_location": "tools",
                        "provider_payload_stable_component": stable_tool_schema_component,
                        "provider_payload_prefix_component": tool_schema_prefix_component,
                        "stable_transport_contract": stable_transport_contract,
                        "transport_contract_role": "stable_transport_contract"
                        if stable_transport_contract
                        else str(tool_schema_metadata.get("transport_contract_role") or ""),
                        "message_prefix_cacheable": tool_schema_prefix_component,
                        "provider_payload_prefix_component_reason": (
                            "transport_prefix_open"
                            if tool_schema_prefix_component
                            else "tools_are_after_non_prefix_message_in_transport_order"
                        ),
                        **tool_schema_metadata,
                    },
                )
            )
            tool_schema_inserted = True

        for index, message in enumerate(normalized_messages):
            segment_payload = canonical_json(message)
            planned = planned_by_index.get(index)
            kind = str(planned.get("kind") or "unknown_unplanned") if planned else "unknown_unplanned"
            cache_role = _cache_role(planned.get("cache_role")) if planned else "never_cache"
            prefix_tier = _prefix_tier(planned.get("prefix_tier"), cache_scope=str(planned.get("cache_scope") or "none"), cache_role=cache_role) if planned else "none"
            compression_role = _compression_role(planned.get("compression_role")) if planned else "summarize"
            stable_message = is_cache_eligible_prefix(cache_role=cache_role, prefix_tier=prefix_tier)
            ordinal += 1
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
            if not stable_message:
                message_transport_prefix_open = False
        if normalized_tools and not tool_schema_inserted:
            append_tool_schema_segment()
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
        name = _tool_name(tool)
        description = _tool_description(tool)
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
            payload["tool_calls"] = _normalize_tool_calls_for_hash(message.get("tool_calls"))
        if message.get("reasoning_content"):
            _mark_reasoning_content(payload, message.get("reasoning_content"))
        else:
            _copy_reasoning_content_markers(payload, message)
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
        payload["tool_calls"] = _normalize_tool_calls_for_hash(tool_calls)
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


def _normalize_tool_calls_for_hash(value: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    raw_calls = list(value or []) if isinstance(value, (list, tuple)) else []
    for index, raw in enumerate(raw_calls, start=1):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        function = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = str(item.get("name") or function.get("name") or "").strip()
        call_id = str(item.get("id") or item.get("call_id") or f"tool-call-{index}").strip()
        args = item.get("args")
        if args is None:
            args = item.get("arguments")
        if args is None:
            args = function.get("arguments")
        calls.append(
            {
                "id": call_id,
                "name": name,
                "args": _normalize_tool_arguments(args),
            }
        )
    return _json_stable(calls)


def _normalize_tool_arguments(value: Any) -> Any:
    if isinstance(value, dict):
        return _json_stable(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(parsed, dict):
            return _json_stable(parsed)
        return parsed
    if value in (None, ""):
        return {}
    return _json_stable(value)


def _copy_reasoning_content_markers(payload: dict[str, Any], message: dict[str, Any]) -> None:
    if not bool(message.get("reasoning_content_present")):
        return
    content_hash = str(message.get("reasoning_content_hash") or "").strip()
    if not content_hash:
        return
    payload["reasoning_content_present"] = True
    payload["reasoning_content_chars"] = _int_value(message.get("reasoning_content_chars"))
    payload["reasoning_content_estimated_tokens"] = _int_value(
        message.get("reasoning_content_estimated_tokens")
    )
    payload["reasoning_content_hash"] = content_hash


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
    if isinstance(tool, dict):
        function_payload = tool.get("function")
        if isinstance(function_payload, dict):
            for key in ("parameters", "input_schema", "schema"):
                value = function_payload.get(key)
                if value:
                    return _json_stable(value)
        for key in ("input_schema", "schema", "parameters", "args_schema"):
            value = tool.get(key)
            if value:
                return _json_stable(value)
        return {}
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


def _tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        function_payload = tool.get("function")
        if isinstance(function_payload, dict):
            for key in ("name", "tool_name"):
                text = str(function_payload.get(key) or "").strip()
                if text:
                    return text
        for key in ("tool_name", "name"):
            text = str(tool.get(key) or "").strip()
            if text:
                return text
        return "dict"
    return str(getattr(tool, "name", "") or getattr(tool, "__name__", "") or type(tool).__name__)


def _tool_description(tool: Any) -> str:
    if isinstance(tool, dict):
        function_payload = tool.get("function")
        if isinstance(function_payload, dict):
            text = str(function_payload.get("description") or function_payload.get("display_name") or "").strip()
            if text:
                return text
        return str(tool.get("description") or tool.get("display_name") or "").strip()
    return str(getattr(tool, "description", "") or getattr(tool, "display_name", "") or "")


def _unmanifested_tool_schema_profile(
    *,
    normalized_tools: list[dict[str, Any]],
    has_provider_payload_manifest: bool,
) -> dict[str, Any]:
    reason = (
        "missing_provider_payload_tool_segment"
        if has_provider_payload_manifest
        else "missing_provider_payload_manifest"
    )
    return {
        "kind": "native_tool_binding_schema",
        "cache_role": "never_cache",
        "prefix_tier": "none",
        "source": "model_request.tools",
        "metadata": {
            "tool_count": len(normalized_tools),
            "cache_note": "native_tool_binding_schema_requires_provider_payload_manifest",
            "native_tool_binding_decision": "not_promoted",
            "native_tool_binding_reason": reason,
            "provider_payload_manifest_required": True,
        },
    }


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


def _model_request_provider_payload_manifest(model_request: Any | None) -> dict[str, Any]:
    if model_request is None:
        return {}
    value = getattr(model_request, "provider_payload_manifest", None)
    if value is None and isinstance(model_request, dict):
        value = model_request.get("provider_payload_manifest")
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    return dict(value or {}) if isinstance(value, dict) else {}


def _provider_payload_tool_segment(manifest: dict[str, Any]) -> dict[str, Any]:
    for item in list(dict(manifest or {}).get("segments") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("transport_location") or "") != "tools":
            continue
        metadata = dict(item.get("metadata") or {})
        return {
            "kind": str(item.get("kind") or "native_tool_binding_schema"),
            "cache_role": _cache_role(item.get("cache_role")),
            "prefix_tier": _prefix_tier(
                item.get("prefix_tier"),
                cache_scope=str(item.get("cache_scope") or "none"),
                cache_role=_cache_role(item.get("cache_role")),
            ),
            "source": str(item.get("source_ref") or "model_request.tools"),
            "metadata": {
                **metadata,
                "provider_payload_manifest_ref": str(dict(manifest or {}).get("manifest_id") or ""),
                "provider_payload_segment_id": str(item.get("segment_id") or ""),
                "provider_payload_authority": str(item.get("authority") or ""),
            },
        }
    return {}


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
                "block_id": str(binding.get("block_id") or ""),
                "slot": str(binding.get("slot") or ""),
                "semantic_role": str(binding.get("semantic_role") or ""),
                "function_cell": str(binding.get("function_cell") or ""),
                "agent_running_cycle": str(binding.get("agent_running_cycle") or ""),
                "override_strategy": str(binding.get("override_strategy") or ""),
                "volatile_reason": str(binding.get("volatile_reason") or ""),
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
        "block_id": str(planned.get("block_id") or ""),
        "slot": str(planned.get("slot") or ""),
        "semantic_role": str(planned.get("semantic_role") or ""),
        "function_cell": str(planned.get("function_cell") or ""),
        "agent_running_cycle": str(planned.get("agent_running_cycle") or ""),
        "override_strategy": str(planned.get("override_strategy") or ""),
        "volatile_reason": str(planned.get("volatile_reason") or ""),
        "planned_content_hash": str(planned.get("content_hash") or planned.get("planned_content_hash") or ""),
        **metadata,
    }


def _cache_role(value: Any) -> str:
    return normalize_cache_role(value)


def _prefix_tier(value: Any, *, cache_scope: str, cache_role: str) -> str:
    return normalize_prefix_tier(value, cache_scope=cache_scope, cache_role=cache_role)


def _compression_role(value: Any) -> str:
    return normalize_compression_role(value)


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
