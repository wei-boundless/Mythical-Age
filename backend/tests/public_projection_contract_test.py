from __future__ import annotations

import asyncio
from types import SimpleNamespace

from api.chat import (
    ChatTaskBridgeContext,
    _agent_todo_observation_summary,
    _allow_public_stream_flush,
    _append_chat_public_event,
    _append_task_bridge_terminal,
    _is_task_executor_handoff_terminal,
    _project_task_runtime_event_to_chat,
    _project_public_stream_event,
    _public_turn_status_for_task_status,
    _public_terminal_reason,
    _run_chat_to_event_log,
    _task_terminal_context_from_task_run,
    _tool_permission_decided_data,
    TASK_BRIDGE_TERMINAL_EVENT_TYPES,
    replay_chat_run_events,
)
from harness.entrypoint.models import HarnessRuntimeRequest
from harness.runtime.projection.authority import PUBLIC_PROJECTION_AUTHORITY, PUBLIC_PROJECTION_CONTRACT_REVISION
from harness.runtime.projection.guards import public_text
from harness.runtime.projection.projector import ProjectionLifecycleState, project_public_projection_event
from runtime.output_stream.public_contract import (
    ASSISTANT_PUBLIC_FEEDBACK_EVENT,
    ASSISTANT_TEXT_DELTA_EVENT,
    ASSISTANT_TEXT_FINAL_EVENT,
    SESSION_OUTPUT_COMMIT_ACK_EVENT,
    SESSION_OUTPUT_COMMIT_FAILED_EVENT,
    TASK_BRIDGE_TERMINAL_EVENT,
    TOOL_CALL_REQUESTED_EVENT,
    TOOL_ITEM_COMPLETED_EVENT,
    TOOL_ITEM_STARTED_EVENT,
    TOOL_PERMISSION_DECIDED_EVENT,
    TURN_COMPLETED_EVENT,
)
from runtime.shared.runtime_run_registry import RuntimeRun
from runtime.shared.events import RuntimeEvent
from runtime.shared.stream_replay import RuntimeStreamReplayService
from runtime.tool_runtime import ToolObservation


def _frame(event_type: str, data: dict, *, sequence: int = 1) -> dict:
    frame = project_public_projection_event(
        event_type,
        {
            **data,
            "public_anchor": {
                "session_id": "session:test",
                "turn_id": "turn:test",
                "stream_run_id": "strun:test",
                "task_run_id": "taskrun:turn:test:1",
            },
        },
        session_id="session:test",
        sequence=sequence,
    )["public_projection_frame"]
    assert frame["contract_revision"] == PUBLIC_PROJECTION_CONTRACT_REVISION
    assert frame["event_family"]
    assert frame["channel"]
    assert isinstance(frame["lossless"], bool)
    assert frame["anchor"]["stream_run_id"] == "strun:test"
    return frame


class _RegistrySpy:
    def __init__(self) -> None:
        self.mark_event_calls: list[dict] = []

    def mark_event(self, run: RuntimeRun, **kwargs) -> RuntimeRun:
        self.mark_event_calls.append(dict(kwargs))
        return RuntimeRun(
            stream_run_id=run.stream_run_id,
            session_id=run.session_id,
            event_log_id=run.event_log_id,
            root_request_ref=run.root_request_ref,
            status=kwargs.get("status") or run.status,
            created_at=run.created_at,
            updated_at=run.updated_at + 1,
            latest_event_offset=kwargs.get("latest_event_offset", run.latest_event_offset),
            diagnostics=run.diagnostics,
        )


class _ReplaySpy:
    def __init__(self) -> None:
        self.append_public_event_calls: list[dict] = []

    def append_public_event(self, run: RuntimeRun, *, public_event_type: str, data: dict):
        self.append_public_event_calls.append({"public_event_type": public_event_type, "data": dict(data)})

        class _Logged:
            offset = run.latest_event_offset + 1

        return _Logged()


class _MutableRegistrySpy:
    def __init__(self, run: RuntimeRun) -> None:
        self.run = run

    def mark_running(self, run: RuntimeRun) -> RuntimeRun:
        self.run = RuntimeRun(
            stream_run_id=run.stream_run_id,
            session_id=run.session_id,
            event_log_id=run.event_log_id,
            root_request_ref=run.root_request_ref,
            status="running",
            created_at=run.created_at,
            updated_at=run.updated_at + 1,
            latest_event_offset=run.latest_event_offset,
            terminal_event=run.terminal_event,
            diagnostics=run.diagnostics,
        )
        return self.run

    def mark_event(self, run: RuntimeRun, **kwargs) -> RuntimeRun:
        self.run = RuntimeRun(
            stream_run_id=run.stream_run_id,
            session_id=run.session_id,
            event_log_id=run.event_log_id,
            root_request_ref=run.root_request_ref,
            status=kwargs.get("status") or run.status,
            created_at=run.created_at,
            updated_at=run.updated_at + 1,
            latest_event_offset=kwargs.get("latest_event_offset", run.latest_event_offset),
            terminal_event=kwargs.get("terminal_event") or run.terminal_event,
            diagnostics=kwargs.get("diagnostics") or run.diagnostics,
        )
        return self.run

    def get_run(self, _stream_run_id: str) -> RuntimeRun:
        return self.run


class _OffsetReplaySpy:
    def __init__(self) -> None:
        self.append_public_event_calls: list[dict] = []

    def append_public_event(self, run: RuntimeRun, *, public_event_type: str, data: dict):
        offset = len(self.append_public_event_calls)
        self.append_public_event_calls.append(
            {
                "public_event_type": public_event_type,
                "data": dict(data),
                "previous_latest_event_offset": run.latest_event_offset,
                "offset": offset,
            }
        )
        return SimpleNamespace(offset=offset)


def test_public_stream_flush_yields_only_after_new_public_event(monkeypatch) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("api.chat.asyncio.sleep", fake_sleep)
    unchanged = RuntimeRun(
        stream_run_id="strun:test",
        session_id="session:test",
        event_log_id="chatrun:test",
        root_request_ref="chatreq:test",
        status="running",
        created_at=1.0,
        updated_at=1.0,
        latest_event_offset=0,
    )
    advanced = RuntimeRun(
        stream_run_id="strun:test",
        session_id="session:test",
        event_log_id="chatrun:test",
        root_request_ref="chatreq:test",
        status="running",
        created_at=1.0,
        updated_at=1.0,
        latest_event_offset=1,
    )

    asyncio.run(_allow_public_stream_flush(0, unchanged))
    asyncio.run(_allow_public_stream_flush(0, advanced))

    assert sleep_calls == [0]


def test_chat_event_log_allows_sse_flush_between_contiguous_public_events(monkeypatch) -> None:
    run = RuntimeRun(
        stream_run_id="strun:test",
        session_id="session:test",
        event_log_id="chatrun:test",
        root_request_ref="chatreq:test",
        status="starting",
        created_at=1.0,
        updated_at=1.0,
    )
    registry = _MutableRegistrySpy(run)
    replay = _OffsetReplaySpy()
    flush_calls: list[tuple[int, int, str]] = []

    async def fake_flush(previous_offset: int, current: RuntimeRun) -> None:
        event_type = replay.append_public_event_calls[-1]["public_event_type"]
        flush_calls.append((previous_offset, current.latest_event_offset, event_type))

    async def fake_astream(_request):
        yield {
            "type": "single_agent_turn_started",
            "turn_run_id": "turnrun:turn:test",
            "active_turn_id": "turn:test",
            "event_id": "rtevt:turn:start",
            "event_offset": 0,
        }
        yield {
            "type": ASSISTANT_TEXT_DELTA_EVENT,
            "turn_run_id": "turnrun:turn:test",
            "active_turn_id": "turn:test",
            "stream_ref": "stream:test",
            "message_ref": "message:test",
            "sequence": 1,
            "content": "第一段",
        }
        yield {
            "type": ASSISTANT_TEXT_DELTA_EVENT,
            "turn_run_id": "turnrun:turn:test",
            "active_turn_id": "turn:test",
            "stream_ref": "stream:test",
            "message_ref": "message:test",
            "sequence": 2,
            "content": "第二段",
        }
        yield {
            "type": ASSISTANT_TEXT_FINAL_EVENT,
            "turn_run_id": "turnrun:turn:test",
            "active_turn_id": "turn:test",
            "stream_ref": "stream:test",
            "message_ref": "message:test",
            "sequence": 3,
            "content": "第一段第二段",
        }
        yield {"type": "done", "content": "第一段第二段", "status": "completed"}

    monkeypatch.setattr("api.chat._allow_public_stream_flush", fake_flush)
    host = SimpleNamespace(
        run_registry=registry,
        stream_replay=replay,
        active_turn_registry=SimpleNamespace(snapshot=lambda _session_id: None),
    )
    runtime = SimpleNamespace(
        harness_runtime=SimpleNamespace(
            single_agent_runtime_host=host,
            astream=fake_astream,
        )
    )
    request = HarnessRuntimeRequest(session_id="session:test", message="hello")

    asyncio.run(_run_chat_to_event_log(runtime, run, request))

    public_event_types = [call["public_event_type"] for call in replay.append_public_event_calls]
    assert public_event_types == [
        "chat_run_started",
        "chat_turn_bound",
        "single_agent_turn_started",
        ASSISTANT_TEXT_DELTA_EVENT,
        ASSISTANT_TEXT_DELTA_EVENT,
        ASSISTANT_TEXT_FINAL_EVENT,
        TURN_COMPLETED_EVENT,
    ]
    assert [call[2] for call in flush_calls] == public_event_types
    assert [(previous, current) for previous, current, _event_type in flush_calls] == [
        (-1, 0),
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 4),
        (4, 5),
        (5, 6),
    ]


def test_chat_event_log_does_not_bind_identityless_turn_from_active_registry(monkeypatch) -> None:
    run = RuntimeRun(
        stream_run_id="strun:test",
        session_id="session:test",
        event_log_id="chatrun:test",
        root_request_ref="chatreq:test",
        status="starting",
        created_at=1.0,
        updated_at=1.0,
    )
    registry = _MutableRegistrySpy(run)
    replay = _OffsetReplaySpy()
    snapshot_calls: list[str] = []

    async def fake_flush(_previous_offset: int, _current: RuntimeRun) -> None:
        return None

    async def fake_astream(_request):
        yield {
            "type": "single_agent_turn_started",
            "event_id": "rtevt:turn:start:missing-refs",
            "event_offset": 0,
        }
        yield {"type": "done", "content": "完成", "status": "completed"}

    def active_snapshot(session_id: str):
        snapshot_calls.append(session_id)
        return SimpleNamespace(
            bound_task_run_id="taskrun:active-registry",
            turn_id="turn:active-registry",
            turn_run_id="turnrun:turn:active-registry",
        )

    monkeypatch.setattr("api.chat._allow_public_stream_flush", fake_flush)
    host = SimpleNamespace(
        run_registry=registry,
        stream_replay=replay,
        active_turn_registry=SimpleNamespace(snapshot=active_snapshot),
    )
    runtime = SimpleNamespace(
        harness_runtime=SimpleNamespace(
            single_agent_runtime_host=host,
            astream=fake_astream,
        )
    )
    request = HarnessRuntimeRequest(session_id="session:test", message="hello")

    asyncio.run(_run_chat_to_event_log(runtime, run, request))

    public_event_types = [call["public_event_type"] for call in replay.append_public_event_calls]
    public_data_repr = repr([call["data"] for call in replay.append_public_event_calls])
    assert "chat_turn_bound" not in public_event_types
    assert "taskrun:active-registry" not in public_data_repr
    assert "turn:active-registry" not in public_data_repr
    assert snapshot_calls == []


def test_chat_run_events_replay_returns_public_envelopes(monkeypatch) -> None:
    run = RuntimeRun(
        stream_run_id="strun:test",
        session_id="session:test",
        event_log_id="chatrun:test",
        root_request_ref="chatreq:test",
        status="running",
        created_at=1.0,
        updated_at=1.0,
    )

    expected = {
        "stream_run_id": "strun:test",
        "event_log_id": "chatrun:test",
        "after_offset": -1,
        "latest_event_offset": 1,
        "terminal": True,
        "events": [
            {
                "type": "event",
                "event_offset": 1,
                "public_event_type": TURN_COMPLETED_EVENT,
                "terminal": True,
                "data": {"status": "completed"},
            }
        ],
        "authority": "runtime.stream_replay",
    }
    replay = SimpleNamespace(public_replay_response=lambda _run, after_offset, limit: expected)
    runtime = SimpleNamespace(
        harness_runtime=SimpleNamespace(
            single_agent_runtime_host=SimpleNamespace(stream_replay=replay)
        )
    )

    monkeypatch.setattr("api.chat.require_runtime", lambda: runtime)
    monkeypatch.setattr("api.chat._get_run_or_404", lambda _runtime, _stream_run_id: run)
    response = asyncio.run(replay_chat_run_events("strun:test", after_offset=-1, limit=10))

    assert response == expected


def _task_bridge_context() -> ChatTaskBridgeContext:
    return ChatTaskBridgeContext(
        bridge_id="task-bridge:test",
        stream_run_id="strun:test",
        event_log_id="chatrun:test",
        session_id="session:test",
        turn_id="turn:test",
        turn_run_id="turnrun:test",
        task_run_id="taskrun:turn:test:1",
        assistant_message_ref="assistant:turn:test",
        source_handoff_event_id="event:handoff",
        source_handoff_event_offset=1,
        task_event_start_offset=2,
        public_sequence_base=0,
        created_at=1.0,
    )


def _task_bridge_runtime(run: RuntimeRun, replay: _OffsetReplaySpy) -> SimpleNamespace:
    return SimpleNamespace(
        harness_runtime=SimpleNamespace(
            single_agent_runtime_host=SimpleNamespace(
                run_registry=_MutableRegistrySpy(run),
                stream_replay=replay,
            )
        )
    )


def test_task_bridge_terminal_does_not_infer_commit_failure_from_diagnostics_final_answer() -> None:
    run = RuntimeRun(
        stream_run_id="strun:test",
        session_id="session:test",
        event_log_id="chatrun:test",
        root_request_ref="chatreq:test",
        status="running",
        created_at=1.0,
        updated_at=1.0,
    )
    replay = _OffsetReplaySpy()

    _append_task_bridge_terminal(
        _task_bridge_runtime(run, replay),
        run,
        run,
        request=HarnessRuntimeRequest(session_id="session:test", message="hello"),
        context={
            "task_run_id": "taskrun:turn:test:1",
            "status": "completed",
            "terminal_reason": "completed",
            "final_answer": "diagnostics-only final answer must not decide commit failure",
        },
        projection_lifecycle=ProjectionLifecycleState(),
        bridge_context=_task_bridge_context(),
        task_event=SimpleNamespace(event_id="event:terminal", offset=3),
        output_observed=False,
        commit_observed=False,
    )

    assert [call["public_event_type"] for call in replay.append_public_event_calls] == [
        TASK_BRIDGE_TERMINAL_EVENT,
        TURN_COMPLETED_EVENT,
    ]


def test_task_bridge_terminal_records_commit_failure_when_final_output_lacks_commit_event() -> None:
    run = RuntimeRun(
        stream_run_id="strun:test",
        session_id="session:test",
        event_log_id="chatrun:test",
        root_request_ref="chatreq:test",
        status="running",
        created_at=1.0,
        updated_at=1.0,
    )
    replay = _OffsetReplaySpy()

    _append_task_bridge_terminal(
        _task_bridge_runtime(run, replay),
        run,
        run,
        request=HarnessRuntimeRequest(session_id="session:test", message="hello"),
        context={
            "task_run_id": "taskrun:turn:test:1",
            "status": "failed",
            "terminal_reason": "session_output_commit_failed",
        },
        projection_lifecycle=ProjectionLifecycleState(),
        bridge_context=_task_bridge_context(),
        task_event=SimpleNamespace(event_id="event:terminal", offset=13),
        output_observed=True,
        commit_observed=False,
    )

    assert [call["public_event_type"] for call in replay.append_public_event_calls] == [
        SESSION_OUTPUT_COMMIT_FAILED_EVENT,
        TASK_BRIDGE_TERMINAL_EVENT,
        TURN_COMPLETED_EVENT,
    ]
    assert replay.append_public_event_calls[0]["data"]["reason"] == "task_terminal_final_without_commit_event"


def test_task_bridge_terminal_ignores_diagnostics_output_commit_shadow_receipt() -> None:
    context = _task_terminal_context_from_task_run(
        {
            "task_run_id": "taskrun:turn:test:1",
            "status": "completed",
            "terminal_reason": "completed",
            "diagnostics": {
                "turn_id": "turn:diagnostic-shadow",
                "turn_run_id": "turnrun:diagnostic-shadow",
                "answer_source": "diagnostics.shadow.answer_source",
                "output_commit": {
                    "authority": "harness.session_output_commit",
                    "event_type": "session_output_commit_ack",
                    "event_id": "event:shadow",
                    "state": "committed",
                    "event_offset": 12,
                    "content_sha256": "sha256:shadow",
                },
            },
        }
    )
    run = RuntimeRun(
        stream_run_id="strun:test",
        session_id="session:test",
        event_log_id="chatrun:test",
        root_request_ref="chatreq:test",
        status="running",
        created_at=1.0,
        updated_at=1.0,
    )
    replay = _OffsetReplaySpy()

    _append_task_bridge_terminal(
        _task_bridge_runtime(run, replay),
        run,
        run,
        request=HarnessRuntimeRequest(session_id="session:test", message="hello"),
        context=context,
        projection_lifecycle=ProjectionLifecycleState(),
        bridge_context=_task_bridge_context(),
        task_event=SimpleNamespace(event_id="event:terminal", offset=13),
        output_observed=False,
        commit_observed=False,
    )

    assert "output_commit_state" not in context
    assert "turn_id" not in context
    assert "turn_run_id" not in context
    assert "answer_source" not in context
    assert [call["public_event_type"] for call in replay.append_public_event_calls] == [
        TASK_BRIDGE_TERMINAL_EVENT,
        TURN_COMPLETED_EVENT,
    ]


def test_task_bridge_output_observed_requires_final_or_repair_event() -> None:
    class _TaskEvent:
        def __init__(self, event_type: str, payload: dict, *, offset: int) -> None:
            self.run_id = "taskrun:turn:test:1"
            self.event_id = f"event:{offset}"
            self.event_type = event_type
            self.payload = dict(payload)
            self.refs = {"task_run_ref": self.run_id}
            self.offset = offset
            self.created_at = float(offset)

        def to_dict(self) -> dict:
            return {
                "run_id": self.run_id,
                "event_id": self.event_id,
                "event_type": self.event_type,
                "payload": dict(self.payload),
                "refs": dict(self.refs),
                "offset": self.offset,
                "created_at": self.created_at,
            }

    run = RuntimeRun(
        stream_run_id="strun:test",
        session_id="session:test",
        event_log_id="chatrun:test",
        root_request_ref="chatreq:test",
        status="running",
        created_at=1.0,
        updated_at=1.0,
    )
    runtime = _task_bridge_runtime(run, _OffsetReplaySpy())
    context = _task_bridge_context()
    request = HarnessRuntimeRequest(session_id="session:test", message="hello")

    current, terminal, delta_state = _project_task_runtime_event_to_chat(
        runtime,
        run,
        run,
        request=request,
        task_event=_TaskEvent(ASSISTANT_TEXT_DELTA_EVENT, {"content": "partial"}, offset=2),
        bridge_context=context,
        projection_lifecycle=ProjectionLifecycleState(),
    )
    _current, terminal_after_final, final_state = _project_task_runtime_event_to_chat(
        runtime,
        run,
        current,
        request=request,
        task_event=_TaskEvent(ASSISTANT_TEXT_FINAL_EVENT, {"content": "complete"}, offset=3),
        bridge_context=context,
        projection_lifecycle=ProjectionLifecycleState(),
        output_observed=delta_state["output_observed"],
    )

    assert terminal is False
    assert terminal_after_final is False
    assert delta_state["output_observed"] is False
    assert final_state["output_observed"] is True


def test_public_projection_frame_exposes_dual_channel_contract() -> None:
    body = _frame(ASSISTANT_TEXT_FINAL_EVENT, {"content": "完成。"})
    tool = _frame(TOOL_CALL_REQUESTED_EVENT, {"tool_call_id": "call:read", "tool_name": "read_file"})
    commit = _frame(SESSION_OUTPUT_COMMIT_ACK_EVENT, {"state": "committed"})
    terminal = _frame(TURN_COMPLETED_EVENT, {"status": "completed"})
    status = _frame("runtime_step_summary", {"summary": "准备执行", "status": "running"})

    assert body["event_family"] == "assistant_body"
    assert body["channel"] == "body"
    assert body["lossless"] is True
    assert tool["event_family"] == "tool_control"
    assert tool["channel"] == "control"
    assert tool["lossless"] is True
    assert commit["event_family"] == "runtime_commit"
    assert commit["channel"] == "commit"
    assert commit["lossless"] is True
    assert terminal["event_family"] == "turn_anchor_terminal"
    assert terminal["channel"] == "terminal"
    assert terminal["lossless"] is True
    assert status["event_family"] == "status_trace"
    assert status["channel"] == "status"
    assert status["lossless"] is False


def test_public_projection_frame_event_offset_uses_public_sequence_only() -> None:
    frame = _frame(
        ASSISTANT_TEXT_FINAL_EVENT,
        {"content": "完成。", "event_offset": 999, "offset": 998, "sequence": 997},
        sequence=7,
    )

    assert frame["sequence"] == 7
    assert frame["event_offset"] == 7


def test_active_task_steer_accepted_is_lightweight_status_event_not_body() -> None:
    frame = _frame(
        "active_task_steer_accepted",
        {
            "task_run_id": "taskrun:active",
            "turn_id": "turn:test",
        },
    )

    assert frame["op"] == "item_upsert"
    assert frame["slot"] == "status"
    assert frame["main_visibility"] == "visible_live"
    assert frame["retention"] == "transient"
    assert frame["status_kind"] == "status_event"
    assert frame["event_family"] == "status_trace"
    assert frame["channel"] == "status"
    assert frame["slot"] != "body"


def test_runtime_gateway_signals_are_not_public_stream_events() -> None:
    events = _project_public_stream_event(
        "runtime_control_signal_published",
        {
            "event": {
                "event_id": "event:gateway:tool-started",
                "payload": {
                    "signal": {
                        "signal_type": "tool.execution.started",
                        "payload": {
                            "tool_invocation_id": "toolinvoke:private",
                            "tool_call_id": "call:private",
                            "tool_name": "read_file",
                        },
                    }
                },
            },
        },
    )

    assert events == []


def test_runtime_status_only_error_does_not_terminalize_chat_turn() -> None:
    events = _project_public_stream_event(
        "error",
        {
            "code": "harness_entrypoint_error",
            "content": "运行中断",
            "reason": "runtime unavailable",
            "answer_persist_policy": "runtime_status_only",
            "answer_finalization_policy": "no_agent_answer_runtime_unavailable",
            "event_id": "event:runtime-error",
        },
    )

    assert events == []


def test_fail_closed_visible_error_still_terminalizes_chat_turn() -> None:
    events = _project_public_stream_event(
        "error",
        {
            "code": "blocked_runtime",
            "content": "当前运行环境未能完成装配，无法继续执行本轮请求。",
            "reason": "runtime_assembly_blocked",
            "answer_persist_policy": "assistant_message_committed",
            "answer_finalization_policy": "fail_closed_visible_message",
            "turn_run_id": "turnrun:turn:test:blocked",
            "message_ref": "history-message:turn:test:blocked:assistant",
            "event_id": "event:blocked-runtime",
        },
    )

    assert [event_type for event_type, _ in events] == [TURN_COMPLETED_EVENT]
    data = events[0][1]
    assert data["status"] == "failed"
    assert data["terminal_reason"]
    assert data["final_message_ref"] == "history-message:turn:test:blocked:assistant"


def test_model_admission_projects_tool_request_before_runtime_tool_lifecycle() -> None:
    events = _project_public_stream_event(
        "model_action_admission",
        {
            "event": {
                "event_id": "event:admission",
                "payload": {
                    "turn_id": "turn:test",
                    "model_action_request": {
                        "request_id": "request:read",
                        "action_type": "tool_call",
                        "public_progress_note": "读取 README。",
                        "public_action_state": {"next_action": "读取 README.md"},
                        "tool_call": {
                            "id": "call:read",
                            "tool_name": "read_file",
                            "args": {"path": "README.md"},
                        },
                    },
                    "admission": {"decision": "allow", "decision_id": "permit:read"},
                },
                "refs": {"turn_run_ref": "turnrun:turn:test:1"},
            },
        },
    )

    assert [event_type for event_type, _ in events] == [
        TOOL_CALL_REQUESTED_EVENT,
        TOOL_PERMISSION_DECIDED_EVENT,
    ]
    requested = events[0][1]
    permission = events[1][1]
    assert requested["tool_call_id"] == "call:read"
    assert requested["tool_name"] == "read_file"
    assert requested["turn_run_id"] == "turnrun:turn:test:1"
    assert permission["tool_call_id"] == "call:read"
    assert permission["permission_decision"] == "allow"


def test_model_admission_projects_terminal_command_as_public_target() -> None:
    command = "npm test -- src/components/chat/PublicTimelineActivity.test.ts"
    events = _project_public_stream_event(
        "model_action_admission",
        {
            "event": {
                "event_id": "event:admission:terminal",
                "payload": {
                    "turn_id": "turn:test",
                    "model_action_request": {
                        "request_id": "request:terminal",
                        "action_type": "tool_call",
                        "tool_call": {
                            "id": "call:terminal",
                            "tool_name": "terminal",
                            "args": {"command": command, "cwd": "D:/AI/langchain-agent"},
                        },
                    },
                    "admission": {"decision": "allow", "decision_id": "permit:terminal"},
                },
                "refs": {"turn_run_ref": "turnrun:turn:test:terminal"},
            },
        },
    )

    requested = next(data for event_type, data in events if event_type == TOOL_CALL_REQUESTED_EVENT)
    assert requested["tool_call_id"] == "call:terminal"
    assert requested["tool_name"] == "terminal"
    assert requested["target"] == command
    assert f"command={command}" in requested["arguments_preview"]

    frame = _frame(TOOL_CALL_REQUESTED_EVENT, requested)
    assert frame["title"] == f"运行命令：{command}"
    assert frame["target"] == command
    assert frame["arguments_preview"]


def test_chat_bridge_does_not_generate_tool_call_id_for_legacy_identityless_admission() -> None:
    events = _project_public_stream_event(
        "model_action_admission",
        {
            "event": {
                "event_id": "event:admission:no-tool-id",
                "payload": {
                    "turn_id": "turn:test",
                    "model_action_request": {
                        "request_id": "request:read",
                        "action_type": "tool_call",
                        "tool_call": {
                            "tool_name": "read_file",
                            "args": {"path": "README.md"},
                        },
                    },
                    "admission": {"decision": "allow"},
                },
                "refs": {"turn_run_ref": "turnrun:turn:test:1"},
            },
        },
    )

    assert events == []


def test_chat_bridge_does_not_construct_tool_request_from_legacy_top_level_tool_fields() -> None:
    events = _project_public_stream_event(
        "model_action_admission",
        {
            "event": {
                "event_id": "event:admission:top-level-tool-fields",
                "payload": {
                    "turn_id": "turn:test",
                    "model_action_request": {
                        "request_id": "request:legacy-read",
                        "action_type": "tool_call",
                        "tool_call_id": "call:legacy-top-level",
                        "tool_name": "read_file",
                        "tool_args": {"path": "README.md"},
                    },
                    "admission": {"decision": "allow"},
                },
                "refs": {"turn_run_ref": "turnrun:turn:test:1"},
            },
        },
    )

    assert events == []


def test_tool_permission_decision_does_not_use_action_request_ref_as_tool_call_id() -> None:
    data = _tool_permission_decided_data(
        {
            "event": {
                "event_id": "event:permission:no-tool-id",
                "payload": {
                    "admission": {
                        "decision": "allow",
                        "action_request_ref": "model-action:read",
                    },
                },
            },
        },
        request_data={"request_id": "model-action:read", "tool_name": "read_file"},
    )

    assert data == {}


def test_chat_bridge_projects_tool_calls_array_without_admission_body_feedback() -> None:
    events = _project_public_stream_event(
        "model_action_admission",
        {
            "event": {
                "event_id": "event:admission:batch",
                "payload": {
                    "turn_id": "turn:test",
                    "model_action_request": {
                        "request_id": "request:batch",
                        "action_type": "tool_calls",
                        "public_progress_note": "并行检查两个文件。",
                        "tool_calls": [
                            {
                                "id": "call:readme",
                                "tool_name": "read_file",
                                "args": {"path": "README.md"},
                            },
                            {
                                "id": "call:package",
                                "tool_name": "read_file",
                                "args": {"path": "package.json"},
                            },
                        ],
                    },
                    "admission": {"decision": "allow", "admission_id": "permit:batch"},
                },
                "refs": {"turn_run_ref": "turnrun:turn:test:1"},
            },
        },
    )

    assert [event_type for event_type, _ in events] == [
        TOOL_CALL_REQUESTED_EVENT,
        TOOL_PERMISSION_DECIDED_EVENT,
        TOOL_CALL_REQUESTED_EVENT,
        TOOL_PERMISSION_DECIDED_EVENT,
    ]
    requests = [data for event_type, data in events if event_type == TOOL_CALL_REQUESTED_EVENT]
    permissions = [data for event_type, data in events if event_type == TOOL_PERMISSION_DECIDED_EVENT]
    assert [item["tool_call_id"] for item in requests] == ["call:readme", "call:package"]
    assert [item["target"] for item in requests] == ["README.md", "package.json"]
    assert [item["tool_call_id"] for item in permissions] == ["call:readme", "call:package"]
    assert [item["permission_decision_id"] for item in permissions] == [
        "permit:batch:call:readme",
        "permit:batch:call:package",
    ]


def test_tool_call_requested_is_the_only_live_main_tool_projection() -> None:
    frame = _frame(
        TOOL_CALL_REQUESTED_EVENT,
        {
            "tool_call_id": "call:read",
            "tool_lifecycle_id": "call:read",
            "tool_name": "read_file",
            "public_action_state": {"next_action": "读取 README.md"},
            "target": "README.md",
        },
    )

    assert frame["authority"] == PUBLIC_PROJECTION_AUTHORITY
    assert frame["op"] == "item_upsert"
    assert frame["slot"] == "current_action"
    assert frame["source_authority"] == "model"
    assert frame["main_visibility"] == "visible_live"
    assert frame["retention"] == "transient"
    assert frame["tool_call_id"] == "call:read"
    assert frame["tool_lifecycle_id"] == "call:read"
    assert frame["event_family"] == "tool_control"
    assert frame["channel"] == "control"


def test_path_inspection_tool_request_uses_user_facing_title() -> None:
    frame = _frame(
        TOOL_CALL_REQUESTED_EVENT,
        {
            "tool_call_id": "call:stat",
            "tool_lifecycle_id": "call:stat",
            "tool_name": "stat_path",
            "target": "mario.html",
        },
    )

    assert frame["title"] == "检查路径：mario.html"
    assert frame["text"] == "检查路径：mario.html"
    assert frame["tool_name"] == "stat_path"




def test_system_tool_batch_step_summary_stays_trace_only() -> None:
    frame = _frame(
        "runtime_step_summary",
        {
            "runtime_event_id": "event:tool-status",
            "step": "task_tool_batch_started:1",
            "status": "running",
            "presentation_source": "system.tool_call_status",
            "summary": "执行 2 个工具调用：读取文件 README.md、读取文件 package.json。",
        },
    )

    assert frame["op"] == "item_upsert"
    assert frame["slot"] == "trace"
    assert frame["source_authority"] == "runtime"
    assert frame["main_visibility"] == "hidden"
    assert frame["retention"] == "trace"


def test_runtime_status_is_always_hidden_trace() -> None:
    plain = _frame(
        "runtime_status",
        {
            "runtime_event_id": "event:runtime-status:hidden",
            "state": "running",
        },
    )
    marked = _frame(
        "runtime_status",
        {
            "runtime_event_id": "event:runtime-status:visible",
            "state": "running",
            "status_kind": "user_visible_runtime_status",
        },
    )

    for frame in (plain, marked):
        assert frame["slot"] == "trace"
        assert frame["main_visibility"] == "hidden"
        assert frame["retention"] == "trace"
        assert "status_kind" not in frame


def test_task_handoff_uses_canonical_completion_state_not_localized_reason() -> None:
    assert _is_task_executor_handoff_terminal(
        TURN_COMPLETED_EVENT,
        {
            "task_run_id": "taskrun:turn:session:test:1:abcd",
            "terminal_reason": "任务已进入执行流程",
            "completion_state": "task_executor_scheduled",
            "status": "completed",
        },
    ) is True


def test_task_model_wait_heartbeat_is_not_public_projection_input() -> None:
    events = _project_public_stream_event(
        "task_model_action_wait_heartbeat",
        {
            "event": {
                "event_id": "event:model-wait",
                "offset": 12,
                "payload": {
                    "task_run_id": "taskrun:wait",
                    "step": "task_model_action_waiting:1",
                    "status": "running",
                    "presentation_source": "runtime.model_wait",
                    "status_kind": "model_wait_placeholder",
                },
                "refs": {"task_run_ref": "taskrun:wait"},
            },
        },
    )

    assert events == []


def test_stream_recovery_projects_status_contract_without_body_or_detail() -> None:
    events = _project_public_stream_event(
        "stream_recovery",
        {
            "status": "started",
            "reason": "partial_stream_error",
            "detail": "provider socket reset",
            "stream_ref": "modelreq:test",
            "partial_utf8_bytes": 18,
            "recovery_mode": "continue_from_visible_prefix",
        },
    )

    assert [event_type for event_type, _ in events] == ["stream_recovery"]
    data = events[0][1]
    assert data["status"] == "started"
    assert data["reason"] == "partial_stream_error"
    assert data["recovery_mode"] == "continue_from_visible_prefix"
    assert data["partial_utf8_bytes"] == 18
    assert "detail" not in data
    assert "public_projection_frame" not in data


def test_model_wait_runtime_status_fails_closed_as_hidden_trace_if_seen() -> None:
    frame = _frame(
        "runtime_status",
        {
            "task_run_id": "taskrun:wait",
            "item_id": "model-wait:taskrun:wait",
            "title": "正在思考",
            "presentation_source": "runtime.model_wait",
            "status_kind": "model_wait_placeholder",
            "source_task_event_type": "task_model_action_wait_heartbeat",
            "runtime_event_id": "event:model-wait",
        },
    )

    assert frame["slot"] == "trace"
    assert frame["main_visibility"] == "hidden"
    assert frame["retention"] == "trace"
    assert frame["source_authority"] == "runtime"


def test_lifecycle_does_not_coalesce_non_wait_runtime_status() -> None:
    lifecycle = ProjectionLifecycleState()
    status = {
        "task_run_id": "taskrun:stage",
        "status": "running",
        "title": "正在读取项目结构",
        "status_kind": "user_visible_runtime_status",
        "runtime_event_id": "event:status:1",
    }

    assert lifecycle.should_emit_public_event("runtime_status", status) is True
    assert lifecycle.should_emit_public_event("runtime_status", {**status, "runtime_event_id": "event:status:2"}) is True


def test_chat_bridge_rejects_model_wait_placeholder_before_append_and_mark_event() -> None:
    registry = _RegistrySpy()
    replay = _ReplaySpy()
    lifecycle = ProjectionLifecycleState()
    run = RuntimeRun(
        stream_run_id="strun:test",
        session_id="session:test",
        event_log_id="chatrun:test",
        root_request_ref="chatreq:test",
        status="running",
        created_at=1.0,
        updated_at=1.0,
    )
    wait_status = {
        "task_run_id": "taskrun:wait",
        "turn_id": "turn:test",
        "turn_run_id": "turnrun:test",
        "item_id": "model-wait:taskrun:wait",
        "status": "running",
        "presentation_source": "runtime.model_wait",
        "status_kind": "model_wait_placeholder",
        "source_task_event_type": "task_model_action_wait_heartbeat",
    }

    current = _append_chat_public_event(
        registry=registry,
        replay=replay,
        current=run,
        public_event_type="runtime_status",
        data={**wait_status, "runtime_event_id": "event:model-wait:1"},
        session_id="session:test",
        projection_lifecycle=lifecycle,
        runtime_task_run_id="taskrun:wait",
        runtime_turn_run_id="turnrun:test",
        runtime_active_turn_id="turn:test",
    )

    assert current is run
    assert replay.append_public_event_calls == []
    assert registry.mark_event_calls == []


def test_protocol_repair_step_summary_stays_trace_only_without_public_surface() -> None:
    frame = _frame(
        "runtime_step_summary",
        {
            "runtime_event_id": "event:runtime-repair",
            "source_task_event_offset": 14,
            "task_run_id": "taskrun:repair",
            "step": "model_action_protocol_repair_required:1",
            "status": "running",
            "presentation_source": "runtime.protocol_repair",
            "summary": "当前步骤输出格式不完整，正在自动修正后继续。",
            "current_judgment": "public_response_required, public_progress_note_required",
        },
    )

    assert frame["op"] == "item_upsert"
    assert frame["slot"] == "trace"
    assert frame["source_authority"] == "runtime"
    assert frame["main_visibility"] == "hidden"
    assert frame["retention"] == "trace"
    assert "status_kind" not in frame
    assert not frame.get("title")
    assert not frame.get("text")
    assert not frame.get("detail")
    assert "当前步骤输出格式不完整" not in str(frame)
    assert "public_response_required" not in str(frame)
    assert frame["slot"] != "body"


def test_assistant_final_and_protocol_feedback_projection_do_not_cross_body_channel() -> None:
    assistant_events = _project_public_stream_event(
        ASSISTANT_TEXT_FINAL_EVENT,
        {
            "content": "OCR 已读取题目，下面给出完整解法。",
            "turn_run_id": "turnrun:test",
            "terminal_reason": "assistant_message",
            "answer_source": "harness.single_agent_turn",
            "answer_channel": "conversation",
        },
    )
    protocol_events = _project_public_stream_event(
        "turn_runtime_control_signal_observed",
        {
            "event": {
                "event_id": "event:protocol",
                "payload": {
                    "runtime_control_signal": {
                        "signal_kind": "model_protocol_violation",
                        "protocol_error": {"code": "single_agent_turn_invalid_json_action"},
                    }
                },
                "refs": {"turn_run_ref": "turnrun:test"},
            }
        },
    )

    assert [event_type for event_type, _ in assistant_events] == [ASSISTANT_TEXT_FINAL_EVENT]
    assert len(protocol_events) == 1
    body_frame = project_public_projection_event(
        assistant_events[0][0],
        assistant_events[0][1],
        session_id="session:test",
        sequence=1,
    )["public_projection_frame"]
    protocol_frame = project_public_projection_event(
        protocol_events[0][0],
        protocol_events[0][1],
        session_id="session:test",
        sequence=2,
    )["public_projection_frame"]

    assert body_frame["op"] == "body_finalize"
    assert body_frame["slot"] == "body"
    assert body_frame["main_visibility"] == "visible_final"
    assert body_frame["text"] == "OCR 已读取题目，下面给出完整解法。"
    assert protocol_frame["slot"] == "trace"
    assert protocol_frame["main_visibility"] == "hidden"
    assert "OCR 已读取题目" not in str(protocol_frame)


def test_runtime_control_observation_public_replay_keeps_only_signal_index() -> None:
    for event_type in ("turn_runtime_control_signal_observed", "task_runtime_control_signal_observed"):
        run = RuntimeRun(
            stream_run_id=f"strun:{event_type}",
            session_id="session:test",
            event_log_id=f"chatrun:{event_type}",
            root_request_ref="chatreq:test",
            status="running",
            created_at=1.0,
            updated_at=1.0,
            latest_event_offset=-1,
        )
        registry = _RegistrySpy()
        replay = _ReplaySpy()

        _append_chat_public_event(
            registry=registry,
            replay=replay,
            current=run,
            public_event_type=event_type,
            data={
                "runtime_event_id": f"rtevt:{event_type}:1",
                "turn_run_id": "turnrun:test",
                "task_run_id": "taskrun:test",
                "runtime_control_signal": {
                    "runtime_control_signal_ref": "rtsig:protocol",
                    "signal_kind": "model_protocol_violation",
                    "protocol_error": {
                        "code": "single_agent_turn_invalid_json_action",
                        "raw_model_output": "{\"action_type\":\"tool_call\",\"args\":{\"secret\":\"runtime-private\"}}",
                    },
                    "closeout_instruction": "Do not expose this internal repair prompt.",
                },
            },
            session_id="session:test",
            projection_lifecycle=ProjectionLifecycleState(),
        )

        replay_data = replay.append_public_event_calls[0]["data"]
        signal = replay_data["runtime_control_signal"]
        frame = replay_data["public_projection_frame"]

        assert signal == {
            "runtime_control_signal_ref": "rtsig:protocol",
            "signal_kind": "model_protocol_violation",
        }
        assert "protocol_error" not in str(replay_data)
        assert "closeout_instruction" not in str(replay_data)
        assert frame["slot"] == "trace"
        assert frame["main_visibility"] == "hidden"


def test_replay_read_path_rejects_noncanonical_projection_frame_and_sanitizes_control_signal() -> None:
    run = RuntimeRun(
        stream_run_id="strun:legacy",
        session_id="session:test",
        event_log_id="chatrun:legacy",
        root_request_ref="chatreq:test",
        status="running",
        created_at=1.0,
        updated_at=1.0,
        latest_event_offset=0,
    )
    event = RuntimeEvent(
        event_id="rtevt:legacy:0",
        run_id="chatrun:legacy",
        event_type="chat_stream_event",
        offset=0,
        created_at=1.0,
        payload={
            "stream_run_id": "strun:legacy",
            "public_event_type": "turn_runtime_control_signal_observed",
            "terminal": False,
            "data": {
                "turn_run_id": "turnrun:test",
                "runtime_control_signal": {
                    "runtime_control_signal_ref": "rtsig:protocol",
                    "signal_kind": "model_protocol_violation",
                    "protocol_error": {"raw_model_output": "private model output"},
                    "closeout_instruction": "private closeout instruction",
                },
                "public_projection_frame": {
                    "op": "item_upsert",
                    "slot": "status",
                    "main_visibility": "visible_live",
                    "retention": "transient",
                    "title": "private noncanonical title",
                    "detail": "private noncanonical detail",
                },
            },
        },
        refs={},
    )
    service = RuntimeStreamReplayService(SimpleNamespace(list_events=lambda _run_id: [event]))

    envelope = service.to_public_envelope(run, event)
    records = service.list_public_event_records(run)

    assert envelope["data"]["runtime_control_signal"] == {
        "runtime_control_signal_ref": "rtsig:protocol",
        "signal_kind": "model_protocol_violation",
    }
    assert records[0]["data"]["runtime_control_signal"] == envelope["data"]["runtime_control_signal"]
    assert envelope["public_projection_frame"] == {}
    assert "public_projection_frame" not in envelope["data"]
    assert records[0]["public_projection_frame"] == {}
    assert "public_projection_frame" not in records[0]["data"]
    assert "protocol_error" not in str(envelope)
    assert "closeout_instruction" not in str(envelope)
    assert "private noncanonical" not in str(envelope)
    assert "private model output" not in str(records)
    assert "private closeout instruction" not in str(records)


def test_runtime_step_summary_never_directly_projects_as_assistant_body() -> None:
    frame = _frame(
        "runtime_step_summary",
        {
            "runtime_event_id": "event:stage:1",
            "source_task_event_offset": 10,
            "task_run_id": "taskrun:stage",
            "step": "model_action_received:1",
            "status": "running",
            "presentation_source": "model_action.current_judgment",
            "current_judgment": "已确认目标文件完整可用。",
        },
    )

    assert frame["op"] == "item_upsert"
    assert frame["slot"] == "trace"
    assert frame["event_family"] == "status_trace"
    assert frame["channel"] == "status"
    assert frame["source_authority"] == "runtime"
    assert frame["main_visibility"] == "hidden"


def test_assistant_public_feedback_stream_event_projects_as_body_frame() -> None:
    events = _project_public_stream_event(
        ASSISTANT_PUBLIC_FEEDBACK_EVENT,
        {
            "runtime_event_id": "event:stage:1",
            "source_task_event_offset": 10,
            "task_run_id": "taskrun:stage",
            "step": "model_action_received:1",
            "status": "running",
            "presentation_source": "model_action.current_judgment",
            "current_judgment": "已确认目标文件完整可用。",
        },
    )
    assert [event_type for event_type, _ in events] == [ASSISTANT_PUBLIC_FEEDBACK_EVENT]


def test_model_action_step_summary_stays_runtime_summary_not_assistant_feedback() -> None:
    events = _project_public_stream_event(
        "runtime_step_summary",
        {
            "runtime_event_id": "event:stage:1",
            "source_task_event_offset": 10,
            "task_run_id": "taskrun:stage",
            "step": "model_action_received:1",
            "status": "running",
            "presentation_source": "model_action.current_judgment",
            "current_judgment": "已确认目标文件完整可用。",
        },
    )
    assert [event_type for event_type, _ in events] == ["runtime_step_summary"]


def test_assistant_public_feedback_projects_as_body_frame() -> None:
    events = _project_public_stream_event(
        ASSISTANT_PUBLIC_FEEDBACK_EVENT,
        {
            "runtime_event_id": "event:stage:1",
            "source_task_event_offset": 10,
            "task_run_id": "taskrun:stage",
            "step": "model_action_received:1",
            "status": "running",
            "presentation_source": "model_action.current_judgment",
            "current_judgment": "已确认目标文件完整可用。",
        },
    )

    frame = project_public_projection_event(
        events[0][0],
        events[0][1],
        session_id="session:test",
        sequence=1,
    )["public_projection_frame"]

    assert frame["source_event_type"] == ASSISTANT_PUBLIC_FEEDBACK_EVENT
    assert frame["op"] == "body_append"
    assert frame["slot"] == "body"
    assert frame["event_family"] == "assistant_body"
    assert frame["channel"] == "body"
    assert frame["source_authority"] == "model"
    assert frame["main_visibility"] == "visible_live"
    assert frame["text"] == "已确认目标文件完整可用。"


def test_assistant_public_feedback_body_is_not_truncated_to_title_preview() -> None:
    full_feedback = (
        "现在我已完全读取了整个主题系统。以下是完整的审查结论和修复方案。\n\n"
        "## 审查结论\n\n"
        "主题系统由主题变量层和工作台外壳层组成。这里故意写一段很长的反馈，"
        "超过投影标题预览的长度，正文通道仍然必须保持完整，因为这是 agent "
        "已经公开输出给用户的反馈正文，不是状态标题，也不是工具摘要。"
        "为了覆盖真实事故，还要继续补充足够长的分析段落，让标题预览必然被缩短，"
        "同时正文里的最后一段、最后一个标记和换行都必须原样保留下来。\n\n"
        "TAIL-MUST-SURVIVE"
    )

    frame = project_public_projection_event(
        ASSISTANT_PUBLIC_FEEDBACK_EVENT,
        {
            "runtime_event_id": "event:stage:long-feedback",
            "source_task_event_offset": 10,
            "task_run_id": "taskrun:stage",
            "step": "model_action_public_feedback",
            "status": "running",
            "presentation_source": "model_action.assistant_content_preamble",
            "public_progress_note": full_feedback,
            "feedback_identity": "feedback:long",
        },
        session_id="session:test",
        sequence=1,
    )["public_projection_frame"]

    assert frame["source_event_type"] == ASSISTANT_PUBLIC_FEEDBACK_EVENT
    assert frame["lossless"] is True
    assert frame["text"] == full_feedback
    assert "TAIL-MUST-SURVIVE" in frame["text"]
    assert frame["title"].endswith("...")


def test_no_public_event_feedback_projects_only_thinking_text() -> None:
    events = _project_public_stream_event(
        ASSISTANT_PUBLIC_FEEDBACK_EVENT,
        {
            "runtime_event_id": "event:thinking:1",
            "task_run_id": "taskrun:thinking",
            "step": "no_public_event_thinking:1",
            "status": "running",
            "summary": "正在思考。",
            "public_progress_note": "正在思考。",
            "presentation_source": "runtime.no_public_event",
            "feedback_identity": "no-public-event-thinking:taskrun:thinking:1",
        },
    )

    frame = project_public_projection_event(
        events[0][0],
        events[0][1],
        session_id="session:test",
        sequence=1,
    )["public_projection_frame"]

    assert frame["source_event_type"] == ASSISTANT_PUBLIC_FEEDBACK_EVENT
    assert frame["text"] == "正在思考。"
    assert "action" not in frame["text"].lower()
    assert "tool" not in frame["text"].lower()
    replay_frame = project_public_projection_event(
        events[0][0],
        events[0][1],
        session_id="session:test",
        sequence=2,
    )["public_projection_frame"]
    assert replay_frame["item_id"] == frame["item_id"]


def test_model_action_feedback_identity_keeps_replayed_body_frame_stable() -> None:
    lifecycle = ProjectionLifecycleState()
    anchor = {
        "session_id": "session:test",
        "turn_id": "turn:test",
        "turn_run_id": "turnrun:test",
        "task_run_id": "taskrun:test",
    }
    first = {
        "public_anchor": anchor,
        "runtime_event_id": "event:model-feedback:1",
        "source_task_event_offset": 10,
        "task_run_id": "taskrun:test",
        "step": "model_action_received:1",
        "presentation_source": "model_action.public_progress_note",
        "feedback_identity": "request:model-feedback:1",
        "public_progress_note": "用户表达感谢，直接回复即可。",
        "current_judgment": "用户表达感谢，当前对话自然收口。",
        "next_action": "等待用户下一步需求。",
        "status": "running",
    }
    second = {
        **first,
        "runtime_event_id": "event:model-feedback:2",
        "source_task_event_offset": 11,
    }

    assert lifecycle.should_emit_public_event(ASSISTANT_PUBLIC_FEEDBACK_EVENT, first) is True
    first_frame = project_public_projection_event(
        ASSISTANT_PUBLIC_FEEDBACK_EVENT,
        first,
        session_id="session:test",
        sequence=1,
        lifecycle_state=lifecycle,
    )["public_projection_frame"]
    assert lifecycle.should_emit_public_event(ASSISTANT_PUBLIC_FEEDBACK_EVENT, second) is True
    second_frame = project_public_projection_event(
        ASSISTANT_PUBLIC_FEEDBACK_EVENT,
        second,
        session_id="session:test",
        sequence=2,
        lifecycle_state=lifecycle,
    )["public_projection_frame"]

    assert first_frame["source_event_type"] == ASSISTANT_PUBLIC_FEEDBACK_EVENT
    assert first_frame["op"] == "body_append"
    assert first_frame["slot"] == "body"
    assert first_frame["source_authority"] == "model"
    assert first_frame["text"] == "用户表达感谢，直接回复即可。\n\n用户表达感谢，当前对话自然收口。"
    assert second_frame["op"] == "body_append"
    assert second_frame["slot"] == "body"
    assert second_frame["source_authority"] == "model"
    assert second_frame["text"] == first_frame["text"]
    assert second_frame["item_id"] == first_frame["item_id"]
    assert second_frame["frame_id"] == first_frame["frame_id"]


def test_raw_tool_started_without_permission_is_hidden_protocol_diagnostic() -> None:
    frame = _frame(
        TOOL_ITEM_STARTED_EVENT,
        {"tool_name": "read_file", "runtime_event_id": "event:tool-start"},
    )

    assert frame["op"] == "item_upsert"
    assert frame["slot"] == "trace"
    assert frame["source_authority"] == "system"
    assert frame["main_visibility"] == "hidden"
    assert frame["diagnostics"]["code"] == "tool_started_without_request_or_permission"


def test_successful_tool_completed_retires_current_action_to_trace() -> None:
    frame = _frame(
        TOOL_ITEM_COMPLETED_EVENT,
        {
            "tool_call_id": "call:read",
            "permission_decision_id": "permit:read",
            "tool_name": "read_file",
            "state": "done",
            "observation": "读取完成。",
        },
    )

    assert frame["op"] == "item_retire"
    assert frame["slot"] == "trace"
    assert frame["main_visibility"] == "trace_only"
    assert frame["tool_call_id"] == "call:read"
    assert "title" not in frame
    assert "text" not in frame


def test_failed_tool_completed_is_pinned_until_resolved() -> None:
    frame = _frame(
        TOOL_ITEM_COMPLETED_EVENT,
        {
            "tool_call_id": "call:read",
            "permission_decision_id": "permit:read",
            "tool_name": "read_file",
            "state": "failed",
            "error": "文件不存在。",
        },
    )

    assert frame["op"] == "item_upsert"
    assert frame["slot"] == "pinned"
    assert frame["main_visibility"] == "pinned"
    assert frame["retention"] == "pinned_until_resolved"
    assert frame["pin_reason"] == "failed"


def test_failed_runtime_context_rehydration_tool_retires_any_visible_card() -> None:
    frame = _frame(
        TOOL_ITEM_COMPLETED_EVENT,
        {
            "tool_call_id": "call:rehydrate",
            "permission_decision_id": "permit:rehydrate",
            "tool_name": "read_persisted_tool_result",
            "state": "failed",
            "error": "Read persisted tool result failed: hidden path",
        },
    )

    assert frame["op"] == "item_retire"
    assert frame["slot"] == "trace"
    assert frame["main_visibility"] == "hidden"
    assert frame["retention"] == "trace"
    assert frame["tool_call_id"] == "call:rehydrate"


def test_successful_turn_completed_is_hidden_trace_only() -> None:
    frame = _frame(TURN_COMPLETED_EVENT, {"status": "completed", "turn_run_id": "turnrun:test"})

    assert frame["op"] == "item_upsert"
    assert frame["slot"] == "trace"
    assert frame["main_visibility"] == "hidden"
    assert "commit" not in frame
    assert "text" not in frame


def test_task_bridge_terminal_authority_rejects_waiting_as_chat_completion() -> None:
    assert TASK_BRIDGE_TERMINAL_EVENT_TYPES == {"task_run_lifecycle_finished", "task_run_terminal_observed"}
    for status in ("waiting_executor", "waiting_user", "waiting_approval"):
        assert _public_turn_status_for_task_status(status) != "completed"


def test_agent_contract_feedback_turn_completed_stays_hidden_trace_only() -> None:
    frame = _frame(
        TURN_COMPLETED_EVENT,
        {
            "status": "failed",
            "turn_run_id": "turnrun:test",
            "terminal_reason": "agent_contract_feedback_required",
            "error_summary": "内部纠错观察",
        },
    )

    assert frame["op"] == "item_upsert"
    assert frame["slot"] == "trace"
    assert frame["source_authority"] == "runtime"
    assert frame["main_visibility"] == "hidden"
    assert frame["retention"] == "trace"
    assert "status_kind" not in frame
    assert "title" not in frame
    assert "text" not in frame
    assert frame["slot"] != "body"


def test_protocol_contract_failure_turn_completed_stays_hidden_trace_only() -> None:
    frame = _frame(
        TURN_COMPLETED_EVENT,
        {
            "status": "failed",
            "turn_run_id": "turnrun:test",
            "terminal_reason": "task_contract_invalid",
            "error_summary": "处理失败",
        },
    )

    assert frame["op"] == "item_upsert"
    assert frame["slot"] == "trace"
    assert frame["source_authority"] == "runtime"
    assert frame["main_visibility"] == "hidden"
    assert frame["retention"] == "trace"
    assert "status_kind" not in frame
    assert "title" not in frame
    assert "text" not in frame


def test_runtime_transport_turn_completed_stays_hidden_trace_only() -> None:
    frame = _frame(
        TURN_COMPLETED_EVENT,
        {
            "status": "stopped",
            "turn_run_id": "turnrun:test",
            "terminal_reason": "runtime_process_restarted",
            "completion_state": "interrupted",
            "orphaned_by": "single_agent_runtime_host.startup_reconciliation",
        },
    )

    assert frame["op"] == "item_upsert"
    assert frame["slot"] == "trace"
    assert frame["source_authority"] == "runtime"
    assert frame["main_visibility"] == "hidden"
    assert frame["retention"] == "trace"
    assert "status_kind" not in frame
    assert "title" not in frame
    assert "text" not in frame


def test_commit_ack_is_hidden_commit_authority() -> None:
    frame = _frame(
        SESSION_OUTPUT_COMMIT_ACK_EVENT,
        {
            "state": "committed",
            "message_ref": "history-message:turn:test:assistant",
            "content_sha256": "sha256:body",
            "event_offset": 12,
        },
    )

    assert frame["op"] == "commit_ack"
    assert frame["main_visibility"] == "hidden"
    assert frame["commit"]["state"] == "committed"
    assert frame["commit"]["content_sha256"] == "sha256:body"


def test_commit_failed_is_recovery_event_not_body() -> None:
    frame = _frame(
        SESSION_OUTPUT_COMMIT_FAILED_EVENT,
        {"state": "failed", "reason": "history write failed", "event_offset": 12},
    )

    assert frame["op"] == "item_upsert"
    assert frame["slot"] == "status"
    assert frame["main_visibility"] == "visible_live"
    assert frame["retention"] == "final"
    assert frame["status_kind"] == "recovery_event"
    assert frame["commit"]["state"] == "failed"
    assert frame["slot"] != "body"
    rendered = f"{frame.get('title', '')} {frame.get('text', '')} {frame.get('detail', '')}"
    assert "系统已" not in rendered


def test_private_paths_do_not_project_as_public_text() -> None:
    private_path = (
        "backend/mythical-agent/sessions/session-123/environments/coding/vibe-workspace/"
        "runtime_state/dynamic_context/replacements/replacement_e21050df8baca858bdde6a4d.json"
    )

    assert public_text(private_path) == ""
    events = _project_public_stream_event(
        "model_action_admission",
        {
            "event": {
                "event_id": "event:admission:private-path",
                "payload": {
                    "turn_id": "turn:test",
                    "model_action_request": {
                        "request_id": "request:read-private",
                        "action_type": "tool_call",
                        "tool_call": {
                            "id": "call:read-private",
                            "tool_name": "read_file",
                            "args": {"path": private_path},
                        },
                    },
                    "admission": {"decision": "allow"},
                },
                "refs": {"turn_run_ref": "turnrun:turn:test:private"},
            },
        },
    )

    visible = str(events)
    assert "replacement_e21050df8baca858bdde6a4d" not in visible
    assert "target" not in events[0][1]
    assert "arguments_preview" not in events[0][1]


def test_tool_observation_promotes_real_tool_call_id_for_public_completion() -> None:
    observation = ToolObservation(
        observation_id="toolobs:read:1",
        invocation_id="toolinvoke:turnrun:1:read_file:call:read",
        caller_kind="agent_turn",
        caller_ref="turnrun:turn:test:1",
        tool_name="read_file",
        operation_id="op.read_file",
        status="ok",
        text="读取完成。",
        result_envelope={"tool_name": "read_file", "tool_call_id": "call:read", "text": "读取完成。"},
    )

    assert observation.to_dict()["tool_call_id"] == "call:read"


def test_tool_observation_does_not_promote_diagnostics_action_request_tool_call_id() -> None:
    observation = ToolObservation(
        observation_id="toolobs:read:diagnostic-shadow",
        invocation_id="toolinvoke:turnrun:1:read_file:shadow",
        caller_kind="agent_turn",
        caller_ref="turnrun:turn:test:1",
        tool_name="read_file",
        operation_id="op.read_file",
        status="ok",
        text="读取完成。",
        diagnostics={
            "action_request": {
                "tool_call": {
                    "id": "call:diagnostic-shadow",
                    "name": "read_file",
                    "args": {"path": "README.md"},
                }
            }
        },
    )

    payload = observation.to_dict()
    assert "tool_call_id" not in payload
    assert payload["diagnostics"]["action_request"]["tool_call"]["id"] == "call:diagnostic-shadow"


def test_task_tool_observation_wrapper_projects_inner_identity_without_diagnostics_args() -> None:
    events = _project_public_stream_event(
        "task_tool_observation_recorded",
        {
            "event": {
                "event_id": "event:tool-observation",
                "payload": {
                    "observation": {
                        "task_run_id": "taskrun:turn:test:1",
                        "observation_type": "tool_result",
                        "request_ref": "request:read",
                            "payload": {
                                "caller_ref": "turnrun:turn:test:1",
                                "task_run_id": "taskrun:turn:test:1",
                                "invocation_id": "toolinv:read:1",
                                "tool_name": "read_file",
                                "status": "ok",
                                "text": "读取完成。",
                            "tool_call_id": "call:read",
                            "result_envelope": {
                                "tool_name": "read_file",
                                "tool_call_id": "call:read",
                                "text": "读取完成。",
                            },
                            "execution_receipt": {
                                "tool_call_id": "call:read",
                                "admission_ref": "admission:request:read",
                            },
                            "diagnostics": {
                                "action_request": {
                                    "request_id": "request:read",
                                    "tool_call": {
                                        "id": "call:read",
                                        "tool_name": "read_file",
                                        "args": {
                                            "path": "backend/capability_system/capabilities/retrieval/parser_adapter.py",
                                            "line_count": 80,
                                        },
                                    },
                                }
                            },
                        },
                    }
                },
                "refs": {"turn_run_ref": "turnrun:turn:test:1", "task_run_ref": "taskrun:turn:test:1"},
            }
        },
    )

    assert [event_type for event_type, _ in events] == [TOOL_ITEM_COMPLETED_EVENT]
    completed = events[0][1]
    assert completed["tool_call_id"] == "call:read"
    assert completed["tool_lifecycle_id"] == "toolinv:read:1"
    assert completed["permission_decision_id"] == "admission:request:read"
    assert completed["tool_name"] == "read_file"
    assert "target" not in completed
    assert "arguments_preview" not in completed


def test_tool_completion_does_not_promote_wrapper_tool_call_id_without_envelope_identity() -> None:
    events = _project_public_stream_event(
        "task_tool_observation_recorded",
        {
            "event": {
                "event_id": "event:tool-observation:wrapper-shadow",
                "payload": {
                    "observation": {
                        "task_run_id": "taskrun:turn:test:1",
                        "observation_type": "tool_result",
                        "request_ref": "request:read",
                        "payload": {
                            "caller_ref": "turnrun:turn:test:1",
                            "task_run_id": "taskrun:turn:test:1",
                            "invocation_id": "toolinv:read:wrapper-shadow",
                            "tool_name": "read_file",
                            "status": "ok",
                            "text": "读取完成。",
                            "tool_call_id": "call:wrapper-shadow",
                            "result_envelope": {
                                "tool_name": "read_file",
                                "text": "读取完成。",
                            },
                        },
                    }
                },
                "refs": {"turn_run_ref": "turnrun:turn:test:1", "task_run_ref": "taskrun:turn:test:1"},
            }
        },
    )

    assert events == []


def test_agent_todo_summary_ignores_envelope_metadata_before_text_payload() -> None:
    summary = _agent_todo_observation_summary(
        {"tool_name": "agent_todo"},
        result_envelope={
            "tool_name": "agent_todo",
            "structured_payload": {"truncated": False, "sandbox": {}},
            "text": (
                '{"status":"ok","plan_id":"agent-todo:test","active_item_id":"todo:1",'
                '"items":[{"todo_id":"todo:1","content":"修复 fps_game.html","status":"in_progress"}]}'
            ),
        },
    )

    assert summary == "任务清单：0/1 已完成，正在：修复 fps_game.html。"


def test_tool_completion_uses_request_ref_for_permission_identity() -> None:
    events = _project_public_stream_event(
        "task_tool_observation_recorded",
        {
            "event": {
                "event_id": "event:tool-observation:no-admission-ref",
                "payload": {
                    "observation": {
                        "task_run_id": "taskrun:turn:test:1",
                        "observation_type": "tool_result",
                        "request_ref": "request:read",
                            "payload": {
                                "caller_ref": "turnrun:turn:test:1",
                                "task_run_id": "taskrun:turn:test:1",
                                "invocation_id": "toolinv:read:request-ref",
                                "tool_name": "read_file",
                                "status": "ok",
                                "text": "读取完成。",
                            "tool_call_id": "call:read",
                            "result_envelope": {
                                "tool_name": "read_file",
                                "tool_call_id": "call:read",
                                "text": "读取完成。",
                            },
                        },
                    }
                },
                "refs": {"turn_run_ref": "turnrun:turn:test:1", "task_run_ref": "taskrun:turn:test:1"},
            }
        },
    )

    assert [event_type for event_type, _ in events] == [TOOL_ITEM_COMPLETED_EVENT]
    completed = events[0][1]
    assert completed["tool_call_id"] == "call:read"
    assert completed["tool_lifecycle_id"] == "toolinv:read:request-ref"
    assert completed["permission_decision_id"] == "admission:request:read"


def test_tool_failure_feedback_survives_completion_projection_detail() -> None:
    error_text = "Edit failed: old_text not found"
    events = _project_public_stream_event(
        "turn_tool_observation_recorded",
        {
            "event": {
                "event_id": "event:tool-observation:edit-failed",
                "payload": {
                    "tool_observation": {
                        "caller_ref": "turnrun:turn:test:1",
                        "task_run_id": "taskrun:turn:test:1",
                        "invocation_id": "toolinv:edit:1",
                        "tool_name": "edit_file",
                        "status": "error",
                        "text": error_text,
                        "tool_call_id": "call:edit",
                        "result_envelope": {
                            "tool_name": "edit_file",
                            "tool_call_id": "call:edit",
                            "text": error_text,
                        },
                        "execution_receipt": {
                            "tool_call_id": "call:edit",
                            "admission_ref": "admission:request:edit",
                            "error": error_text,
                        },
                    }
                },
                "refs": {"turn_run_ref": "turnrun:turn:test:1", "task_run_ref": "taskrun:turn:test:1"},
            }
        },
    )

    assert [event_type for event_type, _ in events] == [TOOL_ITEM_COMPLETED_EVENT]
    completed = events[0][1]
    assert completed["state"] == "error"
    assert completed["error"] == error_text
    assert completed["observation"] == error_text

    frame = project_public_projection_event(
        TOOL_ITEM_COMPLETED_EVENT,
        {
            **completed,
            "public_anchor": {
                "session_id": "session:test",
                "turn_id": "turn:test",
                "task_run_id": "taskrun:turn:test:1",
            },
        },
        session_id="session:test",
        sequence=1,
    )["public_projection_frame"]

    assert frame["op"] == "item_upsert"
    assert frame["slot"] == "pinned"
    assert frame["state"] == "failed"
    assert frame["detail"] == error_text


def test_agent_contract_feedback_required_is_not_public_stream_event() -> None:
    raw_event = {
        "event": {
            "event_id": "event:agent-contract-feedback",
            "payload": {
                "turn_id": "turn:test:feedback",
                "model_visible": True,
                "agent_contract_feedback": {
                    "signal_kind": "agent_contract_feedback_required",
                    "agent_feedback": "上一条输出没有进入会话，也不会展示给用户。",
                },
            },
        }
    }
    events = _project_public_stream_event("agent_contract_feedback_required", raw_event)

    assert events == []


def test_public_terminal_reason_names_agent_closeout_boundaries() -> None:
    assert _public_terminal_reason("agent_contract_feedback_required") == "状态已更新"
    assert _public_terminal_reason("tool_budget_exhausted") == "本轮工具预算已用完"
    assert _public_terminal_reason("single_turn_tool_iteration_limit") == "本轮工具预算已用完"
    assert _public_terminal_reason("single_agent_turn_empty_response") == "agent 未生成可发布回复"


def test_lifecycle_closes_completion_by_tool_call_id_even_when_completion_permission_ref_drifts() -> None:
    lifecycle = ProjectionLifecycleState()
    anchor = {
        "session_id": "session:test",
        "turn_id": "turn:test",
        "task_run_id": "taskrun:turn:test:1",
    }
    project_public_projection_event(
        TOOL_CALL_REQUESTED_EVENT,
        {
            "public_anchor": anchor,
            "event_offset": 1,
            "tool_call_id": "call:read",
            "tool_name": "read_file",
            "target": "backend/harness/graph/flow_edges.py",
            "arguments_preview": "path=backend/harness/graph/flow_edges.py, line_count=80",
        },
        session_id="session:test",
        sequence=1,
        lifecycle_state=lifecycle,
    )
    project_public_projection_event(
        TOOL_PERMISSION_DECIDED_EVENT,
        {
            "public_anchor": anchor,
            "event_offset": 2,
            "tool_call_id": "call:read",
            "permission_decision_id": "admission:request:read",
            "permission_decision": "allow",
        },
        session_id="session:test",
        sequence=2,
        lifecycle_state=lifecycle,
    )
    project_public_projection_event(
        TOOL_ITEM_STARTED_EVENT,
        {
            "public_anchor": anchor,
            "event_offset": 3,
            "tool_call_id": "call:read",
            "permission_decision_id": "admission:request:read",
            "tool_name": "read_file",
        },
        session_id="session:test",
        sequence=3,
        lifecycle_state=lifecycle,
    )

    frame = project_public_projection_event(
        TOOL_ITEM_COMPLETED_EVENT,
        {
            "public_anchor": anchor,
            "event_offset": 4,
            "tool_call_id": "call:read",
            "permission_decision_id": "admission:call:read",
            "tool_name": "read_file",
            "state": "done",
        },
        session_id="session:test",
        sequence=4,
        lifecycle_state=lifecycle,
    )["public_projection_frame"]

    assert frame["op"] == "item_retire"
    assert frame["tool_call_id"] == "call:read"
    assert frame["permission_decision_id"] == "admission:request:read"
    assert frame["tool_name"] == "read_file"
    assert frame["target"] == "backend/harness/graph/flow_edges.py"
    assert frame["arguments_preview"] == "path=backend/harness/graph/flow_edges.py, line_count=80"
    assert "diagnostics" not in frame
