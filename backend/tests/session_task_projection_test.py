from __future__ import annotations

from types import SimpleNamespace

from harness.runtime.projection.task_projection import build_single_agent_task_projection


def test_task_projection_does_not_surface_raw_boolean_latest_summary():
    task_run = SimpleNamespace(
        task_run_id="taskrun:turn:test:abc",
        task_id="task:turn:test",
        status="running",
        diagnostics={
            "turn_id": "turn:test",
            "summary": "true",
            "contract": {"user_visible_goal": "检查投影链路"},
        },
        created_at=1.0,
        updated_at=2.0,
    )

    projection = build_single_agent_task_projection(
        None,
        task_run,
        events=[],
        monitor={"latest_step_summary": "true", "latest_public_progress_note": "true"},
        anchor_turn_id="turn:test",
        anchor_message_id="assistant:test",
    )

    assert projection["authority"] == "harness.runtime.single_agent_task_projection"
    assert projection["anchor_turn_id"] == "turn:test"
    assert projection.get("current_action", {}) == {}
    assert "true" not in str(projection.get("summary", "")).lower()


def test_task_projection_keeps_tool_observation_on_tool_surface():
    task_run = SimpleNamespace(
        task_run_id="taskrun:turn:test:abc",
        task_id="task:turn:test",
        status="running",
        diagnostics={"turn_id": "turn:test"},
        created_at=1.0,
        updated_at=2.0,
    )

    projection = build_single_agent_task_projection(
        None,
        task_run,
        events=[
            {
                "event_id": "event:tool",
                "event_type": "task_tool_observation_recorded",
                "payload": {
                    "observation": {
                        "tool_name": "path_exists",
                        "summary": "目标路径存在",
                    }
                },
            }
        ],
        monitor={},
        anchor_turn_id="turn:test",
        anchor_message_id="assistant:test",
    )

    assert projection["activities"][0]["display_surface"] == "tool_window"
    assert projection["activities"][0]["kind"] == "tool_observation"

