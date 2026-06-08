from __future__ import annotations

from types import SimpleNamespace

from runtime.shared.models import TaskRun
from tests.support.runtime_stubs import build_harness_runtime

from api.chat import _attach_task_projection_to_public_data, _status_for_public_event
from harness.runtime.session_task_projection import (
    SINGLE_AGENT_TASK_PROJECTION_AUTHORITY,
    build_single_agent_task_projection,
)


def _single_agent_task_run(*, status: str = "waiting_executor", diagnostics: dict[str, object] | None = None) -> TaskRun:
    merged_diagnostics = {
        "turn_id": "turn:session-projection:1",
        "contract": {
            "user_visible_goal": "修复单 Agent 会话任务投影",
            "task_run_goal": "任务在后台 executor 继续执行时保持运行态。",
        },
    }
    merged_diagnostics.update(dict(diagnostics or {}))
    return TaskRun(
        task_run_id="taskrun:turn:session-projection:1:abc",
        session_id="session-projection",
        task_id="task:turn:session-projection:1",
        execution_runtime_kind="single_agent_task",
        status=status,
        created_at=1.0,
        updated_at=2.0,
        diagnostics=merged_diagnostics,
    )


def test_single_agent_task_projection_keeps_scheduled_executor_running() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run = _single_agent_task_run(status="running", diagnostics={"executor_status": "scheduled"})
    events = [
        {
            "event_id": "rtevt:scheduled",
            "run_id": task_run.task_run_id,
            "event_type": "task_run_executor_scheduled",
            "created_at": 3.0,
            "payload": {"step": "task_executor_scheduled"},
            "refs": {"turn_ref": "turn:session-projection:1"},
        }
    ]

    projection = build_single_agent_task_projection(host, task_run, events=events)

    assert projection["authority"] == SINGLE_AGENT_TASK_PROJECTION_AUTHORITY
    assert projection["task_run_id"] == task_run.task_run_id
    assert projection["anchor_turn_id"] == "turn:session-projection:1"
    assert projection["status"] == "running"
    assert projection["phase"] == "scheduled"
    assert projection["user_visible_goal"] == "修复单 Agent 会话任务投影"
    assert "public_timeline" not in projection


def test_chat_scheduled_done_completes_stream_and_carries_task_projection() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run = _single_agent_task_run(diagnostics={"executor_status": "scheduled"})
    host.state_index.upsert_task_run(task_run)
    payload = {
        "terminal_reason": "task_executor_scheduled",
        "runtime_task_run_id": task_run.task_run_id,
    }

    app_runtime = SimpleNamespace(harness_runtime=runtime)

    _attach_task_projection_to_public_data(
        runtime=app_runtime,
        task_run_id=task_run.task_run_id,
        data=payload,
    )

    assert _status_for_public_event("done", payload) == "completed"
    assert payload["background_task_run_id"] == task_run.task_run_id
    assert payload["turn_handoff_completed"] is True
    assert payload["work_status"] == "running"
    assert payload["task_projection"]["status"] == "running"
    assert payload["task_projection"]["phase"] == "scheduled"
    assert "public_timeline" not in payload["task_projection"]


def test_single_agent_task_projection_shows_protocol_repair_as_ready_to_continue() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run = _single_agent_task_run(
        diagnostics={
            "executor_status": "waiting_executor",
            "recovery_action": "rerun_task_executor",
        },
    )
    task_run = TaskRun(
        **{
            **task_run.to_dict(),
            "terminal_reason": "model_action_protocol_repair_required",
        }
    )

    projection = build_single_agent_task_projection(host, task_run, events=[])

    assert projection["status"] == "waiting_user"
    assert projection["task_work_state"] == "ready_to_continue"
    assert projection["phase"] == "handoff"
    assert projection["control"]["can_pause"] is False
    assert projection["control"]["can_resume"] is True
    assert projection["control"]["can_stop"] is True


def test_single_agent_task_projection_prioritizes_recovery_over_stale_executor_status_as_resume_ready() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run = _single_agent_task_run(
        diagnostics={
            "executor_status": "running",
            "recovery_action": "rerun_task_executor",
        },
    )

    projection = build_single_agent_task_projection(host, task_run, events=[])

    assert projection["status"] == "waiting_user"
    assert projection["task_work_state"] == "ready_to_continue"
    assert projection["phase"] == "handoff"
    assert projection["control"]["can_pause"] is False
    assert projection["control"]["can_resume"] is True
    assert projection["control"]["can_stop"] is True
