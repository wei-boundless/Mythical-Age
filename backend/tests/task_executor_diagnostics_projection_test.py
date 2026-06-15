from __future__ import annotations

from types import SimpleNamespace

from runtime.shared.models import AgentRun, TaskRun
from harness.loop.task_executor import _step_summary_diagnostics_update
from harness.loop.task_executor import _pause_executor_for_step_budget, _runtime_control_signal_projection_from_observations


class _EventStub:
    def __init__(self, *, run_id: str, event_type: str, payload: dict, refs: dict, offset: int) -> None:
        self.event_id = f"event:{offset}"
        self.run_id = run_id
        self.event_type = event_type
        self.payload = payload
        self.refs = refs
        self.offset = offset
        self.created_at = 100.0 + offset

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "refs": self.refs,
            "offset": self.offset,
            "created_at": self.created_at,
        }


class _EventLogStub:
    def __init__(self) -> None:
        self.events: list[_EventStub] = []

    def append(self, run_id: str, event_type: str, *, payload: dict | None = None, refs: dict | None = None) -> _EventStub:
        event = _EventStub(
            run_id=run_id,
            event_type=event_type,
            payload=dict(payload or {}),
            refs=dict(refs or {}),
            offset=len(self.events),
        )
        self.events.append(event)
        return event

    def list_events(self, run_id: str) -> list[_EventStub]:
        return [event for event in self.events if event.run_id == run_id]


class _RuntimeObjectsStub:
    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}

    def put_object(self, kind: str, object_id: str, payload: dict) -> str:
        ref = f"rtobj:{kind}:{object_id}"
        self.objects[ref] = dict(payload or {})
        return ref

    def get_object(self, ref: str) -> dict:
        return dict(self.objects.get(str(ref or ""), {}))


class _StateIndexStub:
    def __init__(self, task_run: TaskRun) -> None:
        self.task_runs = {task_run.task_run_id: task_run}
        self.agent_runs: dict[str, AgentRun] = {}

    def get_task_run(self, task_run_id: str) -> TaskRun | None:
        return self.task_runs.get(task_run_id)

    def upsert_task_run(self, task_run: TaskRun) -> None:
        self.task_runs[task_run.task_run_id] = task_run

    def upsert_agent_run(self, agent_run: AgentRun) -> None:
        self.agent_runs[agent_run.agent_run_id] = agent_run


def test_trace_only_tool_summary_does_not_overwrite_public_progress() -> None:
    update = _step_summary_diagnostics_update(
        step="tool_observation:agent_todo",
        status="completed",
        summary='{"items":[{"todo_id":"todo:1"}]}',
        public_progress_note="",
        agent_brief_output='{"items":[{"todo_id":"todo:1"}]}',
        public_action_state={},
        current_judgment="",
        next_action="",
        completion_status="",
        presentation_source="tool_observation.summary",
        tool_name="agent_todo",
    )

    assert update["latest_tool_observation_trace"].startswith('{"items"')
    assert "latest_public_progress_note" not in update
    assert "latest_public_status" not in update
    assert "agent_brief_output" not in update


def test_trace_only_user_steer_status_does_not_overwrite_public_progress() -> None:
    update = _step_summary_diagnostics_update(
        step="active_task_steer_recorded",
        status="running",
        summary="已收到你的补充说明，会在后续处理里优先纳入。",
        public_progress_note="",
        agent_brief_output="",
        public_action_state={},
        current_judgment="",
        next_action="",
        completion_status="",
        presentation_source="system.user_steer_status",
        tool_name="",
    )

    assert "latest_public_progress_note" not in update
    assert "latest_public_status" not in update
    assert update["latest_step_summary"] == ""


def test_model_stage_summary_updates_public_and_model_diagnostics() -> None:
    update = _step_summary_diagnostics_update(
        step="model_action_received:3",
        status="running",
        summary="fallback summary",
        public_progress_note="",
        agent_brief_output="",
        public_action_state={"current_judgment": "已确认目标文件完整可用。"},
        current_judgment="已确认目标文件完整可用。",
        next_action="执行精确修改。",
        completion_status="working",
        presentation_source="model_action.current_judgment",
        tool_name="",
    )

    assert update["latest_public_status"] == "已确认目标文件完整可用。"
    assert update["latest_model_judgment"] == "已确认目标文件完整可用。"
    assert update["latest_next_action"] == "执行精确修改。"
    assert update["latest_completion_status"] == "working"


def test_step_budget_boundary_records_model_visible_control_observation_and_public_wait_status() -> None:
    task_run = TaskRun(
        task_run_id="taskrun:test:step-budget",
        session_id="session-test",
        task_id="task:test:step-budget",
        execution_runtime_kind="single_agent_task",
        status="running",
        created_at=1.0,
        updated_at=1.0,
        diagnostics={"executor_epoch": 2, "active_packet_ref": "packet:test:step-budget"},
    )
    agent_run = AgentRun(
        agent_run_id="agrun:test:step-budget",
        task_run_id=task_run.task_run_id,
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        status="running",
    )
    runtime_host = SimpleNamespace(
        event_log=_EventLogStub(),
        runtime_objects=_RuntimeObjectsStub(),
        state_index=_StateIndexStub(task_run),
    )

    result = _pause_executor_for_step_budget(runtime_host, task_run=task_run, agent_run=agent_run, max_steps=2)

    updated = runtime_host.state_index.get_task_run(task_run.task_run_id)
    assert result["error"] == "task_execution_step_budget_exhausted"
    assert updated is not None
    assert updated.status == "waiting_executor"
    assert updated.terminal_reason == ""
    assert updated.diagnostics["wait_reason"] == "task_execution_step_budget_exhausted"
    assert "可续跑边界" in updated.diagnostics["latest_public_progress_note"]
    assert updated.diagnostics["latest_completion_status"] == "blocked"

    signal_events = [
        event
        for event in runtime_host.event_log.events
        if event.event_type == "task_runtime_control_signal_observed"
    ]
    assert len(signal_events) == 1
    observation = dict(signal_events[0].payload["observation"])
    assert observation["source"] == "system:runtime_control_signal"
    assert observation["needs_model_followup"] is True
    assert observation["payload"]["signal_kind"] == "budget_exhausted"
    assert observation["payload"]["structured_signal"]["code"] == "runtime_control_budget_exhausted"

    projection = _runtime_control_signal_projection_from_observations([observation])
    assert projection[0]["signal_kind"] == "budget_exhausted"
    assert projection[0]["runtime_control_state"] == "waiting_executor"
    assert "预算" in projection[0]["repair_instruction"]
