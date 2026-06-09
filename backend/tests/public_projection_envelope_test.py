from __future__ import annotations

from api.chat import _attach_public_projection_envelope
from harness.runtime.public_projection_envelope import (
    PUBLIC_PROJECTION_ENVELOPE_AUTHORITY,
    build_public_projection_envelope,
)
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
                "surface": "body",
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
            "surface": "body",
            "source_authority": "model",
            "text": "I will inspect the current chain first.",
            "state": "running",
            "slot": "body",
        }
    ]


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
