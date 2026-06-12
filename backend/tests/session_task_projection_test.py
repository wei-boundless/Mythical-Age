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


def test_task_projection_keeps_runtime_rehydration_tool_observation_visible():
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
                "event_id": "event:tool-error",
                "event_type": "task_tool_observation_recorded",
                "payload": {
                    "observation": {
                        "source": "tool:read_persisted_tool_result",
                        "payload": {
                            "tool_name": "read_persisted_tool_result",
                            "result": '{"ok": false, "error": "missing_required_tool_inputs"}',
                        },
                        "error": "missing_required_tool_inputs",
                    }
                },
            }
        ],
        monitor={},
        anchor_turn_id="turn:test",
        anchor_message_id="assistant:test",
    )

    activity = projection["activities"][0]
    assert activity["display_surface"] == "tool_window"
    assert activity["kind"] == "tool_observation"
    assert activity["tool_name"] == "read_persisted_tool_result"
    assert activity["title"] == "工具输出读取失败"
    assert activity["detail"] == "missing_required_tool_inputs"


def test_task_projection_keeps_task_tool_observation_step_summary_when_it_is_the_only_output():
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
                "event_id": "event:tool-step",
                "event_type": "step_summary_recorded",
                "payload": {
                    "step": "task_tool_observation_recorded:3",
                    "status": "running",
                    "summary": "工具结果已返回，可以继续整理页面实现。",
                    "agent_brief_output": "工具结果已返回，可以继续整理页面实现。",
                },
            }
        ],
        monitor={},
        anchor_turn_id="turn:test",
        anchor_message_id="assistant:test",
    )

    assert projection["activities"][0]["kind"] == "progress"
    assert projection["activities"][0]["title"] == "工具结果已返回，可以继续整理页面实现。"


def test_task_projection_ignores_system_tool_step_summaries():
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
                "event_id": "event:batch",
                "event_type": "step_summary_recorded",
                "payload": {
                    "step": "task_tool_batch_started:2",
                    "status": "running",
                    "summary": "执行 2 个工具调用：读取目录 backend/、搜索文本 invocation_kind。",
                    "presentation_source": "system.tool_call_status",
                },
            },
            {
                "event_id": "event:repair",
                "event_type": "step_summary_recorded",
                "payload": {
                    "step": "task_tool_repair_required:2",
                    "status": "running",
                    "summary": "工具调用失败，正在根据失败原因调整处理路径。",
                },
            },
        ],
        monitor={},
        anchor_turn_id="turn:test",
        anchor_message_id="assistant:test",
    )

    visible = str(projection)
    assert projection.get("activities", []) == []
    assert projection.get("current_action", {}) == {}
    assert "执行 2 个工具调用" not in visible
    assert "工具调用失败" not in visible


def test_waiting_executor_projection_does_not_promote_stale_running_step_to_current_action():
    task_run = SimpleNamespace(
        task_run_id="taskrun:turn:test:abc",
        task_id="task:turn:test",
        status="waiting_executor",
        diagnostics={
            "turn_id": "turn:test",
            "latest_step_summary": "后端运行时已重启，当前工作已恢复为可继续状态。",
            "executor_status": "waiting_executor",
        },
        created_at=1.0,
        updated_at=2.0,
    )

    projection = build_single_agent_task_projection(
        None,
        task_run,
        events=[
            {
                "event_id": "event:stale-running-step",
                "event_type": "step_summary_recorded",
                "payload": {
                    "step": "task_tool_batch_group_started",
                    "status": "running",
                    "summary": "正在执行工具批次",
                },
            }
        ],
        monitor={},
        anchor_turn_id="turn:test",
        anchor_message_id="assistant:test",
    )

    assert projection["status"] == "waiting"
    assert projection["phase"] == "waiting_executor"
    assert projection["current_action"]["state"] == "waiting"
    assert projection["current_action"].get("event_ref") != "event:stale-running-step"
    assert {item.get("state") for item in projection.get("activities", [])} == {"waiting"}


def test_waiting_executor_runtime_restart_uses_recovery_action_not_stale_judgment():
    task_run = SimpleNamespace(
        task_run_id="taskrun:turn:test:abc",
        task_id="task:turn:test",
        status="waiting_executor",
        diagnostics={
            "turn_id": "turn:test",
            "latest_current_judgment": "正在读取掉线前的旧文件。",
            "latest_next_action": "继续掉线前的旧步骤。",
            "latest_step": "task_executor_recovered_after_runtime_start",
            "latest_step_summary": "后端运行时已重启，当前任务可继续。",
            "latest_public_progress_note": "后端运行时已重启，当前任务可继续。",
            "executor_status": "waiting_executor",
            "recoverable_error": {
                "error_code": "task_executor_interrupted_by_runtime_restart",
                "retryable": True,
                "user_message": "后端运行时已重启，任务可以继续续跑。",
            },
            "recovery_action": "rerun_task_executor",
        },
        created_at=1.0,
        updated_at=2.0,
    )

    projection = build_single_agent_task_projection(
        None,
        task_run,
        events=[
            {
                "event_id": "event:old-tool",
                "event_type": "step_summary_recorded",
                "payload": {
                    "step": "task_tool_observation_recorded:3",
                    "status": "running",
                    "summary": "掉线前的旧读取动作。",
                },
            }
        ],
        monitor={},
        anchor_turn_id="turn:test",
        anchor_message_id="assistant:test",
    )

    assert projection["status"] == "waiting"
    assert projection["phase"] == "waiting_executor"
    assert projection["current_action"]["kind"] == "lifecycle"
    assert projection["current_action"]["title"] == "后端运行时已重启，当前任务可继续。"
    assert projection["current_action"]["state"] == "waiting"
    assert "掉线前" not in projection["current_action"]["title"]


def test_waiting_executor_todo_current_action_uses_waiting_state():
    task_run = SimpleNamespace(
        task_run_id="taskrun:turn:test:abc",
        task_id="task:turn:test",
        status="waiting_executor",
        diagnostics={"turn_id": "turn:test", "executor_status": "waiting_executor"},
        created_at=1.0,
        updated_at=2.0,
    )

    projection = build_single_agent_task_projection(
        None,
        task_run,
        events=[
            {
                "event_id": "event:todo",
                "event_type": "agent_todo_initialized",
                "payload": {
                    "plan_id": "plan:test",
                    "active_item_id": "todo:one",
                    "items": [
                        {"todo_id": "todo:one", "content": "检查恢复边界", "status": "in_progress"},
                        {"todo_id": "todo:two", "content": "完成验证", "status": "pending"},
                    ],
                },
            }
        ],
        monitor={},
        anchor_turn_id="turn:test",
        anchor_message_id="assistant:test",
    )

    assert projection["current_action"]["kind"] == "todo"
    assert projection["current_action"]["state"] == "waiting"
    assert projection["todo"]["active_item_id"] == "todo:one"
