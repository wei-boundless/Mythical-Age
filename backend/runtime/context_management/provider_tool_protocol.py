from __future__ import annotations

import hashlib
import json
from typing import Any


PROVIDER_TOOL_PROTOCOL_UNIT = "provider_native_tool_round"
PROVIDER_TOOL_PROTOCOL_AUTHORITY = "runtime.context_management.provider_tool_protocol"


def annotate_provider_tool_round_specs(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    source: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    result = [dict(item) for item in list(specs or []) if isinstance(item, dict)]
    round_count = 0
    annotated_spec_count = 0
    index = 0
    while index < len(result):
        message = spec_model_message(result[index])
        if str(message.get("role") or "").strip() != "assistant":
            index += 1
            continue
        tool_call_ids = assistant_tool_call_ids(message)
        if not tool_call_ids:
            index += 1
            continue
        tool_indexes: dict[str, int] = {}
        cursor = index + 1
        while cursor < len(result) and len(tool_indexes) < len(tool_call_ids):
            tool_message = spec_model_message(result[cursor])
            if str(tool_message.get("role") or "").strip() != "tool":
                break
            tool_call_id = str(tool_message.get("tool_call_id") or "").strip()
            if tool_call_id not in tool_call_ids or tool_call_id in tool_indexes:
                break
            tool_indexes[tool_call_id] = cursor
            cursor += 1
        if set(tool_call_ids).issubset(set(tool_indexes)):
            round_id = provider_tool_round_id(message, tool_call_ids=tool_call_ids)
            result[index] = with_provider_tool_protocol_metadata(
                result[index],
                round_id=round_id,
                round_member_role="assistant",
                round_order=0,
                tool_call_ids=tool_call_ids,
                source=source,
            )
            annotated_spec_count += 1
            for order, tool_call_id in enumerate(tool_call_ids, start=1):
                tool_index = tool_indexes[tool_call_id]
                result[tool_index] = with_provider_tool_protocol_metadata(
                    result[tool_index],
                    round_id=round_id,
                    round_member_role="tool",
                    round_order=order,
                    tool_call_ids=tool_call_ids,
                    tool_call_id=tool_call_id,
                    source=source,
                )
                annotated_spec_count += 1
            round_count += 1
            index = cursor
            continue
        index += 1
    return result, {
        "source": str(source or ""),
        "annotated_provider_tool_round_count": round_count,
        "annotated_provider_tool_round_spec_count": annotated_spec_count,
        "authority": PROVIDER_TOOL_PROTOCOL_AUTHORITY,
    }


def with_provider_tool_protocol_metadata(
    spec: dict[str, Any],
    *,
    round_id: str,
    round_member_role: str,
    round_order: int,
    tool_call_ids: list[str] | tuple[str, ...],
    tool_call_id: str = "",
    source: str = "",
) -> dict[str, Any]:
    payload = dict(spec or {})
    metadata = dict(payload.get("metadata") or {})
    protocol = {
        "unit": PROVIDER_TOOL_PROTOCOL_UNIT,
        "round_id": str(round_id or ""),
        "round_member_role": str(round_member_role or ""),
        "round_order": int(round_order or 0),
        "tool_call_ids": [str(item) for item in list(tool_call_ids or []) if str(item or "")],
        "tool_call_id": str(tool_call_id or ""),
        "complete": True,
        "source": str(source or ""),
        "authority": PROVIDER_TOOL_PROTOCOL_AUTHORITY,
    }
    metadata["provider_tool_protocol"] = protocol
    payload["metadata"] = metadata
    return payload


def provider_tool_protocol_from_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    protocol = dict(dict(metadata or {}).get("provider_tool_protocol") or {})
    if str(protocol.get("unit") or "").strip() != PROVIDER_TOOL_PROTOCOL_UNIT:
        return {}
    round_id = str(protocol.get("round_id") or "").strip()
    round_member_role = str(protocol.get("round_member_role") or "").strip()
    if not round_id or round_member_role not in {"assistant", "tool"}:
        return {}
    return {
        "unit": PROVIDER_TOOL_PROTOCOL_UNIT,
        "round_id": round_id,
        "round_member_role": round_member_role,
        "round_order": _safe_int(protocol.get("round_order")),
        "round_start_entry_index": _safe_int(protocol.get("round_start_entry_index")),
        "tool_call_ids": [str(item) for item in list(protocol.get("tool_call_ids") or []) if str(item or "")],
        "tool_call_id": str(protocol.get("tool_call_id") or "").strip(),
        "complete": bool(protocol.get("complete") is True),
        "source": str(protocol.get("source") or ""),
        "authority": str(protocol.get("authority") or PROVIDER_TOOL_PROTOCOL_AUTHORITY),
    }


def provider_tool_protocol_from_entry(entry: dict[str, Any] | None) -> dict[str, Any]:
    return provider_tool_protocol_from_metadata({"provider_tool_protocol": dict(dict(entry or {}).get("provider_tool_protocol") or {})})


def provider_tool_protocol_order(metadata: dict[str, Any] | None, *, fallback_entry_index: int = 0) -> tuple[int, int, int]:
    protocol = provider_tool_protocol_from_metadata(metadata)
    if not protocol:
        entry_index = _safe_int(dict(metadata or {}).get("provider_visible_append_entry_index") or fallback_entry_index)
        return (entry_index, 0, entry_index)
    round_start = _safe_int(protocol.get("round_start_entry_index"))
    if round_start <= 0:
        round_start = _safe_int(dict(metadata or {}).get("provider_visible_append_entry_index") or fallback_entry_index)
    return (
        round_start,
        _safe_int(protocol.get("round_order")),
        _safe_int(dict(metadata or {}).get("provider_visible_append_entry_index") or fallback_entry_index),
    )


def provider_tool_round_id(message: dict[str, Any], *, tool_call_ids: list[str] | tuple[str, ...]) -> str:
    seed = {
        "unit": PROVIDER_TOOL_PROTOCOL_UNIT,
        "tool_call_ids": [str(item) for item in list(tool_call_ids or []) if str(item or "")],
        "assistant_tool_calls_hash": _stable_json_hash(dict(message or {}).get("tool_calls") or []),
    }
    return "ptround:" + _stable_json_hash(seed).split(":", 1)[-1][:24]


def spec_model_message(spec: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(spec or {})
    message = dict(payload.get("model_message") or {})
    if message:
        return message
    return {
        "role": str(payload.get("role") or "user"),
        "content": str(payload.get("content") or ""),
    }


def assistant_tool_call_ids(message: dict[str, Any] | None) -> list[str]:
    payload = dict(message or {})
    ids: list[str] = []
    for raw_call in list(payload.get("tool_calls") or []):
        if not isinstance(raw_call, dict):
            continue
        call_id = str(dict(raw_call).get("id") or "").strip()
        if call_id and call_id not in ids:
            ids.append(call_id)
    return ids


def closed_provider_tool_round_entries(
    entries: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    round_id: str,
) -> list[dict[str, Any]]:
    grouped = [
        dict(item)
        for item in list(entries or [])
        if provider_tool_protocol_from_entry(dict(item)).get("round_id") == str(round_id or "").strip()
    ]
    if not grouped:
        return []
    assistant_entries = [
        item
        for item in grouped
        if provider_tool_protocol_from_entry(item).get("round_member_role") == "assistant"
    ]
    if len(assistant_entries) != 1:
        return []
    assistant = dict(assistant_entries[0])
    message = dict(assistant.get("provider_visible_message") or {})
    expected = assistant_tool_call_ids(message) or provider_tool_protocol_from_entry(assistant).get("tool_call_ids") or []
    expected_ids = [str(item) for item in list(expected or []) if str(item or "")]
    if not expected_ids or len(expected_ids) != len(set(expected_ids)):
        return []
    tool_by_id: dict[str, dict[str, Any]] = {}
    for item in grouped:
        protocol = provider_tool_protocol_from_entry(item)
        if protocol.get("round_member_role") != "tool":
            continue
        tool_message = dict(item.get("provider_visible_message") or {})
        tool_call_id = str(tool_message.get("tool_call_id") or protocol.get("tool_call_id") or "").strip()
        if tool_call_id not in expected_ids or tool_call_id in tool_by_id:
            return []
        tool_by_id[tool_call_id] = item
    if not set(expected_ids).issubset(set(tool_by_id)):
        return []
    start_index = min(_safe_int(item.get("entry_index")) for item in grouped if _safe_int(item.get("entry_index")) > 0)
    if start_index <= 0:
        start_index = _safe_int(assistant.get("entry_index"))
    return [
        _entry_with_round_start(assistant, round_start_entry_index=start_index),
        *[
            _entry_with_round_start(tool_by_id[tool_call_id], round_start_entry_index=start_index)
            for tool_call_id in expected_ids
        ],
    ]


def _entry_with_round_start(entry: dict[str, Any], *, round_start_entry_index: int) -> dict[str, Any]:
    payload = dict(entry or {})
    protocol = provider_tool_protocol_from_entry(payload)
    if protocol:
        protocol["round_start_entry_index"] = int(round_start_entry_index or 0)
        protocol["authority"] = PROVIDER_TOOL_PROTOCOL_AUTHORITY
        payload["provider_tool_protocol"] = protocol
    return payload


def _stable_json_hash(value: Any) -> str:
    text = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
