from __future__ import annotations

from typing import Any

from runtime.output_stream.public_contract import (
    SESSION_OUTPUT_COMMIT_ACK_EVENT,
    SESSION_OUTPUT_COMMIT_CHECKED_EVENT,
    SESSION_OUTPUT_COMMIT_FAILED_EVENT,
    SESSION_OUTPUT_COMMIT_SKIPPED_EVENT,
)


_COMMIT_EVENT_TYPES = {
    SESSION_OUTPUT_COMMIT_CHECKED_EVENT,
    SESSION_OUTPUT_COMMIT_ACK_EVENT,
    SESSION_OUTPUT_COMMIT_FAILED_EVENT,
    SESSION_OUTPUT_COMMIT_SKIPPED_EVENT,
}


def project_session_output_commit_state(
    events: list[Any],
    *,
    diagnostics: dict[str, Any],
    task_run: Any,
    authority: str,
) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for event in list(events or []):
        event_type = _event_type(event)
        if event_type not in _COMMIT_EVENT_TYPES:
            continue
        payload = _event_payload(event)
        state = str(payload.get("state") or payload.get("status") or "").strip()
        if event_type == SESSION_OUTPUT_COMMIT_CHECKED_EVENT and not state:
            state = "checked"
        elif event_type == SESSION_OUTPUT_COMMIT_ACK_EVENT:
            state = "committed"
        elif event_type == SESSION_OUTPUT_COMMIT_FAILED_EVENT:
            state = "failed"
        elif event_type == SESSION_OUTPUT_COMMIT_SKIPPED_EVENT:
            state = "skipped"
        latest = {
            "authority": authority,
            "state": state,
            "session_id": str(payload.get("session_id") or getattr(task_run, "session_id", "") or ""),
            "turn_id": str(payload.get("turn_id") or dict(diagnostics or {}).get("turn_id") or ""),
            "task_run_id": str(payload.get("task_run_id") or getattr(task_run, "task_run_id", "") or ""),
            "task_id": str(payload.get("task_id") or getattr(task_run, "task_id", "") or ""),
            "anchor_message_id": str(payload.get("anchor_message_id") or ""),
            "content_sha256": str(payload.get("content_sha256") or ""),
            "reason": str(payload.get("reason") or ""),
            "commit_event_offset": _int_value(_event_offset(event), fallback=-1),
            "checked_event_offset": _int_value(payload.get("checked_event_offset"), fallback=-1),
            "created_at": _float_value(_event_created_at(event), fallback=0.0),
        }
    if latest:
        return {key: value for key, value in latest.items() if value not in ("", None)}
    diagnostic_commit = _record(dict(diagnostics or {}).get("output_commit"))
    state = str(
        diagnostic_commit.get("state")
        or diagnostic_commit.get("status")
        or ""
    ).strip()
    if not state:
        return {}
    return {
        "authority": authority,
        "state": state,
        "session_id": str(diagnostic_commit.get("session_id") or getattr(task_run, "session_id", "") or ""),
        "turn_id": str(diagnostic_commit.get("turn_id") or dict(diagnostics or {}).get("turn_id") or ""),
        "task_run_id": str(diagnostic_commit.get("task_run_id") or getattr(task_run, "task_run_id", "") or ""),
        "task_id": str(diagnostic_commit.get("task_id") or getattr(task_run, "task_id", "") or ""),
        "anchor_message_id": str(diagnostic_commit.get("anchor_message_id") or ""),
        "content_sha256": str(diagnostic_commit.get("content_sha256") or ""),
        "reason": str(diagnostic_commit.get("reason") or ""),
        "commit_event_offset": _int_value(diagnostic_commit.get("event_offset"), fallback=-1),
    }


def _event_type(event: Any) -> str:
    if isinstance(event, dict):
        return str(event.get("event_type") or "").strip()
    return str(getattr(event, "event_type", "") or "").strip()


def _event_payload(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        return _record(event.get("payload"))
    return _record(getattr(event, "payload", {}))


def _event_offset(event: Any) -> Any:
    if isinstance(event, dict):
        return event.get("offset")
    return getattr(event, "offset", None)


def _event_created_at(event: Any) -> Any:
    if isinstance(event, dict):
        return event.get("created_at")
    return getattr(event, "created_at", None)


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _int_value(value: Any, *, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _float_value(value: Any, *, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback
