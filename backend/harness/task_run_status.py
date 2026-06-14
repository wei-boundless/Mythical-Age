from __future__ import annotations

from typing import Any


TERMINAL_TASK_RUN_STATUSES = frozenset(
    {
        "completed",
        "success",
        "failed",
        "error",
        "aborted",
        "cancelled",
        "canceled",
        "stopped",
        "user_aborted",
    }
)

STOP_CONTROL_STATES = frozenset({"stop_requested", "stopped"})


def normalize_task_run_status(value: Any) -> str:
    return str(value or "").strip().lower()


def is_terminal_task_run_status(value: Any) -> bool:
    return normalize_task_run_status(value) in TERMINAL_TASK_RUN_STATUSES


def runtime_control_state_from_task_run(task_run: Any) -> str:
    if task_run is None:
        return ""
    if isinstance(task_run, dict):
        direct = str(task_run.get("control_state") or "").strip().lower()
        diagnostics = task_run.get("diagnostics") if isinstance(task_run.get("diagnostics"), dict) else {}
    else:
        direct = str(getattr(task_run, "control_state", "") or "").strip().lower()
        diagnostics = getattr(task_run, "diagnostics", {}) or {}
    if direct:
        return direct
    control = diagnostics.get("runtime_control") if isinstance(diagnostics, dict) else {}
    if not isinstance(control, dict):
        return ""
    return str(control.get("state") or "").strip().lower()


def is_stopped_or_terminal_task_run(task_run: Any) -> bool:
    if task_run is None:
        return True
    if isinstance(task_run, dict):
        status = task_run.get("status")
        terminal_reason = task_run.get("terminal_reason")
    else:
        status = getattr(task_run, "status", "")
        terminal_reason = getattr(task_run, "terminal_reason", "")
    return (
        is_terminal_task_run_status(status)
        or is_terminal_task_run_status(terminal_reason)
        or runtime_control_state_from_task_run(task_run) in STOP_CONTROL_STATES
    )
