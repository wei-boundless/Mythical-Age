from __future__ import annotations

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
        sanitized: list[dict[str, Any]] = []
        pending: dict[str, dict[str, Any]] = {}
        diagnostics = {
            "source": str(source or ""),
            "turn_id": str(turn_id or ""),
            "input_message_count": len(list(messages or [])),
            "output_message_count": 0,
            "assistant_tool_call_count": 0,
            "tool_output_count": 0,
            "injected_aborted_tool_outputs": 0,
            "dropped_orphan_tool_outputs": 0,
            "dropped_empty_messages": 0,
            "dropped_invalid_role_messages": 0,
            "authority": self.authority,
        }
        for raw in list(messages or []):
            message = _normalize_message(raw)
            if message is None:
                diagnostics["dropped_invalid_role_messages"] += 1
                continue
            role = str(message.get("role") or "")
            if role == "tool":
                tool_call_id = str(message.get("tool_call_id") or "").strip()
                if not tool_call_id:
                    diagnostics["dropped_orphan_tool_outputs"] += 1
                    continue
                if tool_call_id not in pending:
                    if pending:
                        for call_id, call in list(pending.items()):
                            sanitized.append(_aborted_tool_output(call_id=call_id, call=call, turn_id=turn_id))
                            diagnostics["injected_aborted_tool_outputs"] += 1
                        pending.clear()
                    diagnostics["dropped_orphan_tool_outputs"] += 1
                    continue
                sanitized.append(message)
                pending.pop(tool_call_id, None)
                diagnostics["tool_output_count"] += 1
                continue
            if pending:
                for call_id, call in list(pending.items()):
                    sanitized.append(_aborted_tool_output(call_id=call_id, call=call, turn_id=turn_id))
                    diagnostics["injected_aborted_tool_outputs"] += 1
                pending.clear()
            if role == "assistant":
                tool_calls = _tool_calls(message.get("tool_calls"))
                if tool_calls:
                    message["tool_calls"] = tool_calls
                    diagnostics["assistant_tool_call_count"] += len(tool_calls)
                    for call in tool_calls:
                        call_id = str(call.get("id") or "").strip()
                        if call_id:
                            pending[call_id] = call
                elif not str(message.get("content") or "").strip() and not str(message.get("reasoning_content") or "").strip():
                    diagnostics["dropped_empty_messages"] += 1
                    continue
            if role == "user" and not str(message.get("content") or "").strip():
                diagnostics["dropped_empty_messages"] += 1
                continue
            sanitized.append(message)
        for call_id, call in list(pending.items()):
            sanitized.append(_aborted_tool_output(call_id=call_id, call=call, turn_id=turn_id))
            diagnostics["injected_aborted_tool_outputs"] += 1
        diagnostics["output_message_count"] = len(sanitized)
        return ProtocolSanitizerResult(messages=tuple(sanitized), diagnostics=diagnostics)


def sanitize_messages_for_prompt(
    messages: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    turn_id: str = "",
    source: str = "",
) -> ProtocolSanitizerResult:
    return ProtocolSanitizer().sanitize_for_prompt(messages, turn_id=turn_id, source=source)


def _normalize_message(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    item = dict(raw)
    role = str(item.get("role") or item.get("type") or "").strip()
    if role not in {"system", "user", "assistant", "tool"}:
        return None
    message: dict[str, Any] = {
        "role": role,
        "content": _string_content(item.get("content")),
    }
    for key in ("name", "tool_call_id", "turn_id"):
        value = str(item.get(key) or "").strip()
        if value:
            message[key] = value
    if role == "assistant":
        reasoning_content = str(item.get("reasoning_content") or "").strip()
        if reasoning_content:
            message["reasoning_content"] = reasoning_content
        tool_calls = _tool_calls(item.get("tool_calls"))
        if tool_calls:
            message["tool_calls"] = tool_calls
    return message


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
        if not isinstance(args, dict):
            args = {}
        calls.append({"id": call_id, "name": name, "args": dict(args), "type": "tool_call"})
    return calls


def _aborted_tool_output(*, call_id: str, call: dict[str, Any], turn_id: str) -> dict[str, Any]:
    message = {
        "role": "tool",
        "name": str(call.get("name") or ""),
        "tool_call_id": str(call_id or ""),
        "content": "Tool call was aborted before an observation was recorded.",
        "protocol_status": "aborted",
        "authority": "runtime.model_gateway.protocol_sanitizer",
    }
    if turn_id:
        message["turn_id"] = str(turn_id or "")
    return message


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
