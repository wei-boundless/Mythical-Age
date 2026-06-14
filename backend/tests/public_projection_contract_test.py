from __future__ import annotations

from api.chat import _project_public_stream_event
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


def test_chat_bridge_does_not_use_request_id_as_tool_call_id() -> None:
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


def test_runtime_stage_status_uses_stable_task_item_id() -> None:
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

    assert first["op"] == "item_upsert"
    assert first["slot"] == "status"
    assert first["status_kind"] == "public_stage_status"
    assert second["item_id"] == first["item_id"]
    assert second["trace_refs"]


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


def test_lifecycle_does_not_rewrite_completed_permission_id_mismatch() -> None:
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

    assert frame["diagnostics"]["code"] == "tool_completed_without_started_lifecycle"
