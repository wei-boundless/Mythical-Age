from __future__ import annotations

from api.chat import (
    _agent_todo_observation_summary,
    _append_chat_public_event,
    _is_task_executor_handoff_terminal,
    _project_public_stream_event,
)
from harness.runtime.projection.authority import PUBLIC_PROJECTION_AUTHORITY, PUBLIC_PROJECTION_CONTRACT_REVISION
from harness.runtime.projection.guards import public_text
from harness.runtime.projection.projector import ProjectionLifecycleState, project_public_projection_event
from runtime.output_stream.public_contract import (
    ASSISTANT_TEXT_FINAL_EVENT,
    SESSION_OUTPUT_COMMIT_ACK_EVENT,
    SESSION_OUTPUT_COMMIT_FAILED_EVENT,
    TOOL_CALL_REQUESTED_EVENT,
    TOOL_ITEM_COMPLETED_EVENT,
    TOOL_ITEM_STARTED_EVENT,
    TOOL_PERMISSION_DECIDED_EVENT,
    TURN_COMPLETED_EVENT,
)
from runtime.shared.runtime_run_registry import RuntimeRun
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


def test_active_task_steer_accepted_is_visible_status_not_body() -> None:
    frame = _frame(
        "active_task_steer_accepted",
        {
            "task_run_id": "taskrun:active",
            "turn_id": "turn:test",
            "detail": "新的限制已经加入当前任务。",
        },
    )

    assert frame["op"] == "item_upsert"
    assert frame["slot"] == "status"
    assert frame["status_kind"] == "active_task_steer_receipt"
    assert frame["main_visibility"] == "visible_live"
    assert frame["event_family"] == "status_trace"
    assert frame["channel"] == "status"
    assert frame["slot"] != "body"


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
        "runtime_step_summary",
        TOOL_CALL_REQUESTED_EVENT,
        TOOL_PERMISSION_DECIDED_EVENT,
    ]
    status = events[0][1]
    requested = events[1][1]
    permission = events[2][1]
    assert status["presentation_source"] == "model_action.public_progress_note"
    assert status["summary"] == "读取 README。"
    assert requested["tool_call_id"] == "call:read"
    assert requested["tool_name"] == "read_file"
    assert requested["turn_run_id"] == "turnrun:turn:test:1"
    assert permission["tool_call_id"] == "call:read"
    assert permission["permission_decision"] == "allow"


def test_chat_bridge_generates_tool_call_id_without_reusing_request_id() -> None:
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

    assert [event_type for event_type, _ in events] == [
        TOOL_CALL_REQUESTED_EVENT,
        TOOL_PERMISSION_DECIDED_EVENT,
    ]
    requested = events[0][1]
    permission = events[1][1]
    assert requested["request_id"] == "request:read"
    assert requested["tool_call_id"]
    assert requested["tool_call_id"] != "request:read"
    assert requested["tool_lifecycle_id"] == requested["tool_call_id"]
    assert permission["tool_call_id"] == requested["tool_call_id"]
    assert permission["permission_decision_id"] == f"admission:{requested['tool_call_id']}"


def test_chat_bridge_projects_tool_calls_array_with_one_feedback_event() -> None:
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
        "runtime_step_summary",
        TOOL_CALL_REQUESTED_EVENT,
        TOOL_PERMISSION_DECIDED_EVENT,
        TOOL_CALL_REQUESTED_EVENT,
        TOOL_PERMISSION_DECIDED_EVENT,
    ]
    assert events[0][1]["feedback_identity"] == "request:batch"
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


def test_runtime_status_defaults_to_trace_only_unless_public_status_kind() -> None:
    hidden = _frame(
        "runtime_status",
        {
            "runtime_event_id": "event:runtime-status:hidden",
            "title": "内部运行状态",
            "detail": "这只是运行时诊断。",
            "state": "running",
        },
    )
    visible = _frame(
        "runtime_status",
        {
            "runtime_event_id": "event:runtime-status:visible",
            "title": "公开阶段状态",
            "detail": "这条状态明确允许展示。",
            "state": "running",
            "status_kind": "user_visible_runtime_status",
        },
    )

    assert hidden["slot"] == "trace"
    assert hidden["main_visibility"] == "hidden"
    assert hidden["retention"] == "trace"
    assert visible["slot"] == "status"
    assert visible["main_visibility"] == "visible_live"
    assert visible["retention"] == "transient"


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


def test_task_model_wait_heartbeat_projects_as_transient_status_placeholder() -> None:
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

    assert len(events) == 1
    public_event_type, data = events[0]
    assert public_event_type == "runtime_status"
    assert data["status_kind"] == "model_wait_placeholder"
    assert data["item_id"] == "model-wait:taskrun:wait"

    frame = _frame(public_event_type, data)
    assert frame["op"] == "item_upsert"
    assert frame["slot"] == "status"
    assert frame["source_authority"] == "runtime"
    assert frame["main_visibility"] == "visible_live"
    assert frame["retention"] == "transient"
    assert frame["status_kind"] == "model_wait_placeholder"
    assert frame["slot"] != "body"


def test_lifecycle_coalesces_repeated_model_wait_heartbeat_status() -> None:
    lifecycle = ProjectionLifecycleState()
    first = {
        "task_run_id": "taskrun:wait",
        "turn_id": "turn:test",
        "turn_run_id": "turnrun:test",
        "item_id": "model-wait:taskrun:wait",
        "status": "running",
        "presentation_source": "runtime.model_wait",
        "status_kind": "model_wait_placeholder",
        "source_task_event_type": "task_model_action_wait_heartbeat",
        "runtime_event_id": "event:model-wait:1",
    }
    second = {
        **first,
        "runtime_event_id": "event:model-wait:2",
        "source_task_event_id": "event:model-wait:2",
        "source_task_event_offset": 22,
        "wait_round": 2,
    }

    assert lifecycle.should_emit_public_event("runtime_status", first) is True
    assert lifecycle.should_emit_public_event("runtime_status", second) is False


def test_lifecycle_emits_model_wait_status_when_visible_state_changes() -> None:
    lifecycle = ProjectionLifecycleState()
    running = {
        "task_run_id": "taskrun:wait",
        "turn_id": "turn:test",
        "turn_run_id": "turnrun:test",
        "item_id": "model-wait:taskrun:wait",
        "status": "running",
        "presentation_source": "runtime.model_wait",
        "status_kind": "model_wait_placeholder",
    }
    waiting = {
        **running,
        "status": "waiting",
        "runtime_event_id": "event:model-wait:state-change",
    }

    assert lifecycle.should_emit_public_event("runtime_status", running) is True
    assert lifecycle.should_emit_public_event("runtime_status", waiting) is True


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


def test_chat_bridge_suppresses_duplicate_model_wait_before_append_and_mark_event() -> None:
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
    suppressed = _append_chat_public_event(
        registry=registry,
        replay=replay,
        current=current,
        public_event_type="runtime_status",
        data={**wait_status, "runtime_event_id": "event:model-wait:2", "wait_round": 2},
        session_id="session:test",
        projection_lifecycle=lifecycle,
        runtime_task_run_id="taskrun:wait",
        runtime_turn_run_id="turnrun:test",
        runtime_active_turn_id="turn:test",
    )

    assert suppressed is current
    assert len(replay.append_public_event_calls) == 1
    assert len(registry.mark_event_calls) == 1


def test_protocol_repair_status_stays_trace_only_without_public_surface() -> None:
    frame = _frame(
        "runtime_step_summary",
        {
            "runtime_event_id": "event:protocol-repair",
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
    assert frame.get("status_kind") != "protocol_repair_status"
    assert not frame.get("title")
    assert not frame.get("text")
    assert not frame.get("detail")
    assert "当前步骤输出格式不完整" not in str(frame)
    assert "public_response_required" not in str(frame)
    assert frame["slot"] != "body"


def test_model_action_runtime_step_summary_projects_as_body_frame() -> None:
    first = _frame(
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
    second = _frame(
        "runtime_step_summary",
        {
            "runtime_event_id": "event:stage:2",
            "source_task_event_offset": 20,
            "task_run_id": "taskrun:stage",
            "step": "model_action_received:2",
            "status": "running",
            "presentation_source": "model_action.current_judgment",
            "current_judgment": "开始执行精确修改。",
        },
    )

    assert first["op"] == "body_append"
    assert first["slot"] == "body"
    assert first["event_family"] == "assistant_body"
    assert first["channel"] == "body"
    assert first["source_authority"] == "model"
    assert first["main_visibility"] == "visible_live"
    assert second["item_id"] != first["item_id"]
    assert second["trace_refs"]


def test_lifecycle_does_not_filter_legal_model_action_body_output() -> None:
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
        "public_progress_note": "用户表达感谢，直接回复即可。",
        "current_judgment": "用户表达感谢，当前对话自然收口。",
        "next_action": "等待用户下一步需求。",
        "status": "running",
    }
    second = {
        **first,
        "runtime_event_id": "event:model-feedback:2",
        "source_task_event_offset": 11,
        "step": "model_action_received:2",
    }

    assert lifecycle.should_emit_public_event("runtime_step_summary", first) is True
    first_frame = project_public_projection_event(
        "runtime_step_summary",
        first,
        session_id="session:test",
        sequence=1,
        lifecycle_state=lifecycle,
    )["public_projection_frame"]
    assert lifecycle.should_emit_public_event("runtime_step_summary", second) is True
    second_frame = project_public_projection_event(
        "runtime_step_summary",
        second,
        session_id="session:test",
        sequence=2,
        lifecycle_state=lifecycle,
    )["public_projection_frame"]

    assert first_frame["op"] == "body_append"
    assert first_frame["slot"] == "body"
    assert first_frame["source_authority"] == "model"
    assert first_frame["text"] == "用户表达感谢，直接回复即可。\n\n用户表达感谢，当前对话自然收口。"
    assert second_frame["op"] == "body_append"
    assert second_frame["slot"] == "body"
    assert second_frame["source_authority"] == "model"
    assert second_frame["text"] == first_frame["text"]
    assert second_frame["item_id"] != first_frame["item_id"]


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
    assert frame["slot"] == "status"
    assert frame["main_visibility"] == "visible_live"
    assert frame["retention"] == "transient"
    assert frame["tool_call_id"] == "call:rehydrate"


def test_turn_completed_has_no_hydrate_or_main_tool_semantics() -> None:
    frame = _frame(TURN_COMPLETED_EVENT, {"status": "completed", "turn_run_id": "turnrun:test"})

    assert frame["op"] == "turn_terminal"
    assert frame["slot"] == "trace"
    assert frame["main_visibility"] == "hidden"
    assert "commit" not in frame
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


def test_commit_failed_is_pinned() -> None:
    frame = _frame(
        SESSION_OUTPUT_COMMIT_FAILED_EVENT,
        {"state": "failed", "reason": "history write failed", "event_offset": 12},
    )

    assert frame["op"] == "commit_failed"
    assert frame["slot"] == "pinned"
    assert frame["main_visibility"] == "pinned"
    assert frame["pin_reason"] == "commit_failed"


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


def test_task_tool_observation_wrapper_projects_inner_tool_completion_identity() -> None:
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
                                    "tool_call": {"id": "call:read", "tool_name": "read_file"},
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
    assert "diagnostics" not in frame
