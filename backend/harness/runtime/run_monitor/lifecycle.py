from __future__ import annotations

RUNNING_TASK_RUN_STATUSES = {"created", "running"}
WAITING_TASK_RUN_STATUSES = {"waiting_executor", "waiting_approval"}
BLOCKED_TASK_RUN_STATUSES = {"blocked"}
FAILED_TASK_RUN_STATUSES = {"failed", "aborted"}
COMPLETED_TASK_RUN_STATUSES = {"completed"}
TERMINAL_TASK_RUN_STATUSES = COMPLETED_TASK_RUN_STATUSES | FAILED_TASK_RUN_STATUSES
GLOBAL_MONITOR_BUCKETS = ("running", "waiting", "completed", "failed", "diagnostics")
KNOWN_TASK_RUN_STATUSES = (
    RUNNING_TASK_RUN_STATUSES
    | WAITING_TASK_RUN_STATUSES
    | BLOCKED_TASK_RUN_STATUSES
    | FAILED_TASK_RUN_STATUSES
    | COMPLETED_TASK_RUN_STATUSES
)


def task_lifecycle(
    status: str,
    *,
    stale: bool,
    action_required: bool,
    control_state: str = "",
) -> str:
    if status in COMPLETED_TASK_RUN_STATUSES:
        return "completed"
    if status in FAILED_TASK_RUN_STATUSES:
        return "failed"
    if control_state == "paused":
        return "paused"
    if control_state in {"pause_requested", "stop_requested", "replan_requested"}:
        return "running"
    if control_state == "interrupted_for_replan":
        return "waiting"
    if stale:
        return "stale"
    if action_required:
        return "action_required"
    if status in WAITING_TASK_RUN_STATUSES:
        return "waiting"
    return "running"


def monitor_bucket(lifecycle: str) -> str:
    if lifecycle == "completed":
        return "completed"
    if lifecycle == "failed":
        return "failed"
    if lifecycle in {"stale", "action_required", "paused"}:
        return "diagnostics"
    if lifecycle == "waiting":
        return "waiting"
    return "running"


def ended_at(*, status: str, updated_at: float, last_activity_at: float, resource_class: str) -> float | None:
    if resource_class == "dynamic":
        return None
    if status in TERMINAL_TASK_RUN_STATUSES:
        return updated_at or last_activity_at or None
    return last_activity_at or updated_at or None


def is_terminal_status(status: str) -> bool:
    return status in TERMINAL_TASK_RUN_STATUSES
