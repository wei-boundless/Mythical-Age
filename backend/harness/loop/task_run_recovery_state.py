from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from harness.task_run_state_view import task_run_state_view
from harness.task_run_status import COMPLETED_TASK_RUN_STATUSES, normalize_task_run_status

from .task_tool_approval import matching_approval_grant_for_pending


STOP_CONTROL_STATES = {"stop_requested", "stopped"}
PAUSE_CONTROL_STATES = {"pause_requested", "paused"}
REPLAN_CONTROL_STATES = {"replan_requested", "interrupted_for_replan"}

@dataclass(frozen=True, slots=True)
class TaskRunRecoveryState:
    status: str
    executor_status: str
    control_state: str
    terminal_reason: str
    recoverable: bool
    recovery_action: str
    same_run_resumable: bool
    executable: bool
    running_claimed: bool
    paused: bool
    stopped: bool
    graph_controlled: bool
    completed_iteration: bool
    reason: str
    authority: str = "harness.loop.task_run_recovery_state"


def recovery_state_for_task_run(task_run: Any) -> TaskRunRecoveryState:
    status = normalize_task_run_status(getattr(task_run, "status", "") or "")
    terminal_reason = str(getattr(task_run, "terminal_reason", "") or "").strip()
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    executor_status = str(diagnostics.get("executor_status") or "").strip()
    control_state = _control_state(diagnostics)
    recovery_action = str(diagnostics.get("recovery_action") or "").strip()
    view = task_run_state_view(task_run)
    recoverable = bool(view.get("recoverable"))
    graph_controlled = bool(view.get("graph_controlled"))
    task_work_state = str(view.get("task_work_state") or "")
    stopped = task_work_state == "stopped"
    paused = task_work_state == "paused" or control_state in PAUSE_CONTROL_STATES
    completed_iteration = task_work_state == "completed" or status in COMPLETED_TASK_RUN_STATUSES
    running_claimed = bool(view.get("running_claimed"))
    active_executable = bool(task_work_state == "active" and not graph_controlled)

    same_run_resumable = False
    reason = "not_resumable"
    if graph_controlled:
        reason = "graph_controlled"
    elif completed_iteration:
        reason = "completed_iteration"
    elif stopped:
        reason = "stopped_terminal"
    elif running_claimed:
        reason = "executor_claimed"
    elif bool(view.get("can_resume")):
        same_run_resumable = True
        reason = str(view.get("control_reason") or "resumable")
    elif status == "waiting_approval" and matching_approval_grant_for_pending(task_run) is not None:
        same_run_resumable = True
        reason = "approval_granted"
    elif active_executable:
        reason = "active_task_run"

    executable = (active_executable or same_run_resumable) and not paused and control_state not in STOP_CONTROL_STATES
    return TaskRunRecoveryState(
        status=status,
        executor_status=executor_status,
        control_state=control_state,
        terminal_reason=terminal_reason,
        recoverable=recoverable,
        recovery_action=recovery_action,
        same_run_resumable=same_run_resumable,
        executable=executable,
        running_claimed=running_claimed,
        paused=paused,
        stopped=stopped,
        graph_controlled=graph_controlled,
        completed_iteration=completed_iteration,
        reason=reason,
    )


def should_auto_continue_task_run(task_run: Any) -> bool:
    return recovery_state_for_task_run(task_run).executable


def _control_state(diagnostics: dict[str, Any]) -> str:
    control = diagnostics.get("runtime_control")
    if not isinstance(control, dict):
        return ""
    state = str(control.get("state") or "").strip()
    return state if state in {"pause_requested", "paused", "resume_requested", "stop_requested", "stopped", *REPLAN_CONTROL_STATES} else ""
