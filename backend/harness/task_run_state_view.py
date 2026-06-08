from __future__ import annotations

from typing import Any


COMPLETED_STATUSES = {"completed", "success", "done", "succeeded"}
FAILED_STATUSES = {"failed", "error"}
STOPPED_STATUSES = {"aborted", "cancelled", "canceled", "stopped", "user_aborted"}
WAITING_APPROVAL_STATUSES = {"waiting_approval"}
RECOVERY_ACTIONS = {"resume_task_run", "rerun_task_executor"}
PAUSED_CONTROL_STATES = {"pause_requested", "paused"}
STOP_CONTROL_STATES = {"stop_requested", "stopped"}


def task_run_state_view(task_run: Any, *, monitor: dict[str, Any] | None = None) -> dict[str, Any]:
    monitor_record = dict(monitor or {}) if isinstance(monitor, dict) else {}
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    status = _text(getattr(task_run, "status", "") or monitor_record.get("status"))
    terminal_reason = _text(getattr(task_run, "terminal_reason", "") or monitor_record.get("terminal_reason"))
    control = _runtime_control(diagnostics, monitor_record)
    control_state = _text(control.get("state"))
    executor_status = _text(diagnostics.get("executor_status") or monitor_record.get("executor_status"))
    executor_lease_state = _executor_lease_state(
        status=status,
        terminal_reason=terminal_reason,
        executor_status=executor_status,
        diagnostics=diagnostics,
        monitor=monitor_record,
    )
    recovery_action = _text(diagnostics.get("recovery_action") or monitor_record.get("recovery_action"))
    recoverable = _recoverable(diagnostics, recovery_action=recovery_action)
    resumable_breakpoint = _resumable_breakpoint(
        status=status,
        terminal_reason=terminal_reason,
        recovery_action=recovery_action,
        control_state=control_state,
        recoverable=recoverable,
    )
    stopped = control_state in STOP_CONTROL_STATES or terminal_reason in STOPPED_STATUSES or status in STOPPED_STATUSES
    paused = control_state in PAUSED_CONTROL_STATES or status == "paused"
    completed = status in COMPLETED_STATUSES
    terminal_failed = status in FAILED_STATUSES
    pending_approval = _record(diagnostics.get("pending_approval"))
    waiting_approval = status in WAITING_APPROVAL_STATUSES and _text(pending_approval.get("status")) != "approved"
    graph_controlled = _graph_controlled(diagnostics)

    if completed:
        work_state = "completed"
    elif stopped:
        work_state = "stopped"
    elif waiting_approval:
        work_state = "waiting_approval"
    elif paused:
        work_state = "paused"
    elif terminal_failed and recoverable:
        work_state = "ready_to_continue"
    elif terminal_failed:
        work_state = "failed"
    elif status == "blocked" and recoverable:
        work_state = "ready_to_continue"
    elif status == "blocked":
        work_state = "waiting_user"
    elif status == "waiting_executor" and executor_lease_state in {"scheduled", "running"}:
        work_state = "active"
    elif resumable_breakpoint or executor_lease_state in {"lost", "none", "recovering"} and recovery_action in RECOVERY_ACTIONS:
        work_state = "ready_to_continue"
    elif status == "waiting_executor":
        work_state = "waiting_user"
    else:
        work_state = "active"

    can_resume = (
        not graph_controlled
        and work_state in {"ready_to_continue", "paused"}
        and control_state not in STOP_CONTROL_STATES
    )
    running_claimed = work_state == "active" and executor_lease_state in {"scheduled", "running", "recovering"}
    resume_mode = "none"
    if can_resume:
        resume_mode = "same_run"
    elif running_claimed:
        resume_mode = "already_running"
    elif work_state == "waiting_user":
        resume_mode = "needs_user"
    elif work_state == "waiting_approval":
        resume_mode = "needs_approval"

    return {
        "task_status": status,
        "terminal_reason": terminal_reason,
        "task_work_state": work_state,
        "executor_status": executor_status,
        "executor_lease_state": executor_lease_state,
        "control_state": control_state,
        "runtime_control": control,
        "recoverable": recoverable,
        "recovery_action": recovery_action,
        "graph_controlled": graph_controlled,
        "running_claimed": running_claimed,
        "can_resume": can_resume,
        "resume_mode": resume_mode,
        "public_activity_state": _public_activity_state(work_state, executor_lease_state),
        "public_activity_label": _public_activity_label(work_state),
        "control_reason": _control_reason(work_state, executor_lease_state, can_resume, running_claimed),
        "authority": "harness.task_run_state_view",
    }


def _executor_lease_state(
    *,
    status: str,
    terminal_reason: str,
    executor_status: str,
    diagnostics: dict[str, Any],
    monitor: dict[str, Any],
) -> str:
    recovery_action = _text(diagnostics.get("recovery_action") or monitor.get("recovery_action"))
    control_state = _text(_record(diagnostics.get("runtime_control")).get("state") or _record(monitor.get("runtime_control")).get("state"))
    if status == "waiting_executor" and recovery_action in RECOVERY_ACTIONS:
        return "lost"
    if status == "waiting_executor" and (terminal_reason == "waiting_executor" or control_state in {"resume_requested", "paused", "interrupted_for_replan"}):
        return "lost"
    explicit = _text(diagnostics.get("executor_lease_state") or monitor.get("executor_lease_state"))
    if explicit in {"none", "scheduled", "running", "lost", "recovering", "blocked"}:
        return explicit
    if executor_status == "scheduled":
        return "scheduled"
    if executor_status == "running":
        return "running"
    if executor_status in {"retrying", "recovering"}:
        return "recovering"
    if executor_status in {"lost", "waiting_executor"}:
        return "lost"
    if executor_status in {"blocked", "failed", "error"}:
        return "blocked"
    if status == "waiting_executor":
        return "lost"
    return "none"


def _recoverable(diagnostics: dict[str, Any], *, recovery_action: str) -> bool:
    recoverable_error = diagnostics.get("recoverable_error")
    if recovery_action in RECOVERY_ACTIONS:
        if isinstance(recoverable_error, dict):
            return recoverable_error.get("retryable") is not False
        return True
    return isinstance(recoverable_error, dict) and recoverable_error.get("retryable") is not False


def _resumable_breakpoint(
    *,
    status: str,
    terminal_reason: str,
    recovery_action: str,
    control_state: str,
    recoverable: bool,
) -> bool:
    if recovery_action in RECOVERY_ACTIONS and recoverable:
        return True
    if status == "waiting_executor" and terminal_reason == "waiting_executor":
        return True
    if status == "waiting_executor" and control_state in {"resume_requested", "interrupted_for_replan"}:
        return True
    return False


def _runtime_control(diagnostics: dict[str, Any], monitor: dict[str, Any]) -> dict[str, Any]:
    control = monitor.get("runtime_control")
    if not isinstance(control, dict):
        control = diagnostics.get("runtime_control")
    if not isinstance(control, dict):
        return {}
    return {
        "state": str(control.get("state") or ""),
        "requested_by": str(control.get("requested_by") or ""),
        "requested_at": float(control.get("requested_at") or 0.0),
        "reason": str(control.get("reason") or ""),
        "authority": str(control.get("authority") or "orchestration.task_run_control"),
    }


def _public_activity_state(work_state: str, executor_lease_state: str) -> str:
    if work_state == "active":
        return "running"
    if work_state in {"ready_to_continue", "waiting_user", "waiting_approval"}:
        return "waiting"
    if work_state == "paused":
        return "paused"
    if work_state == "completed":
        return "completed"
    if work_state == "stopped":
        return "stopped"
    if work_state == "failed":
        return "failed"
    return "idle"


def _public_activity_label(work_state: str) -> str:
    return {
        "active": "运行中",
        "ready_to_continue": "可继续",
        "paused": "已暂停",
        "waiting_user": "等待处理",
        "waiting_approval": "等待确认",
        "completed": "已完成",
        "stopped": "已停止",
        "failed": "失败",
    }.get(work_state, "任务")


def _control_reason(work_state: str, executor_lease_state: str, can_resume: bool, running_claimed: bool) -> str:
    if can_resume:
        return "resumable"
    if running_claimed:
        return "running_task"
    if executor_lease_state == "lost":
        return "executor_lease_lost"
    if work_state in {"completed", "failed", "stopped"}:
        return "terminal"
    if work_state == "waiting_approval":
        return "waiting_approval"
    if work_state == "waiting_user":
        return "waiting_user"
    return "not_available"


def _graph_controlled(diagnostics: dict[str, Any]) -> bool:
    origin = diagnostics.get("origin")
    origin_kind = str(diagnostics.get("origin_kind") or dict(origin or {}).get("origin_kind") or "").strip() if isinstance(origin, dict) else str(diagnostics.get("origin_kind") or "").strip()
    return origin_kind == "graph_node_assigned" or bool(diagnostics.get("graph_run_id") or diagnostics.get("graph_harness_config_id"))


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()
