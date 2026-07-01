from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


CANONICAL_TASK_RUN_STATUSES = frozenset(
    {
        "created",
        "admitted",
        "running",
        "waiting_executor",
        "waiting_approval",
        "blocked",
        "completed",
        "failed",
        "aborted",
    }
)

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
GATEWAY_BACKED_CONTROL_REQUEST_STATES = frozenset(
    {
        "pause_requested",
        "replan_requested",
        "stop_requested",
    }
)


def normalize_task_run_status(value: Any) -> str:
    return str(value or "").strip().lower()


def is_terminal_task_run_status(value: Any) -> bool:
    return normalize_task_run_status(value) in TERMINAL_TASK_RUN_STATUSES


def is_terminal_task_run_reason(value: Any) -> bool:
    reason = str(value or "").strip().lower()
    return is_terminal_task_run_status(reason) or reason in TERMINAL_TASK_RUN_REASONS


def runtime_control_payload_from_task_run(
    task_run: Any,
    *,
    runtime_control: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if task_run is None:
        return {}
    if isinstance(runtime_control, dict):
        return dict(runtime_control)
    view = _task_run_read_view(task_run)
    if view.runtime_control:
        return dict(view.runtime_control)
    control = view.diagnostics.get("runtime_control")
    if isinstance(control, dict):
        return dict(control)
    if view.control_state:
        return {"state": view.control_state}
    return {}


def runtime_control_signal_ref_from_task_run(
    task_run: Any,
    *,
    runtime_control: dict[str, Any] | None = None,
) -> str:
    control = runtime_control_payload_from_task_run(task_run, runtime_control=runtime_control)
    return str(control.get("runtime_control_signal_ref") or "").strip()


def runtime_control_stop_state_is_authoritative(
    task_run: Any,
    *,
    runtime_host: Any | None = None,
    runtime_control: dict[str, Any] | None = None,
) -> bool:
    control = runtime_control_payload_from_task_run(task_run, runtime_control=runtime_control)
    state = str(control.get("state") or "").strip().lower()
    if state not in STOP_CONTROL_STATES:
        return False
    if _stopped_by_durable_lifecycle(task_run):
        return True
    signal_ref = runtime_control_signal_ref_from_task_run(task_run, runtime_control=control)
    if not signal_ref:
        return False
    if runtime_host is None:
        return False
    task_run_id = _task_run_id(task_run)
    if not task_run_id:
        return False
    runtime_gateway = getattr(runtime_host, "runtime_gateway", None)
    signal_by_id = getattr(runtime_gateway, "signal_by_id", None)
    if not callable(signal_by_id):
        return False
    try:
        return signal_by_id(task_run_id, signal_id=signal_ref) is not None
    except Exception:
        return False


def runtime_control_request_state_is_authoritative(
    task_run: Any,
    *,
    runtime_host: Any | None = None,
    runtime_control: dict[str, Any] | None = None,
) -> bool:
    control = runtime_control_payload_from_task_run(task_run, runtime_control=runtime_control)
    state = str(control.get("state") or "").strip().lower()
    if state not in GATEWAY_BACKED_CONTROL_REQUEST_STATES:
        return False
    signal_ref = runtime_control_signal_ref_from_task_run(task_run, runtime_control=control)
    if not signal_ref:
        return False
    if runtime_host is None:
        return False
    task_run_id = _task_run_id(task_run)
    if not task_run_id:
        return False
    runtime_gateway = getattr(runtime_host, "runtime_gateway", None)
    signal_by_id = getattr(runtime_gateway, "signal_by_id", None)
    if not callable(signal_by_id):
        return False
    try:
        return signal_by_id(task_run_id, signal_id=signal_ref) is not None
    except Exception:
        return False


def runtime_control_state_from_task_run(
    task_run: Any,
    *,
    runtime_host: Any | None = None,
    runtime_control: dict[str, Any] | None = None,
) -> str:
    control = runtime_control_payload_from_task_run(task_run, runtime_control=runtime_control)
    state = str(control.get("state") or "").strip().lower()
    if not state:
        return ""
    if state in GATEWAY_BACKED_CONTROL_REQUEST_STATES and not runtime_control_request_state_is_authoritative(
        task_run,
        runtime_host=runtime_host,
        runtime_control=control,
    ):
        return ""
    if state in STOP_CONTROL_STATES and not runtime_control_stop_state_is_authoritative(
        task_run,
        runtime_host=runtime_host,
        runtime_control=control,
    ):
        return ""
    if state == "paused" and _task_run_status(task_run) not in {"waiting_executor", "paused"}:
        return ""
    if state == "interrupted_for_replan" and _task_run_status(task_run) != "waiting_executor":
        return ""
    return state


def is_stopped_or_terminal_task_run(task_run: Any, *, runtime_host: Any | None = None) -> bool:
    if task_run is None:
        return True
    view = _task_run_read_view(task_run)
    return (
        is_terminal_task_run_status(view.status)
        or is_terminal_task_run_reason(view.terminal_reason)
        or runtime_control_state_from_task_run(task_run, runtime_host=runtime_host) in STOP_CONTROL_STATES
    )


def _stopped_by_durable_lifecycle(task_run: Any) -> bool:
    if task_run is None:
        return False
    view = _task_run_read_view(task_run)
    if normalize_task_run_status(view.status) in STOPPED_TASK_RUN_STATUSES:
        return True
    reason = str(view.terminal_reason or "").strip().lower()
    return normalize_task_run_status(reason) in STOPPED_TASK_RUN_STATUSES


def _task_run_status(task_run: Any) -> str:
    return _task_run_read_view(task_run).status


def _task_run_id(task_run: Any) -> str:
    return _task_run_read_view(task_run).task_run_id


@dataclass(frozen=True, slots=True)
class _TaskRunReadView:
    task_run_id: str = ""
    status: str = ""
    terminal_reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    runtime_control: dict[str, Any] = field(default_factory=dict)
    control_state: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", dict(self.diagnostics or {}))
        object.__setattr__(self, "runtime_control", dict(self.runtime_control or {}))


def _task_run_read_view(task_run: Any) -> _TaskRunReadView:
    if task_run is None:
        return _TaskRunReadView()
    if isinstance(task_run, dict):
        diagnostics = task_run.get("diagnostics")
        runtime_control = task_run.get("runtime_control")
        return _TaskRunReadView(
            task_run_id=str(task_run.get("task_run_id") or task_run.get("task_run_ref") or "").strip(),
            status=normalize_task_run_status(task_run.get("status")),
            terminal_reason=str(task_run.get("terminal_reason") or "").strip(),
            diagnostics=diagnostics if isinstance(diagnostics, dict) else {},
            runtime_control=runtime_control if isinstance(runtime_control, dict) else {},
            control_state=str(task_run.get("control_state") or "").strip(),
        )
    diagnostics = getattr(task_run, "diagnostics", None)
    runtime_control = getattr(task_run, "runtime_control", None)
    return _TaskRunReadView(
        task_run_id=str(getattr(task_run, "task_run_id", "") or "").strip(),
        status=normalize_task_run_status(getattr(task_run, "status", "")),
        terminal_reason=str(getattr(task_run, "terminal_reason", "") or "").strip(),
        diagnostics=diagnostics if isinstance(diagnostics, dict) else {},
        runtime_control=runtime_control if isinstance(runtime_control, dict) else {},
        control_state=str(getattr(task_run, "control_state", "") or "").strip(),
    )
