from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ContinuationSelection:
    reason: str = ""
    context_recovery_status: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.continuation.selector"

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": False,
            "reason": self.reason,
            "context_recovery_status": dict(self.context_recovery_status or {}),
            "task_continuation_authority": "task_system.task_work_environment",
            "legacy_task_run_selector": "removed",
            "authority": self.authority,
        }


def select_session_continuation(
    runtime_host: Any,
    *,
    session_id: str,
    active_work_present: bool = False,
    context_recovery_status: dict[str, Any] | None = None,
) -> ContinuationSelection:
    normalized_session_id = str(session_id or "").strip()
    resolved_context_status = _normalize_context_recovery_status(
        context_recovery_status
        if context_recovery_status is not None
        else _context_recovery_status_from_host(runtime_host, session_id=normalized_session_id)
    )
    if not normalized_session_id:
        return ContinuationSelection(reason="session_id_missing", context_recovery_status=resolved_context_status)
    if active_work_present:
        return ContinuationSelection(reason="live_active_work_present", context_recovery_status=resolved_context_status)
    return ContinuationSelection(
        reason="legacy_task_run_continuation_removed",
        context_recovery_status={
            **resolved_context_status,
            "task_continuation_authority": "task_system.task_work_environment",
            "legacy_task_run_selector": "removed",
        },
    )


def _normalize_context_recovery_status(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    if not data:
        return {
            "available": False,
            "present": False,
            "fresh": False,
            "source": "",
            "reason": "context_recovery_status_unavailable",
            "authority": "harness.continuation.context_recovery_status",
        }
    source = str(data.get("source") or "")
    fresh = bool(data.get("fresh") is True or source == "full_session_history")
    available = bool(data.get("available") is True or fresh)
    return {
        **data,
        "available": available,
        "present": bool(data.get("present") is True or data.get("available") is True),
        "fresh": fresh,
        "source": source,
        "reason": str(data.get("reason") or ""),
        "authority": str(data.get("authority") or "harness.continuation.context_recovery_status"),
    }


def _context_recovery_status_from_host(runtime_host: Any, *, session_id: str) -> dict[str, Any]:
    session_manager = getattr(runtime_host, "session_manager", None)
    loader = getattr(session_manager, "load_session_record", None)
    if not callable(loader):
        return {
            "available": False,
            "present": False,
            "fresh": False,
            "source": "",
            "reason": "session_manager_unavailable",
            "authority": "harness.continuation.context_recovery_status",
        }
    try:
        record = dict(loader(session_id) or {})
    except Exception:
        return {
            "available": False,
            "present": False,
            "fresh": False,
            "source": "",
            "reason": "session_record_unavailable",
            "authority": "harness.continuation.context_recovery_status",
        }
    messages = [item for item in list(record.get("messages") or []) if isinstance(item, dict)]
    compacted = bool(str(record.get("compressed_context") or "").strip()) or _float_value(record.get("provider_protocol_compaction_created_at")) > 0
    if messages and not compacted:
        return {
            "available": True,
            "present": True,
            "fresh": True,
            "source": "full_session_history",
            "raw_message_count": len(messages),
            "requires_context_recovery_package": False,
            "reason": "",
            "authority": "harness.continuation.context_recovery_status",
        }
    return {
        "available": False,
        "present": False,
        "fresh": False,
        "source": "",
        "raw_message_count": len(messages),
        "requires_context_recovery_package": compacted,
        "reason": "context_recovery_package_status_unavailable",
        "authority": "harness.continuation.context_recovery_status",
    }


def _float_value(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
