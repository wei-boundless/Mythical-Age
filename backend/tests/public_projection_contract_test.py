from __future__ import annotations

from api.chat import _project_public_stream_event
from harness.runtime.projection.authority import PUBLIC_PROJECTION_AUTHORITY
from harness.runtime.projection.guards import public_text
from harness.runtime.projection.projector import project_public_projection_event
from runtime.output_stream.public_contract import (
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
    return project_public_projection_event(
        event_type,
        {
            **data,
            "public_anchor": {
                "session_id": "session:test",
                "turn_id": "turn:test",
                "task_run_id": "taskrun:turn:test:1",
            },
        },
        session_id="session:test",
        sequence=sequence,
    )["public_projection_frame"]


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
    assert requested["target"] == "README.md"
    assert requested["public_action_state"]["next_action"] == "读取 README.md"
    assert permission["tool_call_id"] == "call:read"
    assert permission["permission_decision"] == "allow"


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
