from __future__ import annotations

from api.chat import _attach_public_projection_envelope, _project_public_stream_event
from harness.runtime.public_projection_envelope import (
    PUBLIC_PROJECTION_CONTRACT_REVISION,
    PUBLIC_PROJECTION_ENVELOPE_AUTHORITY,
    build_public_projection_envelope,
)
from harness.runtime.public_projection_projector import project_public_projection_event
from harness.runtime.public_timeline_projection import public_work_action_item
from harness.runtime.public_timeline_stream import project_public_timeline_delta
from harness.runtime.runtime_monitor_public_projection import project_runtime_monitor_event_public_delta


def test_handoff_done_envelope_is_control_and_not_visible() -> None:
    data = {
        "terminal_reason": "task_executor_scheduled",
        "answer_channel": "task_control",
        "runtime_task_run_id": "taskrun:turn:session-envelope:1:abc",
        "task_projection_delta": {
            "authority": "harness.runtime.single_agent_task_projection.v1",
            "projection_id": "projection:taskrun:turn:session-envelope:1:abc",
            "task_run_id": "taskrun:turn:session-envelope:1:abc",
            "status": "waiting_executor",
        },
        "public_timeline_delta": [
            {
                "kind": "status_update",
                "surface": "status",
                "title": "Background task accepted",
                "state": "done",
            }
        ],
    }

    _attach_public_projection_envelope(
        "done",
        data,
        session_id="session-envelope",
        sequence=7,
    )

    envelope = data["public_projection_envelope"]
    assert envelope["authority"] == PUBLIC_PROJECTION_ENVELOPE_AUTHORITY
    assert envelope["contract_revision"] == PUBLIC_PROJECTION_CONTRACT_REVISION
    assert envelope["projection_mode"] == "authoritative"
    assert envelope["source_authority"] == "runtime"
    assert envelope["surface"] == "task_projection"
    assert envelope["terminal"] == {
        "event": "done",
        "visible": False,
        "reason": "task_executor_scheduled",
    }
    assert not envelope.get("items")
    assert envelope["task_projection"]["task_run_id"] == "taskrun:turn:session-envelope:1:abc"
    assert envelope["active_turn_update"] == {
        "task_run_id": "taskrun:turn:session-envelope:1:abc",
        "state": "waiting_executor",
    }


def test_model_body_envelope_keeps_body_items_in_body_slot() -> None:
    envelope = build_public_projection_envelope(
        "assistant_text",
        {"answer_channel": "conversation"},
        session_id="session-envelope",
        sequence=2,
        public_timeline_delta=[
            {
                "item_id": "body:1",
                "kind": "assistant_text",
                "slot": "body",
                "surface": "assistant_body",
                "source_authority": "model",
                "text": "I will inspect the current chain first.",
                "state": "running",
            }
        ],
    )

    assert envelope["source_authority"] == "model"
    assert envelope["surface"] == "assistant_body"
    assert envelope["items"] == [
        {
            "item_id": "body:1",
            "kind": "assistant_text",
            "slot": "body",
            "surface": "assistant_body",
            "source_authority": "model",
            "text": "I will inspect the current chain first.",
            "state": "running",
        }
    ]


def test_opening_judgment_channel_projects_as_model_body() -> None:
    delta = project_public_timeline_delta(
        "assistant_text",
        {
            "answer_channel": "opening_judgment",
            "answer_source": "harness.single_agent_turn.request_task_run.opening_judgment",
            "content": "我先把页面目标转成可执行任务，然后推进实现和文件验证。",
        },
    )
    envelope = build_public_projection_envelope(
        "assistant_text",
        {"answer_channel": "opening_judgment"},
        session_id="session-envelope",
        sequence=3,
        public_timeline_delta=delta,
    )

    assert delta[0]["kind"] == "opening_judgment"
    assert envelope["source_authority"] == "model"
    assert envelope["surface"] == "assistant_body"
    assert envelope["items"][0]["slot"] == "body"
    assert "页面目标转成可执行任务" in envelope["items"][0]["text"]


def test_projection_builder_drops_items_without_explicit_slot() -> None:
    envelope = build_public_projection_envelope(
        "assistant_text",
        {"answer_channel": "conversation"},
        session_id="session-envelope",
        sequence=2,
        public_timeline_delta=[
            {
                "item_id": "legacy-body",
                "kind": "final_summary",
                "surface": "assistant_body",
                "source_authority": "model",
                "text": "This old item has no slot.",
                "state": "done",
            }
        ],
    )

    assert envelope.get("items", []) == []


def test_public_work_action_drops_bare_generic_tool_window() -> None:
    assert public_work_action_item(
        item_id="tool:bare-run",
        tool_name="terminal",
        raw_target="powershell -NoProfile -Command Get-ChildItem",
        state="running",
    ) == {}


def test_public_work_action_keeps_targeted_tool_window() -> None:
    item = public_work_action_item(
        item_id="tool:read-chat",
        tool_name="read_file",
        raw_target="frontend/src/components/chat/ChatMessage.tsx",
        state="running",
    )

    assert item["title"] == "正在读取上下文"
    assert item["subject_label"].endswith("ChatMessage.tsx")
    assert item["public_summary"] != item["title"]


def test_projector_does_not_project_done_content_as_body() -> None:
    projected = project_public_projection_event(
        "done",
        {
            "content": "This must not become message body.",
            "summary": "Done summary also stays a status item.",
            "answer_channel": "conversation",
        },
        session_id="session-envelope",
        sequence=9,
    )

    envelope = projected["public_projection_envelope"]
    assert envelope["terminal"] == {"event": "done", "visible": True}
    assert envelope["surface"] == "assistant_body"
    assert all(item.get("slot") != "body" for item in envelope.get("items", []))
    assert all(item.get("slot") != "body" for item in projected.get("public_timeline_delta", []))


def test_projector_does_not_create_generic_done_status_without_summary() -> None:
    projected = project_public_projection_event(
        "done",
        {
            "content": "Done content must not become a generic status.",
            "answer_channel": "conversation",
        },
        session_id="session-envelope",
        sequence=10,
    )

    envelope = projected["public_projection_envelope"]
    assert envelope.get("items", []) == []
    assert "public_timeline_delta" not in projected


def test_typed_assistant_stream_events_do_not_duplicate_body_items() -> None:
    for event_type in ("assistant_text_delta", "assistant_text_final", "assistant_stream_repair"):
        projected = project_public_projection_event(
            event_type,
            {
                "content": "typed stream text",
                "answer_channel": "conversation",
                "answer_source": "model",
            },
            session_id="session-envelope",
            sequence=4,
        )

        envelope = projected["public_projection_envelope"]
        assert envelope["source_authority"] == "model"
        assert envelope["surface"] == "assistant_body"
        assert envelope.get("items", []) == []
        assert "public_timeline_delta" not in projected


def test_typed_assistant_stream_events_ignore_stale_payload_delta() -> None:
    projected = project_public_projection_event(
        "assistant_text_delta",
        {
            "content": "typed stream text",
            "answer_channel": "conversation",
            "answer_source": "model",
            "public_timeline_delta": [
                {
                    "item_id": "stale-body",
                    "kind": "assistant_text",
                    "slot": "body",
                    "surface": "assistant_body",
                    "source_authority": "model",
                    "text": "stale payload body must not be projected",
                    "state": "running",
                }
            ],
        },
        session_id="session-envelope",
        sequence=5,
    )

    envelope = projected["public_projection_envelope"]
    assert envelope.get("items", []) == []
    assert "public_timeline_delta" not in projected


def test_public_anchor_is_honored_by_projection_envelope() -> None:
    projected = project_public_projection_event(
        "runtime_status",
        {
            "title": "等待继续",
            "detail": "任务已进入等待队列。",
            "state": "waiting",
        },
        public_anchor={
            "anchor_turn_id": "turn:session-envelope:42",
            "task_run_id": "taskrun:turn:session-envelope:42:abc",
            "turn_run_id": "turnrun:turn:session-envelope:42",
            "run_id": "taskrun:turn:session-envelope:42:abc",
        },
        sequence=12,
    )

    anchor = projected["public_projection_envelope"]["anchor"]
    assert anchor["turn_id"] == "turn:session-envelope:42"
    assert anchor["task_run_id"] == "taskrun:turn:session-envelope:42:abc"
    assert anchor["turn_run_id"] == "turnrun:turn:session-envelope:42"


def test_waiting_safe_boundary_is_projected_as_waiting_lifecycle() -> None:
    envelope = build_public_projection_envelope(
        "runtime_status",
        {
            "state": "waiting_safe_boundary",
            "active_turn": {
                "turn_id": "turn:session-envelope:safe-boundary",
                "state": "waiting_safe_boundary",
            },
        },
        session_id="session-envelope",
        sequence=18,
    )

    assert envelope["lifecycle"] == "waiting"
    assert envelope["active_turn_update"] == {
        "turn_id": "turn:session-envelope:safe-boundary",
        "state": "waiting_safe_boundary",
    }


def test_runtime_monitor_public_delta_carries_projection_envelope() -> None:
    projected = project_runtime_monitor_event_public_delta(
        {
            "event_id": "rtevt:envelope",
            "run_id": "taskrun:turn:session-envelope:2:abc",
            "event_type": "model_action_request_received",
            "offset": 3,
            "created_at": 1.0,
            "payload": {
                "model_action_request": {
                    "request_id": "act:respond",
                    "action_type": "respond",
                    "public_progress_note": "I have enough context to continue.",
                },
            },
            "refs": {"action_request_ref": "act:respond"},
            "authority": "orchestration.runtime_event",
        }
    )

    envelope = projected["public_projection_envelope"]
    assert envelope["authority"] == PUBLIC_PROJECTION_ENVELOPE_AUTHORITY
    assert envelope["sequence"] == 3
    assert envelope["anchor"]["turn_id"] == "turn:session-envelope:2"
    assert envelope["anchor"]["task_run_id"] == "taskrun:turn:session-envelope:2:abc"
    assert envelope["items"]


def test_generic_request_task_run_progress_is_not_projected_as_model_body() -> None:
    delta = project_public_timeline_delta(
        "model_action_admission",
        {
            "event": {
                "event_id": "rtevt:request-task",
                "payload": {
                    "model_action_request": {
                        "request_id": "act:request-task",
                        "action_type": "request_task_run",
                        "public_progress_note": "正在建立任务运行。",
                        "public_action_state": {
                            "next_action": "正在建立任务运行。",
                        },
                    }
                },
            }
        },
    )

    assert delta == []


def test_tool_admission_can_carry_model_opening_judgment_and_tool_window() -> None:
    projected = project_public_projection_event(
        "model_action_admission",
        {
            "event": {
                "event_id": "rtevt:tool-opening",
                "payload": {
                    "model_action_request": {
                        "request_id": "act:tool-opening",
                        "action_type": "tool_call",
                        "public_action_state": {
                            "current_judgment": "我会先确认 docs 目录是否存在，再决定是否读取计划文件。",
                        },
                        "tool_call": {
                            "name": "path_exists",
                            "args": {"path": "docs"},
                        },
                    }
                },
            }
        },
        session_id="session-envelope",
        sequence=13,
    )

    envelope = projected["public_projection_envelope"]
    assert envelope["source_authority"] == "model"
    assert envelope["surface"] == "assistant_body"
    assert any(item.get("slot") == "body" and "确认 docs 目录" in item.get("text", "") for item in envelope["items"])
    assert any(item.get("slot") == "tool" and item.get("surface") == "tool_window" for item in envelope["items"])


def test_chat_public_projection_sanitizes_model_action_admission_event() -> None:
    projected = _project_public_stream_event(
        "model_action_admission",
        {
            "type": "model_action_admission",
            "event": {
                "event_id": "rtevt:api-tool-opening",
                "payload": {
                    "model_action_request": {
                        "authority": "harness.loop.model_action_request",
                        "request_id": "act:api-tool-opening",
                        "action_type": "tool_call",
                        "public_action_state": {
                            "current_judgment": "我会先确认 docs 目录是否存在。",
                        },
                        "tool_call": {
                            "name": "path_exists",
                            "args": {"path": "docs"},
                        },
                    },
                    "admission": {"decision": "allow"},
                },
            },
        },
    )

    assert projected is not None
    public_event_type, data = projected
    assert public_event_type == "model_action_admission"
    assert "event" not in data
    assert "model_action_request" not in str(data)
    assert "harness.loop.model_action_request" not in str(data)
    assert data["public_action"]["kind"] == "tool"
    assert data["public_action"]["action_state"]["current_judgment"] == "我会先确认 docs 目录是否存在。"

    _attach_public_projection_envelope(public_event_type, data, session_id="session-envelope", sequence=14)
    envelope = data["public_projection_envelope"]
    assert any(item.get("slot") == "body" and "确认 docs 目录" in item.get("text", "") for item in envelope["items"])
    assert any(item.get("slot") == "tool" and item.get("surface") == "tool_window" for item in envelope["items"])


def test_chat_public_projection_keeps_task_admission_out_of_model_body() -> None:
    projected = _project_public_stream_event(
        "model_action_admission",
        {
            "type": "model_action_admission",
            "event": {
                "event_id": "rtevt:api-task-admission",
                "payload": {
                    "model_action_request": {
                        "authority": "harness.loop.model_action_request",
                        "request_id": "act:api-task",
                        "action_type": "request_task_run",
                        "public_progress_note": "正在建立任务运行。",
                        "public_action_state": {
                            "next_action": "正在建立任务运行。",
                        },
                        "task_contract_seed": {
                            "user_visible_goal": "修复投影",
                            "task_run_goal": "修复投影",
                            "completion_criteria": ["控制命令不泄露"],
                        },
                    },
                    "admission": {"decision": "allow"},
                },
            },
        },
    )

    assert projected is not None
    public_event_type, data = projected
    assert data["public_action"] == {"kind": "task"}
    assert "正在建立任务运行" not in str(data)
    _attach_public_projection_envelope(public_event_type, data, session_id="session-envelope", sequence=15)
    envelope = data["public_projection_envelope"]
    assert envelope["source_authority"] == "system"
    assert envelope["surface"] == "control"
    assert envelope.get("items") in (None, [])
    assert "正在建立任务运行" not in str(envelope)


def test_chat_public_projection_drops_raw_model_action_request_events() -> None:
    assert _project_public_stream_event(
        "model_action_request",
        {
            "type": "model_action_request",
            "event": {
                "payload": {
                    "model_action_request": {
                        "authority": "harness.loop.model_action_request",
                        "action_type": "active_work_control",
                    }
                }
            },
        },
    ) is None
    assert _project_public_stream_event(
        "model_action_admission_checked",
        {
            "type": "model_action_admission_checked",
            "event": {
                "payload": {
                    "model_action_request": {
                        "authority": "harness.loop.model_action_request",
                        "action_type": "active_work_control",
                    }
                }
            },
        },
    ) is None


def test_chat_public_projection_sanitizes_control_terminal_reason() -> None:
    projected = _project_public_stream_event(
        "done",
        {
            "type": "done",
            "content": "",
            "answer_channel": "runtime_control",
            "answer_source": "harness.entrypoint.active_turn_steer",
            "terminal_reason": "pause_active_work",
        },
    )

    assert projected is not None
    _, data = projected
    assert data["terminal_reason"] == "work_control"
    assert "pause_active_work" not in str(data)


def test_chat_public_projection_drops_raw_agent_turn_terminal_event() -> None:
    assert _project_public_stream_event(
        "agent_turn_terminal",
        {
            "type": "agent_turn_terminal",
            "event": {
                "payload": {
                    "terminal_reason": "pause_active_work",
                    "model_action_request": {
                        "authority": "harness.loop.model_action_request",
                    },
                }
            },
        },
    ) is None


def test_active_task_steer_projection_uses_work_control_title_for_pause() -> None:
    projected = project_public_projection_event(
        "active_task_steer_accepted",
        {
            "summary": "已请求暂停当前工作。",
            "status": "accepted",
            "runtime_task_run_id": "taskrun:pause-projection",
        },
        session_id="session-envelope",
        sequence=16,
    )

    envelope = projected["public_projection_envelope"]
    assert envelope["source_authority"] == "system"
    assert envelope["surface"] == "status_bar"
    assert any(item.get("title") == "已暂停当前工作" and item.get("phase") == "work_control" for item in envelope["items"])
    assert "pause_active_work" not in str(envelope)


def test_done_task_steer_projection_keeps_pause_out_of_generic_steer_title() -> None:
    projected = project_public_projection_event(
        "done",
        {
            "completion_state": "task_steer_accepted",
            "summary": "好，我先停在这里。后面你说继续，我会从这里接着做。",
            "answer_channel": "runtime_control",
            "terminal_reason": "work_control",
            "runtime_task_run_id": "taskrun:pause-projection",
        },
        session_id="session-envelope",
        sequence=17,
    )

    envelope = projected["public_projection_envelope"]
    assert envelope["source_authority"] == "system"
    assert envelope["surface"] == "control"
    assert any(item.get("title") == "已暂停当前工作" and item.get("phase") == "work_control" for item in envelope["items"])
    assert "已收到补充要求" not in str(envelope["items"])


def test_runtime_monitor_projection_drops_control_agent_turn_terminal_event() -> None:
    projected = project_runtime_monitor_event_public_delta(
        {
            "event_id": "rtevt:control-terminal",
            "run_id": "turnrun:turn:session-envelope:8",
            "event_type": "agent_turn_terminal",
            "offset": 18,
            "created_at": 1.0,
            "payload": {
                "status": "completed",
                "terminal_reason": "pause_active_work",
                "completion_state": "task_steer_accepted",
                "summary": "好，我先停在这里。",
            },
            "refs": {"turn_ref": "turn:session-envelope:8"},
            "authority": "orchestration.runtime_event",
        }
    )

    assert projected == {}
