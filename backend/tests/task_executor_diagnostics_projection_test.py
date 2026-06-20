from __future__ import annotations

from types import SimpleNamespace

from runtime.shared.models import AgentRun, TaskRun
from harness.runtime.runtime_gateway import RuntimeGateway
from harness.runtime.control_events import RuntimeSignalScope
from harness.loop.task_executor import (
    _executor_control_signal_from_task_run,
    _mark_replan_control_signals_consumed_by_model_action,
    _mark_runtime_control_signal_delivered,
    _matching_runtime_control_signal_observation,
    _pause_executor_for_step_budget,
    _runtime_control_signal_already_delivered,
    _runtime_control_signal_fingerprint,
    _runtime_control_signal_projection_from_observations,
    _step_summary_diagnostics_update,
)
from harness.loop.task_run_execution_control import ExecutorControlSignal


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
    event_log = _EventLogStub()
    runtime_host = SimpleNamespace(
        event_log=event_log,
        runtime_gateway=RuntimeGateway(event_log),
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
    gateway_requested = [
        dict(dict(event.payload or {}).get("signal") or {})
        for event in runtime_host.event_log.events
        if event.event_type == "runtime_control_signal_published"
        and dict(dict(event.payload or {}).get("signal") or {}).get("signal_type") == "control.signal.requested"
    ]
    gateway_observed = [
        dict(dict(event.payload or {}).get("signal") or {})
        for event in runtime_host.event_log.events
        if event.event_type == "runtime_control_signal_observed"
        and dict(dict(event.payload or {}).get("signal") or {}).get("signal_type") == "control.signal.requested"
    ]
    assert len(signal_events) == 1
    assert len(gateway_requested) == 1
    assert len(gateway_observed) == 1
    observation = dict(signal_events[0].payload["observation"])
    assert observation["source"] == "system:runtime_control_signal"
    assert observation["needs_model_followup"] is True
    assert observation["payload"]["signal_kind"] == "budget_exhausted"
    assert observation["payload"]["runtime_control_signal_ref"] == gateway_requested[0]["signal_id"]
    assert gateway_observed[0]["signal_id"] == gateway_requested[0]["signal_id"]
    assert dict(gateway_requested[0]["payload"])["adapter"] == "task_executor_step_budget"
    assert observation["payload"]["structured_signal"]["code"] == "runtime_control_budget_exhausted"
    assert runtime_host.runtime_gateway.drain(
        task_run.task_run_id,
        scope=RuntimeSignalScope(session_id="session-test", task_run_id=task_run.task_run_id),
        signal_types={"control.signal.requested"},
    ).pending_signals == ()

    projection = _runtime_control_signal_projection_from_observations(
        [observation],
        runtime_host=runtime_host,
        task_run_id=task_run.task_run_id,
    )
    assert projection[0]["signal_kind"] == "budget_exhausted"
    assert projection[0]["runtime_control_state"] == "waiting_executor"
    assert "预算" in projection[0]["repair_instruction"]


def test_runtime_control_signal_projection_requires_gateway_signal_ref() -> None:
    task_run_id = "taskrun:test:projection-gateway-ref"
    event_log = _EventLogStub()
    runtime_host = SimpleNamespace(runtime_gateway=RuntimeGateway(event_log))
    runtime_host.runtime_gateway.publish(
        task_run_id,
        signal_type="control.signal.requested",
        signal_id="rtsig:canonical",
        scope=RuntimeSignalScope(session_id="session-test", task_run_id=task_run_id),
        source_authority="test.runtime_control_projection",
        payload={"signal_kind": "replan", "reason": "gateway_backed"},
        visibility="model_visible",
    )

    projection = _runtime_control_signal_projection_from_observations(
        [
            {
                "observation_id": "obs:runtime-control:missing-ref",
                "source": "system:runtime_control_signal",
                "summary": "missing Gateway ref must not become model-visible control fact",
                "payload": {
                    "signal_kind": "replan",
                    "runtime_control_state": "waiting_executor",
                    "reason": "legacy_observation_without_gateway_ref",
                },
            },
            {
                "observation_id": "obs:runtime-control:canonical",
                "source": "system:runtime_control_signal",
                "summary": "canonical Gateway-backed signal",
                "payload": {
                    "runtime_control_signal_ref": "rtsig:canonical",
                    "signal_kind": "replan",
                    "runtime_control_state": "waiting_executor",
                    "reason": "gateway_backed",
                },
            },
            {
                "observation_id": "obs:runtime-control:unpublished",
                "source": "system:runtime_control_signal",
                "summary": "unpublished ref must not become model-visible control fact",
                "payload": {
                    "runtime_control_signal_ref": "rtsig:unpublished",
                    "signal_kind": "replan",
                    "runtime_control_state": "waiting_executor",
                    "reason": "unpublished",
                },
            },
        ],
        runtime_host=runtime_host,
        task_run_id=task_run_id,
    )

    assert len(projection) == 1
    assert projection[0]["runtime_control_signal_ref"] == "rtsig:canonical"
    assert projection[0]["signal_id"] == "rtsig:canonical"
    assert projection[0]["signal_kind"] == "replan"


def test_runtime_control_signal_existing_observation_must_match_gateway_signal_ref() -> None:
    signal = ExecutorControlSignal(
        kind="replan",
        task_run_id="taskrun:test:control-match",
        executor_epoch=1,
        reason="test",
        requested_by="test",
        requested_at=1.0,
        signal_id="rtsig:canonical",
    )
    observations = [
        {
            "observation_id": "obs:missing-ref",
            "source": "system:runtime_control_signal",
            "payload": {"runtime_control_signal_fingerprint": "sha256:same"},
        },
        {
            "observation_id": "obs:wrong-ref",
            "source": "system:runtime_control_signal",
            "payload": {
                "runtime_control_signal_ref": "rtsig:other",
                "runtime_control_signal_fingerprint": "sha256:same",
            },
        },
        {
            "observation_id": "obs:canonical",
            "source": "system:runtime_control_signal",
            "payload": {
                "runtime_control_signal_ref": "rtsig:canonical",
                "runtime_control_signal_fingerprint": "sha256:same",
            },
        },
    ]

    matched = _matching_runtime_control_signal_observation(
        observations,
        signal=signal,
        fingerprint="sha256:same",
    )
    no_signal_id = _matching_runtime_control_signal_observation(
        observations,
        signal=ExecutorControlSignal(
            kind="replan",
            task_run_id="taskrun:test:control-match",
            executor_epoch=1,
            reason="test",
            requested_by="test",
            requested_at=1.0,
        ),
        fingerprint="sha256:same",
    )

    assert matched is not None
    assert matched["observation_id"] == "obs:canonical"
    assert no_signal_id is None


def test_runtime_control_signal_delivered_diagnostics_must_match_gateway_signal_ref() -> None:
    signal = ExecutorControlSignal(
        kind="replan",
        task_run_id="taskrun:test:control-delivered",
        executor_epoch=1,
        reason="test",
        requested_by="test",
        requested_at=1.0,
        signal_id="rtsig:canonical",
    )
    fingerprint = "sha256:same"

    missing_ref = TaskRun(
        task_run_id=signal.task_run_id,
        session_id="session-test",
        task_id="task:test:control-delivered",
        execution_runtime_kind="single_agent_task",
        status="running",
        created_at=1.0,
        updated_at=1.0,
        diagnostics={
            "runtime_control": {
                "agent_signal_kind": "replan",
                "agent_signal_fingerprint": fingerprint,
                "agent_signal_observation_ref": "obs:legacy",
            }
        },
    )
    wrong_ref = TaskRun(
        task_run_id=signal.task_run_id,
        session_id="session-test",
        task_id="task:test:control-delivered",
        execution_runtime_kind="single_agent_task",
        status="running",
        created_at=1.0,
        updated_at=1.0,
        diagnostics={
            "runtime_control": {
                "agent_signal_ref": "rtsig:other",
                "agent_signal_kind": "replan",
                "agent_signal_fingerprint": fingerprint,
                "agent_signal_observation_ref": "obs:other",
            }
        },
    )
    matching_ref = TaskRun(
        task_run_id=signal.task_run_id,
        session_id="session-test",
        task_id="task:test:control-delivered",
        execution_runtime_kind="single_agent_task",
        status="running",
        created_at=1.0,
        updated_at=1.0,
        diagnostics={
            "runtime_control": {
                "agent_signal_ref": "rtsig:canonical",
                "agent_signal_kind": "replan",
                "agent_signal_fingerprint": fingerprint,
                "agent_signal_observation_ref": "obs:canonical",
            }
        },
    )

    assert _runtime_control_signal_already_delivered(missing_ref, signal=signal, fingerprint=fingerprint) is False
    assert _runtime_control_signal_already_delivered(wrong_ref, signal=signal, fingerprint=fingerprint) is False
    assert _runtime_control_signal_already_delivered(matching_ref, signal=signal, fingerprint=fingerprint) is True
    assert (
        _runtime_control_signal_already_delivered(
            matching_ref,
            signal=ExecutorControlSignal(
                kind="replan",
                task_run_id=signal.task_run_id,
                executor_epoch=1,
                reason="test",
                requested_by="test",
                requested_at=1.0,
            ),
            fingerprint=fingerprint,
        )
        is False
    )


def test_mark_runtime_control_signal_delivered_persists_gateway_signal_ref() -> None:
    task_run = TaskRun(
        task_run_id="taskrun:test:control-delivered-mark",
        session_id="session-test",
        task_id="task:test:control-delivered-mark",
        execution_runtime_kind="single_agent_task",
        status="running",
        created_at=1.0,
        updated_at=1.0,
        diagnostics={
            "runtime_control": {
                "state": "replan_requested",
                "requested_by": "test",
                "requested_at": 1.0,
                "reason": "test",
            }
        },
    )
    signal = ExecutorControlSignal(
        kind="replan",
        task_run_id=task_run.task_run_id,
        executor_epoch=1,
        reason="test",
        requested_by="test",
        requested_at=1.0,
        signal_id="rtsig:delivered",
    )
    fingerprint = _runtime_control_signal_fingerprint(task_run, signal=signal)
    observation = {
        "observation_id": "obs:delivered",
        "source": "system:runtime_control_signal",
        "created_at": 2.0,
        "payload": {
            "runtime_control_signal_ref": "rtsig:delivered",
            "runtime_control_signal_fingerprint": fingerprint,
        },
    }
    runtime_host = SimpleNamespace(state_index=_StateIndexStub(task_run))

    updated = _mark_runtime_control_signal_delivered(
        runtime_host,
        task_run,
        signal=signal,
        observation=observation,
        fingerprint=fingerprint,
        boundary="test",
        event_offset=7,
    )

    control = dict(updated.diagnostics["runtime_control"])
    assert control["agent_signal_ref"] == "rtsig:delivered"
    assert control["agent_signal_observation_ref"] == "obs:delivered"
    assert _runtime_control_signal_already_delivered(updated, signal=signal, fingerprint=fingerprint) is True
    assert _executor_control_signal_from_task_run(updated, executor_epoch=1, default_reason="test") is None
    assert runtime_host.state_index.get_task_run(task_run.task_run_id) == updated


def test_step_budget_boundary_requires_runtime_gateway_for_model_visible_control_observation() -> None:
    task_run = TaskRun(
        task_run_id="taskrun:test:step-budget-no-gateway",
        session_id="session-test",
        task_id="task:test:step-budget-no-gateway",
        execution_runtime_kind="single_agent_task",
        status="running",
        created_at=1.0,
        updated_at=1.0,
        diagnostics={"executor_epoch": 2, "active_packet_ref": "packet:test:step-budget-no-gateway"},
    )
    agent_run = AgentRun(
        agent_run_id="agrun:test:step-budget-no-gateway",
        task_run_id=task_run.task_run_id,
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        status="running",
    )
    event_log = _EventLogStub()
    runtime_host = SimpleNamespace(
        event_log=event_log,
        runtime_gateway=None,
        runtime_objects=_RuntimeObjectsStub(),
        state_index=_StateIndexStub(task_run),
    )

    result = _pause_executor_for_step_budget(runtime_host, task_run=task_run, agent_run=agent_run, max_steps=2)
    updated = runtime_host.state_index.get_task_run(task_run.task_run_id)
    event_types = [event.event_type for event in runtime_host.event_log.events]

    assert result["ok"] is False
    assert result["error"] == "runtime_gateway_control_signal_unavailable"
    assert updated is not None
    assert updated.status == "waiting_executor"
    assert "runtime_control_signal_published" not in event_types
    assert "task_runtime_control_signal_observed" not in event_types
    assert runtime_host.runtime_objects.objects == {}


def test_replan_steer_consumption_reports_missing_gateway_consumption() -> None:
    task_run = TaskRun(
        task_run_id="taskrun:test:replan-consume-no-gateway",
        session_id="session-test",
        task_id="task:test:replan-consume-no-gateway",
        execution_runtime_kind="single_agent_task",
        status="running",
        created_at=1.0,
        updated_at=1.0,
    )
    runtime_host = SimpleNamespace(runtime_gateway=None)
    observation = {
        "observation_id": "obs:replan:no-gateway",
        "source": "system:runtime_control_signal",
        "payload": {
            "signal_kind": "replan",
            "steer_ref": "steer:no-gateway",
            "runtime_control_signal_ref": "sig:replan:no-gateway",
        },
    }

    result = _mark_replan_control_signals_consumed_by_model_action(
        runtime_host,
        task_run=task_run,
        action_request=SimpleNamespace(request_id="action:consume-steer"),
        observations=[observation],
        consumed_steer_ids=["steer:no-gateway"],
    )

    assert result["required_steer_refs"] == ["steer:no-gateway"]
    assert result["missing_steer_refs"] == ["steer:no-gateway"]
    assert result["consumed_events"] == []


def test_replan_steer_consumption_consumes_canonical_gateway_signal() -> None:
    task_run = TaskRun(
        task_run_id="taskrun:test:replan-consume-canonical",
        session_id="session-test",
        task_id="task:test:replan-consume-canonical",
        execution_runtime_kind="single_agent_task",
        status="running",
        created_at=1.0,
        updated_at=1.0,
    )
    event_log = _EventLogStub()
    gateway = RuntimeGateway(event_log)
    signal_event = gateway.publish(
        task_run.task_run_id,
        signal_type="control.signal.requested",
        scope=RuntimeSignalScope(session_id=task_run.session_id, task_run_id=task_run.task_run_id),
        source_authority="test.replan",
        payload={"signal_kind": "replan", "steer_ref": "steer:canonical"},
    )
    signal_id = str(dict(dict(signal_event.payload or {}).get("signal") or {}).get("signal_id") or "")
    observation = {
        "observation_id": "obs:replan:canonical",
        "source": "system:runtime_control_signal",
        "payload": {
            "signal_kind": "replan",
            "steer_ref": "steer:canonical",
            "runtime_control_signal_ref": signal_id,
        },
    }

    result = _mark_replan_control_signals_consumed_by_model_action(
        SimpleNamespace(runtime_gateway=gateway),
        task_run=task_run,
        action_request=SimpleNamespace(request_id="action:consume-steer"),
        observations=[observation],
        consumed_steer_ids=["steer:canonical"],
    )

    assert result["required_steer_refs"] == ["steer:canonical"]
    assert result["missing_steer_refs"] == []
    assert len(result["consumed_events"]) == 1
    assert gateway.can_consume_by_id(task_run.task_run_id, signal_id=signal_id) is False


def test_replan_steer_consumption_rejects_already_consumed_signal() -> None:
    task_run = TaskRun(
        task_run_id="taskrun:test:replan-consume-closed",
        session_id="session-test",
        task_id="task:test:replan-consume-closed",
        execution_runtime_kind="single_agent_task",
        status="running",
        created_at=1.0,
        updated_at=1.0,
    )
    event_log = _EventLogStub()
    gateway = RuntimeGateway(event_log)
    signal_event = gateway.publish(
        task_run.task_run_id,
        signal_type="control.signal.requested",
        scope=RuntimeSignalScope(session_id=task_run.session_id, task_run_id=task_run.task_run_id),
        source_authority="test.replan",
        payload={"signal_kind": "replan", "steer_ref": "steer:closed"},
    )
    signal_id = str(dict(dict(signal_event.payload or {}).get("signal") or {}).get("signal_id") or "")
    consumed = gateway.mark_consumed_by_id(
        task_run.task_run_id,
        signal_id=signal_id,
        consumed_by="test.preconsumed",
        payload={"terminal_reason": "already_consumed"},
    )
    observation = {
        "observation_id": "obs:replan:closed",
        "source": "system:runtime_control_signal",
        "payload": {
            "signal_kind": "replan",
            "steer_ref": "steer:closed",
            "runtime_control_signal_ref": signal_id,
        },
    }

    result = _mark_replan_control_signals_consumed_by_model_action(
        SimpleNamespace(runtime_gateway=gateway),
        task_run=task_run,
        action_request=SimpleNamespace(request_id="action:consume-steer"),
        observations=[observation],
        consumed_steer_ids=["steer:closed"],
    )

    assert consumed is not None
    assert result["required_steer_refs"] == ["steer:closed"]
    assert result["missing_steer_refs"] == ["steer:closed"]
    assert result["consumed_events"] == []
