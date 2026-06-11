from __future__ import annotations

from api.chat import _project_public_stream_event
from harness.runtime.projection.authority import PUBLIC_PROJECTION_AUTHORITY
from harness.runtime.projection.guards import public_text
from harness.runtime.projection.projector import project_public_projection_event
from harness.runtime.projection.timeline_builder import project_runtime_monitor_event_public_delta
from runtime.tool_runtime import ToolObservation


def test_projection_does_not_generate_assistant_body_or_live_tool_items():
    projected = project_public_projection_event(
        "model_action_admission",
        {
            "model_action_request": {
                "request_id": "call:read",
                "action_type": "tool_call",
                "public_progress_note": "我先确认投影链路的正文归属。",
                "tool_call": {
                    "id": "call:read",
                    "tool_name": "read_file",
                    "args": {"path": "backend/harness/runtime/session_timeline.py"},
                },
            },
            "public_anchor": {"turn_id": "turn:test", "task_run_id": "taskrun:turn:test:abc"},
        },
        sequence=1,
    )

    envelope = projected["public_projection_envelope"]
    assert envelope["authority"] == PUBLIC_PROJECTION_AUTHORITY
    assert envelope.get("items", []) == []
    assert envelope["surface"] == "timeline"


def test_legacy_done_projection_does_not_create_body_or_terminal_authority():
    projected = project_public_projection_event(
        "done",
        {
            "content": "Done content must not become assistant prose.",
            "answer_channel": "conversation",
            "terminal_reason": "completed",
            "public_anchor": {"turn_id": "turn:test", "task_run_id": "taskrun:turn:test:abc"},
        },
        sequence=2,
    )

    envelope = projected["public_projection_envelope"]
    assert envelope.get("items", []) == []
    assert "terminal" not in envelope
    assert "Done content" not in str(envelope)


def test_chat_public_stream_maps_admitted_tool_to_first_class_started_item():
    projected = _project_public_stream_event(
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
                    "admission": {"decision": "allow"},
                },
                "refs": {"turn_run_ref": "turnrun:turn:test:1"},
            },
        },
    )

    assert projected is not None
    event_type, data = projected
    assert event_type == "tool_item_started"
    assert data["item_id"] == "call:read"
    assert data["tool_lifecycle_id"] == "call:read"
    assert data["tool_call_id"] == "call:read"
    assert data["turn_run_id"] == "turnrun:turn:test:1"
    assert data["tool_name"] == "read_file"
    assert data["state"] == "running"
    assert data["target"] == "README.md"


def test_chat_public_stream_drops_runtime_private_path_from_started_tool_target():
    private_path = (
        "backend/mythical-agent/sessions/session-123/environments/coding/vibe-workspace/"
        "runtime_state/dynamic_context/replacements/replacement_e21050df8baca858bdde6a4d.json"
    )
    projected = _project_public_stream_event(
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

    assert projected is not None
    event_type, data = projected
    assert event_type == "tool_item_started"
    assert "target" not in data
    assert "arguments_preview" not in data
    assert "replacement_e21050df8baca858bdde6a4d" not in str(data)


def test_chat_public_stream_maps_tool_observation_to_matching_completed_item():
    projected = _project_public_stream_event(
        "turn_tool_observation_recorded",
        {
            "event": {
                "event_id": "event:observation",
                "payload": {
                    "turn_id": "turn:test",
                    "tool_observation": {
                        "tool_name": "read_file",
                        "status": "ok",
                        "caller_ref": "turnrun:turn:test:1",
                        "result_envelope": {
                            "tool_name": "read_file",
                            "tool_call_id": "call:read",
                            "text": "读取完成。",
                        },
                    },
                },
                "refs": {"turn_run_ref": "turnrun:turn:test:1"},
            },
        },
    )

    assert projected is not None
    event_type, data = projected
    assert event_type == "tool_item_completed"
    assert data["item_id"] == "call:read"
    assert data["tool_lifecycle_id"] == "call:read"
    assert data["tool_call_id"] == "call:read"
    assert data["turn_run_id"] == "turnrun:turn:test:1"
    assert data["tool_name"] == "read_file"
    assert data["state"] == "done"
    assert data["observation"] == "读取完成。"


def test_chat_public_stream_drops_runtime_private_path_from_completed_tool_observation():
    private_path = (
        "backend/mythical-agent/sessions/session-123/environments/coding/vibe-workspace/"
        "runtime_state/dynamic_context/replacements/replacement_e21050df8baca858bdde6a4d.json"
    )
    projected = _project_public_stream_event(
        "turn_tool_observation_recorded",
        {
            "event": {
                "event_id": "event:observation:private-path",
                "payload": {
                    "tool_observation": {
                        "tool_name": "read_file",
                        "status": "ok",
                        "caller_ref": "turnrun:turn:test:private",
                        "result_envelope": {
                            "tool_name": "read_file",
                            "tool_call_id": "call:read-private",
                            "text": private_path,
                        },
                    },
                },
                "refs": {"turn_run_ref": "turnrun:turn:test:private"},
            },
        },
    )

    assert projected is not None
    event_type, data = projected
    assert event_type == "tool_item_completed"
    assert "observation" not in data
    assert "replacement_e21050df8baca858bdde6a4d" not in str(data)


def test_tool_observation_promotes_real_tool_call_id_for_public_completion():
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

    payload = observation.to_dict()

    assert payload["tool_call_id"] == "call:read"


def test_chat_public_stream_does_not_use_invocation_id_as_completed_item_id():
    projected = _project_public_stream_event(
        "turn_tool_observation_recorded",
        {
            "event": {
                "event_id": "event:observation:without-tool-call",
                "payload": {
                    "tool_observation": {
                        "invocation_id": "toolinvoke:turnrun:1:read_file:call:read",
                        "tool_name": "read_file",
                        "status": "ok",
                        "caller_ref": "turnrun:turn:test:1",
                        "text": "读取完成。",
                    },
                },
                "refs": {"turn_run_ref": "turnrun:turn:test:1"},
            },
        },
    )

    assert projected is None


def test_chat_public_stream_maps_internal_done_error_stopped_to_turn_completed():
    done = _project_public_stream_event(
        "done",
        {"turn_run_id": "turnrun:turn:test:1", "message_ref": "msg:final", "completion_state": "completed"},
    )
    error = _project_public_stream_event(
        "error",
        {"turn_run_id": "turnrun:turn:test:1", "error": "backend failed", "code": "stream_exception"},
    )
    stopped = _project_public_stream_event(
        "stopped",
        {"turn_run_id": "turnrun:turn:test:1", "reason": "user_stopped"},
    )

    assert done == (
        "turn_completed",
        {
            "status": "completed",
            "turn_run_id": "turnrun:turn:test:1",
            "final_message_ref": "msg:final",
            "terminal_reason": "completed",
            "completion_state": "completed",
        },
    )
    assert error is not None
    assert error[0] == "turn_completed"
    assert error[1]["status"] == "failed"
    assert error[1]["error_summary"] == "backend failed"
    assert stopped is not None
    assert stopped[0] == "turn_completed"
    assert stopped[1]["status"] == "stopped"
    assert stopped[1]["stopped_reason"] == "user_stopped"


def test_tool_line_numbered_observation_is_not_promoted_to_projection_body():
    projected = project_public_projection_event(
        "task_tool_observation_recorded",
        {
            "event": {
                "event_id": "event:raw-file",
                "payload": {
                    "observation": {
                        "tool_name": "read_file",
                        "target": "docs/review.md",
                        "result": "  1 | # LangChain-Agent 项目代码审查报告\n  2 | 工具读取的文件原文。",
                    }
                },
            },
            "public_anchor": {"turn_id": "turn:test", "task_run_id": "taskrun:turn:test:abc"},
        },
        sequence=4,
    )

    visible = str(projected["public_projection_envelope"])
    assert "LangChain-Agent" not in visible
    assert not any(
        item.get("slot") == "body"
        for item in projected["public_projection_envelope"].get("items", [])
    )


def test_runtime_private_artifact_paths_do_not_project_as_public_text():
    private_path = (
        "backend/mythical-agent/sessions/session-123/environments/coding/vibe-workspace/"
        "runtime_state/dynamic_context/replacements/replacement_e21050df8baca858bdde6a4d.json"
    )

    assert public_text(private_path) == ""

    projected = project_runtime_monitor_event_public_delta(
        {
            "event_id": "event:private-path",
            "event_type": "step_summary_recorded",
            "run_id": "taskrun:turn:test:abc",
            "offset": 5,
            "payload": {
                "step": "tool_result_store",
                "status": "running",
                "summary": private_path,
                "current_judgment": private_path,
            },
            "refs": {"turn_ref": "turn:test", "task_run_ref": "taskrun:turn:test:abc"},
        },
        runtime_host=None,
    )

    visible = str(projected["public_projection_envelope"])
    assert "replacement_e21050df8baca858bdde6a4d" not in visible
    assert projected.get("public_projection_skip_reason") == "empty_public_delta"


def test_runtime_monitor_projection_uses_runtime_status_not_assistant_body():
    projected = project_runtime_monitor_event_public_delta(
        {
            "event_id": "event:summary",
            "event_type": "step_summary_recorded",
            "run_id": "taskrun:turn:test:abc",
            "offset": 4,
            "payload": {
                "step": "stage_feedback",
                "status": "running",
                "current_judgment": "工具结果已返回，需要让模型给出阶段判断。",
            },
            "refs": {"turn_ref": "turn:test", "task_run_ref": "taskrun:turn:test:abc"},
        },
        runtime_host=None,
    )

    envelope = projected["public_projection_envelope"]
    assert envelope["authority"] == PUBLIC_PROJECTION_AUTHORITY
    assert envelope["items"][0]["source_authority"] == "runtime"
    assert envelope["items"][0]["slot"] == "status"
    assert envelope["items"][0]["surface"] == "timeline"
    assert envelope["items"][0]["title"] == "工具结果已返回，需要让模型给出阶段判断。"


def test_active_task_steer_projection_exposes_queue_transition_as_runtime_control_item():
    projected = project_runtime_monitor_event_public_delta(
        {
            "event_id": "event:steer-included",
            "event_type": "active_task_steer_included",
            "run_id": "taskrun:turn:test:abc",
            "offset": 8,
            "payload": {
                "steer": {"steer_id": "steer:test:1", "content": "优先处理新验收要求。"},
                "steer_transition": {
                    "title": "正在按补充要求重规划",
                    "summary": "补充要求已进入下一回合处理队列。",
                    "status": "running",
                },
            },
            "refs": {"turn_ref": "turn:test", "task_run_ref": "taskrun:turn:test:abc"},
        },
        runtime_host=None,
    )

    envelope = projected["public_projection_envelope"]
    assert envelope["authority"] == PUBLIC_PROJECTION_AUTHORITY
    assert envelope["items"][0]["source_authority"] == "runtime"
    assert envelope["items"][0]["slot"] == "control"
    assert envelope["items"][0]["title"] == "正在按补充要求重规划"
    assert envelope["items"][0]["detail"] == "补充要求已进入下一回合处理队列。"
