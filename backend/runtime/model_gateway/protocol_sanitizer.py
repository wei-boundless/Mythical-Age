from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ProtocolSanitizerResult:
    messages: tuple[dict[str, Any], ...]
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.model_gateway.protocol_sanitizer"

    def to_dict(self) -> dict[str, Any]:
        return {
            "messages": [dict(item) for item in self.messages],
            "diagnostics": dict(self.diagnostics),
            "authority": self.authority,
        }


class ProtocolSanitizer:
    """Normalize provider chat protocol before model invocation."""

    authority = "runtime.model_gateway.protocol_sanitizer"

    def sanitize_for_prompt(
        self,
        messages: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        *,
        turn_id: str = "",
        source: str = "",
    ) -> ProtocolSanitizerResult:
        diagnostics = {
            "source": str(source or ""),
            "turn_id": str(turn_id or ""),
            "input_message_count": len(list(messages or [])),
            "output_message_count": 0,
            "assistant_tool_call_count": 0,
            "tool_output_count": 0,
            "dropped_orphan_tool_outputs": 0,
            "dropped_incomplete_tool_rounds": 0,
            "dropped_incomplete_tool_round_messages": 0,
            "dropped_empty_messages": 0,
            "dropped_invalid_role_messages": 0,
            "reordered_adjacent_orphan_tool_rounds": 0,
            "reordered_adjacent_orphan_tool_messages": 0,
            "authority": self.authority,
        }
        normalized_messages: list[dict[str, Any]] = []
        for raw in list(messages or []):
            message = _normalize_message(raw)
            if message is None:
                diagnostics["dropped_invalid_role_messages"] += 1
                continue
            normalized_messages.append(message)
        normalized_messages, repair_diagnostics = _repair_adjacent_orphan_tool_blocks(normalized_messages)
        diagnostics["reordered_adjacent_orphan_tool_rounds"] = repair_diagnostics["round_count"]
        diagnostics["reordered_adjacent_orphan_tool_messages"] = repair_diagnostics["message_count"]

        sanitized: list[dict[str, Any]] = []
        pending: dict[str, dict[str, Any]] = {}
        pending_round_start_index: int | None = None
        for message in normalized_messages:
            role = str(message.get("role") or "")
            if role == "tool":
                tool_call_id = str(message.get("tool_call_id") or "").strip()
                if not tool_call_id:
                    diagnostics["dropped_orphan_tool_outputs"] += 1
                    continue
                if tool_call_id not in pending:
                    if pending:
                        dropped = _drop_pending_tool_round(
                            sanitized,
                            pending_round_start_index=pending_round_start_index,
                        )
                        diagnostics["dropped_incomplete_tool_rounds"] += 1
                        diagnostics["dropped_incomplete_tool_round_messages"] += dropped
                        pending.clear()
                        pending_round_start_index = None
                    diagnostics["dropped_orphan_tool_outputs"] += 1
                    continue
                sanitized.append(message)
                pending.pop(tool_call_id, None)
                diagnostics["tool_output_count"] += 1
                if not pending:
                    pending_round_start_index = None
                continue
            if pending:
                dropped = _drop_pending_tool_round(
                    sanitized,
                    pending_round_start_index=pending_round_start_index,
                )
                diagnostics["dropped_incomplete_tool_rounds"] += 1
                diagnostics["dropped_incomplete_tool_round_messages"] += dropped
                pending.clear()
                pending_round_start_index = None
            if role == "assistant":
                provider_tool_calls = _provider_shaped_tool_calls(message.get("tool_calls"))
                if provider_tool_calls:
                    diagnostics["assistant_tool_call_count"] += len(provider_tool_calls)
                    for call in provider_tool_calls:
                        call_id = str(call.get("id") or "").strip()
                        if call_id:
                            pending[call_id] = call
                    pending_round_start_index = len(sanitized) if pending else None
                    sanitized.append(message)
                    continue
                tool_calls = _tool_calls(message.get("tool_calls"))
                if tool_calls:
                    message["tool_calls"] = tool_calls
                    diagnostics["assistant_tool_call_count"] += len(tool_calls)
                    for call in tool_calls:
                        call_id = str(call.get("id") or "").strip()
                        if call_id:
                            pending[call_id] = call
                    pending_round_start_index = len(sanitized) if pending else None
                elif not str(message.get("content") or "").strip() and not _has_reasoning_content_field(message):
                    diagnostics["dropped_empty_messages"] += 1
                    continue
            if role == "user" and not str(message.get("content") or "").strip():
                diagnostics["dropped_empty_messages"] += 1
                continue
            sanitized.append(message)
        for call_id, call in list(pending.items()):
            del call_id, call
            dropped = _drop_pending_tool_round(
                sanitized,
                pending_round_start_index=pending_round_start_index,
            )
            diagnostics["dropped_incomplete_tool_rounds"] += 1
            diagnostics["dropped_incomplete_tool_round_messages"] += dropped
            break
        diagnostics["output_message_count"] = len(sanitized)
        return ProtocolSanitizerResult(messages=tuple(sanitized), diagnostics=diagnostics)


def sanitize_messages_for_prompt(
    messages: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    turn_id: str = "",
    source: str = "",
) -> ProtocolSanitizerResult:
    return ProtocolSanitizer().sanitize_for_prompt(messages, turn_id=turn_id, source=source)


def standardize_provider_tool_protocol_messages(
    messages: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    turn_id: str = "",
    source: str = "",
) -> ProtocolSanitizerResult:
    return sanitize_messages_for_prompt(messages, turn_id=turn_id, source=source)


def _normalize_message(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    item = dict(raw)
    role = str(item.get("role") or item.get("type") or "").strip()
    if role not in {"system", "user", "assistant", "tool"}:
        return None
    provider_payload = _provider_payload_message(item, role=role)
    if provider_payload is not None:
        return provider_payload
    message: dict[str, Any] = {
        "role": role,
        "content": _string_content(item.get("content")),
    }
    for key in ("name", "tool_call_id", "turn_id"):
        value = str(item.get(key) or "").strip()
        if value:
            message[key] = value
    if role == "assistant":
        reasoning_content = _explicit_reasoning_content(item.get("reasoning_content"))
        if reasoning_content:
            message["reasoning_content"] = reasoning_content
        if item.get("prefix") is True or str(item.get("prefix") or "").strip().lower() == "true":
            message["prefix"] = True
        tool_calls = _tool_calls(item.get("tool_calls"))
        if tool_calls:
            message["tool_calls"] = tool_calls
    return message


def _repair_adjacent_orphan_tool_blocks(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    result: list[dict[str, Any]] = []
    round_count = 0
    message_count = 0
    index = 0
    clean_messages = [dict(item) for item in list(messages or []) if isinstance(item, dict)]
    while index < len(clean_messages):
        message = dict(clean_messages[index])
        role = str(message.get("role") or "")
        if role != "tool":
            result.append(message)
            index += 1
            continue
        block_start = index
        tool_block: list[dict[str, Any]] = []
        tool_call_ids: list[str] = []
        while index < len(clean_messages) and str(clean_messages[index].get("role") or "") == "tool":
            tool_message = dict(clean_messages[index])
            tool_block.append(tool_message)
            tool_call_id = str(tool_message.get("tool_call_id") or "").strip()
            if tool_call_id and tool_call_id not in tool_call_ids:
                tool_call_ids.append(tool_call_id)
            index += 1
        if (
            tool_call_ids
            and index < len(clean_messages)
            and str(clean_messages[index].get("role") or "") == "assistant"
        ):
            assistant = dict(clean_messages[index])
            assistant_tool_call_ids = _assistant_tool_call_ids(assistant)
            if set(tool_call_ids).issubset(set(assistant_tool_call_ids)):
                result.append(assistant)
                result.extend(tool_block)
                round_count += 1
                message_count += len(tool_block) + 1
                index += 1
                continue
        result.extend(tool_block)
        if index == block_start:
            index += 1
    return result, {"round_count": round_count, "message_count": message_count}


def _assistant_tool_call_ids(message: dict[str, Any]) -> list[str]:
    if str(dict(message or {}).get("role") or "") != "assistant":
        return []
    ids: list[str] = []
    provider_tool_calls = _provider_shaped_tool_calls(dict(message or {}).get("tool_calls"))
    tool_calls = provider_tool_calls or _tool_calls(dict(message or {}).get("tool_calls"))
    for call in list(tool_calls or []):
        if not isinstance(call, dict):
            continue
        call_id = str(call.get("id") or "").strip()
        if call_id and call_id not in ids:
            ids.append(call_id)
    return ids


def _tool_calls(value: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    raw_calls = list(value or []) if isinstance(value, (list, tuple)) else []
    for index, raw in enumerate(raw_calls, start=1):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        function = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = str(item.get("name") or function.get("name") or "").strip()
        if not name:
            continue
        call_id = str(item.get("id") or item.get("call_id") or f"tool-call-{index}").strip()
        args = item.get("args")
        if not isinstance(args, dict):
            args = item.get("arguments")
        if not isinstance(args, dict):
            args = function.get("arguments")
        if isinstance(args, str):
            try:
                parsed_args = json.loads(args)
            except json.JSONDecodeError:
                parsed_args = {}
            args = parsed_args if isinstance(parsed_args, dict) else {}
        if not isinstance(args, dict):
            args = {}
        calls.append({"id": call_id, "name": name, "args": dict(args), "type": "tool_call"})
    return calls


def _provider_payload_message(item: dict[str, Any], *, role: str) -> dict[str, Any] | None:
    if isinstance(item.get("additional_kwargs"), dict) and dict(item.get("additional_kwargs") or {}):
        return None
    tool_calls = item.get("tool_calls")
    if tool_calls and not _provider_shaped_tool_calls(tool_calls):
        return None
    message: dict[str, Any] = {
        "role": role,
        "content": copy.deepcopy(item.get("content")) if item.get("content") is not None else "",
    }
    for key in ("name", "tool_call_id", "turn_id"):
        value = str(item.get(key) or "").strip()
        if value:
            message[key] = value
    if role == "assistant":
        reasoning_content = _explicit_reasoning_content(item.get("reasoning_content"))
        if reasoning_content:
            message["reasoning_content"] = reasoning_content
        if item.get("prefix") is True or str(item.get("prefix") or "").strip().lower() == "true":
            message["prefix"] = True
        provider_tool_calls = _provider_shaped_tool_calls(tool_calls)
        if provider_tool_calls:
            message["tool_calls"] = provider_tool_calls
    return message


def _provider_shaped_tool_calls(value: Any) -> list[dict[str, Any]]:
    raw_calls = list(value or []) if isinstance(value, (list, tuple)) else []
    if not raw_calls:
        return []
    result: list[dict[str, Any]] = []
    for raw in raw_calls:
        if not isinstance(raw, dict):
            return []
        item = dict(raw)
        function = item.get("function")
        if str(item.get("type") or "") != "function" or not isinstance(function, dict):
            return []
        if not str(item.get("id") or "").strip():
            return []
        if not str(function.get("name") or "").strip():
            return []
        if not isinstance(function.get("arguments"), str):
            return []
        result.append(copy.deepcopy(item))
    return result


def _explicit_reasoning_content(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return text if text != "" else ""


def _has_reasoning_content_field(message: dict[str, Any]) -> bool:
    return _explicit_reasoning_content(dict(message or {}).get("reasoning_content")) != ""


def _drop_pending_tool_round(
    sanitized: list[dict[str, Any]],
    *,
    pending_round_start_index: int | None,
) -> int:
    if pending_round_start_index is None:
        return 0
    start = int(pending_round_start_index)
    if start < 0 or start >= len(sanitized):
        return 0
    dropped = len(sanitized) - start
    del sanitized[start:]
    return dropped


def _string_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for block in value:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif isinstance(block, dict) and block.get("text") is not None:
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return str(value or "")
