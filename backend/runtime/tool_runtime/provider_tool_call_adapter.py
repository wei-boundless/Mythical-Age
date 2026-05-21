from __future__ import annotations

import html
import json
import re
from typing import Any

from runtime.tool_runtime.tool_call_intent import ToolCallIntent


_DSML_TOKEN_RE = r"[｜|]{1,2}\s*DSML\s*[｜|]{1,2}"
_DSML_INVOKE_RE = re.compile(
    rf"<\s*{_DSML_TOKEN_RE}\s*invoke\s+name=\"(?P<name>[^\"]+)\"\s*>"
    rf"(?P<body>.*?)"
    rf"</\s*{_DSML_TOKEN_RE}\s*invoke\s*>",
    flags=re.IGNORECASE | re.DOTALL,
)
_DSML_PARAMETER_RE = re.compile(
    rf"<\s*{_DSML_TOKEN_RE}\s*parameter\s+name=\"(?P<name>[^\"]+)\"\s+string=\"(?P<string>true|false)\"\s*>"
    rf"(?P<value>.*?)"
    rf"</\s*{_DSML_TOKEN_RE}\s*parameter\s*>",
    flags=re.IGNORECASE | re.DOTALL,
)


def extract_tool_call_intents(response: Any, *, provider: str = "") -> list[ToolCallIntent]:
    raw_candidates: list[Any] = []
    raw_candidates.extend(_as_list(getattr(response, "tool_calls", None)))
    additional_kwargs = dict(getattr(response, "additional_kwargs", {}) or {})
    raw_candidates.extend(_as_list(additional_kwargs.get("tool_calls")))
    if additional_kwargs.get("function_call"):
        raw_candidates.append(additional_kwargs.get("function_call"))
    raw_candidates.extend(_as_list(_raw_payload_value(response, "tool_calls")))
    raw_candidates.extend(_as_list(_raw_payload_value(response, "function_call")))

    intents: list[ToolCallIntent] = []
    for index, item in enumerate(raw_candidates, start=1):
        normalized = _normalize_raw_tool_call(item, index=index, provider=provider)
        if normalized is None:
            continue
        intents.append(normalized)
    intents.extend(_extract_dsml_tool_call_intents(response, provider=provider, start_index=len(intents) + 1))
    return _dedupe_intents(intents)


def normalize_tool_call_dicts(response: Any, *, provider: str = "") -> list[dict[str, Any]]:
    return [
        {
            "id": intent.call_id,
            "name": intent.tool_name,
            "args": dict(intent.args),
            "type": "tool_call",
            "source": intent.source,
        }
        for intent in extract_tool_call_intents(response, provider=provider)
        if not intent.protocol_violation
    ]


def tool_calls_for_langchain_messages(tool_calls: Any) -> list[dict[str, Any]]:
    """Return only the fields accepted by LangChain AIMessage.tool_calls."""
    result: list[dict[str, Any]] = []
    for index, item in enumerate(_as_list(tool_calls), start=1):
        if not isinstance(item, dict):
            continue
        raw = dict(item)
        name = str(raw.get("name") or "").strip()
        if not name:
            function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
            name = str(function.get("name") or "").strip()
        if not name:
            continue
        args = raw.get("args")
        if args is None:
            args = raw.get("arguments")
        if not isinstance(args, dict):
            args = _parse_args(args)
        call_id = str(raw.get("id") or raw.get("call_id") or f"tool-call-{index}").strip()
        result.append(
            {
                "id": call_id,
                "name": name,
                "args": dict(args or {}),
                "type": "tool_call",
            }
        )
    return result


def _normalize_raw_tool_call(item: Any, *, index: int, provider: str) -> ToolCallIntent | None:
    if not isinstance(item, dict):
        return None
    raw = dict(item)
    function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
    name = str(raw.get("name") or function.get("name") or "").strip()
    if not name:
        return None
    args = raw.get("args")
    if args is None:
        args = raw.get("arguments")
    if args is None:
        args = function.get("arguments")
    parsed_args = _parse_args(args)
    call_id = str(raw.get("id") or raw.get("call_id") or f"tool-call-{index}").strip()
    return ToolCallIntent(
        call_id=call_id,
        tool_name=name,
        args=parsed_args,
        provider=provider,
        source="native_tool_call" if raw.get("type") != "function_call" else "provider_function_call",
        raw_ref=call_id,
    )


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


def _extract_dsml_tool_call_intents(response: Any, *, provider: str, start_index: int) -> list[ToolCallIntent]:
    content_candidates = [
        getattr(response, "content", None),
        dict(getattr(response, "additional_kwargs", {}) or {}).get("content"),
        _raw_payload_value(response, "content"),
        _raw_payload_value(response, "text"),
    ]
    intents: list[ToolCallIntent] = []
    for content in content_candidates:
        text = _stringify_content(content)
        if not text:
            continue
        for offset, match in enumerate(_DSML_INVOKE_RE.finditer(text), start=start_index + len(intents)):
            tool_name = html.unescape(str(match.group("name") or "").strip())
            if not tool_name:
                continue
            args = _parse_dsml_parameters(str(match.group("body") or ""))
            intents.append(
                ToolCallIntent(
                    call_id=f"dsml-tool-call-{offset}",
                    tool_name=tool_name,
                    args=args,
                    provider=provider,
                    source="provider_dsml_tool_call",
                    raw_ref=f"dsml:{offset}",
                )
            )
    return intents


def _parse_dsml_parameters(body: str) -> dict[str, Any]:
    args: dict[str, Any] = {}
    for match in _DSML_PARAMETER_RE.finditer(str(body or "")):
        key = html.unescape(str(match.group("name") or "").strip())
        if not key:
            continue
        raw_value = html.unescape(str(match.group("value") or ""))
        is_string = str(match.group("string") or "").strip().lower() == "true"
        if is_string:
            args[key] = raw_value
            continue
        try:
            args[key] = json.loads(raw_value)
        except Exception:
            args[key] = raw_value
    return args


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
                elif block.get("text") is not None:
                    parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return ""


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


def _raw_payload_value(response: Any, key: str) -> Any:
    for attr in ("raw", "raw_response", "response_metadata"):
        payload = getattr(response, attr, None)
        if isinstance(payload, dict) and payload.get(key) is not None:
            return payload.get(key)
    if isinstance(response, dict):
        return response.get(key)
    return None


def _dedupe_intents(intents: list[ToolCallIntent]) -> list[ToolCallIntent]:
    result: list[ToolCallIntent] = []
    seen: set[tuple[str, str]] = set()
    for intent in intents:
        key = (intent.call_id, intent.tool_name)
        if key in seen:
            continue
        seen.add(key)
        result.append(intent)
    return result