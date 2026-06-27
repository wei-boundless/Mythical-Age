from __future__ import annotations

import re
import threading
import time
from types import SimpleNamespace

from tests.support.harness_runtime_facade_support import *
from harness.runtime.assembly import build_runtime_assembly_profile
from harness.runtime.control_events import RuntimeSignalScope
from harness.loop.model_action_protocol import ModelActionRequest, TaskExecutionModelActionRequest
from harness.loop.task_executor import (
    TaskToolChildActionProtocolError,
    _pause_executor_for_tool_approval,
    _task_tool_child_action_requests,
)
from harness.loop.task_lifecycle import contract_from_action_request, start_task_lifecycle
from harness.loop.turn_to_task_context_handoff import build_turn_to_task_context_handoff_seed
from harness.task_run_state_view import task_run_state_view
from runtime.memory.file_evidence_scope import session_file_evidence_scope, task_run_file_evidence_scope
from runtime.shared.models import AgentRun
from runtime.tool_runtime.tool_result_envelope import build_tool_result_envelope


def _runtime_gateway_signals(
    host,
    task_run_id: str,
    event_type: str,
    *,
    signal_type: str = "control.signal.requested",
) -> list[dict[str, object]]:
    trace = host.get_trace(task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    return [
        dict(dict(event.get("payload") or {}).get("signal") or {})
        for event in events
        if event.get("event_type") == event_type
        and dict(dict(event.get("payload") or {}).get("signal") or {}).get("signal_type") == signal_type
    ]


def _wait_until(condition, *, timeout: float = 3.0, interval: float = 0.01, reason: str = "condition") -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return
        time.sleep(interval)
    raise AssertionError(reason)


def test_task_tool_child_requests_do_not_generate_missing_tool_call_id() -> None:
    action = TaskExecutionModelActionRequest(
        request_id="task-action:missing-tool-id",
        turn_id="turn:missing-tool-id",
        action_type="tool_call",
        tool_call={"tool_name": "read_file", "args": {"path": "README.md"}},
        tool_calls=({"tool_name": "read_file", "args": {"path": "README.md"}},),
    )

    try:
        _task_tool_child_action_requests(action)
    except TaskToolChildActionProtocolError as exc:
        assert exc.code == "task_tool_call_id_required"
    else:
        raise AssertionError("task executor must not generate a fallback tool_call_id")


def _wait_for_running_executor(host, task_run_id: str, model=None, *, timeout: float = 3.0) -> None:
    def _running() -> bool:
        task = host.state_index.get_task_run(task_run_id)
        diagnostics = dict(getattr(task, "diagnostics", {}) or {}) if task is not None else {}
        model_started = model is None or int(getattr(model, "calls", 0) or 0) >= 1
        return diagnostics.get("executor_status") == "running" and model_started

    _wait_until(_running, timeout=timeout, reason="scheduled executor did not enter running model call")


def _wait_for_task_status(host, task_run_id: str, status: str, *, timeout: float = 5.0) -> None:
    def _status_reached() -> bool:
        task = host.state_index.get_task_run(task_run_id)
        return task is not None and str(getattr(task, "status", "") or "") == status

    _wait_until(_status_reached, timeout=timeout, reason=f"task did not reach {status}")


def _join_scheduled_cell(host, schedule: dict[str, object], *, timeout: float = 3.0) -> None:
    cell = host.agent_run_supervisor.cell_by_id(str(schedule.get("run_cell_id") or ""))
    if cell is not None and cell.worker_handle is not None:
        assert cell.worker_handle.join(timeout=timeout)


def _assistant_final_text(events: list[dict[str, object]]) -> str:
    finals = [event for event in events if event.get("event_type") == "assistant_text_final"]
    if not finals:
        return ""
    return str(dict(finals[-1].get("payload") or {}).get("content") or "")


def test_scoped_tool_observation_fails_closed_when_agent_scope_gate_unavailable() -> None:
    scoped_status = task_executor_module._agent_cell_scope_status(
        SimpleNamespace(),
        task_run_id="taskrun:scope-gate-missing",
        agent_run_id="agrun:scope-gate-missing",
        run_cell_id="runcell:scope-gate-missing",
    )
    unscoped_status = task_executor_module._agent_cell_scope_status(
        SimpleNamespace(),
        task_run_id="taskrun:scope-gate-missing",
    )

    assert scoped_status["accepted"] is False
    assert scoped_status["reason"] == "agent_scope_gate_unavailable"
    assert scoped_status["rejected_scope"]["run_cell_id"] == "runcell:scope-gate-missing"
    assert unscoped_status["accepted"] is True
    assert unscoped_status["reason"] == "run_cell_scope_unscoped"


def test_runtime_control_closeout_requires_gateway_signal_lookup() -> None:
    class ConsumptionOnlyGateway:
        def mark_consumed_by_id(self, *_args, **_kwargs):
            return SimpleNamespace(event_id="event:consumed")

    can_consume = task_executor_module._runtime_control_signal_gateway_can_consume(
        SimpleNamespace(runtime_gateway=ConsumptionOnlyGateway()),
        task_run=SimpleNamespace(task_run_id="taskrun:missing-signal-lookup"),
        control_observation={
            "payload": {
                "runtime_control_signal_ref": "control-signal:missing-lookup",
            }
        },
    )

    assert can_consume is False


def test_runtime_control_closeout_rejects_already_consumed_signal() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:already-consumed-closeout"
    signal_event = host.runtime_gateway.publish(
        task_run_id,
        signal_type="control.signal.requested",
        scope=RuntimeSignalScope(session_id="session-already-consumed-closeout", task_run_id=task_run_id),
        source_authority="test.runtime_control_closeout",
        payload={"signal_kind": "stop", "task_run_id": task_run_id},
        refs={"task_run_ref": task_run_id},
    )
    signal_id = str(dict(dict(signal_event.payload or {}).get("signal") or {}).get("signal_id") or "")
    consumed = host.runtime_gateway.mark_consumed_by_id(
        task_run_id,
        signal_id=signal_id,
        consumed_by="test.preconsumed",
        payload={"terminal_reason": "already_closed"},
    )

    can_consume = task_executor_module._runtime_control_signal_gateway_can_consume(
        host,
        task_run=SimpleNamespace(task_run_id=task_run_id),
        control_observation={
            "payload": {
                "runtime_control_signal_ref": signal_id,
            }
        },
    )

    assert consumed is not None
    assert can_consume is False


def test_assistant_task_run_final_commit_preserves_structural_lifecycle_fields() -> None:
    runtime = build_harness_runtime()

    runtime._apply_assistant_message_commit(
        "session-structural-taskrun",
        {
            "role": "assistant",
            "content": "final",
            "task_run_id": "taskrun:turn:session-structural-taskrun:1:abc",
            "task_id": "task:turn:session-structural-taskrun:1",
            "completion_state": "completed",
            "terminal_reason": "completed",
            "answer_channel": "final_answer",
            "answer_source": "harness.loop.task_executor.completed",
        },
    )

    messages = runtime.session_manager.load_session("session-structural-taskrun")

    assert len(messages) == 1
    assert messages[0]["task_run_id"] == "taskrun:turn:session-structural-taskrun:1:abc"
    assert messages[0]["task_id"] == "task:turn:session-structural-taskrun:1"
    assert messages[0]["completion_state"] == "completed"
    assert messages[0]["terminal_reason"] == "completed"
    assert messages[0]["answer_channel"] == "final_answer"


def test_task_lifecycle_records_turn_to_task_handoff_and_materializes_file_state(tmp_path) -> None:
    runtime = build_harness_runtime(base_dir=_runtime_test_root(tmp_path))
    host = runtime.single_agent_runtime_host
    session_id = "session-turn-task-handoff"
    turn_id = "turn:session-turn-task-handoff:1"
    read_event = {
        "event_type": "read",
        "path": "backend/harness/loop/single_agent_turn.py",
        "start_line": 1,
        "end_line": 3,
        "total_lines": 500,
        "content_sha256": "sha256:turn-read",
        "read_intent": "inspect",
        "visible_exact": True,
        "artifact_ref_status": "exact",
    }
    host.file_state_store.apply_events_scope(
        session_file_evidence_scope(session_id),
        [read_event],
        observation_ref="toolobs:turn-read",
        tool_call_id="call:turn-read",
    )
    result_envelope = build_tool_result_envelope(
        tool_name="read_file",
        tool_args={"path": "backend/harness/loop/single_agent_turn.py", "start_line": 1, "line_count": 3},
        result={
            "text": "read ok",
            "structured_payload": {
                "observed_paths": ["backend/harness/loop/single_agent_turn.py"],
                "file_state_events": [read_event],
            },
        },
        status="ok",
        tool_call_id="call:turn-read",
        action_request_id="model-action:turn-read",
        caller_kind="agent_turn",
        caller_ref=f"turnrun:{turn_id}",
    ).to_dict()
    handoff_seed = build_turn_to_task_context_handoff_seed(
        runtime_host=host,
        session_id=session_id,
        turn_id=turn_id,
        source_packet_ref="rtpacket:parent-turn",
        tool_observation_payloads=[
            {
                "observation_id": "toolobs:turn-read",
                "invocation_id": "toolinvoke:turn-read",
                "caller_kind": "agent_turn",
                "caller_ref": f"turnrun:{turn_id}",
                "tool_name": "read_file",
                "operation_id": "read_file",
                "status": "ok",
                "text": "read ok",
                "result_envelope": result_envelope,
                "tool_call_id": "call:turn-read",
                "authority": "runtime.tool_runtime.tool_observation",
            }
        ],
        session_context={
            "memory_context": {
                "memory_runtime_view_ref": "memview:turn",
                "context_package_ref": "mempkg:turn",
                "selected_sections": ["relevant_durable_context"],
                "model_visible_sections": {
                    "relevant_durable_context": ["turn-selected memory fact"],
                },
            },
            "turn_input_facts": {"user_intent": "start task with inherited context"},
        },
    )
    action_request = ModelActionRequest(
        request_id="model-action:start-task",
        turn_id=turn_id,
        action_type="request_task_run",
        public_progress_note="Start task.",
        task_contract_seed=_canonical_task_contract_seed(
            {
                "user_visible_goal": "Verify handoff",
                "task_run_goal": "Verify task start handoff",
                "completion_criteria": ["handoff recorded"],
            }
        ),
        diagnostics={"packet_ref": "rtpacket:parent-turn"},
    )
    contract, errors = contract_from_action_request(
        action_request,
        packet_ref="rtpacket:parent-turn",
    )

    assert contract is not None, errors
    task_run, _agent_run, _lifecycle, lifecycle_events = start_task_lifecycle(
        host,
        session_id=session_id,
        turn_id=turn_id,
        task_id="task:handoff",
        action_request=action_request,
        contract=contract,
        agent_profile_ref="main_interactive_agent",
        start_context_handoff=handoff_seed,
    )
    stored_task = host.state_index.get_task_run(task_run.task_run_id)
    diagnostics = dict(stored_task.diagnostics)
    handoff_ref = diagnostics["turn_to_task_context_handoff_ref"]
    handoff = host.runtime_objects.get_object(handoff_ref)
    lifecycle_started = next(event for event in lifecycle_events if event["type"] == "task_run_lifecycle_started")
    file_state = host.file_state_store.snapshot_scope(
        task_run_file_evidence_scope(task_run.task_run_id, session_id=session_id)
    )

    assert handoff["source_packet_ref"] == "rtpacket:parent-turn"
    assert handoff["inherited_memory_context"]["memory_runtime_view_ref"] == "memview:turn"
    assert handoff["inherited_observation_refs"] == ["toolobs:turn-read"]
    assert dict(lifecycle_started["event"]["refs"])["turn_to_task_context_handoff_ref"] == handoff_ref
    assert any(event["type"] == "task_run_lifecycle_event" and dict(event["event"])["event_type"] == "turn_to_task_context_handoff_recorded" for event in lifecycle_events)
    assert file_state
    assert file_state[-1]["path"] == "backend/harness/loop/single_agent_turn.py"


def test_task_run_success_projects_body_after_commit_ack_before_completed_lifecycle() -> None:
    final_answer = "Executor final answer."
    runtime = build_harness_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            content=json.dumps(
                _action_request(
                    action_type="respond",
                    final_answer=final_answer,
                    public_progress_note="Ready to complete.",
                ),
                ensure_ascii=False,
            )
        )
    )
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:turn:session-output-order:1:abc",
        session_id="session-output-order",
        status="created",
    )
    seeded = host.state_index.get_task_run(task_run_id)
    host.state_index.upsert_task_run(
        replace(
            seeded,
            diagnostics={
                **dict(seeded.diagnostics or {}),
                "turn_id": "turn:session-output-order:1",
            },
        )
    )

    schedule_result = runtime.schedule_task_run_executor(
        task_run_id,
        scheduler="test_session_output_order",
        turn_id="turn:session-output-order:1",
        max_steps=2,
    )
    cell = host.agent_run_supervisor.cell_by_id(str(schedule_result.get("run_cell_id") or ""))
    assert schedule_result["ok"] is True
    assert schedule_result["scheduled"] is True
    assert cell is not None
    assert cell.worker_handle is not None
    assert cell.worker_handle.join(timeout=3)
    events = host.event_log.list_events(task_run_id)
    event_types = [str(event.event_type) for event in events]
    body_event = next(event for event in events if event.event_type == "assistant_text_final")
    ack_event = next(event for event in events if event.event_type == "session_output_commit_ack")
    completed_event = next(
        event
        for event in events
        if event.event_type == "task_run_lifecycle_finished"
        and dict(dict(event.payload or {}).get("lifecycle") or {}).get("status") == "completed"
    )
    messages = runtime.session_manager.load_session("session-output-order")
    finished_task = host.state_index.get_task_run(task_run_id)

    assert finished_task.status == "completed"
    assert dict(body_event.payload)["content"] == final_answer
    assert event_types.index("session_output_commit_checked") < event_types.index("session_output_commit_ack")
    assert event_types.index("session_output_commit_ack") < event_types.index("assistant_text_final")
    assert int(ack_event.offset) < int(completed_event.offset)
    assert dict(ack_event.payload)["state"] == "committed"
    assert dict(finished_task.diagnostics)["output_commit_status"] == "committed"
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == final_answer
    assert messages[-1]["turn_id"] == "turn:session-output-order:1"


def test_old_cell_final_commit_is_rejected_before_session_write(tmp_path) -> None:
    runtime = build_harness_runtime(base_dir=_runtime_test_root(tmp_path))
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:turn:session-late-commit-cell:1:abc",
        session_id="session-late-commit-cell",
        status="running",
    )
    release = threading.Event()

    async def _hold_current_cell() -> dict[str, object]:
        while not release.is_set():
            await asyncio.sleep(0.01)
        return {"status": "completed"}

    schedule = host.agent_run_supervisor.schedule_task_run(
        task_run_id=task_run_id,
        work_factory=_hold_current_cell,
        scheduler="test.current-cell",
        max_steps=1,
    )
    assert schedule["scheduled"] is True
    current_task = host.state_index.get_task_run(task_run_id)
    stale_scope = {
        "session_id": current_task.session_id,
        "task_run_id": task_run_id,
        "agent_run_id": "agrun:old-late-final",
        "run_cell_id": "runcell:old-late-final",
        "invocation_kind": "task_run",
    }
    stale_task = replace(
        current_task,
        diagnostics={
            **dict(current_task.diagnostics or {}),
            "agent_run_scope": stale_scope,
            "agent_run_id": stale_scope["agent_run_id"],
            "run_cell_id": stale_scope["run_cell_id"],
        },
    )

    try:
        receipt = task_executor_module._commit_task_run_final_message(
            runtime._task_executor_services_for_task_run(current_task),
            task_run=stale_task,
            final_answer="late answer from an old cell",
        )
        events = host.event_log.list_events(task_run_id)
        event_types = [str(event.event_type) for event in events]
        late_event = next(event for event in events if event.event_type == "agent_runtime_cell_late_event_rejected")

        assert receipt["state"] == "skipped"
        assert receipt["reason"] == "agent_cell_stale_run_cell"
        assert "assistant_text_final" not in event_types
        assert "session_output_commit_ack" not in event_types
        assert dict(late_event.payload)["event_kind"] == "output_commit"
        assert dict(dict(late_event.payload)["scope_status"])["accepted"] is False
        assert runtime.session_manager.load_session("session-late-commit-cell") == []
    finally:
        release.set()
        cell = host.agent_run_supervisor.cell_by_id(str(schedule.get("run_cell_id") or ""))
        if cell is not None and cell.worker_handle is not None:
            assert cell.worker_handle.join(timeout=3)


def test_closed_cell_final_commit_is_rejected_before_session_write(tmp_path) -> None:
    runtime = build_harness_runtime(base_dir=_runtime_test_root(tmp_path))
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:turn:session-closed-cell-commit:1:abc",
        session_id="session-closed-cell-commit",
        status="running",
    )

    async def _short_cell() -> dict[str, object]:
        return {"status": "completed"}

    schedule = host.agent_run_supervisor.schedule_task_run(
        task_run_id=task_run_id,
        work_factory=_short_cell,
        scheduler="test.closed-cell",
        max_steps=1,
    )
    assert schedule["scheduled"] is True
    cell = host.agent_run_supervisor.cell_by_id(str(schedule.get("run_cell_id") or ""))
    assert cell is not None
    assert cell.worker_handle is not None
    assert cell.worker_handle.join(timeout=3)
    assert host.agent_run_supervisor.active_cell_for_task_run(task_run_id, session_id="session-closed-cell-commit") is None

    task = host.state_index.get_task_run(task_run_id)
    receipt = task_executor_module._commit_task_run_final_message(
        runtime._task_executor_services_for_task_run(task),
        task_run=task,
        final_answer="late answer from a closed cell",
    )
    events = host.event_log.list_events(task_run_id)
    event_types = [str(event.event_type) for event in events]
    late_event = next(event for event in events if event.event_type == "agent_runtime_cell_late_event_rejected")

    assert receipt["state"] == "skipped"
    assert receipt["reason"] == "agent_cell_active_cell_missing"
    assert "assistant_text_final" not in event_types
    assert "session_output_commit_ack" not in event_types
    assert dict(late_event.payload)["event_kind"] == "output_commit"
    assert dict(dict(late_event.payload)["scope_status"])["reason"] == "active_cell_missing"
    assert runtime.session_manager.load_session("session-closed-cell-commit") == []


def test_closed_cell_output_commit_skipped_uses_current_cell_gate(tmp_path) -> None:
    runtime = build_harness_runtime(base_dir=_runtime_test_root(tmp_path))
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:turn:session-closed-cell-skipped:1:abc",
        session_id="session-closed-cell-skipped",
        status="running",
    )

    async def _short_cell() -> dict[str, object]:
        return {"status": "completed"}

    schedule = host.agent_run_supervisor.schedule_task_run(
        task_run_id=task_run_id,
        work_factory=_short_cell,
        scheduler="test.closed-cell-skipped",
        max_steps=1,
    )
    assert schedule["scheduled"] is True
    cell = host.agent_run_supervisor.cell_by_id(str(schedule.get("run_cell_id") or ""))
    assert cell is not None
    assert cell.worker_handle is not None
    assert cell.worker_handle.join(timeout=3)
    assert host.agent_run_supervisor.active_cell_for_task_run(task_run_id, session_id="session-closed-cell-skipped") is None

    task = host.state_index.get_task_run(task_run_id)
    receipt = task_executor_module._record_session_output_commit_skipped(
        host,
        task_run=task,
        final_answer="subagent output should not be session visible",
        reason="not_main_session_visible",
    )
    events = host.event_log.list_events(task_run_id)
    late_event = next(event for event in events if event.event_type == "agent_runtime_cell_late_event_rejected")
    skipped_event = next(event for event in events if event.event_type == "session_output_commit_skipped")

    assert receipt["state"] == "skipped"
    assert receipt["reason"] == "agent_cell_active_cell_missing"
    assert dict(late_event.payload)["event_kind"] == "output_commit"
    assert dict(dict(late_event.payload)["scope_status"])["reason"] == "active_cell_missing"
    assert dict(skipped_event.refs)["run_cell_ref"] == str(schedule["run_cell_id"])
    assert runtime.session_manager.load_session("session-closed-cell-skipped") == []


def test_task_run_tool_lifecycle_preserves_model_tool_call_id(tmp_path) -> None:
    model_tool_call_id = "call:task-read-custom"
    model = NativeToolCallSequenceModelRuntimeStub(
        [
            {
                "content": json.dumps(
                    _tool_calls_action_request(
                        tool_calls=[
                            {
                                "id": model_tool_call_id,
                                "tool_name": "read_file",
                                "args": {"path": "harness/loop/task_executor.py", "line_count": 1},
                            }
                        ],
                        public_progress_note="读取 task executor 入口。",
                    ),
                    ensure_ascii=False,
                )
            },
            {
                "content": json.dumps(
                    _action_request(
                        action_type="respond",
                        final_answer="读取完成。",
                        public_progress_note="工具结果已经确认。",
                    ),
                    ensure_ascii=False,
                )
            },
        ]
    )
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(_project_backend_dir(), {"read_file"}),
    )
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:turn:session-tool-id:1:abc",
        session_id="session-tool-id",
        status="running",
    )
    seeded = host.state_index.get_task_run(task_run_id)
    host.state_index.upsert_task_run(
        replace(
            seeded,
            diagnostics={
                **dict(seeded.diagnostics or {}),
                "turn_id": "turn:session-tool-id:1",
            },
        )
    )

    async def _work() -> dict[str, object]:
        return await runtime.execute_task_run(task_run_id, max_steps=3)

    schedule = host.agent_run_supervisor.schedule_task_run(
        task_run_id=task_run_id,
        work_factory=_work,
        scheduler="test.task-tool-lifecycle-id",
        max_steps=3,
    )
    assert schedule["scheduled"] is True
    cell = host.agent_run_supervisor.cell_by_id(str(schedule.get("run_cell_id") or ""))
    assert cell is not None
    assert cell.worker_handle is not None
    assert cell.worker_handle.join(timeout=60)
    assert cell.worker_handle.error is None
    result = cell.worker_handle.result
    events = host.event_log.list_events(task_run_id)
    admission_event = next(
        event
        for event in events
        if event.event_type == "model_action_admission_checked"
        and dict(dict(event.payload or {}).get("model_action_request") or {}).get("action_type") == "tool_call"
    )
    started_event = next(event for event in events if event.event_type == "tool_item_started")
    observation_event = next(event for event in events if event.event_type == "task_tool_observation_recorded")
    observation = dict(dict(observation_event.payload or {}).get("observation") or {})
    tool_payload = dict(observation.get("payload") or {})
    completed = _project_public_stream_event(
        "task_tool_observation_recorded",
        {"event": observation_event.to_dict()},
    )

    assert result["ok"] is True
    assert dict(dict(admission_event.payload or {}).get("model_action_request") or {})["tool_call"]["id"] == model_tool_call_id
    assert str(dict(admission_event.refs or {}).get("action_lifecycle_ref") or "")
    assert dict(started_event.refs or {}).get("action_lifecycle_ref") == dict(admission_event.refs or {}).get("action_lifecycle_ref")
    assert dict(started_event.payload)["tool_call_id"] == model_tool_call_id
    assert observation["tool_call_id"] == model_tool_call_id
    assert tool_payload["tool_call_id"] == model_tool_call_id
    assert [event_type for event_type, _ in completed] == ["tool_item_completed"]
    assert completed[0][1]["tool_call_id"] == model_tool_call_id


def test_old_cell_tool_observation_is_rejected_before_observation_write(tmp_path, monkeypatch) -> None:
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        tool_runtime=_tool_runtime_for_names(_project_backend_dir(), {"read_file"}),
    )
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:turn:session-late-tool-cell:1:abc",
        session_id="session-late-tool-cell",
        status="running",
    )
    release = threading.Event()

    async def _hold_current_cell() -> dict[str, object]:
        while not release.is_set():
            await asyncio.sleep(0.01)
        return {"status": "completed"}

    schedule = host.agent_run_supervisor.schedule_task_run(
        task_run_id=task_run_id,
        work_factory=_hold_current_cell,
        scheduler="test.current-cell",
        max_steps=1,
    )
    assert schedule["scheduled"] is True
    current_task = host.state_index.get_task_run(task_run_id)
    stale_scope = {
        "session_id": current_task.session_id,
        "task_run_id": task_run_id,
        "agent_run_id": "agrun:old-late-tool",
        "run_cell_id": "runcell:old-late-tool",
        "invocation_kind": "task_run",
    }
    stale_task = replace(
        current_task,
        diagnostics={
            **dict(current_task.diagnostics or {}),
            "agent_run_scope": stale_scope,
            "agent_run_id": stale_scope["agent_run_id"],
            "run_cell_id": stale_scope["run_cell_id"],
        },
    )
    action_request = TaskExecutionModelActionRequest(
        request_id="request:late-tool",
        turn_id="turn:session-late-tool-cell:1",
        action_type="tool_call",
        tool_call={"id": "call:late-tool", "tool_name": "read_file", "args": {"path": "README.md"}},
        tool_calls=({"id": "call:late-tool", "tool_name": "read_file", "args": {"path": "README.md"}},),
    )
    stale_observation = {
        "observation_id": "toolobs:old-late-tool",
        "task_run_id": task_run_id,
        "observation_type": "tool_result",
        "source": "tool:read_file",
        "request_ref": "request:late-tool",
        "directive_ref": "runtime-directive:late-tool",
        "content_chars": 11,
        "payload": {
            "tool_name": "read_file",
            "tool_call_id": "call:late-tool",
            "agent_run_id": str(schedule["agent_run_id"]),
            "run_cell_id": str(schedule["run_cell_id"]),
            "status": "ok",
            "result_ref": "tool-result:old-late-tool",
            "execution_receipt": {
                "task_run_id": task_run_id,
                "agent_run_id": str(schedule["agent_run_id"]),
                "run_cell_id": str(schedule["run_cell_id"]),
                "tool_invocation_id": "toolinv:old-late-tool",
            },
            "result_envelope": {
                "result_ref": "tool-result:old-late-tool",
                "tool_call_id": "call:late-tool",
                "execution_receipt": {
                    "task_run_id": task_run_id,
                    "agent_run_id": stale_scope["agent_run_id"],
                    "run_cell_id": stale_scope["run_cell_id"],
                },
            },
        },
        "needs_model_followup": False,
        "authority": "runtime.runtime_observation",
    }

    async def _late_group_result(group, *, invocation_rows, **_kwargs):
        return {"results": [(invocation_rows[0], stale_observation)], "interrupt": None}

    monkeypatch.setattr(task_executor_module, "_execute_task_tool_batch_group", _late_group_result)

    try:
        result = asyncio.run(
            task_executor_module._process_task_tool_call_batch(
                host,
                services=runtime._task_executor_services_for_task_run(current_task),
                current_task=stale_task,
                agent_run=AgentRun(
                    agent_run_id=stale_scope["agent_run_id"],
                    task_run_id=task_run_id,
                    agent_id="agent:old",
                    agent_profile_id="main_interactive_agent",
                    status="running",
                ),
                action_request=action_request,
                runtime_assembly=SimpleNamespace(profile=SimpleNamespace(to_dict=lambda: {}), to_dict=lambda: {}),
                runtime_tool_plan=SimpleNamespace(plan_id="toolplan:late-tool", dispatchable_tool_names=("read_file",)),
                allowed_tool_names={"read_file"},
                runtime_permission_mode="full_access",
                runtime_fingerprint={"tool_config_hash": "tool-config:late-tool"},
                raw_observations=[],
                observations=[],
                execution_state={},
                artifact_refs=[],
                packet_ref="rtpacket:late-tool",
                step_index=1,
            )
        )
        events = host.event_log.list_events(task_run_id)
        event_types = [str(event.event_type) for event in events]
        late_event = next(event for event in events if event.event_type == "agent_runtime_cell_late_event_rejected")

        assert result["raw_observations"] == []
        assert result["observations"] == []
        assert host.runtime_objects.get_object("rtobj:observation:toolobs:old-late-tool") == {}
        assert "task_tool_observation_recorded" not in event_types
        assert dict(late_event.payload)["event_kind"] == "tool_observation"
        assert dict(dict(late_event.payload)["scope_status"])["reason"] == "stale_run_cell"
        assert dict(late_event.refs)["run_cell_ref"] == stale_scope["run_cell_id"]
    finally:
        release.set()
        cell = host.agent_run_supervisor.cell_by_id(str(schedule.get("run_cell_id") or ""))
        if cell is not None and cell.worker_handle is not None:
            assert cell.worker_handle.join(timeout=3)


def test_closed_cell_tool_observation_is_rejected_before_observation_write(tmp_path, monkeypatch) -> None:
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        tool_runtime=_tool_runtime_for_names(_project_backend_dir(), {"read_file"}),
    )
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:turn:session-closed-tool-cell:1:abc",
        session_id="session-closed-tool-cell",
        status="running",
    )

    async def _short_cell() -> dict[str, object]:
        return {"status": "completed"}

    schedule = host.agent_run_supervisor.schedule_task_run(
        task_run_id=task_run_id,
        work_factory=_short_cell,
        scheduler="test.closed-tool-cell",
        max_steps=1,
    )
    assert schedule["scheduled"] is True
    cell = host.agent_run_supervisor.cell_by_id(str(schedule.get("run_cell_id") or ""))
    assert cell is not None
    assert cell.worker_handle is not None
    assert cell.worker_handle.join(timeout=3)
    assert host.agent_run_supervisor.active_cell_for_task_run(task_run_id, session_id="session-closed-tool-cell") is None

    task = host.state_index.get_task_run(task_run_id)
    agent_run_id = str(schedule["agent_run_id"])
    run_cell_id = str(schedule["run_cell_id"])
    action_request = TaskExecutionModelActionRequest(
        request_id="request:closed-late-tool",
        turn_id="turn:session-closed-tool-cell:1",
        action_type="tool_call",
        tool_call={"id": "call:closed-late-tool", "tool_name": "read_file", "args": {"path": "README.md"}},
        tool_calls=({"id": "call:closed-late-tool", "tool_name": "read_file", "args": {"path": "README.md"}},),
    )
    late_observation = {
        "observation_id": "toolobs:closed-late-tool",
        "task_run_id": task_run_id,
        "observation_type": "tool_result",
        "source": "tool:read_file",
        "request_ref": "request:closed-late-tool",
        "directive_ref": "runtime-directive:closed-late-tool",
        "content_chars": 11,
        "payload": {
            "tool_name": "read_file",
            "tool_call_id": "call:closed-late-tool",
            "status": "ok",
            "result_ref": "tool-result:closed-late-tool",
            "execution_receipt": {
                "task_run_id": task_run_id,
                "agent_run_id": agent_run_id,
                "run_cell_id": run_cell_id,
                "tool_invocation_id": "toolinv:closed-late-tool",
            },
            "result_envelope": {
                "result_ref": "tool-result:closed-late-tool",
                "tool_call_id": "call:closed-late-tool",
                "execution_receipt": {
                    "task_run_id": task_run_id,
                    "agent_run_id": agent_run_id,
                    "run_cell_id": run_cell_id,
                },
            },
        },
        "needs_model_followup": False,
        "authority": "runtime.runtime_observation",
    }

    async def _late_group_result(group, *, invocation_rows, **_kwargs):
        return {"results": [(invocation_rows[0], late_observation)], "interrupt": None}

    monkeypatch.setattr(task_executor_module, "_execute_task_tool_batch_group", _late_group_result)

    result = asyncio.run(
        task_executor_module._process_task_tool_call_batch(
            host,
            services=runtime._task_executor_services_for_task_run(task),
            current_task=task,
            agent_run=AgentRun(
                agent_run_id=agent_run_id,
                task_run_id=task_run_id,
                agent_id="agent:closed",
                agent_profile_id="main_interactive_agent",
                status="running",
            ),
            action_request=action_request,
            runtime_assembly=SimpleNamespace(profile=SimpleNamespace(to_dict=lambda: {}), to_dict=lambda: {}),
            runtime_tool_plan=SimpleNamespace(plan_id="toolplan:closed-late-tool", dispatchable_tool_names=("read_file",)),
            allowed_tool_names={"read_file"},
            runtime_permission_mode="full_access",
            runtime_fingerprint={"tool_config_hash": "tool-config:closed-late-tool"},
            raw_observations=[],
            observations=[],
            execution_state={},
            artifact_refs=[],
            packet_ref="rtpacket:closed-late-tool",
            step_index=1,
        )
    )
    events = host.event_log.list_events(task_run_id)
    event_types = [str(event.event_type) for event in events]
    late_event = next(event for event in events if event.event_type == "agent_runtime_cell_late_event_rejected")

    assert result["raw_observations"] == []
    assert result["observations"] == []
    assert host.runtime_objects.get_object("rtobj:observation:toolobs:closed-late-tool") == {}
    assert "task_tool_observation_recorded" not in event_types
    assert dict(late_event.payload)["event_kind"] == "tool_observation"
    assert dict(dict(late_event.payload)["scope_status"])["reason"] == "active_cell_missing"
    assert dict(late_event.refs)["run_cell_ref"] == run_cell_id


def test_task_run_pending_approval_preserves_model_tool_call_id(tmp_path) -> None:
    from harness.loop.task_executor import approve_task_run_tool_call
    from harness.loop.task_tool_approval import publish_task_tool_approval_requested

    runtime = build_harness_runtime(base_dir=_runtime_test_root(tmp_path))
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:turn:session-tool-approval-id:1:abc",
        session_id="session-tool-approval-id",
        status="running",
    )
    task_run = host.state_index.get_task_run(task_run_id)
    agent_run = AgentRun(
        agent_run_id=f"agrun:{task_run_id}:main",
        task_run_id=task_run_id,
        agent_id="agent:main",
        agent_profile_id="main_interactive_agent",
        status="running",
    )
    action_request = TaskExecutionModelActionRequest(
        request_id="request:write-file",
        turn_id="turn:session-tool-approval-id:1",
        action_type="tool_call",
        tool_call={
            "id": "call:write-file-model",
            "tool_name": "write_file",
            "args": {"path": "README.md", "content": "updated"},
        },
        tool_calls=(
            {
                "id": "call:write-file-model",
                "tool_name": "write_file",
                "args": {"path": "README.md", "content": "updated"},
            },
        ),
    )

    result = _pause_executor_for_tool_approval(
        host,
        task_run=task_run,
        agent_run=agent_run,
        action_request=action_request,
        observation={
            "observation_id": "toolobs:approval:write",
            "directive_ref": "runtime-directive:approval:write",
            "payload": {
                "operation_id": "op.write_file",
                "approval_risk_fingerprint": "approval-risk:write-file-model",
                "operation_gate": {"decision": "requires_approval"},
                "execution_receipt": {"tool_call_id": "call:write-file-shadow"},
                "result_envelope": {
                    "operation_id": "op.write_file",
                    "tool_call_id": "call:write-file-model",
                    "execution_receipt": {"tool_call_id": "call:write-file-model"},
                },
            },
        },
        observation_event=SimpleNamespace(offset=7),
        step_index=1,
    )
    updated_task = host.state_index.get_task_run(task_run_id)
    publish_task_tool_approval_requested(
        host,
        task_run=updated_task,
        pending_approval=result["pending_approval"],
    )
    approval_result = approve_task_run_tool_call(host, task_run_id, reason="looks_good", requested_by="user")
    events = host.event_log.list_events(task_run_id)
    approval_requested = [
        dict(dict(event.payload or {}).get("signal") or {})
        for event in events
        if event.event_type == "runtime_control_signal_published"
        and dict(dict(event.payload or {}).get("signal") or {}).get("signal_type") == "approval.requested"
    ]
    approval_granted = [
        dict(dict(event.payload or {}).get("signal") or {})
        for event in events
        if event.event_type == "runtime_control_signal_published"
        and dict(dict(event.payload or {}).get("signal") or {}).get("signal_type") == "approval.granted"
    ]

    assert result["error"] == "waiting_approval"
    assert result["pending_approval"]["action_request_ref"] == "request:write-file"
    assert result["pending_approval"]["tool_call_id"] == "call:write-file-model"
    assert result["pending_approval"]["execution_receipt"]["tool_call_id"] == "call:write-file-model"
    assert dict(updated_task.diagnostics)["pending_approval"]["tool_call_id"] == "call:write-file-model"
    assert approval_result["accepted"] is True
    assert len(approval_requested) == 1
    assert len(approval_granted) == 1
    assert approval_requested[0]["signal_id"] == f"approval-requested:{result['pending_approval']['approval_request_id']}"
    assert approval_granted[0]["signal_id"] == f"approval-granted:{approval_result['approval_grant']['grant_id']}"
    assert dict(approval_requested[0]["payload"])["approval_request_id"] == result["pending_approval"]["approval_request_id"]
    assert dict(approval_granted[0]["payload"])["grant_id"] == approval_result["approval_grant"]["grant_id"]
    assert dict(approval_granted[0]["payload"])["approval_request_id"] == result["pending_approval"]["approval_request_id"]
    assert dict(approval_requested[0]["scope"])["task_run_id"] == task_run_id
    assert dict(approval_granted[0]["scope"])["task_run_id"] == task_run_id


def test_task_tool_approval_grant_requires_and_matches_tool_call_id() -> None:
    from harness.loop.task_tool_approval import build_task_tool_approval_grant, grant_matches_pending

    task = SimpleNamespace(task_run_id="taskrun:approval-identity")
    pending = {
        "task_run_id": "taskrun:approval-identity",
        "approval_request_id": "approval-request:identity",
        "action_request_ref": "request:write-file",
        "tool_call_id": "call:write-file-a",
        "tool_name": "write_file",
        "operation_id": "op.write_file",
        "directive_ref": "runtime-directive:approval:identity",
        "approval_risk_fingerprint": "approval-risk:identity",
    }

    assert build_task_tool_approval_grant(
        task_run=task,
        pending_approval={key: value for key, value in pending.items() if key != "tool_call_id"},
        requested_by="user",
    ) is None

    grant = build_task_tool_approval_grant(
        task_run=task,
        pending_approval=pending,
        requested_by="user",
    )

    assert grant is not None
    assert grant.tool_call_id == "call:write-file-a"
    assert grant_matches_pending(grant, pending) is True
    assert grant_matches_pending(grant, {**pending, "tool_call_id": "call:write-file-b"}) is False


def test_tool_approval_request_requires_runtime_gateway(tmp_path) -> None:
    runtime = build_harness_runtime(base_dir=_runtime_test_root(tmp_path))
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:approval-request-no-gateway",
        session_id="session-approval-request-no-gateway",
        status="running",
    )
    task_run = host.state_index.get_task_run(task_run_id)
    agent_run = AgentRun(
        agent_run_id=f"agrun:{task_run_id}:main",
        task_run_id=task_run_id,
        agent_id="agent:main",
        agent_profile_id="main_interactive_agent",
        status="running",
    )
    action_request = TaskExecutionModelActionRequest(
        request_id="request:write-no-gateway",
        turn_id="turn:approval-request-no-gateway:1",
        action_type="tool_call",
        tool_call={
            "id": "call:write-no-gateway",
            "tool_name": "write_file",
            "args": {"path": "README.md", "content": "updated"},
        },
    )
    host.runtime_gateway = None

    result = _pause_executor_for_tool_approval(
        host,
        task_run=task_run,
        agent_run=agent_run,
        action_request=action_request,
        observation={
            "observation_id": "toolobs:approval:no-gateway",
            "directive_ref": "runtime-directive:approval:no-gateway",
            "payload": {
                "operation_id": "op.write_file",
                "approval_risk_fingerprint": "approval-risk:no-gateway",
                "operation_gate": {"decision": "requires_approval"},
                "execution_receipt": {"tool_call_id": "call:write-no-gateway"},
            },
        },
        observation_event=SimpleNamespace(offset=3),
        step_index=1,
    )
    stored = host.state_index.get_task_run(task_run_id)
    event_types = [event.event_type for event in host.event_log.list_events(task_run_id)]

    assert result["ok"] is False
    assert result["error"] == "runtime_gateway_approval_signal_unavailable"
    assert stored.status == "running"
    assert "approval_waiting" not in event_types
    assert "pending_approval" not in dict(stored.diagnostics or {})


def test_tool_approval_grant_requires_runtime_gateway(tmp_path) -> None:
    from harness.loop.task_executor import approve_task_run_tool_call

    runtime = build_harness_runtime(base_dir=_runtime_test_root(tmp_path))
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:approval-grant-no-gateway",
        session_id="session-approval-grant-no-gateway",
        status="waiting_approval",
    )
    task_run = host.state_index.get_task_run(task_run_id)
    pending = {
        "approval_request_id": "approval-request:no-gateway",
        "status": "pending",
        "task_run_id": task_run_id,
        "action_request_ref": "request:no-gateway",
        "tool_call_id": "call:no-gateway",
        "tool_name": "write_file",
        "operation_id": "op.write_file",
        "directive_ref": "runtime-directive:approval:no-gateway",
        "approval_risk_fingerprint": "approval-risk:grant-no-gateway",
        "tool_args_hash": "hash:no-gateway",
    }
    host.state_index.upsert_task_run(replace(task_run, diagnostics={**dict(task_run.diagnostics or {}), "pending_approval": pending}))
    host.runtime_gateway = None

    result = approve_task_run_tool_call(host, task_run_id, reason="ok", requested_by="user")
    stored = host.state_index.get_task_run(task_run_id)
    event_types = [event.event_type for event in host.event_log.list_events(task_run_id)]

    assert result["ok"] is False
    assert result["error"] == "runtime_gateway_approval_signal_unavailable"
    assert dict(stored.diagnostics or {})["pending_approval"]["status"] == "pending"
    assert "approval_state" not in dict(stored.diagnostics or {})
    assert "task_tool_approval_granted" not in event_types


def test_task_run_final_output_without_turn_id_uses_task_run_output_turn_id() -> None:
    runtime = build_harness_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            content=json.dumps(
                _action_request(
                    action_type="respond",
                    final_answer="This answer is committed with a task-run scoped output turn id.",
                    public_progress_note="Ready to complete.",
                ),
                ensure_ascii=False,
            )
        )
    )
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:turn:session-output-missing-turn:1:abc",
        session_id="session-output-missing-turn",
        status="waiting_executor",
    )
    seeded_task = host.state_index.get_task_run(task_run_id)
    host.state_index.upsert_task_run(
        replace(
            seeded_task,
            diagnostics={
                **dict(seeded_task.diagnostics or {}),
                "executor_status": "waiting_executor",
                "recovery_action": "rerun_task_executor",
                "recoverable_error": {
                    "error_code": "test_task_run_output_turn_id_recovery",
                    "retryable": True,
                },
            },
        )
    )

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=2))
    events = host.event_log.list_events(task_run_id)
    packet_event = next(event for event in events if event.event_type == "runtime_invocation_packet_compiled")
    evidence_event = next(event for event in events if event.event_type == "runtime_evidence_projection_published")
    ack_event = next(event for event in events if event.event_type == "session_output_commit_ack")
    lifecycle_event = next(event for event in events if event.event_type == "task_run_lifecycle_finished")
    evidence_payload = dict(dict(evidence_event.payload or {}).get("evidence_projection") or {})
    ack_payload = dict(ack_event.payload or {})
    lifecycle_payload = dict(dict(lifecycle_event.payload or {}).get("lifecycle") or {})
    finished_task = host.state_index.get_task_run(task_run_id)
    messages = runtime.session_manager.load_session("session-output-missing-turn")

    assert result["ok"] is True
    assert finished_task.status == "completed"
    assert lifecycle_payload["status"] == "completed"
    assert int(packet_event.offset) < int(evidence_event.offset) < int(ack_event.offset)
    assert evidence_event.refs["runtime_invocation_packet_ref"] == packet_event.refs["runtime_invocation_packet_ref"]
    assert evidence_payload["task_run_id"] == task_run_id
    assert evidence_payload["scope"]["task_run_id"] == task_run_id
    assert int(ack_event.offset) < int(lifecycle_event.offset)
    assert ack_payload["reason"] == "committed"
    assert str(ack_payload["turn_id"]).startswith("taskrun-final:")
    assert dict(finished_task.diagnostics)["execution_result_status"] == "completed"
    assert dict(finished_task.diagnostics)["output_commit_status"] == "committed"
    assert messages[-1]["turn_id"] == ack_payload["turn_id"]


def test_running_stop_signal_is_observed_by_agent_before_closeout() -> None:
    from harness.loop.task_executor import stop_task_run

    class InterruptibleStopModelRuntime:
        def __init__(self) -> None:
            self.calls = 0
            self.seen_messages: list[list[object]] = []

        async def invoke_messages(self, messages, **_kwargs):
            self.calls += 1
            self.seen_messages.append(list(messages or []))
            if self.calls == 1:
                await asyncio.sleep(60)
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(
                        action_type="respond",
                        final_answer="agent-authored stop closeout",
                    ),
                    ensure_ascii=False,
                )
            )

    model = InterruptibleStopModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:stop-signal",
        session_id="session-stop-signal",
        status="created",
    )

    schedule = runtime.schedule_task_run_executor(task_run_id, scheduler="test_stop_signal", max_steps=4)
    stop_requested = False
    try:
        assert schedule["scheduled"] is True
        _wait_for_running_executor(host, task_run_id, model)
        stop_result = stop_task_run(host, task_run_id, reason="user_stop_test", requested_by="user")
        stop_requested = True
        assert stop_result["accepted"] is True
        _wait_for_task_status(host, task_run_id, "aborted")
        _join_scheduled_cell(host, schedule)
    finally:
        if not stop_requested:
            stop_task_run(host, task_run_id, reason="test_cleanup", requested_by="test")
        _join_scheduled_cell(host, schedule, timeout=1)

    task = host.state_index.get_task_run(task_run_id)
    trace = host.get_trace(task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    event_types = [str(event.get("event_type") or "") for event in events]
    gateway_requested = [
        dict(dict(event.get("payload") or {}).get("signal") or {})
        for event in events
        if event.get("event_type") == "runtime_control_signal_published"
        and dict(dict(event.get("payload") or {}).get("signal") or {}).get("signal_type") == "control.signal.requested"
    ]
    gateway_observed = [
        dict(dict(event.get("payload") or {}).get("signal") or {})
        for event in events
        if event.get("event_type") == "runtime_control_signal_observed"
        and dict(dict(event.get("payload") or {}).get("signal") or {}).get("signal_type") == "control.signal.requested"
    ]
    gateway_consumed = [
        dict(dict(event.get("payload") or {}).get("signal") or {})
        for event in events
        if event.get("event_type") == "runtime_control_signal_consumed"
        and dict(dict(event.get("payload") or {}).get("signal") or {}).get("signal_type") == "control.signal.requested"
    ]
    control_observations = [
        dict(dict(event.get("payload") or {}).get("observation") or {})
        for event in events
        if event.get("event_type") == "task_runtime_control_signal_observed"
    ]
    lifecycle_event = next(
        event
        for event in events
        if event.get("event_type") == "task_run_lifecycle_finished"
        and dict(dict(event.get("payload") or {}).get("lifecycle") or {}).get("status") == "aborted"
    )
    second_model_payload = json.dumps(model.seen_messages[1:], ensure_ascii=False, default=str)

    assert task is not None
    assert task.status == "aborted"
    assert task.terminal_reason == "user_aborted"
    assert _assistant_final_text(events) == "agent-authored stop closeout"
    assert event_types.count("task_runtime_control_signal_observed") == 1
    assert len(gateway_requested) == 1
    assert len(gateway_observed) == 1
    assert len(gateway_consumed) == 1
    assert gateway_requested[0]["signal_id"] == gateway_observed[0]["signal_id"]
    assert gateway_requested[0]["signal_id"] == gateway_consumed[0]["signal_id"]
    assert dict(gateway_requested[0]["payload"])["signal_kind"] == "stop"
    assert dict(gateway_observed[0]["payload"])["observation_ref"] == control_observations[0]["observation_id"]
    assert dict(gateway_consumed[0]["payload"])["observation_ref"] == control_observations[0]["observation_id"]
    assert dict(gateway_consumed[0]["payload"])["terminal_reason"] == "user_aborted"
    assert dict(gateway_consumed[0]["payload"])["lifecycle_status"] == "aborted"
    assert dict(gateway_consumed[0]["payload"])["task_lifecycle_event_ref"] == lifecycle_event["event_id"]
    assert int(dict(gateway_consumed[0]["payload"])["task_lifecycle_event_offset"]) == int(lifecycle_event["offset"])
    assert host.runtime_gateway.drain(
        task_run_id,
        scope=RuntimeSignalScope(
            session_id="session-stop-signal",
            task_run_id=task_run_id,
        ),
        signal_types={"control.signal.requested"},
    ).pending_signals == ()
    assert "task_run_stopped" not in event_types
    assert control_observations
    assert control_observations[0]["source"] == "system:runtime_control_signal"
    assert dict(control_observations[0]["payload"])["signal_kind"] == "stop"
    assert dict(control_observations[0]["payload"])["runtime_control_signal_ref"] == gateway_requested[0]["signal_id"]
    assert "runtime_control_signal" in second_model_payload
    assert "signal_kind" in second_model_payload


def test_scheduled_stop_signal_uses_cell_scoped_runtime_gateway() -> None:
    from harness.loop.task_executor import stop_task_run

    class InterruptibleStopModelRuntime:
        def __init__(self) -> None:
            self.calls = 0

        async def invoke_messages(self, messages, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                await asyncio.sleep(60)
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(
                        action_type="respond",
                        final_answer="scheduled cell stop closeout",
                    ),
                    ensure_ascii=False,
                )
            )

    model = InterruptibleStopModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:scheduled-stop-signal",
        session_id="session-scheduled-stop-signal",
        status="created",
    )

    schedule = runtime.task_executor_controller.schedule(task_run_id, scheduler="test_stop_signal", max_steps=4)
    stop_requested = False
    try:
        assert schedule["scheduled"] is True
        _wait_for_running_executor(host, task_run_id, model)

        stop_result = stop_task_run(host, task_run_id, reason="scheduled_user_stop_test", requested_by="user")
        stop_requested = True
        assert stop_result["accepted"] is True

        _wait_for_task_status(host, task_run_id, "aborted")

        trace = host.get_trace(task_run_id, include_payloads=True)
        events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
        requested = [
            dict(dict(event.get("payload") or {}).get("signal") or {})
            for event in events
            if event.get("event_type") == "runtime_control_signal_published"
            and dict(dict(event.get("payload") or {}).get("signal") or {}).get("signal_type") == "control.signal.requested"
        ]
        observed = [
            dict(dict(event.get("payload") or {}).get("signal") or {})
            for event in events
            if event.get("event_type") == "runtime_control_signal_observed"
            and dict(dict(event.get("payload") or {}).get("signal") or {}).get("signal_type") == "control.signal.requested"
        ]
        consumed = [
            dict(dict(event.get("payload") or {}).get("signal") or {})
            for event in events
            if event.get("event_type") == "runtime_control_signal_consumed"
            and dict(dict(event.get("payload") or {}).get("signal") or {}).get("signal_type") == "control.signal.requested"
        ]
        lifecycle_event = next(
            event
            for event in events
            if event.get("event_type") == "task_run_lifecycle_finished"
            and dict(dict(event.get("payload") or {}).get("lifecycle") or {}).get("status") == "aborted"
        )

        assert len(requested) == 1
        assert len(observed) == 1
        assert len(consumed) == 1
        assert requested[0]["signal_id"] == observed[0]["signal_id"]
        assert requested[0]["signal_id"] == consumed[0]["signal_id"]
        assert dict(requested[0]["scope"])["agent_run_id"] == schedule["agent_run_id"]
        assert dict(requested[0]["scope"])["run_cell_id"] == schedule["run_cell_id"]
        assert dict(consumed[0]["payload"])["terminal_reason"] == "user_aborted"
        assert dict(consumed[0]["payload"])["lifecycle_status"] == "aborted"
        assert dict(consumed[0]["payload"])["task_lifecycle_event_ref"] == lifecycle_event["event_id"]
        assert int(dict(consumed[0]["payload"])["task_lifecycle_event_offset"]) == int(lifecycle_event["offset"])
        assert host.runtime_gateway.drain(
            task_run_id,
            scope=RuntimeSignalScope(
                session_id="session-scheduled-stop-signal",
                task_run_id=task_run_id,
                agent_run_id=str(schedule["agent_run_id"]),
                run_cell_id=str(schedule["run_cell_id"]),
            ),
            signal_types={"control.signal.requested"},
        ).pending_signals == ()
    finally:
        if not stop_requested:
            stop_task_run(host, task_run_id, reason="test_cleanup", requested_by="test")
        cell = host.agent_run_supervisor.cell_by_id(str(schedule.get("run_cell_id") or ""))
        if cell is not None and cell.worker_handle is not None:
            cell.worker_handle.join(timeout=1)


def test_stale_running_stop_finishes_without_gateway_signal() -> None:
    from harness.loop.task_executor import stop_task_run

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:stop-without-registry",
        session_id="session-stop-without-registry",
        status="running",
    )
    task = host.state_index.get_task_run(task_run_id)
    host.state_index.upsert_task_run(
        replace(
            task,
            diagnostics={
                **dict(task.diagnostics or {}),
                "executor_status": "running",
                "executor_epoch": 42,
            },
        )
    )

    stop_result = stop_task_run(host, task_run_id, reason="stale_running_stop", requested_by="user")
    trace = host.get_trace(task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    requested = [
        dict(dict(event.get("payload") or {}).get("signal") or {})
        for event in events
        if event.get("event_type") == "runtime_control_signal_published"
        and dict(dict(event.get("payload") or {}).get("signal") or {}).get("signal_type") == "control.signal.requested"
    ]
    unavailable = _runtime_gateway_signals(
        host,
        task_run_id,
        "runtime_control_signal_published",
        signal_type="control.signal.target_unavailable",
    )

    stored = host.state_index.get_task_run(task_run_id)
    assert stop_result["accepted"] is True
    assert requested == []
    assert unavailable == []
    assert stored.status == "aborted"
    assert stored.terminal_reason == "user_aborted"
    assert dict(stored.diagnostics or {})["executor_status"] == "stopped"
    stop_requested_event = next(event for event in events if event.get("event_type") == "task_run_stop_requested")
    stored_control = dict(dict(stored.diagnostics or {}).get("runtime_control") or {})
    assert dict(stop_result["control"])["state"] == "stopped"
    assert "runtime_control_signal_ref" not in stored_control
    assert "runtime_control_signal_ref" not in dict(stop_requested_event["payload"])
    assert "runtime_control_signal_ref" not in dict(stop_requested_event["refs"])
    assert host.runtime_gateway.drain(
        task_run_id,
        scope=RuntimeSignalScope(
            session_id="session-stop-without-registry",
            task_run_id=task_run_id,
        ),
        signal_types={"control.signal.requested"},
    ).pending_signals == ()


def test_stale_running_pause_settles_without_gateway_signal() -> None:
    from harness.loop.task_executor import request_task_run_pause

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:pause-without-registry",
        session_id="session-pause-without-registry",
        status="running",
    )
    task = host.state_index.get_task_run(task_run_id)
    host.state_index.upsert_task_run(
        replace(
            task,
            diagnostics={
                **dict(task.diagnostics or {}),
                "executor_status": "running",
                "executor_epoch": 43,
            },
        )
    )

    pause_result = request_task_run_pause(host, task_run_id, reason="stale_running_pause", requested_by="user")
    trace = host.get_trace(task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    requested = _runtime_gateway_signals(host, task_run_id, "runtime_control_signal_published")
    unavailable = _runtime_gateway_signals(
        host,
        task_run_id,
        "runtime_control_signal_published",
        signal_type="control.signal.target_unavailable",
    )

    stored = host.state_index.get_task_run(task_run_id)
    assert pause_result["accepted"] is True
    assert requested == []
    assert unavailable == []
    assert stored.status == "waiting_executor"
    assert stored.terminal_reason == ""
    assert dict(stored.diagnostics or {})["executor_status"] == "waiting_executor"
    assert dict(stored.diagnostics or {})["recovery_action"] == "resume_task_run"
    pause_requested_event = next(event for event in events if event.get("event_type") == "task_run_pause_requested")
    stored_control = dict(dict(stored.diagnostics or {}).get("runtime_control") or {})
    assert dict(pause_result["control"])["state"] == "paused"
    assert "runtime_control_signal_ref" not in stored_control
    assert "runtime_control_signal_ref" not in dict(pause_requested_event["payload"])
    assert "runtime_control_signal_ref" not in dict(pause_requested_event["refs"])
    assert host.runtime_gateway.drain(
        task_run_id,
        scope=RuntimeSignalScope(
            session_id="session-pause-without-registry",
            task_run_id=task_run_id,
        ),
        signal_types={"control.signal.requested"},
    ).pending_signals == ()


def test_stale_running_replan_records_steer_without_gateway_signal() -> None:
    from harness.loop.task_executor import append_user_work_instruction

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:replan-without-registry",
        session_id="session-replan-without-registry",
        status="running",
    )
    task = host.state_index.get_task_run(task_run_id)
    host.state_index.upsert_task_run(
        replace(
            task,
            diagnostics={
                **dict(task.diagnostics or {}),
                "executor_status": "running",
                "executor_epoch": 44,
            },
        )
    )

    replan_result = append_user_work_instruction(
        host,
        task_run_id,
        content="把后续验证范围扩展到网关 replay。",
        intent="append_instruction_to_active_work",
    )
    steer_ref = str(dict(replan_result["steer"])["steer_id"])
    trace = host.get_trace(task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    requested = _runtime_gateway_signals(host, task_run_id, "runtime_control_signal_published")
    unavailable = _runtime_gateway_signals(
        host,
        task_run_id,
        "runtime_control_signal_published",
        signal_type="control.signal.target_unavailable",
    )

    stored = host.state_index.get_task_run(task_run_id)
    assert replan_result["accepted"] is True
    assert requested == []
    assert unavailable == []
    assert stored.status == "running"
    assert dict(stored.diagnostics or {})["latest_user_steer_ref"] == steer_ref
    assert not [event for event in events if event.get("event_type") == "task_run_replan_requested"]
    stored_control = dict(dict(host.state_index.get_task_run(task_run_id).diagnostics or {}).get("runtime_control") or {})
    result_control = dict(dict(replan_result["task_run"]).get("diagnostics") or {}).get("runtime_control") or {}
    assert dict(result_control) == {}
    assert stored_control == {}
    assert host.runtime_gateway.drain(
        task_run_id,
        scope=RuntimeSignalScope(
            session_id="session-replan-without-registry",
            task_run_id=task_run_id,
        ),
        signal_types={"control.signal.requested"},
    ).pending_signals == ()


def test_stale_running_pause_stop_do_not_require_gateway_without_live_cell() -> None:
    from harness.loop.task_executor import append_user_work_instruction, request_task_run_pause, stop_task_run

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:control-no-gateway",
        session_id="session-control-no-gateway",
        status="running",
    )
    task = host.state_index.get_task_run(task_run_id)
    host.state_index.upsert_task_run(
        replace(
            task,
            diagnostics={
                **dict(task.diagnostics or {}),
                "executor_status": "running",
                "executor_epoch": 50,
            },
        )
    )
    host.runtime_gateway = None

    pause_result = request_task_run_pause(host, task_run_id, reason="pause_without_gateway", requested_by="user")
    stop_result = stop_task_run(host, task_run_id, reason="stop_without_gateway", requested_by="user")
    replan_result = append_user_work_instruction(
        host,
        task_run_id,
        content="补充要求必须经过 Gateway。",
        turn_id="turn:control-no-gateway:2",
    )
    stored = host.state_index.get_task_run(task_run_id)
    event_types = [event.event_type for event in host.event_log.list_events(task_run_id)]

    assert pause_result["ok"] is True
    assert pause_result["accepted"] is True
    assert stop_result["ok"] is True
    assert stop_result["accepted"] is True
    assert replan_result["ok"] is False
    assert replan_result["error"] == "task_run_terminal:user_aborted"
    assert stored.status == "aborted"
    assert stored.terminal_reason == "user_aborted"
    assert dict(stored.diagnostics or {})["executor_status"] == "stopped"
    assert "task_run_pause_requested" in event_types
    assert "task_run_stop_requested" in event_types
    assert "task_run_replan_requested" not in event_types
    assert "active_task_steer_recorded" not in event_types


def test_executor_observes_pending_gateway_stop_without_memory_signal() -> None:
    class GatewayOnlyStopModelRuntime:
        def __init__(self) -> None:
            self.calls = 0

        async def invoke_messages(self, messages, **_kwargs):
            self.calls += 1
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(
                        action_type="respond",
                        final_answer="Gateway replay stop closeout",
                    ),
                    ensure_ascii=False,
                )
            )

    model = GatewayOnlyStopModelRuntime()
    runtime = build_harness_runtime(
        model_runtime=model,
    )
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:gateway-replay-stop",
        session_id="session-gateway-replay-stop",
        status="created",
    )

    signal_event = host.runtime_gateway.publish(
        task_run_id,
        signal_type="control.signal.requested",
        scope=RuntimeSignalScope(
            session_id="session-gateway-replay-stop",
            task_run_id=task_run_id,
        ),
        source_authority="test.runtime_gateway",
        payload={
            "signal_kind": "stop",
            "task_run_id": task_run_id,
            "executor_epoch": 0,
            "reason": "gateway_replay_stop",
            "requested_by": "user",
            "requested_at": time.time(),
            "adapter": "test_gateway_only",
        },
        refs={"task_run_ref": task_run_id},
    )
    schedule = runtime.schedule_task_run_executor(task_run_id, scheduler="test_gateway_replay_stop", max_steps=2)
    assert schedule["scheduled"] is True
    _wait_for_task_status(host, task_run_id, "aborted")
    _join_scheduled_cell(host, schedule)

    trace = host.get_trace(task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    requested = [
        dict(dict(event.get("payload") or {}).get("signal") or {})
        for event in events
        if event.get("event_type") == "runtime_control_signal_published"
        and dict(dict(event.get("payload") or {}).get("signal") or {}).get("signal_type") == "control.signal.requested"
    ]
    observed = [
        dict(dict(event.get("payload") or {}).get("signal") or {})
        for event in events
        if event.get("event_type") == "runtime_control_signal_observed"
        and dict(dict(event.get("payload") or {}).get("signal") or {}).get("signal_type") == "control.signal.requested"
    ]
    consumed = [
        dict(dict(event.get("payload") or {}).get("signal") or {})
        for event in events
        if event.get("event_type") == "runtime_control_signal_consumed"
        and dict(dict(event.get("payload") or {}).get("signal") or {}).get("signal_type") == "control.signal.requested"
    ]
    control_observations = [
        dict(dict(event.get("payload") or {}).get("observation") or {})
        for event in events
        if event.get("event_type") == "task_runtime_control_signal_observed"
    ]

    assert _assistant_final_text(events) == "Gateway replay stop closeout"
    assert len(requested) == 1
    assert len(observed) == 1
    assert len(consumed) == 1
    assert requested[0]["signal_id"] == dict(dict(signal_event.payload)["signal"])["signal_id"]
    assert requested[0]["signal_id"] == observed[0]["signal_id"]
    assert requested[0]["signal_id"] == consumed[0]["signal_id"]
    assert control_observations
    assert dict(control_observations[0]["payload"])["runtime_control_signal_ref"] == requested[0]["signal_id"]
    assert host.runtime_gateway.drain(
        task_run_id,
        scope=RuntimeSignalScope(
            session_id="session-gateway-replay-stop",
            task_run_id=task_run_id,
        ),
        signal_types={"control.signal.requested"},
    ).pending_signals == ()


def test_executor_observes_pending_gateway_pause_without_memory_signal() -> None:
    class GatewayOnlyPauseModelRuntime:
        def __init__(self) -> None:
            self.calls = 0

        async def invoke_messages(self, messages, **_kwargs):
            self.calls += 1
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(
                        action_type="respond",
                        final_answer="Gateway replay pause closeout",
                    ),
                    ensure_ascii=False,
                )
            )

    model = GatewayOnlyPauseModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:gateway-replay-pause",
        session_id="session-gateway-replay-pause",
        status="created",
    )

    signal_event = host.runtime_gateway.publish(
        task_run_id,
        signal_type="control.signal.requested",
        scope=RuntimeSignalScope(
            session_id="session-gateway-replay-pause",
            task_run_id=task_run_id,
        ),
        source_authority="test.runtime_gateway",
        payload={
            "signal_kind": "pause",
            "task_run_id": task_run_id,
            "executor_epoch": 0,
            "reason": "gateway_replay_pause",
            "requested_by": "user",
            "requested_at": time.time(),
            "adapter": "test_gateway_only",
        },
        refs={"task_run_ref": task_run_id},
    )
    schedule = runtime.schedule_task_run_executor(task_run_id, scheduler="test_gateway_replay_pause", max_steps=2)
    assert schedule["scheduled"] is True
    _wait_for_task_status(host, task_run_id, "waiting_executor")
    _join_scheduled_cell(host, schedule)

    task = host.state_index.get_task_run(task_run_id)
    requested = _runtime_gateway_signals(host, task_run_id, "runtime_control_signal_published")
    observed = _runtime_gateway_signals(host, task_run_id, "runtime_control_signal_observed")
    consumed = _runtime_gateway_signals(host, task_run_id, "runtime_control_signal_consumed")
    trace = host.get_trace(task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    control_observations = [
        dict(dict(event.get("payload") or {}).get("observation") or {})
        for event in events
        if event.get("event_type") == "task_runtime_control_signal_observed"
    ]

    assert task is not None
    assert task.status == "waiting_executor"
    assert _assistant_final_text(events) == "Gateway replay pause closeout"
    assert dict(task.diagnostics)["recovery_action"] == "resume_task_run"
    assert len(requested) == 1
    assert len(observed) == 1
    assert len(consumed) == 1
    assert requested[0]["signal_id"] == dict(dict(signal_event.payload)["signal"])["signal_id"]
    assert requested[0]["signal_id"] == observed[0]["signal_id"]
    assert requested[0]["signal_id"] == consumed[0]["signal_id"]
    assert dict(requested[0]["payload"])["signal_kind"] == "pause"
    assert dict(consumed[0]["payload"])["lifecycle_status"] == "waiting_executor"
    assert dict(consumed[0]["payload"])["terminal_reason"] == "waiting_executor"
    assert control_observations
    assert dict(control_observations[0]["payload"])["runtime_control_signal_ref"] == requested[0]["signal_id"]
    assert host.runtime_gateway.drain(
        task_run_id,
        scope=RuntimeSignalScope(
            session_id="session-gateway-replay-pause",
            task_run_id=task_run_id,
        ),
        signal_types={"control.signal.requested"},
    ).pending_signals == ()


def test_executor_observes_pending_gateway_replan_without_memory_signal_and_consumes_steer_ref() -> None:
    from harness.loop.task_steering import create_active_task_steer

    class GatewayOnlyReplanModelRuntime:
        def __init__(self) -> None:
            self.calls = 0
            self.steer_ref = ""

        async def invoke_messages(self, messages, **_kwargs):
            self.calls += 1
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(
                        action_type="respond",
                        final_answer="Gateway replay replan absorbed",
                        diagnostics={
                            "consumed_steer_refs": [self.steer_ref],
                            "contract_revision_decisions": [
                                {
                                    "steer_ref": self.steer_ref,
                                    "status": "accepted",
                                    "reason": "absorbed during Gateway replay replan",
                                }
                            ],
                        },
                    ),
                    ensure_ascii=False,
                )
            )

    model = GatewayOnlyReplanModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:gateway-replay-replan",
        session_id="session-gateway-replay-replan",
        status="created",
    )

    steer = create_active_task_steer(
        host,
        task_run_id,
        content="把后续验证范围扩展到网关 replay。",
        intent="append_instruction_to_active_work",
    )
    steer_ref = str(dict(steer["steer"])["steer_id"])
    model.steer_ref = steer_ref
    signal_event = host.runtime_gateway.publish(
        task_run_id,
        signal_type="control.signal.requested",
        scope=RuntimeSignalScope(
            session_id="session-gateway-replay-replan",
            task_run_id=task_run_id,
        ),
        source_authority="test.runtime_gateway",
        payload={
            "signal_kind": "replan",
            "task_run_id": task_run_id,
            "executor_epoch": 0,
            "reason": "gateway_replay_replan",
            "requested_by": "user",
            "requested_at": time.time(),
            "steer_ref": steer_ref,
            "adapter": "test_gateway_only",
        },
        refs={"task_run_ref": task_run_id, "steer_ref": steer_ref},
    )
    schedule = runtime.schedule_task_run_executor(task_run_id, scheduler="test_gateway_replay_replan", max_steps=4)
    assert schedule["scheduled"] is True
    _wait_for_task_status(host, task_run_id, "completed")
    _join_scheduled_cell(host, schedule)

    requested = _runtime_gateway_signals(host, task_run_id, "runtime_control_signal_published")
    observed = _runtime_gateway_signals(host, task_run_id, "runtime_control_signal_observed")
    consumed = _runtime_gateway_signals(host, task_run_id, "runtime_control_signal_consumed")
    trace = host.get_trace(task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    control_observations = [
        dict(dict(event.get("payload") or {}).get("observation") or {})
        for event in events
        if event.get("event_type") == "task_runtime_control_signal_observed"
    ]

    assert _assistant_final_text(events) == "Gateway replay replan absorbed"
    assert len(requested) == 1
    assert len(observed) == 1
    assert len(consumed) == 1
    assert requested[0]["signal_id"] == dict(dict(signal_event.payload)["signal"])["signal_id"]
    assert requested[0]["signal_id"] == observed[0]["signal_id"]
    assert requested[0]["signal_id"] == consumed[0]["signal_id"]
    assert dict(requested[0]["payload"])["signal_kind"] == "replan"
    assert dict(requested[0]["payload"])["steer_ref"] == steer_ref
    assert dict(observed[0]["payload"])["observation_ref"] == control_observations[0]["observation_id"]
    assert dict(consumed[0]["payload"])["signal_kind"] == "replan"
    assert dict(consumed[0]["payload"])["steer_ref"] == steer_ref
    assert dict(consumed[0]["payload"])["model_action_consumption"] == "consumed_steer_refs"
    assert control_observations
    assert dict(control_observations[0]["payload"])["runtime_control_signal_ref"] == requested[0]["signal_id"]
    assert dict(control_observations[0]["payload"])["steer_ref"] == steer_ref
    assert dict(control_observations[0]["payload"])["tool_calls_allowed_after_signal"] is True
    assert host.runtime_gateway.drain(
        task_run_id,
        scope=RuntimeSignalScope(
            session_id="session-gateway-replay-replan",
            task_run_id=task_run_id,
        ),
        signal_types={"control.signal.requested"},
    ).pending_signals == ()


def test_task_executor_absorbs_queued_active_turn_steer_before_compiling_next_packet() -> None:
    class CaptureQueuedSteerModelRuntime:
        def __init__(self) -> None:
            self.prompt_text = ""

        async def invoke_messages(self, messages, **_kwargs):
            self.prompt_text = "\n\n".join(
                str(dict(message).get("content") or "")
                for message in list(messages or [])
                if isinstance(message, dict)
            )
            match = re.search(r"steer:[A-Za-z0-9:_-]+", self.prompt_text)
            consumed = [match.group(0)] if match else []
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(
                        action_type="respond",
                        final_answer="已吸收 queued steer。",
                        diagnostics={
                            "consumed_steer_refs": consumed,
                            "contract_revision_decisions": [
                                {
                                    "steer_ref": consumed[0] if consumed else "",
                                    "status": "accepted",
                                    "reason": "queued active-turn steer absorbed before packet compilation",
                                }
                            ],
                        },
                    ),
                    ensure_ascii=False,
                )
            )

    model = CaptureQueuedSteerModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    session_id = "session-queued-active-turn-task"
    turn_id = "turn:session-queued-active-turn-task:1"
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:queued-active-turn-task",
        session_id=session_id,
        status="waiting_executor",
    )
    seeded_task = host.state_index.get_task_run(task_run_id)
    host.state_index.upsert_task_run(
        replace(
            seeded_task,
            diagnostics={
                **dict(seeded_task.diagnostics or {}),
                "executor_status": "waiting_executor",
                "recovery_action": "rerun_task_executor",
                "recoverable_error": {
                    "error_code": "test_resume_for_queued_active_turn_steer",
                    "retryable": True,
                },
            },
        )
    )
    host.active_turn_registry.start(
        session_id=session_id,
        turn_id=turn_id,
        stream_run_id="strun:queued-active-turn-task",
        state="running_task",
    )
    host.active_turn_registry.bind_task_run(
        session_id=session_id,
        turn_id=turn_id,
        task_run_id=task_run_id,
        state="running_task",
    )
    item = host.queued_user_inputs.enqueue(
        session_id=session_id,
        content="补充：下一步必须先验证 active_turn 队列已进入任务上下文。",
        client_message_id="user:queued-active-turn-task",
        input_policy="steer",
        expected_active_turn_id=turn_id,
        task_run_id=task_run_id,
    )

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=3))

    stored = host.queued_user_inputs.get_item(session_id, item.queue_item_id)
    trace = host.get_trace(task_run_id, include_payloads=True)
    events = [dict(event) for event in list(dict(trace or {}).get("events") or [])]
    event_types = [str(event.get("event_type") or "") for event in events]

    assert result["ok"] is True
    assert stored is not None
    assert stored.status == "dispatched"
    assert stored.dispatch_stream_run_id == "strun:queued-active-turn-task"
    assert "active_task_steer_recorded" in event_types
    assert "active_task_steer_included" in event_types
    assert "active_task_steer_consumed" in event_types
    assert "pending_user_steers" in model.prompt_text
    assert "补充：下一步必须先验证 active_turn 队列已进入任务上下文。" in model.prompt_text
    assert "active_turn_queued_user_steer" in json.dumps(events, ensure_ascii=False)
    assert host.run_registry.list_session_runs(session_id) == []


def test_runtime_start_recovery_marks_network_interrupted_executor_resumable() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:network-interrupted",
        session_id="session-network-interrupted",
        status="running",
    )
    task = host.state_index.get_task_run(task_run_id)
    host.state_index.upsert_task_run(
        replace(
            task,
            diagnostics={
                **dict(task.diagnostics or {}),
                "executor_status": "running",
            },
        )
    )

    result = runtime.task_executor_controller.recover_interrupted_executor_leases()
    recovered = host.state_index.get_task_run(task_run_id)
    events = [event.event_type for event in host.event_log.list_events(task_run_id)]

    assert result["recovered_count"] == 1
    assert result["task_run_ids"] == [task_run_id]
    assert recovered.status == "waiting_executor"
    assert recovered.terminal_reason == ""
    assert dict(recovered.diagnostics)["executor_status"] == "waiting_executor"
    assert dict(recovered.diagnostics)["wait_reason"] == "task_executor_interrupted_by_runtime_restart"
    assert dict(recovered.diagnostics)["recovery_action"] == "rerun_task_executor"
    assert dict(dict(recovered.diagnostics)["recoverable_error"])["error_code"] == "task_executor_interrupted_by_runtime_restart"
    assert "task_run_executor_recovered_after_runtime_start" in events
    state_view = task_run_state_view(recovered)
    assert state_view["task_work_state"] == "ready_to_continue"
    assert state_view["recovery_cause"] == "runtime_restart"
    assert state_view["control_reason"] == "runtime_restart_waiting_resume"
    assert state_view["activity"]["activity_label"] == "连接恢复后待续跑"
    assert "连接已恢复" in state_view["activity"]["detail"]


def test_runtime_start_recovery_does_not_auto_schedule_recovered_executor() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:restart-recovered-no-autoschedule",
        session_id="session-restart-recovered-no-autoschedule",
        status="running",
    )
    task = host.state_index.get_task_run(task_run_id)
    host.state_index.upsert_task_run(
        replace(
            task,
            diagnostics={
                **dict(task.diagnostics or {}),
                "executor_status": "running",
            },
        )
    )
    runtime.task_executor_controller.recover_interrupted_executor_leases()

    result = runtime.task_executor_controller.schedule(
        task_run_id,
        scheduler="runtime_start_recovery",
        max_steps=4,
        recovered_from="runtime_start_recovery",
    )
    unchanged = host.state_index.get_task_run(task_run_id)

    assert result["ok"] is False
    assert result["scheduled"] is False
    assert result["reason"] == "runtime_start_recovery_does_not_auto_schedule"
    assert unchanged.status == "waiting_executor"
    assert dict(unchanged.diagnostics)["executor_status"] == "waiting_executor"

    recover_result = runtime.task_executor_controller.recover_scheduled(
        task_run_id,
        scheduler="runtime_start_recovery",
        max_steps=4,
        recovered_from="runtime_start_recovery",
    )

    assert recover_result["ok"] is False
    assert recover_result["scheduled"] is False
    assert recover_result["reason"] == "runtime_start_recovery_does_not_auto_schedule"


def test_runtime_start_recovery_does_not_promote_unclaimed_shadow_control_to_gateway() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:unclaimed-shadow-pause",
        session_id="session-unclaimed-shadow-pause",
        status="blocked",
    )
    task = host.state_index.get_task_run(task_run_id)
    host.state_index.upsert_task_run(
        replace(
            task,
            diagnostics={
                **dict(task.diagnostics or {}),
                "runtime_control": {
                    "state": "pause_requested",
                    "requested_by": "test",
                    "reason": "shadow pause",
                },
            },
        )
    )

    result = runtime.task_executor_controller.recover_interrupted_executor_leases()
    unchanged = host.state_index.get_task_run(task_run_id)
    requested = _runtime_gateway_signals(host, task_run_id, "runtime_control_signal_published")
    events = [event.event_type for event in host.event_log.list_events(task_run_id)]

    assert result["recovered_count"] == 0
    assert result["task_run_ids"] == []
    assert result["user_controlled_interruption_task_run_ids"] == []
    assert unchanged.status == "blocked"
    assert "runtime_control_signal_ref" not in dict(dict(unchanged.diagnostics)["runtime_control"])
    assert requested == []
    assert "task_run_executor_recovered_after_runtime_start" not in events


def test_explicit_contract_task_starts_lifecycle_without_model_action_loop() -> None:
    runtime = build_harness_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            content="单轮收口回答",
            agent_turn_action_request=_action_request(
                action_type="respond",
                final_answer="不应调用模型动作协议。",
            )
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-explicit-contract",
                message="按合同启动任务。",
                runtime_contract={
                    "task_environment_id": "env.coding.vibe_workspace",
                    "allowed_operations": ["op.model_response", "op.read_file"],
                    "system_issued_contract": True,
                    "task_contract": {
                        "contract_id": "contract:explicit:test",
                        "user_visible_goal": "交付显式合同任务。",
                        "task_run_goal": "根据显式合同创建并执行任务。",
                        "working_scope": {
                            "target_objects": ["显式合同任务"],
                            "workspace_refs": [],
                            "source_refs": [],
                            "excluded_scope": [],
                            "known_constraints": ["任务生命周期必须由系统直接启动"],
                        },
                        "required_artifacts": [{"artifact_kind": "html_app", "user_visible_name": "可运行页面"}],
                        "completion_criteria": ["任务生命周期必须由系统直接启动"],
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    branch = dict(next(event for event in events if event.get("type") == "runtime_branch_decided").get("runtime_branch") or {})
    lifecycle = [
        event
        for event in events
        if event.get("type") == "task_run_lifecycle_started"
    ][0]
    task_run_event = dict(lifecycle.get("event") or {})
    payload = dict(task_run_event.get("payload") or {})
    task_run = dict(payload.get("task_run") or {})
    task_run_id = str(task_run.get("task_run_id") or "")
    stored_task = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    contract = dict(runtime.single_agent_runtime_host.runtime_objects.get_object(str(getattr(stored_task, "task_contract_ref", "") or "")) or {})

    assert branch.get("branch_kind") == "explicit_contract_task"
    assert branch.get("invocation_kind") == "task_execution_start"
    assert "runtime_invocation_packet" not in stream_types
    assert "model_action_request" not in stream_types
    assert "model_action_admission" not in stream_types
    assert "harness_run_started" in stream_types
    assert task_run_id.startswith("taskrun:")
    assert stored_task is not None
    assert contract["contract_source"] == "explicit_contract"
    assert contract["source_contract_ref"] == "contract:explicit:test"
    assert contract["task_environment_id"] == "env.coding.vibe_workspace"
    assert contract["runtime_profile"]["execution_permit"]["allowed_operations"] == ["op.model_response", "op.read_file"]
    runtime_contract = dict(dict(getattr(stored_task, "diagnostics", {}) or {}).get("runtime_contract") or {})
    assert runtime_contract["allowed_operations"] == ["op.model_response", "op.read_file"]
    assert dict(runtime_contract["runtime_profile"])["execution_permit"]["allowed_operations"] == ["op.model_response", "op.read_file"]
    assert dict(getattr(stored_task, "diagnostics", {}) or {}).get("origin_kind") == "explicit_contract"
    assert dict(getattr(stored_task, "diagnostics", {}) or {}).get("origin_authority") == "harness.explicit_contract_task"


def test_invalid_explicit_contract_fails_closed_without_model_action_loop() -> None:
    class NoModelFallbackRuntime:
        async def invoke_messages(self, *_args, **_kwargs):
            raise AssertionError("invalid explicit contract must not fall back to model action loop")

    runtime = build_harness_runtime(model_runtime=NoModelFallbackRuntime())

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-invalid-explicit-contract",
                message="按无效合同启动任务。",
                runtime_contract={
                    "task_environment_id": "env.coding.vibe_workspace",
                    "system_issued_contract": True,
                    "task_contract": {
                        "contract_id": "contract:explicit:invalid",
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    branch = dict(next(event for event in events if event.get("type") == "runtime_branch_decided").get("runtime_branch") or {})
    runtime_status = next(event for event in events if event.get("type") == "runtime_status")
    error = next(event for event in events if event.get("type") == "error")

    assert branch.get("branch_kind") == "explicit_contract_task"
    assert "model_action_request" not in stream_types
    assert "model_action_admission" not in stream_types
    assert "task_run_lifecycle_started" not in stream_types
    assert runtime_status["terminal_reason"] == "explicit_contract_invalid"
    assert runtime_status["state"] == "blocked"
    assert error["code"] == "explicit_contract_invalid"
    assert error["answer_finalization_policy"] == "fail_closed_visible_message"


def test_task_model_action_stream_failure_does_not_non_stream_resample() -> None:
    fallback_called = False

    def failing_streamer(_messages, **_kwargs):
        async def _stream():
            raise RuntimeError("stream transport dropped")
            yield SimpleNamespace(content="unreachable")

        return _stream()

    async def forbidden_invoker(_messages, **_kwargs):
        nonlocal fallback_called
        fallback_called = True
        return SimpleNamespace(
            content=json.dumps(
                _action_request(
                    action_type="respond",
                    final_answer="This would be a re-sampled control decision.",
                ),
                ensure_ascii=False,
            )
        )

    async def _invoke() -> None:
        await task_executor_module._invoke_task_model_action_response(
            invoker=forbidden_invoker,
            streamer=failing_streamer,
            messages=[],
            model_selection={
                "provider": "test",
                "model": "json-action",
                "stream_policy": {
                    "enabled": True,
                    "fallback_to_non_stream_on_error": True,
                },
            },
            accounting_context={},
        )

    try:
        asyncio.run(_invoke())
    except Exception as exc:
        assert getattr(exc, "code", "") == "non_stream_fallback_disabled_for_task_action_protocol"
        assert getattr(exc, "retryable", None) is True
    else:
        raise AssertionError("task action stream failure must fail closed instead of falling back")

    policy = task_executor_module._stream_policy_for_task_model_requirement(
        {"fallback_to_non_stream_on_error": True},
        requirement={"streaming_required": True},
    )
    assert policy["fallback_to_non_stream_on_error"] is False
    assert fallback_called is False


def test_plain_task_contract_selection_does_not_bypass_agent_turn() -> None:
    runtime = build_harness_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            content="我会先判断是否需要启动任务。",
            agent_turn_action_request=_action_request(
                action_type="respond",
                final_answer="我会先判断是否需要启动任务。",
            )
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-plain-contract-selection",
                message="这个只是普通会话输入，不能直接启动任务。",
                runtime_contract={
                    "task_environment_id": "env.coding.vibe_workspace",
                    "task_contract": {
                        "contract_id": "contract:plain:test",
                        "user_visible_goal": "普通输入里的合同片段。",
                        "task_run_goal": "不应由路由直接启动。",
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    branch = dict(next(event for event in events if event.get("type") == "runtime_branch_decided").get("runtime_branch") or {})

    assert branch.get("branch_kind") == "single_agent_turn"
    assert "single_agent_turn_started" in stream_types
    assert "task_run_lifecycle_started" not in stream_types

def test_agent_action_request_launches_task_run_and_initializes_todo() -> None:
    model_selection = {
        "provider": "test-provider",
        "model": "turn-bound-test-model",
        "timeout_seconds": 7,
    }
    runtime = build_harness_runtime(
        model_runtime=NativeToolCallModelRuntimeStub(
            content="",
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed=_canonical_task_contract_seed({
                    "user_visible_goal": "交付一个真实可验证产物。",
                    "task_run_goal": "交付一个真实可验证产物。",
                    "required_artifacts": [{"artifact_kind": "test_artifact", "user_visible_name": "测试交付物"}],
                    "required_verifications": [{"verification_kind": "test_verification"}],
                    "completion_criteria": ["交付物和验证证据都已记录"],
                }),
            )
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-taskrun",
                message="请交付产物。",
                model_selection=model_selection,
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    started = [
        event
        for event in events
        if event.get("type") == "harness_run_started"
        and str(dict(event.get("task_run") or {}).get("task_run_id") or "").startswith("taskrun:")
    ][0]
    task_run_id = str(dict(started.get("task_run") or {}).get("task_run_id") or "")
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [
        str(dict(item).get("event_type") or "")
        for item in list(dict(trace or {}).get("events") or [])
    ]
    stream_types = [str(event.get("type") or "") for event in events]
    branch_events = [dict(event.get("runtime_branch") or {}) for event in events if event.get("type") == "runtime_branch_decided"]

    assert "runtime_assembly_compiled" in stream_types
    assert branch_events and branch_events[0].get("branch_kind") == "single_agent_turn"
    assert "single_agent_turn_started" in stream_types
    assert "model_action_request" not in stream_types
    admissions = _admission_payloads(events)
    assert admissions
    assert dict(admissions[0].get("admission") or {}).get("decision") == "allow"
    assert dict(admissions[0].get("model_action_request") or {}).get("action_type") == "request_task_run"
    assert "task_run_lifecycle_started" in stream_types
    assert "task_run_lifecycle_event" in stream_types
    assert not any(event.get("type") == "assistant_text" and event.get("answer_channel") == "task_control" for event in events)
    assert "agent_todo_initialized" in event_types
    assert "task_run_executor_scheduled" in event_types
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    assert task_run is not None
    assert dict(task_run.diagnostics or {}).get("origin_kind") == "single_agent_turn_json_action"
    assert dict(dict(task_run.diagnostics or {}).get("origin") or {}).get("origin_authority") == "harness.loop.single_agent_turn"
    assert dict(task_run.diagnostics or {}).get("model_selection") == model_selection
    assert dict(dict(task_run.diagnostics or {}).get("model_selection_binding") or {}).get("scope") == "task_run"
    contract = runtime.single_agent_runtime_host.runtime_objects.get_object(task_run.task_contract_ref)
    assert dict(contract or {}).get("origin", {}).get("origin_kind") == "single_agent_turn_json_action"

def test_invalid_single_agent_task_request_reports_error_without_task_run() -> None:
    runtime = build_harness_runtime(
        model_runtime=NativeToolCallModelRuntimeStub(
            tool_calls=[
                {
                    "id": "invalid-request-task-run",
                    "name": "request_task_run",
                    "args": {},
                }
            ]
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-invalid", message="请执行。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    done = next(event for event in events if event.get("type") == "done")

    assert not any(event.get("type") == "task_run_lifecycle_started" for event in events)
    assert "agent_contract_feedback_required" in stream_types
    assert done.get("answer_channel") == "runtime_control"
    assert done.get("answer_persist_policy") == "do_not_persist"
    assert done.get("terminal_reason") == "agent_contract_feedback_required"
    assert dict(done.get("agent_contract_feedback") or {}).get("lifecycle") == "agent_contract_feedback_required"
    assert dict(dict(done.get("agent_contract_feedback") or {}).get("contract_failure") or {}).get("kind") == "agent_output_contract_not_satisfied"
    assert any(event.get("type") == "single_agent_turn_started" for event in events)

def test_task_lifecycle_start_does_not_rewrite_request_to_current_session_handoff() -> None:
    session_id = "session-lifecycle-no-current-handoff"
    existing_task_run_id = "taskrun:lifecycle-no-current-handoff:old"
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    _seed_active_work(
        runtime,
        task_run_id=existing_task_run_id,
        session_id=session_id,
        status="waiting_executor",
    )
    schedule_results: list[dict[str, object]] = []
    committed: list[dict[str, object]] = []

    async def _commit(_session_id: str, message: dict[str, object]) -> None:
        committed.append(dict(message))

    def _schedule_task_run_executor(*args, **kwargs):
        result = runtime.schedule_task_run_executor(*args, **kwargs)
        schedule_results.append(dict(result or {}))
        return result

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        action_request = ModelActionRequest(
            request_id="model-action:lifecycle-no-current-handoff",
            turn_id="turn:lifecycle-no-current-handoff",
            action_type="request_task_run",
            public_progress_note="我会开始处理新的持续任务。",
            task_contract_seed=_canonical_task_contract_seed({
                "user_visible_goal": "启动一个新的持续任务。",
                "task_run_goal": "验证 lifecycle 层不把模型请求改写成 current-session handoff。",
                "completion_criteria": ["必须创建新的 TaskRun"],
            }),
        )
        async for event in start_task_lifecycle_from_action_request(
            runtime_host=host,
            session_id=session_id,
            turn_id="turn:lifecycle-no-current-handoff",
            runtime_contract={"task_id": "task:lifecycle-no-current-handoff"},
            model_selection={},
            action_request=action_request,
            agent_runtime_profile=SimpleNamespace(agent_profile_id="main_interactive_agent"),
            runtime_assembly=SimpleNamespace(
                to_dict=lambda: {
                    "profile": {"task_lifecycle_policy": {"request_task_run": True}},
                    "permission_mode": "default",
                    "task_environment": {},
                }
            ),
            runtime_branch={"branch_kind": "single_agent_turn"},
            answer_source="test.lifecycle",
            scheduler="test_lifecycle",
            max_steps=1,
            commit_assistant_message=_commit,
            initialize_task_todo=lambda **_kwargs: None,
            schedule_task_run_executor=_schedule_task_run_executor,
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    session_task_runs = host.state_index.list_session_task_runs(session_id)
    new_tasks = [task for task in session_task_runs if task.task_run_id != existing_task_run_id]
    old_task = host.state_index.get_task_run(existing_task_run_id)

    assert "task_run_lifecycle_reused_current" not in stream_types
    assert not any(str(event.get("terminal_reason") or "") == "session_active_task_exists" for event in events)
    assert "task_run_lifecycle_started" in stream_types
    assert len(new_tasks) == 1
    assert new_tasks[0].status == "running"
    assert old_task is not None
    assert old_task.status == "waiting_executor"
    assert schedule_results
    assert schedule_results[0].get("run_cell_id")
    assert dict(new_tasks[0].diagnostics or {}).get("run_cell_id") == schedule_results[0].get("run_cell_id")
    assert dict(dict(new_tasks[0].diagnostics or {}).get("agent_run_scope") or {}).get("run_cell_id") == schedule_results[0].get("run_cell_id")
    assert host.agent_run_supervisor.cell_by_id(str(schedule_results[0].get("run_cell_id") or "")) is not None
    assert committed == []

def test_task_contract_preserves_runtime_fields_without_goal_aliases() -> None:
    from harness.loop.model_action_protocol import ModelActionRequest
    from harness.loop.task_lifecycle import contract_from_action_request

    invalid, errors = contract_from_action_request(
        ModelActionRequest(
            request_id="model-action:contract-fields:invalid",
            turn_id="turn-contract-fields",
            action_type="request_task_run",
            task_contract_seed={
                "goal": "旧字段不能替代正式合同字段",
                "completion_criteria": ["需要真实验收"],
            },
        ),
        packet_ref="rtpacket:contract-fields",
    )

    assert invalid is None
    assert "task_goal_required" in errors
    assert "task_run_goal_required" in errors

    contract, contract_errors = contract_from_action_request(
        ModelActionRequest(
            request_id="model-action:contract-fields:valid",
            turn_id="turn-contract-fields",
            action_type="request_task_run",
                task_contract_seed=_canonical_task_contract_seed({
                    "user_visible_goal": "交付可运行示例",
                    "task_run_goal": "创建并验证可运行示例",
                    "completion_criteria": ["示例可以被验证"],
                    "task_environment_id": "env.coding.vibe_workspace",
                    "runtime_profile": {"runtime_policy": {"planning_policy": {"plan_mode": "available"}}},
                    "source_contract_ref": "contract.demo",
                    "external_plan_ref": "plan.demo",
                    "prompt_contract": {"role_prompt": "你是执行者。"},
                }),
            ),
        packet_ref="rtpacket:contract-fields",
        task_environment_id="env.office.file_search",
    )

    assert contract_errors == []
    assert contract is not None
    assert contract.user_visible_goal == "交付可运行示例"
    assert contract.task_run_goal == "创建并验证可运行示例"
    assert contract.task_environment_id == "env.office.file_search"
    assert contract.runtime_profile["runtime_policy"]["planning_policy"]["plan_mode"] == "available"
    assert contract.source_contract_ref == "contract.demo"
    assert contract.external_plan_ref == "plan.demo"

def test_agent_requested_task_run_inherits_selected_runtime_environment() -> None:
    runtime = build_harness_runtime(
        model_runtime=NativeToolCallModelRuntimeStub(
            content="",
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed=_canonical_task_contract_seed({
                    "user_visible_goal": "交付开发环境产物。",
                    "task_run_goal": "在用户选择的开发环境中交付产物。",
                    "required_artifacts": [{"artifact_kind": "html_app", "user_visible_name": "可运行页面"}],
                    "completion_criteria": ["产物位于所选任务环境的 artifact 区域"],
                    "task_environment_id": "env.general.workspace",
                }),
            )
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-selected-env-taskrun",
                message="开发一个可运行页面。",
                runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    started = [
        event
        for event in events
        if event.get("type") == "harness_run_started"
        and str(dict(event.get("task_run") or {}).get("task_run_id") or "").startswith("taskrun:")
    ][0]
    task_run_id = str(dict(started.get("task_run") or {}).get("task_run_id") or "")
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    assert task_run is not None
    contract = dict(runtime.single_agent_runtime_host.runtime_objects.get_object(task_run.task_contract_ref) or {})
    runtime_contract = dict(dict(task_run.diagnostics or {}).get("runtime_contract") or {})

    assert contract["task_environment_id"] == "env.coding.vibe_workspace"
    assert runtime_contract["task_environment_id"] == "env.coding.vibe_workspace"

def test_task_run_permission_without_tools_uses_single_agent_turn_for_direct_answer() -> None:
    runtime = build_harness_runtime(
        model_runtime=_TurnActionSequenceModelRuntime(
            [_action_request(action_type="respond", final_answer="可以直接回答。")]
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-native-direct",
                message="这个问题可以直接回答。",
                runtime_contract={
                    "allowed_operations": ["op.model_response"],
                    "control_capabilities": {"may_request_task_run": True, "may_use_subagents": False},
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    branch = dict(next(event for event in events if event.get("type") == "runtime_branch_decided").get("runtime_branch") or {})

    assert branch.get("branch_kind") == "single_agent_turn"
    assert "single_agent_turn_started" in stream_types
    assert "runtime_invocation_packet" not in stream_types
    assert "model_action_request" not in stream_types
    assert "task_run_lifecycle_started" not in stream_types
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "可以直接回答。" for event in events)

def test_single_agent_turn_native_request_task_run_repairs_to_json_before_lifecycle() -> None:
    task_seed = _canonical_task_contract_seed(
        {
            "user_visible_goal": "交付一个真实页面。",
            "task_run_goal": "创建并验证一个真实 HTML 页面。",
            "working_scope": {
                "target_objects": ["真实 HTML 页面"],
                "workspace_refs": [],
                "source_refs": [],
                "excluded_scope": [],
                "known_constraints": ["页面文件必须真实存在"],
            },
            "required_artifacts": [{"artifact_kind": "html_app", "user_visible_name": "页面"}],
            "required_verifications": [{"verification_kind": "file_exists"}],
            "completion_criteria": ["页面文件真实存在"],
        },
        capability_groups=["file_work", "artifact_generation"],
    )
    model = _UnexpectedNativeToolCallModelRuntime(
        tool_calls=[
            {
                "id": "call-request-task-run",
                "name": "request_task_run",
                "args": {
                    "user_visible_goal": "交付一个真实页面。",
                    "task_run_goal": "创建并验证一个真实 HTML 页面。",
                    "public_progress_note": "我先把页面目标转成可执行任务，然后推进实现和文件验证。",
                },
            }
        ],
        recovery_action=_action_request(
            action_type="request_task_run",
            public_progress_note="我先把页面目标转成可执行任务，然后推进实现和文件验证。",
            task_contract_seed=task_seed,
        ),
    )
    runtime = build_harness_runtime(model_runtime=model)

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-native-taskrun",
                message="帮我做一个页面。",
                runtime_contract={
                    "allowed_operations": ["op.model_response"],
                    "control_capabilities": {"may_request_task_run": True, "may_use_subagents": False},
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    branch = dict(next(event for event in events if event.get("type") == "runtime_branch_decided").get("runtime_branch") or {})
    lifecycle = [event for event in events if event.get("type") == "task_run_lifecycle_started"][0]
    task_run_event = dict(lifecycle.get("event") or {})
    payload = dict(task_run_event.get("payload") or {})
    task_run = dict(payload.get("task_run") or {})
    task_run_id = str(task_run.get("task_run_id") or "")
    stored_task = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)

    assert branch.get("branch_kind") == "single_agent_turn"
    admissions = _admission_payloads(events)
    control_signals = [
        dict(dict(event.get("event") or {}).get("payload") or {}).get("runtime_control_signal")
        for event in events
        if event.get("type") == "turn_runtime_control_signal_observed"
    ]
    assert admissions
    assert dict(admissions[0].get("admission") or {}).get("decision") == "allow"
    admitted_action = dict(admissions[0].get("model_action_request") or {})
    assert admitted_action.get("action_type") == "request_task_run"
    assert any(
        dict(signal or {}).get("signal_kind") == "model_protocol_violation"
        and dict(dict(signal or {}).get("protocol_error") or {}).get("code") == "single_agent_turn_invalid_native_action"
        for signal in control_signals
    )
    assert "runtime_invocation_packet" not in stream_types
    assert "model_action_request" not in stream_types
    assert "task_run_lifecycle_started" in stream_types
    assert task_run_id.startswith("taskrun:")
    assert stored_task is not None
    assert dict(getattr(stored_task, "diagnostics", {}) or {}).get("origin_kind") == "single_agent_turn_json_action"

def test_single_agent_turn_json_request_task_run_starts_real_task_lifecycle() -> None:
    runtime = build_harness_runtime(
        model_runtime=_TurnActionSequenceModelRuntime(
            [
                _action_request(
                    action_type="request_task_run",
                    public_progress_note="我先把 JSON 页面目标转成持续任务，然后推进实现和验证。",
                    task_contract_seed=_canonical_task_contract_seed({
                        "user_visible_goal": "交付一个 JSON 协议页面。",
                        "task_run_goal": "通过 JSON action 创建页面任务。",
                        "required_artifacts": [{"artifact_kind": "html_app", "user_visible_name": "页面"}],
                        "required_verifications": [{"verification_kind": "file_exists"}],
                        "completion_criteria": ["页面文件真实存在"],
                    }, capability_groups=["file_work", "artifact_generation"]),
                )
            ]
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-json-taskrun",
                message="帮我做一个页面。",
                runtime_contract={
                    "allowed_operations": ["op.model_response"],
                    "control_capabilities": {
                        "may_request_task_run": True,
                        "requires_json_action_protocol": True,
                        "may_use_subagents": False,
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    lifecycle = [event for event in events if event.get("type") == "task_run_lifecycle_started"][0]
    task_run_event = dict(lifecycle.get("event") or {})
    payload = dict(task_run_event.get("payload") or {})
    task_run = dict(payload.get("task_run") or {})
    task_run_id = str(task_run.get("task_run_id") or "")
    stored_task = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    admissions = _admission_payloads(events)

    assert "task_run_lifecycle_started" in stream_types
    assert admissions
    assert dict(admissions[0].get("model_action_request") or {}).get("action_type") == "request_task_run"
    assert task_run_id.startswith("taskrun:")
    assert stored_task is not None
    assert dict(getattr(stored_task, "diagnostics", {}) or {}).get("origin_kind") == "single_agent_turn_json_action"


def test_single_agent_turn_surrounding_text_fenced_request_task_run_starts_lifecycle_without_recovery() -> None:
    task_seed = _canonical_task_contract_seed({
        "user_visible_goal": "修复 agent 输出吞没问题。",
        "task_run_goal": "修复控制契约恢复链路，确保被拒绝 action 能准确回传给 agent。",
        "required_artifacts": [{"artifact_kind": "code_change", "user_visible_name": "恢复契约修复"}],
        "required_verifications": [{"verification_kind": "pytest"}],
        "completion_criteria": ["恢复 observation 包含未执行 action", "重提 JSON 后启动真实 TaskRun"],
    }, capability_groups=["file_work"])
    action = _action_request(
        action_type="request_task_run",
        public_progress_note="我已判断需要进入持续任务，并会保留可验证的完成标准。",
        task_contract_seed=task_seed,
    )

    class SurroundingTextFencedJsonTaskRunModelRuntime:
        def __init__(self) -> None:
            self.invocation_count = 0

        async def invoke_messages(self, messages, **_kwargs):
            del messages
            self.invocation_count += 1
            return SimpleNamespace(
                content=(
                    "我已经掌握了 CSS，现在发起持续任务。\n"
                    "```json\n"
                    + json.dumps(action, ensure_ascii=False)
                    + "\n```"
                )
            )

    model = SurroundingTextFencedJsonTaskRunModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-surrounding-text-taskrun",
                message="帮我修复 agent 输出吞没问题。",
                runtime_contract={
                    "allowed_operations": ["op.model_response"],
                    "control_capabilities": {
                        "may_request_task_run": True,
                        "requires_json_action_protocol": True,
                        "may_use_subagents": False,
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    lifecycle = [event for event in events if event.get("type") == "task_run_lifecycle_started"][0]
    task_run_event = dict(lifecycle.get("event") or {})
    payload = dict(task_run_event.get("payload") or {})
    task_run = dict(payload.get("task_run") or {})
    task_run_id = str(task_run.get("task_run_id") or "")
    stored_task = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    admissions = _admission_payloads(events)

    assert model.invocation_count == 1
    assert "turn_runtime_control_signal_observed" not in stream_types
    assert "agent_contract_feedback_required" not in stream_types
    assert "task_run_lifecycle_started" in stream_types
    assert admissions
    assert dict(admissions[0].get("admission") or {}).get("decision") == "allow"
    assert dict(admissions[0].get("model_action_request") or {}).get("action_type") == "request_task_run"
    diagnostics = dict(dict(admissions[0].get("model_action_request") or {}).get("diagnostics") or {})
    parse_transport = dict(diagnostics.get("parse_transport") or {})
    assert parse_transport["embedded_action_object"] is True
    assert parse_transport["markdown_fence"] is True
    assert task_run_id.startswith("taskrun:")
    assert stored_task is not None
    assert dict(getattr(stored_task, "diagnostics", {}) or {}).get("origin_kind") == "single_agent_turn_json_action"

def test_default_runtime_policy_uses_main_profile_for_standard_chat() -> None:
    runtime = build_harness_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-standard-chat",
                message="普通对话。",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})

    assert dict(assembly.get("profile") or {}).get("profile_ref") == "main_interactive_agent"

def test_default_runtime_policy_exposes_plan_policy() -> None:
    runtime = build_harness_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-default-policy",
                message="执行需要真实产物的任务。",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})
    profile = dict(assembly.get("profile") or {})

    assert profile["profile_ref"] == "main_interactive_agent"
    assert dict(profile.get("planning_policy") or {}).get("specified_plan_allowed") is True
    prompt_policy = dict(profile.get("prompt_policy") or {})
    assert prompt_policy.get("template_id") == "prompt_template.general.agent_runtime"
    assert prompt_policy.get("template_selection_source") == "agent_runtime_profile.metadata.prompt_template_id"
    assert dict(assembly.get("task_environment") or {}).get("environment_id") == "env.general.workspace"

def test_prompt_template_is_not_injected_without_explicit_selection() -> None:
    profile = build_runtime_assembly_profile(agent_runtime_profile=None, runtime_contract={})

    assert profile.prompt_policy == {}

    explicit = build_runtime_assembly_profile(
        agent_runtime_profile=None,
        runtime_contract={"prompt_template_id": "prompt_template.general.agent_runtime"},
    )

    assert explicit.prompt_policy["template_id"] == "prompt_template.general.agent_runtime"
    assert explicit.prompt_policy["template_selection_source"] == "runtime_contract.prompt_template_id"

def test_runtime_policy_can_override_default_runtime_assembly() -> None:
    runtime = build_harness_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-specific-mode-policy",
                message="按特定任务配置运行。",
                runtime_contract={
                    "task_environment_id": "env.office.file_search",
                    "runtime_policy": {
                        "planning_policy": {"plan_mode": "disabled", "specified_plan_allowed": False},
                        "task_lifecycle_policy": {"request_task_run": True, "requires_completion_evidence": True},
                        "self_review_policy": {"enabled": True, "checkpoints": ["before_final"]},
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})
    profile = dict(assembly.get("profile") or {})

    assert profile["profile_ref"] == "main_interactive_agent"
    assert dict(profile.get("planning_policy") or {}).get("specified_plan_allowed") is False
    assert dict(profile.get("self_review_policy") or {}).get("checkpoints") == ["before_final"]
    assert dict(assembly.get("task_environment") or {}).get("environment_id") == "env.office.file_search"

def test_runtime_profile_uses_explicit_runtime_policy_and_environment() -> None:
    runtime = build_harness_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-custom-mode-policy",
                message="按显式运行策略执行。",
                runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
                runtime_profile={
                    "runtime_policy": {
                        "interaction_policy": {"style": "custom_review"},
                        "planning_policy": {"plan_mode": "disabled"},
                        "task_lifecycle_policy": {"request_task_run": False},
                        "tool_exposure_policy": {
                            "read_only_tools_only": True,
                            "operation_ceiling": ["op.model_response", "op.read_file"],
                        },
                        "self_review_policy": {"enabled": True, "before_final": "strict_review"},
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})
    profile = dict(assembly.get("profile") or {})

    assert profile["profile_ref"] == "main_interactive_agent"
    assert dict(profile.get("interaction_policy") or {}).get("style") == "custom_review"
    assert dict(profile.get("task_lifecycle_policy") or {}).get("request_task_run") is False
    assert dict(profile.get("self_review_policy") or {}).get("before_final") == "strict_review"
    assert dict(assembly.get("task_environment") or {}).get("environment_id") == "env.coding.vibe_workspace"

def test_turn_packet_does_not_expose_obsolete_task_goal_type_from_selection() -> None:
    class CaptureModelRuntime:
        def __init__(self) -> None:
            self.messages: list[object] = []

        async def invoke_messages(self, messages, **_kwargs):
            self.messages = list(messages)
            return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer="ok")))

    model = CaptureModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)

    async def _collect() -> None:
        async for _event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-no-legacy-goal-type",
                message="做一个小游戏。",
                runtime_contract={"task_goal_type": "code_fix_execution", "selected_task_id": "legacy"},
            )
        ):
            pass

    asyncio.run(_collect())
    packet_payload = json.dumps(model.messages, ensure_ascii=False)

    assert "task_selection" not in packet_payload
    assert "code_fix_execution" not in packet_payload

def test_main_session_model_action_writes_prompt_accounting_ledger() -> None:
    class AccountingModelRuntime(SingleMessageModelRuntimeStub):
        def __init__(self) -> None:
            super().__init__(
                agent_turn_action_request=_action_request(
                    action_type="respond",
                    final_answer="ok",
                )
            )
            self.ledger = None
            self.serializer = CanonicalPromptSerializer()
            self.cache_planner = PromptCachePlanner()

        def attach_prompt_accounting_ledger(self, ledger):
            self.ledger = ledger

        async def invoke_messages(self, messages, **kwargs):
            response = await super().invoke_messages(messages, **kwargs)
            context = dict(kwargs.get("accounting_context") or {})
            if self.ledger is not None and context:
                request_id = str(context.get("request_id") or "modelreq:test")
                run_id = str(context.get("run_id") or context.get("task_run_id") or "")
                task_run_id = str(context.get("task_run_id") or "")
                segment_map = self.serializer.build_segment_map(
                    request_id=request_id,
                    messages=list(messages),
                    run_id=run_id,
                    task_run_id=task_run_id,
                    session_id=str(context.get("session_id") or ""),
                    provider="stub",
                    model="stub-model",
                )
                self.ledger.record_segment_map(segment_map)
                self.ledger.record_token_usage(
                    ModelTokenUsageRecord(
                        usage_id=f"tokuse:{request_id}:local_prediction",
                        request_id=request_id,
                        run_id=run_id,
                        task_run_id=task_run_id,
                        session_id=str(context.get("session_id") or ""),
                        provider="stub",
                        model="stub-model",
                        source="local_prediction",
                        prompt_tokens=segment_map.predicted_prompt_tokens,
                        total_tokens=segment_map.predicted_prompt_tokens,
                        created_at=1.0,
                    )
                )
                provider_response = SimpleNamespace(
                    content=response.content,
                    usage_metadata={"input_tokens": 12, "output_tokens": 3},
                )
                provider_usage = extract_provider_usage(
                    provider_response,
                    request_id=request_id,
                    run_id=run_id,
                    task_run_id=task_run_id,
                    session_id=str(context.get("session_id") or ""),
                    provider="stub",
                    model="stub-model",
                    created_at=2.0,
                )
                self.ledger.record_token_usage(provider_usage)
                self.ledger.record_prompt_cache(
                    self.cache_planner.with_provider_usage(self.cache_planner.plan(segment_map), provider_usage)
                )
            return response

    runtime = build_harness_runtime(model_runtime=AccountingModelRuntime())

    async def _collect() -> None:
        async for _event in runtime.astream(HarnessRuntimeRequest(session_id="session-accounting", message="hello")):
            pass

    asyncio.run(_collect())
    turn_run_id = runtime.single_agent_runtime_host.list_session_traces("session-accounting")["turn_runs"][0]["turn_run_id"]
    summary = runtime.single_agent_runtime_host.prompt_accounting_ledger.summarize_run(turn_run_id)

    assert summary["exact_total_tokens"] == 15
    assert summary["provider_usage_record_count"] == 1
    assert summary["local_prediction_record_count"] == 1
