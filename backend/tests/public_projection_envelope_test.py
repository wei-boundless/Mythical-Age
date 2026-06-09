from __future__ import annotations

from api.chat import _attach_public_projection_envelope
from harness.runtime.public_projection_envelope import (
    PUBLIC_PROJECTION_ENVELOPE_AUTHORITY,
    build_public_projection_envelope,
)
from harness.runtime.public_projection_projector import project_public_projection_event
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
