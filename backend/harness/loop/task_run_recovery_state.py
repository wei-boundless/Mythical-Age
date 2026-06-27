from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from harness.task_run_status import (
    COMPLETED_TASK_RUN_STATUSES,
    FAILED_TASK_RUN_STATUSES,
    STOPPED_TASK_RUN_STATUSES,
    is_terminal_task_run_reason,
    normalize_task_run_status,
    runtime_control_state_from_task_run,
)

from .task_launch_gate import matching_launch_gate_pass_for_pending
from .task_tool_approval import matching_approval_grant_for_pending


STOP_CONTROL_STATES = {"stop_requested", "stopped"}
PAUSE_CONTROL_STATES = {"pause_requested", "paused"}
RECOVERY_ACTIONS = {"resume_task_run", "rerun_task_executor"}
RECOVERY_WAIT_REASONS = {
    "resume_requested",
    "task_executor_interrupted_by_runtime_restart",
    "model_call_recovery_required",
    "user_interrupt_replan_required",
    "task_execution_step_budget_exhausted",
    "repeated_admission_denial",
}
RESUME_REQUEST_CONTROL_STATE = "resume_requested"

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


def recovery_state_for_task_run(task_run: Any, *, runtime_host: Any | None = None) -> TaskRunRecoveryState:
    status = normalize_task_run_status(getattr(task_run, "status", "") or "")
    terminal_reason = str(getattr(task_run, "terminal_reason", "") or "").strip()
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    executor_status = str(diagnostics.get("executor_status") or "").strip()
    recovery_action = str(diagnostics.get("recovery_action") or "").strip()
    control_state = runtime_control_state_from_task_run(task_run, runtime_host=runtime_host)
    recoverable = _has_explicit_retryable_recovery(diagnostics, recovery_action=recovery_action)
    graph_controlled = _graph_controlled(diagnostics)
    running_claimed = _has_live_executor_claim(runtime_host, task_run)
    stopped = (
        control_state in STOP_CONTROL_STATES
        or status in STOPPED_TASK_RUN_STATUSES
        or (is_terminal_task_run_reason(terminal_reason) and normalize_task_run_status(terminal_reason) == "aborted")
    )
    paused = control_state in PAUSE_CONTROL_STATES or status == "paused"
    completed_iteration = status in COMPLETED_TASK_RUN_STATUSES
    failed_terminal = status in FAILED_TASK_RUN_STATUSES

    same_run_resumable = False
    reason = "not_resumable"
    if graph_controlled:
        reason = "graph_controlled"
    elif completed_iteration:
        reason = "completed_iteration"
    elif stopped:
        reason = "stopped_terminal"
    elif failed_terminal:
        reason = "failed_terminal"
    elif running_claimed:
        reason = "executor_claimed"
    elif _is_durable_paused_boundary(status=status, control_state=control_state):
        same_run_resumable = True
        reason = "paused"
    elif _is_explicit_resume_request(status=status, control_state=control_state, diagnostics=diagnostics, recovery_action=recovery_action):
        same_run_resumable = True
        reason = "resume_requested"
    elif _is_explicit_recovery_checkpoint(status=status, diagnostics=diagnostics, recovery_action=recovery_action, recoverable=recoverable):
        same_run_resumable = True
        reason = _recovery_reason(diagnostics, fallback="resumable")
    elif status == "waiting_approval" and matching_approval_grant_for_pending(task_run) is not None:
        same_run_resumable = True
        reason = "approval_granted"
    elif status == "waiting_approval" and matching_launch_gate_pass_for_pending(task_run) is not None:
        same_run_resumable = True
        reason = "launch_gate_passed"

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


def should_auto_continue_task_run(task_run: Any, *, runtime_host: Any | None = None) -> bool:
    return recovery_state_for_task_run(task_run, runtime_host=runtime_host).executable


def _has_explicit_retryable_recovery(diagnostics: dict[str, Any], *, recovery_action: str) -> bool:
    if recovery_action not in RECOVERY_ACTIONS:
        return False
    recoverable_error = diagnostics.get("recoverable_error")
    if not isinstance(recoverable_error, dict):
        return False
    return recoverable_error.get("retryable") is not False


def _is_explicit_recovery_checkpoint(
    *,
    status: str,
    diagnostics: dict[str, Any],
    recovery_action: str,
    recoverable: bool,
) -> bool:
    if status not in {"waiting_executor", "blocked"}:
        return False
    if recovery_action not in RECOVERY_ACTIONS or not recoverable:
        return False
    wait_reason = str(diagnostics.get("wait_reason") or "").strip()
    recoverable_error = diagnostics.get("recoverable_error")
    error_code = ""
    if isinstance(recoverable_error, dict):
        error_code = str(recoverable_error.get("error_code") or recoverable_error.get("code") or "").strip()
    return bool(wait_reason or error_code or str(diagnostics.get("latest_step") or "").strip())


def _is_explicit_resume_request(
    *,
    status: str,
    control_state: str,
    diagnostics: dict[str, Any],
    recovery_action: str,
) -> bool:
    if status != "waiting_executor":
        return False
    if recovery_action not in RECOVERY_ACTIONS:
        return False
    if control_state != RESUME_REQUEST_CONTROL_STATE:
        return False
    return str(diagnostics.get("wait_reason") or "").strip() == "resume_requested"


def _is_durable_paused_boundary(*, status: str, control_state: str) -> bool:
    return status in {"waiting_executor", "paused"} and control_state in PAUSE_CONTROL_STATES


def _recovery_reason(diagnostics: dict[str, Any], *, fallback: str) -> str:
    wait_reason = str(diagnostics.get("wait_reason") or "").strip()
    if wait_reason in RECOVERY_WAIT_REASONS:
        return wait_reason
    recoverable_error = diagnostics.get("recoverable_error")
    if isinstance(recoverable_error, dict):
        code = str(recoverable_error.get("error_code") or recoverable_error.get("code") or "").strip()
        if code:
            return code
    return fallback


def _graph_controlled(diagnostics: dict[str, Any]) -> bool:
    origin = diagnostics.get("origin")
    if isinstance(origin, dict):
        origin_kind = str(diagnostics.get("origin_kind") or origin.get("origin_kind") or "").strip()
    else:
        origin_kind = str(diagnostics.get("origin_kind") or "").strip()
    return origin_kind == "graph_node_assigned" or bool(diagnostics.get("graph_run_id") or diagnostics.get("graph_config_id"))


def _has_live_executor_claim(runtime_host: Any | None, task_run: Any) -> bool:
    if runtime_host is None:
        return False
    supervisor = getattr(runtime_host, "agent_run_supervisor", None)
    active_cell = getattr(supervisor, "active_cell_for_task_run", None)
    if not callable(active_cell):
        return False
    task_run_id = str(getattr(task_run, "task_run_id", "") or "").strip()
    session_id = str(getattr(task_run, "session_id", "") or "").strip()
    if not task_run_id:
        return False
    try:
        return active_cell(task_run_id, session_id=session_id) is not None
    except Exception:
        return False
