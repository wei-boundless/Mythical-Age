from __future__ import annotations

import json
import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolResultEnvelope:
    envelope_id: str
    tool_name: str
    tool_args: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    tool_call_id: str = ""
    action_request_id: str = ""
    caller_kind: str = ""
    caller_ref: str = ""
    text: str = ""
    structured_payload: dict[str, Any] = field(default_factory=dict)
    observed_paths: tuple[str, ...] = ()
    matched_paths: tuple[str, ...] = ()
    written_paths: tuple[str, ...] = ()
    artifact_refs: tuple[dict[str, Any], ...] = ()
    file_state_events: tuple[dict[str, Any], ...] = ()
    artifact_state_events: tuple[dict[str, Any], ...] = ()
    verification_events: tuple[dict[str, Any], ...] = ()
    command_receipt: dict[str, Any] = field(default_factory=dict)
    execution_receipt: dict[str, Any] = field(default_factory=dict)
    result_ref: str = ""
    idempotency_key: str = ""
    error: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "execution.tool_result_envelope"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observed_paths"] = list(self.observed_paths)
        payload["matched_paths"] = list(self.matched_paths)
        payload["written_paths"] = list(self.written_paths)
        payload["artifact_refs"] = [dict(item) for item in self.artifact_refs]
        payload["file_state_events"] = [dict(item) for item in self.file_state_events]
        payload["artifact_state_events"] = [dict(item) for item in self.artifact_state_events]
        payload["verification_events"] = [dict(item) for item in self.verification_events]
        payload["diagnostics"] = dict(self.diagnostics)
        return payload


def build_tool_result_envelope(
    *,
    tool_name: str,
    tool_args: dict[str, Any] | None = None,
    result: Any = None,
    status: str = "",
    execution_receipt: dict[str, Any] | None = None,
    result_ref: str = "",
    idempotency_key: str = "",
    tool_call_id: str = "",
    action_request_id: str = "",
    caller_kind: str = "",
    caller_ref: str = "",
    truncated: bool = False,
    sandbox: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> ToolResultEnvelope:
    name = str(tool_name or "").strip()
    args = dict(tool_args or {})
    result_payload = _structured_result_payload(result)
    text = str(result_payload.get("text") if result_payload else result or "")
    resolved_status = _normalize_status(status) or ("error" if _looks_failed(text) else "ok")
    structured_payload = {
        "truncated": bool(truncated),
        "sandbox": dict(sandbox or {}),
    }
    if result_payload:
        structured_payload.update(dict(result_payload.get("structured_payload") or {}))
    observed_paths = tuple(_string_tuple(structured_payload.get("observed_paths")))
    matched_paths = tuple(_string_tuple(structured_payload.get("matched_paths")))
    written_paths = tuple(_string_tuple(structured_payload.get("written_paths")))
    artifact_refs = tuple(_dict_tuple(structured_payload.get("artifact_refs")))
    file_state_events = tuple(_dict_tuple(structured_payload.get("file_state_events"))) or infer_file_state_events(
        tool_name=name,
        tool_args=args,
        status=resolved_status,
        structured_payload=structured_payload,
        observed_paths=observed_paths,
        matched_paths=matched_paths,
        written_paths=written_paths,
    )
    artifact_state_events = tuple(_dict_tuple(structured_payload.get("artifact_state_events")))
    verification_events = tuple(_dict_tuple(structured_payload.get("verification_events")))
    command_receipt = dict(structured_payload.get("command_receipt") or {})
    resolved_tool_call_id = str(tool_call_id or "").strip()
    resolved_action_request_id = str(action_request_id or "").strip()
    resolved_caller_ref = str(caller_ref or "").strip()
    resolved_idempotency_key = str(idempotency_key or "").strip() or str(
        dict(execution_receipt or {}).get("idempotency_key") or ""
    ).strip()
    if not resolved_idempotency_key:
        resolved_idempotency_key = build_tool_result_idempotency_key(
            caller_ref=resolved_caller_ref,
            action_request_id=resolved_action_request_id,
            tool_call_id=resolved_tool_call_id,
            tool_name=name,
            tool_args=args,
        )
    if observed_paths:
        structured_payload["observed_paths"] = list(observed_paths)
    if artifact_refs:
        structured_payload["artifact_refs"] = [dict(item) for item in artifact_refs]
    if matched_paths:
        structured_payload["matched_paths"] = list(matched_paths)
    if command_receipt:
        structured_payload["command_receipt"] = dict(command_receipt)
    if written_paths:
        structured_payload["written_paths"] = list(written_paths)
    if file_state_events:
        structured_payload["file_state_events"] = [dict(item) for item in file_state_events]
    return ToolResultEnvelope(
        envelope_id=build_tool_result_envelope_id(resolved_idempotency_key),
        tool_name=name,
        tool_args=args,
        status=resolved_status,
        tool_call_id=resolved_tool_call_id,
        action_request_id=resolved_action_request_id,
        caller_kind=str(caller_kind or ""),
        caller_ref=resolved_caller_ref,
        text=text,
        structured_payload=structured_payload,
        observed_paths=observed_paths,
        matched_paths=matched_paths,
        written_paths=written_paths,
        artifact_refs=artifact_refs,
        file_state_events=file_state_events,
        artifact_state_events=artifact_state_events,
        verification_events=verification_events,
        command_receipt=command_receipt,
        execution_receipt=dict(execution_receipt or {}),
        result_ref=str(result_ref or ""),
        idempotency_key=resolved_idempotency_key,
        error=text if resolved_status != "ok" else "",
        diagnostics=dict(diagnostics or {}),
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
            "text": str(payload.get("text") or payload.get("message") or payload.get("error") or json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            "structured_payload": structured_payload,
        }
    artifact_refs = [dict(item) for item in list(payload.get("artifact_refs") or []) if isinstance(item, dict)]
    image_payload = dict(payload.get("image") or {}) if isinstance(payload.get("image"), dict) else {}
    if artifact_refs or image_payload:
        structured_payload = {
            "tool_result": payload,
        }
        if artifact_refs:
            structured_payload["artifact_refs"] = artifact_refs
        return {
            "text": str(payload.get("text") or payload.get("message") or payload.get("summary") or json.dumps(payload, ensure_ascii=False, sort_keys=True)),
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
            tool_name = str(envelope.get("tool_name") or item.get("tool_name") or "")
            tool_args = dict(envelope.get("tool_args") or item.get("tool_args") or {})
            tool_call_id = str(envelope.get("tool_call_id") or item.get("tool_call_id") or "")
            action_request_id = str(envelope.get("action_request_id") or item.get("request_ref") or item.get("action_request_ref") or "")
            caller_ref = str(envelope.get("caller_ref") or item.get("caller_ref") or "")
            idempotency_key = str(envelope.get("idempotency_key") or dict(envelope.get("execution_receipt") or {}).get("idempotency_key") or "")
            if not idempotency_key:
                idempotency_key = build_tool_result_idempotency_key(
                    caller_ref=caller_ref,
                    action_request_id=action_request_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                )
            return ToolResultEnvelope(
                envelope_id=str(envelope.get("envelope_id") or build_tool_result_envelope_id(idempotency_key)),
                tool_name=tool_name,
                tool_args=tool_args,
                status=str(envelope.get("status") or "ok"),
                tool_call_id=tool_call_id,
                action_request_id=action_request_id,
                caller_kind=str(envelope.get("caller_kind") or item.get("caller_kind") or ""),
                caller_ref=caller_ref,
                text=str(envelope.get("text") or item.get("result") or ""),
                structured_payload=dict(envelope.get("structured_payload") or {}),
                observed_paths=tuple(str(value) for value in list(envelope.get("observed_paths") or []) if str(value).strip()),
                matched_paths=tuple(str(value) for value in list(envelope.get("matched_paths") or []) if str(value).strip()),
                written_paths=tuple(str(value) for value in list(envelope.get("written_paths") or []) if str(value).strip()),
                artifact_refs=tuple(dict(value) for value in list(envelope.get("artifact_refs") or []) if isinstance(value, dict)),
                file_state_events=tuple(dict(value) for value in list(envelope.get("file_state_events") or []) if isinstance(value, dict)),
                artifact_state_events=tuple(dict(value) for value in list(envelope.get("artifact_state_events") or []) if isinstance(value, dict)),
                verification_events=tuple(dict(value) for value in list(envelope.get("verification_events") or []) if isinstance(value, dict)),
                command_receipt=dict(envelope.get("command_receipt") or {}),
                execution_receipt=dict(envelope.get("execution_receipt") or item.get("execution_receipt") or {}),
                result_ref=str(envelope.get("result_ref") or item.get("result_ref") or ""),
                idempotency_key=idempotency_key,
                error=str(envelope.get("error") or ""),
                diagnostics=dict(envelope.get("diagnostics") or {}),
            )
        except Exception:
            return None
    return None


def _normalize_status(value: str) -> str:
    status = str(value or "").strip()
    if status in {"ok", "error", "denied", "needs_approval", "needs_contract", "aborted", "canceled"}:
        return status
    if status == "cancelled":
        return "canceled"
    return ""


def build_tool_result_idempotency_key(
    *,
    caller_ref: str = "",
    action_request_id: str = "",
    tool_call_id: str = "",
    tool_name: str = "",
    tool_args: dict[str, Any] | None = None,
) -> str:
    primary = {
        "caller_ref": str(caller_ref or ""),
        "action_request_id": str(action_request_id or ""),
        "tool_call_id": str(tool_call_id or ""),
    }
    if any(primary.values()):
        raw = json.dumps(primary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
    fallback = {
        "tool_name": str(tool_name or ""),
        "tool_args": dict(tool_args or {}),
    }
    raw = json.dumps(fallback, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_tool_result_envelope_id(idempotency_key: str) -> str:
    key = str(idempotency_key or "").strip()
    if not key:
        key = hashlib.sha256(b"tool-result").hexdigest()
    return f"tool-result:{key[:16]}"


def infer_file_state_events(
    *,
    tool_name: str,
    tool_args: dict[str, Any] | None = None,
    status: str = "ok",
    structured_payload: dict[str, Any] | None = None,
    observed_paths: tuple[str, ...] = (),
    matched_paths: tuple[str, ...] = (),
    written_paths: tuple[str, ...] = (),
) -> tuple[dict[str, Any], ...]:
    if str(status or "").strip() != "ok":
        return ()
    name = str(tool_name or "").strip()
    args = dict(tool_args or {})
    structured = dict(structured_payload or {})
    tool_result = dict(structured.get("tool_result") or {})
    events: list[dict[str, Any]] = []
    if name == "read_file":
        path = _first_path(tool_result.get("path"), observed_paths, args.get("path"))
        if path:
            events.append(
                _drop_empty(
                    {
                        "event_type": "read",
                        "path": path,
                        "start_line": _int_or_none(tool_result.get("start_line")),
                        "end_line": _int_or_none(tool_result.get("end_line")),
                        "returned_lines": _int_or_none(tool_result.get("returned_lines")),
                        "line_count": _int_or_none(tool_result.get("line_count")),
                        "total_lines": _int_or_none(tool_result.get("total_lines")),
                        "next_start_line": _int_or_none(tool_result.get("next_start_line")),
                        "has_more": tool_result.get("has_more") if isinstance(tool_result.get("has_more"), bool) else None,
                        "content_sha256": str(tool_result.get("content_sha256") or tool_result.get("sha256") or "").strip(),
                        "mtime_ns": _int_or_none(tool_result.get("mtime_ns")),
                        "read_intent": str(tool_result.get("read_intent") or args.get("read_intent") or "").strip(),
                        "file_unchanged": tool_result.get("file_unchanged") if isinstance(tool_result.get("file_unchanged"), bool) else None,
                        "content_omitted": tool_result.get("content_omitted") if isinstance(tool_result.get("content_omitted"), bool) else None,
                        "previous_observation_ref": str(tool_result.get("previous_observation_ref") or "").strip(),
                        "reusable_result_ref": str(tool_result.get("reusable_result_ref") or "").strip(),
                        "exact_artifact_ref": str(tool_result.get("exact_artifact_ref") or "").strip(),
                        "artifact_ref_status": str(tool_result.get("artifact_ref_status") or "").strip(),
                        "visible_exact": tool_result.get("visible_exact") if isinstance(tool_result.get("visible_exact"), bool) else None,
                        "text_sha256": str(tool_result.get("text_sha256") or "").strip(),
                        "authority": "runtime.tool_result_envelope.file_state_event",
                    }
                )
            )
    elif name in {"write_file", "edit_file"}:
        paths = written_paths or observed_paths or _string_tuple([tool_result.get("path") or args.get("path")])
        for path in paths:
            events.append(
                _drop_empty(
                    {
                        "event_type": "write" if name == "write_file" else "edit",
                        "path": path,
                        "content_sha256": str(tool_result.get("sha256") or tool_result.get("content_sha256") or "").strip(),
                        "mtime_ns": _int_or_none(tool_result.get("mtime_ns")),
                        "repository_id": str(tool_result.get("repository_id") or "").strip(),
                        "authority": "runtime.tool_result_envelope.file_state_event",
                    }
                )
            )
    elif name == "search_text":
        matches = [dict(item) for item in list(tool_result.get("matches") or []) if isinstance(item, dict)]
        paths = tuple(_string_tuple(matched_paths or tuple(str(item.get("path") or "") for item in matches)))
        for path in paths:
            path_matches = [item for item in matches if str(item.get("path") or "").replace("\\", "/").strip() == path]
            events.append(
                _drop_empty(
                    {
                        "event_type": "search",
                        "path": path,
                        "query": str(tool_result.get("query") or args.get("query") or "").strip(),
                        "matches": path_matches[:20],
                        "authority": "runtime.tool_result_envelope.file_state_event",
                    }
                )
            )
    elif name in {"stat_path", "path_exists"}:
        path = _first_path(tool_result.get("path"), observed_paths, args.get("path"))
        if path:
            events.append(
                _drop_empty(
                    {
                        "event_type": "stat" if name == "stat_path" else "exists",
                        "path": path,
                        "exists": tool_result.get("exists") if isinstance(tool_result.get("exists"), bool) else None,
                        "is_dir": tool_result.get("is_dir") if isinstance(tool_result.get("is_dir"), bool) else None,
                        "is_file": tool_result.get("is_file") if isinstance(tool_result.get("is_file"), bool) else None,
                        "authority": "runtime.tool_result_envelope.file_state_event",
                    }
                )
            )
    return tuple(event for event in events if event)


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


def _first_path(*values: Any) -> str:
    for value in values:
        if isinstance(value, (list, tuple)):
            for item in value:
                text = str(item or "").replace("\\", "/").strip().strip("/")
                if text:
                    return text
            continue
        text = str(value or "").replace("\\", "/").strip().strip("/")
        if text:
            return text
    return ""


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


