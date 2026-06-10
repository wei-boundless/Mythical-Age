from __future__ import annotations

from harness.runtime.projection.authority import PUBLIC_PROJECTION_AUTHORITY
from harness.runtime.projection.projector import project_public_projection_event
from harness.runtime.projection.timeline_builder import project_runtime_monitor_event_public_delta


def test_model_body_requires_model_source_and_assistant_body_surface():
    projected = project_public_projection_event(
        "model_action_admission",
        {
            "model_action_request": {
                "action_type": "tool_call",
                "public_progress_note": "我先确认投影链路的正文归属。",
                "tool_call": {"tool_name": "read_file", "args": {"path": "backend/harness/runtime/session_timeline.py"}},
            },
            "public_anchor": {"turn_id": "turn:test", "task_run_id": "taskrun:turn:test:abc"},
        },
        sequence=1,
    )

    envelope = projected["public_projection_envelope"]
    assert envelope["authority"] == PUBLIC_PROJECTION_AUTHORITY
    assert envelope["items"][0]["kind"] == "opening_judgment"
    assert envelope["items"][0]["source_authority"] == "model"
    assert envelope["items"][0]["surface"] == "assistant_body"
    assert envelope["items"][1]["surface"] == "tool_window"


def test_public_action_projects_model_body_and_tool_window_from_same_model_action():
    projected = project_public_projection_event(
        "model_action_admission",
        {
            "public_action": {
                "kind": "tool",
                "progress_note": "我先读取配置和测试入口，再判断为什么正文没有显示。",
                "action_state": {
                    "current_judgment": "当前需要先核对前端投影链路和后端事件结构。",
                    "next_action": "读取投影相关文件。",
                    "completion_status": "waiting_for_tool",
                },
                "tool": {
                    "tool_name": "read_file",
                    "target": "frontend/src/lib/store/events.ts",
                },
            },
            "public_anchor": {"turn_id": "turn:test", "task_run_id": "taskrun:turn:test:abc"},
        },
        sequence=1,
    )

    items = projected["public_projection_envelope"]["items"]
    assert items[0]["kind"] == "opening_judgment"
    assert items[0]["surface"] == "assistant_body"
    assert items[0]["source_authority"] == "model"
    assert items[0]["text"] == "当前需要先核对前端投影链路和后端事件结构。"
    assert items[1]["surface"] == "tool_window"
    assert items[1]["source_authority"] == "tool"


def test_task_control_done_is_hidden_control_not_body():
    projected = project_public_projection_event(
        "done",
        {
            "answer_channel": "task_control",
            "terminal_reason": "task_executor_scheduled",
            "public_anchor": {"turn_id": "turn:test", "task_run_id": "taskrun:turn:test:abc"},
        },
        sequence=2,
    )

    envelope = projected["public_projection_envelope"]
    assert envelope["surface"] == "control"
    assert envelope["terminal"] == {"event": "done", "visible": False, "reason": "task_executor_scheduled"}
    assert envelope.get("items", []) == []


def test_tool_boolean_observation_is_public_tool_fact_not_raw_boolean_body():
    projected = project_public_projection_event(
        "task_tool_observation_recorded",
        {
            "event": {
                "event_id": "event:path",
                "payload": {
                    "observation": {
                        "tool_name": "path_exists",
                        "target": "README.md",
                        "result": True,
                    }
                },
            },
            "public_anchor": {"turn_id": "turn:test", "task_run_id": "taskrun:turn:test:abc"},
        },
        sequence=3,
    )

    items = projected["public_projection_envelope"]["items"]
    assert len(items) == 1
    assert items[0]["surface"] == "tool_window"
    assert items[0]["source_authority"] == "tool"
    assert items[0]["observation"] == "目标路径存在"
    assert "true" not in str(items[0]).lower()


def test_tool_line_numbered_observation_is_not_promoted_to_public_body_or_observation():
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


def test_runtime_monitor_projection_uses_new_authority():
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
    assert envelope["items"][0]["source_authority"] == "model"
    assert envelope["items"][0]["surface"] == "assistant_body"
