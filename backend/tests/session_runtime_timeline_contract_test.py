from __future__ import annotations

from types import SimpleNamespace

from harness.runtime.projection.projector import project_public_projection_event
from harness.runtime.session_timeline import build_session_runtime_timeline
from runtime.output_stream.public_contract import (
    ASSISTANT_TEXT_FINAL_EVENT,
    SESSION_OUTPUT_COMMIT_ACK_EVENT,
    TOOL_CALL_REQUESTED_EVENT,
    TURN_COMPLETED_EVENT,
)


class _Event:
    def __init__(self, payload: dict) -> None:
        self._payload = dict(payload)

    def to_dict(self) -> dict:
        return dict(self._payload)


class _EventLog:
    def __init__(self, events_by_run: dict[str, list[dict]]) -> None:
        self.events_by_run = {
            run_id: [_Event(event) for event in events]
            for run_id, events in events_by_run.items()
        }

    def list_event_window(self, run_id: str, *, limit: int, include_payloads: bool = True) -> list[_Event]:
        return list(self.events_by_run.get(run_id, []))[-limit:]

    def estimated_event_count(self, run_id: str) -> int:
        return len(self.events_by_run.get(run_id, []))


class _StateIndex:
    def __init__(self, *, task_runs: list[SimpleNamespace], turn_runs: list[SimpleNamespace] | None = None) -> None:
        self._task_runs = list(task_runs)
        self._turn_runs = list(turn_runs or [])

    def list_session_task_runs(self, session_id: str) -> list[SimpleNamespace]:
        return [run for run in self._task_runs if run.session_id == session_id]

    def list_session_turn_runs(self, session_id: str) -> list[SimpleNamespace]:
        return [run for run in self._turn_runs if run.session_id == session_id]


class _RunRegistry:
    def __init__(self, runs: list[SimpleNamespace] | None = None) -> None:
        self._runs = list(runs or [])

    def list_session_runs(self, session_id: str) -> list[SimpleNamespace]:
        return [run for run in self._runs if run.session_id == session_id]


class _StreamReplay:
    def __init__(self, records_by_run: dict[str, list[dict]] | None = None) -> None:
        self.records_by_run = dict(records_by_run or {})

    def list_public_event_records(self, run: SimpleNamespace) -> list[dict]:
        return list(self.records_by_run.get(run.stream_run_id, []))


def _runtime_host(
    *,
    task_runs: list[SimpleNamespace],
    events_by_run: dict[str, list[dict]],
    turn_runs: list[SimpleNamespace] | None = None,
    stream_runs: list[SimpleNamespace] | None = None,
    public_events_by_stream_run: dict[str, list[dict]] | None = None,
):
    return SimpleNamespace(
        state_index=_StateIndex(task_runs=task_runs, turn_runs=turn_runs),
        event_log=_EventLog(events_by_run),
        run_registry=_RunRegistry(stream_runs),
        stream_replay=_StreamReplay(public_events_by_stream_run),
    )


def _public_ledger_record(
    public_event_type: str,
    data: dict,
    *,
    offset: int,
    session_id: str = "session-a",
    turn_id: str = "turn:session-a:1",
    stream_run_id: str = "strun:session-a:1",
    task_run_id: str = "taskrun:turn:session-a:1:abc",
    message_id: str = "history-message:turn:session-a:1:assistant",
) -> dict:
    payload = {
        **data,
        "public_anchor": {
            "session_id": session_id,
            "turn_id": turn_id,
            "stream_run_id": stream_run_id,
            "task_run_id": task_run_id,
            "message_id": message_id,
        },
    }
    frame = project_public_projection_event(
        public_event_type,
        payload,
        session_id=session_id,
        sequence=offset,
    )["public_projection_frame"]
    return {
        "stream_run_id": stream_run_id,
        "event_log_id": f"chatrun:{session_id}:1",
        "event_id": f"event:{offset}",
        "event_offset": offset,
        "created_at": float(offset),
        "public_event_type": public_event_type,
        "terminal": public_event_type == SESSION_OUTPUT_COMMIT_ACK_EVENT,
        "data": {**data, "public_projection_frame": frame},
        "public_projection_frame": frame,
    }


def test_session_runtime_timeline_closed_task_uses_public_ledger_closeout_surface() -> None:
    task_run_id = "taskrun:turn:session-a:1:abc"
    stream_run_id = "strun:session-a:1"
    stream_run = SimpleNamespace(
        stream_run_id=stream_run_id,
        session_id="session-a",
        event_log_id="chatrun:session-a:1",
        status="completed",
        diagnostics={"active_turn_id": "turn:session-a:1", "runtime_task_run_id": task_run_id},
        created_at=1.0,
        updated_at=3.0,
    )
    runtime_host = _runtime_host(
        task_runs=[],
        events_by_run={},
        stream_runs=[stream_run],
        public_events_by_stream_run={
            stream_run_id: [
                _public_ledger_record(
                    TOOL_CALL_REQUESTED_EVENT,
                    {"tool_call_id": "call:read", "tool_name": "read_file", "target": "README.md"},
                    offset=1,
                    stream_run_id=stream_run_id,
                    task_run_id=task_run_id,
                ),
                _public_ledger_record(
                    ASSISTANT_TEXT_FINAL_EVENT,
                    {"content": "done"},
                    offset=2,
                    stream_run_id=stream_run_id,
                    task_run_id=task_run_id,
                ),
                _public_ledger_record(
                    SESSION_OUTPUT_COMMIT_ACK_EVENT,
                    {"state": "committed", "content_sha256": "sha256:final"},
                    offset=3,
                    stream_run_id=stream_run_id,
                    task_run_id=task_run_id,
                ),
            ]
        },
    )

    timeline = build_session_runtime_timeline(
        session_id="session-a",
        history={
            "messages": [
                {"role": "user", "content": "run", "turn_id": "turn:session-a:1"},
                {"role": "assistant", "content": "done", "turn_id": "turn:session-a:1"},
            ]
        },
        runtime_host=runtime_host,
    )

    attachment = timeline["runtime_attachments"][0]
    assert attachment["stream_run_id"] == stream_run_id
    assert attachment["event_log_id"] == "chatrun:session-a:1"
    assert attachment["display_state"] == "task_closed"
    assert attachment["main_chat_surface"] == "closeout_summary"
    assert attachment["closeout_summary"] == "done"
    assert attachment["tool_event_count"] == 1
    assert attachment["log_ref"] == "chatrun:session-a:1"
    assert attachment["projection_anchor"]["anchor_turn_id"] == "turn:session-a:1"
    assert attachment["projection_anchor"]["anchor_message_id"] == "history-message:turn:session-a:1:assistant"
    assert [frame["event_family"] for frame in attachment["public_projection_frames"]] == [
        "tool_control",
        "assistant_body",
        "runtime_commit",
    ]
    assert "public_timeline" not in attachment
    assert "task_projection" not in attachment
    assert "public_projection_status" not in attachment


def test_session_runtime_timeline_running_task_replays_live_timeline_surface() -> None:
    task_run_id = "taskrun:turn:session-a:1:abc"
    stream_run_id = "strun:session-a:1"
    stream_run = SimpleNamespace(
        stream_run_id=stream_run_id,
        session_id="session-a",
        event_log_id="chatrun:session-a:1",
        status="running",
        diagnostics={"active_turn_id": "turn:session-a:1", "runtime_task_run_id": task_run_id},
        created_at=1.0,
        updated_at=2.0,
    )
    runtime_host = _runtime_host(
        task_runs=[],
        events_by_run={},
        stream_runs=[stream_run],
        public_events_by_stream_run={
            stream_run_id: [
                _public_ledger_record(
                    TOOL_CALL_REQUESTED_EVENT,
                    {"tool_call_id": "call:read", "tool_name": "read_file", "target": "README.md"},
                    offset=1,
                    stream_run_id=stream_run_id,
                    task_run_id=task_run_id,
                )
            ]
        },
    )

    timeline = build_session_runtime_timeline(
        session_id="session-a",
        history={"messages": [{"role": "user", "content": "run", "turn_id": "turn:session-a:1"}]},
        runtime_host=runtime_host,
    )

    attachment = timeline["runtime_attachments"][0]
    assert attachment["display_state"] == "task_live"
    assert attachment["main_chat_surface"] == "live_timeline"
    assert attachment["public_projection_frames"][0]["tool_call_id"] == "call:read"
    assert attachment["tool_event_count"] == 1


def test_session_runtime_timeline_restores_model_feedback_identity_for_step_summaries() -> None:
    task_run_id = "taskrun:turn:session-a:1:abc"
    stream_run_id = "strun:session-a:1"
    task_run = SimpleNamespace(
        task_run_id=task_run_id,
        session_id="session-a",
        task_id="task:turn:session-a:1",
        status="running",
        diagnostics={"active_turn_id": "turn:session-a:1", "runtime_task_run_id": task_run_id},
        created_at=1.0,
        updated_at=2.0,
    )
    stream_run = SimpleNamespace(
        stream_run_id=stream_run_id,
        session_id="session-a",
        event_log_id="chatrun:session-a:1",
        status="running",
        diagnostics={"active_turn_id": "turn:session-a:1", "runtime_task_run_id": task_run_id},
        created_at=1.0,
        updated_at=2.0,
    )
    runtime_host = _runtime_host(
        task_runs=[task_run],
        events_by_run={
            task_run_id: [
                {
                    "event_id": "event:step-summary",
                    "event_type": "step_summary_recorded",
                    "offset": 7,
                    "created_at": 7.0,
                    "payload": {
                        "step": "model_action_received:1",
                        "status": "running",
                        "summary": "我先核对当前正文。",
                        "public_progress_note": "我先核对当前正文。",
                        "presentation_source": "model_action.public_progress_note",
                    },
                    "refs": {
                        "task_run_ref": task_run_id,
                        "action_request_ref": "request:feedback:1",
                    },
                }
            ],
        },
        stream_runs=[stream_run],
        public_events_by_stream_run={
            stream_run_id: [
                _public_ledger_record(
                    "runtime_step_summary",
                    {
                        "summary": "我先核对当前正文。",
                        "public_progress_note": "我先核对当前正文。",
                        "presentation_source": "model_action.public_progress_note",
                        "feedback_identity": "request:feedback:1",
                    },
                    offset=7,
                    stream_run_id=stream_run_id,
                    task_run_id=task_run_id,
                ),
            ]
        },
    )

    timeline = build_session_runtime_timeline(
        session_id="session-a",
        history={"messages": [{"role": "user", "content": "run", "turn_id": "turn:session-a:1"}]},
        runtime_host=runtime_host,
    )

    task_attachment = next(item for item in timeline["runtime_attachments"] if item.get("task_run_id") == task_run_id)
    stream_attachment = next(item for item in timeline["runtime_attachments"] if item.get("stream_run_id") == stream_run_id)
    assert task_attachment["public_projection_frames"][0]["item_id"] == stream_attachment["public_projection_frames"][0]["item_id"]
    assert task_attachment["public_projection_frames"][0]["frame_id"] == stream_attachment["public_projection_frames"][0]["frame_id"]


def test_session_runtime_timeline_sanitizes_legacy_protocol_repair_frames() -> None:
    task_run_id = "taskrun:turn:session-a:1:abc"
    stream_run_id = "strun:session-a:1"
    stream_run = SimpleNamespace(
        stream_run_id=stream_run_id,
        session_id="session-a",
        event_log_id="chatrun:session-a:1",
        status="running",
        diagnostics={"active_turn_id": "turn:session-a:1", "runtime_task_run_id": task_run_id},
        created_at=1.0,
        updated_at=2.0,
    )
    legacy_frame = {
        "frame_id": "frame:legacy-protocol-repair",
        "op": "item_upsert",
        "slot": "status",
        "source_authority": "runtime",
        "main_visibility": "visible_live",
        "retention": "transient",
        "status_kind": "protocol_repair_status",
        "title": "当前步骤输出格式不完整，正在自动修正后继续。",
        "text": "当前步骤输出格式不完整，正在自动修正后继续。",
        "detail": "",
        "anchor": {
            "session_id": "session-a",
            "turn_id": "turn:session-a:1",
            "stream_run_id": stream_run_id,
            "task_run_id": task_run_id,
            "message_id": "history-message:turn:session-a:1:assistant",
        },
    }
    runtime_host = _runtime_host(
        task_runs=[],
        events_by_run={},
        stream_runs=[stream_run],
        public_events_by_stream_run={
            stream_run_id: [
                {
                    "stream_run_id": stream_run_id,
                    "event_log_id": "chatrun:session-a:1",
                    "event_id": "event:legacy-protocol-repair",
                    "event_offset": 1,
                    "created_at": 1.0,
                    "public_event_type": "runtime_step_summary",
                    "terminal": False,
                    "data": {"public_projection_frame": legacy_frame},
                    "public_projection_frame": legacy_frame,
                }
            ]
        },
    )

    timeline = build_session_runtime_timeline(
        session_id="session-a",
        history={"messages": [{"role": "user", "content": "run", "turn_id": "turn:session-a:1"}]},
        runtime_host=runtime_host,
    )

    frame = timeline["runtime_attachments"][0]["public_projection_frames"][0]
    assert frame["slot"] == "trace"
    assert frame["main_visibility"] == "hidden"
    assert frame["retention"] == "trace"
    assert "status_kind" not in frame
    assert "当前步骤输出格式不完整" not in str(frame)


def test_session_runtime_timeline_stream_failure_does_not_close_main_surface() -> None:
    task_run_id = "taskrun:turn:session-a:1:abc"
    stream_run_id = "strun:session-a:1"
    stream_run = SimpleNamespace(
        stream_run_id=stream_run_id,
        session_id="session-a",
        event_log_id="chatrun:session-a:1",
        status="stopped",
        diagnostics={"active_turn_id": "turn:session-a:1", "runtime_task_run_id": task_run_id},
        created_at=1.0,
        updated_at=3.0,
    )
    runtime_host = _runtime_host(
        task_runs=[],
        events_by_run={},
        stream_runs=[stream_run],
        public_events_by_stream_run={
            stream_run_id: [
                _public_ledger_record(
                    TOOL_CALL_REQUESTED_EVENT,
                    {"tool_call_id": "call:read", "tool_name": "read_file", "target": "README.md"},
                    offset=1,
                    stream_run_id=stream_run_id,
                    task_run_id=task_run_id,
                ),
                _public_ledger_record(
                    TURN_COMPLETED_EVENT,
                    {"status": "stopped", "terminal_reason": "runtime_process_restarted"},
                    offset=2,
                    stream_run_id=stream_run_id,
                    task_run_id=task_run_id,
                ),
            ]
        },
    )

    timeline = build_session_runtime_timeline(
        session_id="session-a",
        history={"messages": [{"role": "user", "content": "run", "turn_id": "turn:session-a:1"}]},
        runtime_host=runtime_host,
    )

    attachment = timeline["runtime_attachments"][0]
    assert attachment["display_state"] == "task_live"
    assert attachment["main_chat_surface"] == "live_timeline"
    assert attachment["closeout_summary"] == ""
    assert [frame["op"] for frame in attachment["public_projection_frames"]] == ["item_upsert", "turn_terminal"]


def test_turn_runtime_attachment_keeps_projection_anchor_without_legacy_projection_fields() -> None:
    turn_run_id = "turnrun:turn:session-a:2"
    turn_run = SimpleNamespace(
        turn_run_id=turn_run_id,
        session_id="session-a",
        turn_id="turn:session-a:2",
        status="completed",
        terminal_reason="assistant_message",
        created_at=4.0,
        updated_at=5.0,
    )
    runtime_host = _runtime_host(
        task_runs=[],
        turn_runs=[turn_run],
        events_by_run={
            turn_run_id: [
                {
                    "event_id": "event:turn",
                    "event_type": "turn_completed",
                    "run_id": turn_run_id,
                    "offset": 1,
                    "created_at": 5.0,
                    "payload": {"status": "completed"},
                    "refs": {"turn_ref": "turn:session-a:2"},
                }
            ]
        },
    )

    timeline = build_session_runtime_timeline(
        session_id="session-a",
        history={"messages": [{"role": "user", "content": "hi", "turn_id": "turn:session-a:2"}]},
        runtime_host=runtime_host,
    )

    attachment = timeline["runtime_attachments"][0]
    assert attachment["run_id"] == turn_run_id
    assert attachment["trace_available"] is True
    assert attachment["display_state"] == "log_only"
    assert attachment["main_chat_surface"] == "log_only"
    assert attachment["projection_anchor"]["anchor_turn_id"] == "turn:session-a:2"
    assert attachment["public_projection_frames"] == []
    assert "public_timeline" not in attachment
    assert "task_projection" not in attachment
