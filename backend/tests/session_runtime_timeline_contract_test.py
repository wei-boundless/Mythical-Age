from __future__ import annotations

from types import SimpleNamespace

from harness.runtime.projection.projector import project_public_projection_event
from harness.runtime.session_timeline import (
    _task_closeout_summary,
    build_session_runtime_projection,
    build_session_runtime_timeline,
)
from runtime.output_stream.public_contract import (
    ASSISTANT_PUBLIC_FEEDBACK_EVENT,
    ASSISTANT_TEXT_FINAL_EVENT,
    SESSION_OUTPUT_COMMIT_ACK_EVENT,
    TOOL_ITEM_COMPLETED_EVENT,
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

def _projection_slice(attachment: dict) -> dict:
    slices = list(attachment.get("projection_slices") or [])
    assert len(slices) <= 1
    return slices[0] if slices else {}


def _projection_frames(attachment: dict) -> list[dict]:
    return list(_projection_slice(attachment).get("frames") or [])


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


def test_task_closeout_summary_ignores_diagnostics_final_answer_shadow_text() -> None:
    task_run = SimpleNamespace(
        diagnostics={
            "final_answer": "diagnostics shadow final answer",
            "latest_public_status": "diagnostics shadow status",
        }
    )

    summary = _task_closeout_summary(
        task_run,
        session_output_commit={"state": "committed", "reason": "committed"},
        projection_frames=[
            {"slot": "body", "text": "committed body frame"},
        ],
    )
    fallback = _task_closeout_summary(
        task_run,
        session_output_commit={"state": "committed", "reason": "committed"},
        projection_frames=[],
    )

    assert summary == "committed body frame"
    assert fallback == "任务已完成。"


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
    slice_ = _projection_slice(attachment)
    assert slice_["schema_version"] == "chronological_projection"
    assert slice_["event_log_id"] == "chatrun:session-a:1"
    assert slice_["start_offset"] == 1
    assert slice_["end_offset"] == 3
    assert slice_["projection_key"]["turn_id"] == "turn:session-a:1"
    assert slice_["projection_key"]["message_id"] == "history-message:turn:session-a:1:assistant"
    assert slice_["projection_key"]["event_log_id"] == "chatrun:session-a:1"
    assert slice_["cursor"]["frame_count"] == 3
    assert slice_["display_hint"]["lifecycle"] == "committed"
    assert slice_["display_hint"]["main_surface_hint"] == "closeout"
    assert [frame["event_family"] for frame in _projection_frames(attachment)] == [
        "tool_control",
        "assistant_body",
        "runtime_commit",
    ]
    assert "public_timeline" not in attachment
    assert "task_projection" not in attachment
    assert "public_projection_status" not in attachment


def test_session_runtime_projection_keeps_tool_activity_without_task_run_anchor() -> None:
    stream_run_id = "strun:session-a:no-task-anchor"
    stream_run = SimpleNamespace(
        stream_run_id=stream_run_id,
        session_id="session-a",
        event_log_id="chatrun:session-a:no-task-anchor",
        status="completed",
        diagnostics={"active_turn_id": "turn:session-a:1"},
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
                    task_run_id="",
                ),
                _public_ledger_record(
                    ASSISTANT_TEXT_FINAL_EVENT,
                    {"content": "done"},
                    offset=2,
                    stream_run_id=stream_run_id,
                    task_run_id="",
                ),
                _public_ledger_record(
                    SESSION_OUTPUT_COMMIT_ACK_EVENT,
                    {"state": "committed", "content_sha256": "sha256:final"},
                    offset=3,
                    stream_run_id=stream_run_id,
                    task_run_id="",
                ),
            ],
        },
    )

    projection = build_session_runtime_projection(
        session_id="session-a",
        history={
            "messages": [
                {"role": "user", "content": "run", "turn_id": "turn:session-a:1"},
                {"role": "assistant", "content": "done", "turn_id": "turn:session-a:1"},
            ]
        },
        runtime_host=runtime_host,
    )

    attachment = projection["runtime_attachments"][0]
    assert attachment["stream_run_id"] == stream_run_id
    assert attachment["display_state"] == "task_closed"
    assert attachment["main_chat_surface"] == "closeout_summary"
    assert attachment["tool_event_count"] == 1
    assert attachment["closeout_summary"] == "done"
    assert _projection_slice(attachment)["display_hint"]["main_surface_hint"] == "closeout"
    assert [frame["event_family"] for frame in _projection_frames(attachment)] == [
        "tool_control",
        "assistant_body",
        "runtime_commit",
    ]


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
    assert _projection_frames(attachment)[0]["tool_call_id"] == "call:read"
    assert attachment["tool_event_count"] == 1


def test_session_runtime_timeline_replays_public_ledger_agent_todo_as_structured_plan() -> None:
    task_run_id = "taskrun:turn:session-a:1:todo"
    stream_run_id = "strun:session-a:todo"
    todo_payload = {
        "status": "ok",
        "plan_id": f"agent-todo:session-a:{task_run_id}",
        "active_item_id": "todo:1",
        "completion_ready": False,
        "items": [
            {
                "todo_id": "todo:1",
                "content": "修复任务清单投影",
                "active_form": "正在修复任务清单投影",
                "status": "in_progress",
            },
            {
                "todo_id": "todo:2",
                "content": "验证刷新后仍可见",
                "status": "pending",
            },
        ],
    }
    stream_run = SimpleNamespace(
        stream_run_id=stream_run_id,
        session_id="session-a",
        event_log_id="chatrun:session-a:todo",
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
                    TOOL_ITEM_COMPLETED_EVENT,
                    {
                        "tool_call_id": "call:agent-todo",
                        "permission_decision_id": "permit:agent-todo",
                        "tool_name": "agent_todo",
                        "state": "done",
                        "todo_plan": todo_payload,
                    },
                    offset=1,
                    stream_run_id=stream_run_id,
                    task_run_id=task_run_id,
                )
            ],
        },
    )

    timeline = build_session_runtime_timeline(
        session_id="session-a",
        history={"messages": [{"role": "user", "content": "run", "turn_id": "turn:session-a:1"}]},
        runtime_host=runtime_host,
    )

    attachment = timeline["runtime_attachments"][0]
    frames = _projection_frames(attachment)
    todo_frame = next(frame for frame in frames if frame.get("status_kind") == "todo_plan")

    assert attachment["display_state"] == "task_live"
    assert attachment["main_chat_surface"] == "live_timeline"
    assert attachment["stream_run_id"] == stream_run_id
    assert attachment["tool_event_count"] == 0
    assert todo_frame["title"] == "任务清单"
    assert todo_frame["plan_id"] == f"agent-todo:session-a:{task_run_id}"
    assert todo_frame["active_item_id"] == "todo:1"
    assert todo_frame["completion_ready"] is False
    assert [item["content"] for item in todo_frame["todo_items"]] == ["修复任务清单投影", "验证刷新后仍可见"]


def test_session_runtime_timeline_keeps_steer_projection_on_steer_turn_not_target_turn() -> None:
    task_run_id = "taskrun:turn:session-a:1:abc"
    stream_run_id = "strun:session-a:steer"
    stream_run = SimpleNamespace(
        stream_run_id=stream_run_id,
        session_id="session-a",
        event_log_id="chatrun:session-a:steer",
        status="completed",
        diagnostics={
            "active_turn_input_policy": "steer",
            "expected_active_turn_id": "turn:session-a:1",
            "active_turn_id": "turn:session-a:1",
            "runtime_turn_run_id": "turnrun:turn:session-a:2",
            "runtime_task_run_id": task_run_id,
        },
        created_at=3.0,
        updated_at=4.0,
    )
    frame = {
        "authority": "harness.public_projection",
        "frame_id": "frame:steer:accepted",
        "projection_id": "frame:steer:accepted",
        "source_event_type": "active_task_steer_accepted",
        "sequence": 1,
        "event_offset": 1,
        "event_family": "status",
        "channel": "status",
        "lossless": True,
        "anchor": {
            "session_id": "session-a",
            "stream_run_id": stream_run_id,
            "run_id": stream_run_id,
            "task_run_id": task_run_id,
        },
        "op": "item_upsert",
        "slot": "status",
        "source_authority": "runtime",
        "main_visibility": "visible_live",
        "retention": "transient",
        "status_kind": "status_event",
        "item_id": "active-task-steer:accepted",
        "title": "补充要求已接入当前任务",
        "text": "请优先修正 steer 投影归属。",
        "state": "done",
    }
    runtime_host = _runtime_host(
        task_runs=[],
        events_by_run={},
        stream_runs=[stream_run],
        public_events_by_stream_run={
            stream_run_id: [
                {
                    "stream_run_id": stream_run_id,
                    "event_log_id": "chatrun:session-a:steer",
                    "event_id": "event:steer:accepted",
                    "event_offset": 1,
                    "created_at": 4.0,
                    "public_event_type": "active_task_steer_accepted",
                    "terminal": False,
                    "data": {"public_projection_frame": frame},
                    "public_projection_frame": frame,
                }
            ],
        },
    )

    timeline = build_session_runtime_timeline(
        session_id="session-a",
        history={
            "messages": [
                {"id": "user:turn:1", "role": "user", "content": "开始任务", "turn_id": "turn:session-a:1"},
                {"id": "assistant:turn:1", "role": "assistant", "content": "我会启动任务。", "turn_id": "turn:session-a:1"},
                {"id": "user:turn:2", "role": "user", "content": "补充：先修 steer", "turn_id": "turn:session-a:2"},
                {"id": "assistant:turn:2", "role": "assistant", "content": "已收到补充要求。", "turn_id": "turn:session-a:2"},
            ]
        },
        runtime_host=runtime_host,
    )

    attachment = timeline["runtime_attachments"][0]
    frames = _projection_frames(attachment)

    assert attachment["projection_anchor"]["anchor_turn_id"] == "turn:session-a:2"
    assert attachment["projection_anchor"]["anchor_message_id"] == "assistant:turn:2"
    assert attachment["projection_anchor"]["task_run_id"] == task_run_id
    assert frames[0]["anchor"]["turn_id"] == "turn:session-a:2"
    assert frames[0]["anchor"]["message_id"] == "assistant:turn:2"
    assert _projection_slice(attachment)["projection_key"]["turn_id"] == "turn:session-a:2"
    assert _projection_slice(attachment)["projection_key"]["message_id"] == "assistant:turn:2"


def test_session_runtime_projection_filters_body_only_history_and_bounds_frames() -> None:
    old_stream_run_id = "strun:session-a:old"
    live_stream_run_id = "strun:session-a:live"
    task_run_id = "taskrun:turn:session-a:2:abc"
    old_stream_run = SimpleNamespace(
        stream_run_id=old_stream_run_id,
        session_id="session-a",
        event_log_id="chatrun:session-a:old",
        status="completed",
        diagnostics={"active_turn_id": "turn:session-a:1"},
        created_at=1.0,
        updated_at=1.0,
    )
    live_stream_run = SimpleNamespace(
        stream_run_id=live_stream_run_id,
        session_id="session-a",
        event_log_id="chatrun:session-a:live",
        status="running",
        diagnostics={"active_turn_id": "turn:session-a:2", "runtime_task_run_id": task_run_id},
        created_at=2.0,
        updated_at=2.0,
    )
    runtime_host = _runtime_host(
        task_runs=[],
        events_by_run={},
        stream_runs=[old_stream_run, live_stream_run],
        public_events_by_stream_run={
            old_stream_run_id: [
                _public_ledger_record(
                    ASSISTANT_TEXT_FINAL_EVENT,
                    {"content": f"old {index}"},
                    offset=index,
                    turn_id="turn:session-a:1",
                    stream_run_id=old_stream_run_id,
                    task_run_id="",
                )
                for index in range(1, 40)
            ],
            live_stream_run_id: [
                _public_ledger_record(
                    TOOL_CALL_REQUESTED_EVENT,
                    {"tool_call_id": f"call:{index}", "tool_name": "read_file", "target": f"file-{index}.py"},
                    offset=index,
                    turn_id="turn:session-a:2",
                    stream_run_id=live_stream_run_id,
                    task_run_id=task_run_id,
                )
                for index in range(1, 50)
            ],
        },
    )

    projection = build_session_runtime_projection(
        session_id="session-a",
        history={
            "messages": [
                {"role": "user", "content": "old", "turn_id": "turn:session-a:1"},
                {"role": "assistant", "content": "old final", "turn_id": "turn:session-a:1"},
                {"role": "user", "content": "live", "turn_id": "turn:session-a:2"},
            ]
        },
        runtime_host=runtime_host,
        max_projection_frames_per_attachment=12,
    )

    attachments = projection["runtime_attachments"]
    assert projection["authority"] == "session_runtime_projection"
    assert [item["stream_run_id"] for item in attachments] == [live_stream_run_id]
    assert attachments[0]["main_chat_surface"] == "live_timeline"
    assert len(_projection_frames(attachments[0])) == 12


def test_session_runtime_projection_keeps_complete_committed_slice_beyond_frame_limit() -> None:
    stream_run_id = "strun:session-a:closed-many-tools"
    task_run_id = "taskrun:turn:session-a:3:abc"
    stream_run = SimpleNamespace(
        stream_run_id=stream_run_id,
        session_id="session-a",
        event_log_id="chatrun:session-a:closed-many-tools",
        status="completed",
        diagnostics={"active_turn_id": "turn:session-a:3", "runtime_task_run_id": task_run_id},
        created_at=3.0,
        updated_at=60.0,
    )
    tool_records = [
        _public_ledger_record(
            TOOL_CALL_REQUESTED_EVENT,
            {"tool_call_id": f"call:{index}", "tool_name": "read_file", "target": f"file-{index}.py"},
            offset=index,
            turn_id="turn:session-a:3",
            stream_run_id=stream_run_id,
            task_run_id=task_run_id,
            message_id="assistant:turn:3",
        )
        for index in range(1, 51)
    ]
    public_events = [
        *tool_records,
        _public_ledger_record(
            ASSISTANT_TEXT_FINAL_EVENT,
            {"content": "最终正文。"},
            offset=51,
            turn_id="turn:session-a:3",
            stream_run_id=stream_run_id,
            task_run_id=task_run_id,
            message_id="assistant:turn:3",
        ),
        _public_ledger_record(
            SESSION_OUTPUT_COMMIT_ACK_EVENT,
            {"state": "committed", "content_sha256": "sha256:final"},
            offset=52,
            turn_id="turn:session-a:3",
            stream_run_id=stream_run_id,
            task_run_id=task_run_id,
            message_id="assistant:turn:3",
        ),
    ]
    runtime_host = _runtime_host(
        task_runs=[],
        events_by_run={},
        stream_runs=[stream_run],
        public_events_by_stream_run={stream_run_id: public_events},
    )

    projection = build_session_runtime_projection(
        session_id="session-a",
        history={
            "messages": [
                {"role": "user", "content": "closed", "turn_id": "turn:session-a:3"},
                {"id": "assistant:turn:3", "role": "assistant", "content": "最终正文。", "turn_id": "turn:session-a:3"},
            ]
        },
        runtime_host=runtime_host,
        max_projection_frames_per_attachment=12,
    )

    attachment = projection["runtime_attachments"][0]
    frames = _projection_frames(attachment)
    slice_ = _projection_slice(attachment)

    assert attachment["main_chat_surface"] == "closeout_summary"
    assert attachment["tool_event_count"] == 50
    assert attachment["log_ref"] == "chatrun:session-a:closed-many-tools"
    assert len(frames) == 52
    assert frames[0]["tool_call_id"] == "call:1"
    assert frames[-1]["op"] == "commit_ack"
    assert slice_["integrity"] == "complete"
    assert slice_["committed"] is True
    assert slice_["cursor"]["frame_count"] == 52
    assert slice_["display_hint"]["tool_event_count"] == 50


def test_session_runtime_timeline_restores_model_feedback_identity_for_public_feedback() -> None:
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
                    ASSISTANT_PUBLIC_FEEDBACK_EVENT,
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
    assert task_attachment["main_chat_surface"] == "log_only"
    assert task_attachment["projection_slices"] == []
    frame = _projection_frames(stream_attachment)[0]
    assert frame["source_event_type"] == ASSISTANT_PUBLIC_FEEDBACK_EVENT
    assert frame["item_id"].startswith("assistant-public-feedback:")
    assert frame["frame_id"].startswith("assistant-public-feedback-frame:")


def test_session_runtime_timeline_rejects_noncanonical_projection_frames() -> None:
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
    noncanonical_frame = {
        "frame_id": "frame:noncanonical-runtime-status",
        "op": "item_upsert",
        "slot": "status",
        "source_authority": "runtime",
        "main_visibility": "visible_live",
        "retention": "transient",
        "status_kind": "runtime_status",
        "title": "noncanonical private status must not hydrate",
        "text": "noncanonical private status must not hydrate",
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
                    "event_id": "event:noncanonical-frame",
                    "event_offset": 1,
                    "created_at": 1.0,
                    "public_event_type": "runtime_step_summary",
                    "terminal": False,
                    "data": {"public_projection_frame": noncanonical_frame},
                    "public_projection_frame": noncanonical_frame,
                }
            ]
        },
    )

    timeline = build_session_runtime_timeline(
        session_id="session-a",
        history={"messages": [{"role": "user", "content": "run", "turn_id": "turn:session-a:1"}]},
        runtime_host=runtime_host,
    )

    attachment = timeline["runtime_attachments"][0]
    assert _projection_frames(attachment) == []
    assert "noncanonical private status must not hydrate" not in str(attachment)


def test_session_runtime_timeline_runtime_interruption_terminal_is_trace_only() -> None:
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
    frames = _projection_frames(attachment)
    assert [frame["op"] for frame in frames] == ["item_upsert", "item_upsert"]
    assert frames[1]["slot"] == "trace"
    assert frames[1]["main_visibility"] == "hidden"
    assert frames[1]["retention"] == "trace"
    assert "status_kind" not in frames[1]


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
    assert attachment["projection_slices"] == []
    assert "public_timeline" not in attachment
    assert "task_projection" not in attachment
