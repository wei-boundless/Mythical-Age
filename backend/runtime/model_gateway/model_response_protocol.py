from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from runtime.model_gateway.model_runtime import stringify_content
from runtime.tool_runtime.provider_tool_call_adapter import normalize_tool_call_dicts


@dataclass(frozen=True, slots=True)
class ModelResponseProtocolResult:
    protocol_id: str
    content: str
    response_digest: str
    native_tool_calls: tuple[dict[str, Any], ...] = ()
    json_payload: dict[str, Any] = field(default_factory=dict)
    parse_diagnostics: dict[str, Any] = field(default_factory=dict)
    response_diagnostics: dict[str, Any] = field(default_factory=dict)
    protocol_errors: tuple[str, ...] = ()
    reasoning_content: str = ""
    authority: str = "runtime.model_gateway.model_response_protocol"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["native_tool_calls"] = [dict(item) for item in self.native_tool_calls]
        payload["json_payload"] = dict(self.json_payload or {})
        payload["parse_diagnostics"] = dict(self.parse_diagnostics or {})
        payload["response_diagnostics"] = dict(self.response_diagnostics or {})
        payload["protocol_errors"] = list(self.protocol_errors)
        return payload


def model_response_protocol_from_response(
    response: Any,
    *,
    request_id: str = "",
    turn_id: str = "",
    provider: str = "",
    require_json_action: bool = False,
    allow_native_tool_calls: bool = True,
) -> ModelResponseProtocolResult:
    content = stringify_content(getattr(response, "content", response))
    additional_kwargs = dict(getattr(response, "additional_kwargs", {}) or {})
    resolved_provider = str(provider or additional_kwargs.get("provider") or getattr(response, "provider", "") or "").strip()
    native_tool_calls = tuple(normalize_tool_call_dicts(response, provider=resolved_provider))
    json_payload, parse_diagnostics = parse_json_object_with_diagnostics(content)
    errors: list[str] = []
    # `require_json_action` means the text transport must contain one
    # unambiguous structured action. Models commonly wrap that object in
    # Markdown fences or a short natural-language preamble; when the parser can
    # isolate exactly one action-like object, preserve the agent decision
    # instead of treating transport style as a protocol failure.
    del require_json_action
    if native_tool_calls and not allow_native_tool_calls:
        errors.append("native_tool_call_transport_not_available")
    digest = _response_digest(
        content=content,
        native_tool_calls=native_tool_calls,
        request_id=request_id,
        turn_id=turn_id,
    )
    return ModelResponseProtocolResult(
        protocol_id=f"model-response-protocol:{digest[:16]}",
        content=content,
        response_digest=digest,
        native_tool_calls=native_tool_calls,
        json_payload=json_payload,
        parse_diagnostics=parse_diagnostics,
        response_diagnostics=response_protocol_diagnostics(response),
        protocol_errors=tuple(errors),
        reasoning_content=_reasoning_content_from_response(response),
    )


def parse_json_object_with_diagnostics(content: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    text = str(content or "").strip()
    original_text = text
    unwrapped_markdown = False
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
        unwrapped_markdown = True
    diagnostics: dict[str, Any] = {
        "content_chars": len(original_text),
        "unwrapped_markdown_fence": unwrapped_markdown,
        "raw_content_preview": _compact_text(original_text, limit=600),
        "authority": "runtime.model_gateway.model_response_protocol",
    }
    if not text:
        diagnostics["parse_error"] = "empty_content"
        return {}, diagnostics
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        repaired = _parse_json_object_prefix_with_ignorable_trailing_text(text)
        if repaired is None:
            embedded = _parse_single_embedded_json_object(text)
            if embedded is None:
                diagnostics["parse_error"] = exc.__class__.__name__
                diagnostics["parse_error_message"] = str(exc)
                diagnostics["starts_with"] = text[:24]
                diagnostics["ends_with"] = text[-24:] if text else ""
                return {}, diagnostics
            else:
                parsed, leading, trailing, parsed_from_markdown_fence = embedded
                diagnostics["parsed_with_embedded_object_repair"] = True
                diagnostics["ignored_leading_text"] = _compact_text(leading, limit=240)
                if trailing:
                    diagnostics["ignored_trailing_text"] = _compact_text(trailing, limit=240)
                if parsed_from_markdown_fence:
                    diagnostics["parsed_from_markdown_fence"] = True
                diagnostics["embedded_json_repair_authority"] = "runtime.model_gateway.model_response_protocol"
        if repaired is not None:
            parsed, trailing = repaired
            diagnostics["parsed_with_trailing_repair"] = True
            diagnostics["ignored_trailing_text"] = trailing
    except Exception as exc:
        diagnostics["parse_error"] = exc.__class__.__name__
        diagnostics["starts_with"] = text[:24]
        diagnostics["ends_with"] = text[-24:] if text else ""
        return {}, diagnostics
    if not isinstance(parsed, dict):
        diagnostics["parsed_type"] = type(parsed).__name__
        diagnostics["parse_error"] = "json_root_not_object"
        return {}, diagnostics
    diagnostics["parsed_type"] = "object"
    return dict(parsed), diagnostics


def _reasoning_content_from_response(response: Any) -> str:
    additional_kwargs = dict(getattr(response, "additional_kwargs", {}) or {})
    reasoning_content = _explicit_provider_text(additional_kwargs.get("reasoning_content"))
    if reasoning_content:
        return reasoning_content
    raw_response = getattr(response, "raw_response", None)
    if not isinstance(raw_response, dict):
        raw_response = getattr(response, "raw", None)
    if isinstance(raw_response, dict):
        for choice in list(raw_response.get("choices") or []):
            if not isinstance(choice, dict):
                continue
            message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
            reasoning_content = _first_explicit_provider_text(
                dict(message).get("reasoning_content"),
                dict(message).get("reasoning"),
                dict(delta).get("reasoning_content"),
                dict(delta).get("reasoning"),
            )
            if reasoning_content:
                return reasoning_content
    if isinstance(response, dict):
        reasoning_content = _explicit_provider_text(response.get("reasoning_content"))
        if reasoning_content:
            return reasoning_content
        response_additional_kwargs = response.get("additional_kwargs")
        if isinstance(response_additional_kwargs, dict):
            return _explicit_provider_text(response_additional_kwargs.get("reasoning_content"))
    return ""


def _first_explicit_provider_text(*values: Any) -> str:
    for value in values:
        text = _explicit_provider_text(value)
        if text:
            return text
    return ""


def _explicit_provider_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return text if text != "" else ""


def _parse_json_object_prefix_with_ignorable_trailing_text(text: str) -> tuple[dict[str, Any], str] | None:
    try:
        parsed, index = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    trailing = str(text[index:] or "").strip()
    if not trailing:
        return parsed, trailing
    if trailing in {'"', "'", "```"}:
        return parsed, trailing
    if trailing.strip("`").strip() in {'"', "'"}:
        return parsed, trailing
    return None


def _parse_single_embedded_json_object(text: str) -> tuple[dict[str, Any], str, str, bool] | None:
    decoder = json.JSONDecoder()
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            candidates.append((index, index + end, dict(parsed)))
    action_like = [
        candidate
        for candidate in candidates
        if _looks_like_model_action_object(candidate[2])
    ]
    selected = action_like if action_like else candidates
    if len(selected) != 1:
        return None
    start, end, payload = selected[0]
    leading = text[:start].strip()
    trailing = text[end:].strip()
    return payload, leading, trailing, _span_inside_markdown_fence(text, start, end)


def _span_inside_markdown_fence(text: str, start: int, end: int) -> bool:
    opening = text.rfind("```", 0, max(0, start))
    if opening < 0:
        return False
    closing = text.find("```", max(0, end))
    if closing < 0:
        return False
    return True


def _looks_like_model_action_object(payload: dict[str, Any]) -> bool:
    keys = {str(key) for key in payload.keys()}
    return bool(
        "action_type" in keys
        or "authority" in keys
        or "tool_call" in keys
        or "tool_calls" in keys
        or "task_run_contract_seed" in keys
        or "task_contract_seed" in keys
        or "active_work_control" in keys
    )


def response_protocol_diagnostics(response: Any) -> dict[str, Any]:
    metadata = _safe_dict(getattr(response, "response_metadata", None))
    usage = _safe_dict(getattr(response, "usage_metadata", None))
    token_usage = _safe_dict(metadata.get("token_usage"))
    return _drop_empty(
        {
            "finish_reason": str(metadata.get("finish_reason") or metadata.get("stop_reason") or ""),
            "output_tokens": _first_int(
                usage.get("output_tokens"),
                usage.get("completion_tokens"),
                token_usage.get("completion_tokens"),
                token_usage.get("output_tokens"),
            ),
            "provider": str(getattr(response, "provider", "") or ""),
            "authority": "runtime.model_gateway.model_response_protocol",
        }
    )


def _response_digest(
    *,
    content: str,
    native_tool_calls: tuple[dict[str, Any], ...],
    request_id: str,
    turn_id: str,
) -> str:
    payload = {
        "content": str(content or ""),
        "native_tool_calls": [dict(item) for item in tuple(native_tool_calls or ())],
        "request_id": str(request_id or ""),
        "turn_id": str(turn_id or ""),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _compact_text(value: Any, *, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[truncated]"


def _safe_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _first_int(*values: Any) -> int:
    for value in values:
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return 0


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(payload or {}).items()
        if value not in ("", None, [], {})
    }
