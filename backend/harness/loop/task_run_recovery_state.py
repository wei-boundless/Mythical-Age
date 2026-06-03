from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .task_tool_approval import matching_approval_grant_for_pending


RECOVERY_ACTIONS = {"resume_task_run", "rerun_task_executor"}
STOP_CONTROL_STATES = {"stop_requested", "stopped"}
PAUSE_CONTROL_STATES = {"pause_requested", "paused"}
REPLAN_CONTROL_STATES = {"replan_requested", "interrupted_for_replan"}
TERMINAL_COMPLETED_STATUSES = {"completed", "success"}
TERMINAL_STOPPED_STATUSES = {"aborted", "cancelled"}
TERMINAL_FAILED_STATUSES = {"failed", "error"}


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
    status = str(getattr(task_run, "status", "") or "").strip()
    terminal_reason = str(getattr(task_run, "terminal_reason", "") or "").strip()
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    executor_status = str(diagnostics.get("executor_status") or "").strip()
    control_state = _control_state(diagnostics)
    recovery_action = str(diagnostics.get("recovery_action") or "").strip()
    recoverable = _is_recoverable(diagnostics, recovery_action=recovery_action)
    graph_controlled = _is_graph_controlled(diagnostics)
    stopped = control_state in STOP_CONTROL_STATES or terminal_reason == "user_aborted" or status in TERMINAL_STOPPED_STATUSES
    paused = control_state in PAUSE_CONTROL_STATES
    completed_iteration = status in TERMINAL_COMPLETED_STATUSES
    running_claimed = status == "running" and executor_status in {"scheduled", "running"}

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
    elif status == "waiting_executor":
        same_run_resumable = True
        reason = "waiting_executor"
    elif status == "waiting_approval" and matching_approval_grant_for_pending(task_run) is not None:
        same_run_resumable = True
        reason = "approval_granted"
    elif status in {"blocked", "failed"} and recoverable:
        same_run_resumable = True
        reason = "recoverable_terminal"

    executable = same_run_resumable and not paused and control_state not in STOP_CONTROL_STATES
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


def _is_recoverable(diagnostics: dict[str, Any], *, recovery_action: str) -> bool:
    if recovery_action in RECOVERY_ACTIONS:
        recoverable = diagnostics.get("recoverable_error")
        if isinstance(recoverable, dict):
            return recoverable.get("retryable") is not False
        return True
    recoverable = diagnostics.get("recoverable_error")
    return isinstance(recoverable, dict) and recoverable.get("retryable") is not False


def _is_graph_controlled(diagnostics: dict[str, Any]) -> bool:
    origin = diagnostics.get("origin")
    origin_kind = str(diagnostics.get("origin_kind") or dict(origin or {}).get("origin_kind") or "").strip() if isinstance(origin, dict) else str(diagnostics.get("origin_kind") or "").strip()
    return origin_kind == "graph_node_assigned" or bool(diagnostics.get("graph_run_id") or diagnostics.get("graph_harness_config_id"))
