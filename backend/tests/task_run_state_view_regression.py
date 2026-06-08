from __future__ import annotations

import pytest

from harness.loop.task_run_recovery_state import recovery_state_for_task_run
from harness.task_run_state_view import task_run_state_view
from runtime.shared.models import TaskRun


def _task_run(
    *,
    status: str,
    terminal_reason: str = "",
    diagnostics: dict[str, object] | None = None,
) -> TaskRun:
    return TaskRun(
        task_run_id=f"taskrun:state-view:{status}",
        session_id="session-state-view",
        task_id=f"task:{status}",
        execution_runtime_kind="single_agent_task",
        status=status,
        terminal_reason=terminal_reason,
        created_at=1.0,
        updated_at=2.0,
        diagnostics=dict(diagnostics or {}),
    )


@pytest.mark.parametrize(
    ("task_kwargs", "expected"),
    [
        (
            {
                "status": "waiting_executor",
                "terminal_reason": "waiting_executor",
                "diagnostics": {"executor_status": "waiting_executor", "recovery_action": "rerun_task_executor"},
            },
            {"work": "ready_to_continue", "activity": "waiting", "pause": False, "resume": True, "stop": True},
        ),
        (
            {
                "status": "waiting_executor",
                "terminal_reason": "waiting_executor",
                "diagnostics": {
                    "runtime_control": {"state": "paused", "requested_by": "user"},
                    "executor_status": "waiting_executor",
                    "recovery_action": "resume_task_run",
                },
            },
            {"work": "paused", "activity": "paused", "pause": False, "resume": True, "stop": True},
        ),
        (
            {"status": "running", "diagnostics": {"executor_status": "running"}},
            {"work": "active", "activity": "running", "pause": True, "resume": False, "stop": True},
        ),
        (
            {"status": "waiting_approval", "diagnostics": {"pending_approval": {"status": "pending"}}},
            {"work": "waiting_approval", "activity": "waiting", "pause": False, "resume": False, "stop": True},
        ),
        (
            {"status": "running", "diagnostics": {"executor_status": "running", "origin_kind": "graph_node_assigned"}},
            {"work": "active", "activity": "running", "pause": False, "resume": False, "stop": False, "graph": True},
        ),
        (
            {
                "status": "failed",
                "terminal_reason": "model_call_recovery_required",
                "diagnostics": {
                    "executor_status": "failed",
                    "recoverable_error": {"error_code": "model_call_failed", "retryable": True},
                    "recovery_action": "rerun_task_executor",
                },
            },
            {"work": "failed", "activity": "failed", "pause": False, "resume": False, "stop": False, "executable": False},
        ),
    ],
)
def test_task_run_state_view_control_matrix(task_kwargs: dict[str, object], expected: dict[str, object]) -> None:
    task_run = _task_run(**task_kwargs)  # type: ignore[arg-type]
    view = task_run_state_view(task_run)
    capability = dict(view.get("control_capability") or {})

    assert view["task_work_state"] == expected["work"]
    assert view["activity"]["activity_state"] == expected["activity"]
    assert view["graph_controlled"] is bool(expected.get("graph", False))
    assert capability["can_pause_task"] is expected["pause"]
    assert capability["can_resume_task"] is expected["resume"]
    assert capability["can_stop_task"] is expected["stop"]
    if "executable" in expected:
        assert recovery_state_for_task_run(task_run).executable is expected["executable"]
