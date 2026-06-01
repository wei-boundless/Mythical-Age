from __future__ import annotations

import uuid
import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolResultEnvelope:
    envelope_id: str
    tool_name: str
    tool_args: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    text: str = ""
    structured_payload: dict[str, Any] = field(default_factory=dict)
    observed_paths: tuple[str, ...] = ()
    matched_paths: tuple[str, ...] = ()
    artifact_refs: tuple[dict[str, Any], ...] = ()
    command_receipt: dict[str, Any] = field(default_factory=dict)
    execution_receipt: dict[str, Any] = field(default_factory=dict)
    result_ref: str = ""
    error: str = ""
    authority: str = "execution.tool_result_envelope"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observed_paths"] = list(self.observed_paths)
        payload["matched_paths"] = list(self.matched_paths)
        payload["artifact_refs"] = [dict(item) for item in self.artifact_refs]
        return payload


def build_tool_result_envelope(
    *,
    tool_name: str,
    tool_args: dict[str, Any] | None = None,
    result: Any = None,
    execution_receipt: dict[str, Any] | None = None,
    result_ref: str = "",
    truncated: bool = False,
    sandbox: dict[str, Any] | None = None,
) -> ToolResultEnvelope:
    name = str(tool_name or "").strip()
    args = dict(tool_args or {})
    result_payload = _structured_result_payload(result)
    text = str(result_payload.get("text") if result_payload else result or "")
    status = "error" if _looks_failed(text) else "ok"
    structured_payload = {
        "truncated": bool(truncated),
        "sandbox": dict(sandbox or {}),
    }
    if result_payload:
        structured_payload.update(dict(result_payload.get("structured_payload") or {}))
    observed_paths = tuple(_string_tuple(structured_payload.get("observed_paths")))
    matched_paths = tuple(_string_tuple(structured_payload.get("matched_paths")))
    artifact_refs = tuple(_dict_tuple(structured_payload.get("artifact_refs")))
    command_receipt = dict(structured_payload.get("command_receipt") or {})
    if observed_paths:
        structured_payload["observed_paths"] = list(observed_paths)
    if artifact_refs:
        structured_payload["artifact_refs"] = [dict(item) for item in artifact_refs]
    if matched_paths:
        structured_payload["matched_paths"] = list(matched_paths)
    if command_receipt:
        structured_payload["command_receipt"] = dict(command_receipt)
    return ToolResultEnvelope(
        envelope_id=f"tool-result:{uuid.uuid4().hex[:12]}",
        tool_name=name,
        tool_args=args,
        status=status,
        text=text,
        structured_payload=structured_payload,
        observed_paths=observed_paths,
        matched_paths=matched_paths,
        artifact_refs=artifact_refs,
        command_receipt=command_receipt,
        execution_receipt=dict(execution_receipt or {}),
        result_ref=str(result_ref or ""),
        error=text if status == "error" else "",
    )


def _structured_result_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, str):
        parsed = _json_result_payload(result)
        if not parsed:
            return {}
        return _structured_result_payload(parsed)
    if not isinstance(result, dict):
        return {}
    payload = dict(result)
    if payload.get("ok") is False or payload.get("structured_error") or payload.get("error"):
        structured_payload = {
            "structured_error": dict(payload.get("structured_error") or {}) if isinstance(payload.get("structured_error"), dict) else {},
            "error": str(payload.get("error") or ""),
        }
        return {
            "text": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            "structured_payload": structured_payload,
        }
    if "structured_payload" not in payload:
        return {}
    return {
        "text": str(payload.get("text") or payload.get("summary") or ""),
        "structured_payload": dict(payload.get("structured_payload") or {}),
    }


def tool_result_envelope_from_payload(payload: dict[str, Any] | None) -> ToolResultEnvelope | None:
    item = dict(payload or {})
    envelope = item.get("result_envelope")
    if isinstance(envelope, dict):
        try:
            return ToolResultEnvelope(
                envelope_id=str(envelope.get("envelope_id") or ""),
                tool_name=str(envelope.get("tool_name") or item.get("tool_name") or ""),
                tool_args=dict(envelope.get("tool_args") or item.get("tool_args") or {}),
                status=str(envelope.get("status") or "ok"),
                text=str(envelope.get("text") or item.get("result") or ""),
                structured_payload=dict(envelope.get("structured_payload") or {}),
                observed_paths=tuple(str(value) for value in list(envelope.get("observed_paths") or []) if str(value).strip()),
                matched_paths=tuple(str(value) for value in list(envelope.get("matched_paths") or []) if str(value).strip()),
                artifact_refs=tuple(dict(value) for value in list(envelope.get("artifact_refs") or []) if isinstance(value, dict)),
                command_receipt=dict(envelope.get("command_receipt") or {}),
                execution_receipt=dict(envelope.get("execution_receipt") or item.get("execution_receipt") or {}),
                result_ref=str(envelope.get("result_ref") or item.get("result_ref") or ""),
                error=str(envelope.get("error") or ""),
            )
        except Exception:
            return None
    return None


def _looks_failed(text: str) -> bool:
    lowered = str(text or "").lower()
    structured = _json_result_payload(text)
    if structured and (structured.get("ok") is False or structured.get("error") or structured.get("structured_error")):
        return True
    if lowered.startswith(("read failed", "structured read failed", "search failed", "write failed", "edit failed", "blocked:", "timed out")):
        return True
    return _looks_like_failed_command_output(lowered)


def _json_result_payload(text: str) -> dict[str, Any]:
    stripped = str(text or "").strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return {}
    try:
        parsed = __import__("json").loads(stripped)
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _looks_like_failed_command_output(lowered: str) -> bool:
    text = str(lowered or "")
    if not text:
        return False
    failure_needles = (
        "parsererror",
        "parentcontainserrorrecordexception",
        "fullyqualifiederrorid",
        "traceback (most recent call last)",
        "syntaxerror:",
        "exception:",
        "the token '&&' is not a valid statement separator",
        "is not a valid statement separator",
        "commandnotfoundexception",
        "nativecommanderror",
        "exit code 1",
        "exit code: 1",
        "returned non-zero exit status",
        "subprocess.calledprocesserror",
        "= failures =",
        "=== failures ===",
        " failed in ",
        " error in ",
    )
    if any(needle in text for needle in failure_needles):
        return True
    failure_patterns = (
        "(^|\\s)[1-9]\\d*\\s+failed\\b",
        "(^|\\s)[1-9]\\d*\\s+errors?\\b",
        "\\bfailed,\\s*[1-9]\\d*\\s+passed\\b",
        "\\b[1-9]\\d*\\s+passed,\\s*[1-9]\\d*\\s+failed\\b",
        "\\berror:\\s+",
    )
    import re

    if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in failure_patterns):
        return True
    success_patterns = (
        "(^|\\s)[1-9]\\d*\\s+passed\\b",
        "\\bpassed in \\d",
        "\\bno tests ran\\b",
    )
    if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in success_patterns):
        return False
    return False


def _string_tuple(value: Any) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in list(value or []):
        item = str(raw or "").strip().replace("\\", "/")
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)


def _dict_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in list(value or []):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        key = str(item.get("path") or repr(sorted(item.items()))).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return tuple(result)


