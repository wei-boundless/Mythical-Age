from __future__ import annotations

from typing import Any


CANONICAL_TASK_RUN_STATUSES = frozenset(
    {
        "created",
        "running",
        "waiting_executor",
        "waiting_approval",
        "blocked",
        "completed",
        "failed",
        "aborted",
    }
)

LEGACY_TASK_RUN_STATUS_ALIASES = {
    "success": "completed",
    "succeeded": "completed",
    "done": "completed",
    "error": "failed",
    "cancelled": "aborted",
    "canceled": "aborted",
    "stopped": "aborted",
    "user_aborted": "aborted",
    "blocked_expired": "aborted",
    "runtime_retention_expired": "aborted",
    "approval_expired": "aborted",
}

COMPLETED_TASK_RUN_STATUSES = frozenset({"completed"})
FAILED_TASK_RUN_STATUSES = frozenset({"failed"})
STOPPED_TASK_RUN_STATUSES = frozenset({"aborted"})
TERMINAL_TASK_RUN_STATUSES = frozenset(
    {
        "completed",
        "failed",
        "aborted",
    }
)

TERMINAL_TASK_RUN_REASONS = frozenset(
    {
        "completed",
        "failed",
        "aborted",
        "user_aborted",
        "blocked_expired",
        "runtime_retention_expired",
        "approval_expired",
        "internal_error",
        "executor_failed",
        "model_response_timeout_after_partial_output",
        "artifact_validation_failed",
        "partial_contract_failed",
        "tool_loop_budget_exceeded",
        "commit_failed",
    }
)

STOP_CONTROL_STATES = frozenset({"stop_requested", "stopped"})


def normalize_task_run_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    return LEGACY_TASK_RUN_STATUS_ALIASES.get(status, status)


def is_terminal_task_run_status(value: Any) -> bool:
    return normalize_task_run_status(value) in TERMINAL_TASK_RUN_STATUSES


def is_terminal_task_run_reason(value: Any) -> bool:
    reason = str(value or "").strip().lower()
    return is_terminal_task_run_status(reason) or reason in TERMINAL_TASK_RUN_REASONS


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
        or is_terminal_task_run_reason(terminal_reason)
        or runtime_control_state_from_task_run(task_run) in STOP_CONTROL_STATES
    )
