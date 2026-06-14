from __future__ import annotations

from harness.loop.task_executor import _step_summary_diagnostics_update


def test_trace_only_tool_summary_does_not_overwrite_public_progress() -> None:
    update = _step_summary_diagnostics_update(
        step="tool_observation:agent_todo",
        status="completed",
        summary='{"items":[{"todo_id":"todo:1"}]}',
        public_progress_note="",
        agent_brief_output='{"items":[{"todo_id":"todo:1"}]}',
        public_action_state={},
        current_judgment="",
        next_action="",
        completion_status="",
        presentation_source="tool_observation.summary",
        tool_name="agent_todo",
    )

    assert update["latest_tool_observation_trace"].startswith('{"items"')
    assert "latest_public_progress_note" not in update
    assert "latest_public_status" not in update
    assert "agent_brief_output" not in update


def test_trace_only_user_steer_status_does_not_overwrite_public_progress() -> None:
    update = _step_summary_diagnostics_update(
        step="active_task_steer_recorded",
        status="running",
        summary="已收到你的补充说明，会在后续处理里优先纳入。",
        public_progress_note="",
        agent_brief_output="",
        public_action_state={},
        current_judgment="",
        next_action="",
        completion_status="",
        presentation_source="system.user_steer_status",
        tool_name="",
    )

    assert "latest_public_progress_note" not in update
    assert "latest_public_status" not in update
    assert update["latest_step_summary"] == ""


def test_model_stage_summary_updates_public_and_model_diagnostics() -> None:
    update = _step_summary_diagnostics_update(
        step="model_action_received:3",
        status="running",
        summary="fallback summary",
        public_progress_note="",
        agent_brief_output="",
        public_action_state={"current_judgment": "已确认目标文件完整可用。"},
        current_judgment="已确认目标文件完整可用。",
        next_action="执行精确修改。",
        completion_status="working",
        presentation_source="model_action.current_judgment",
        tool_name="",
    )

    assert update["latest_public_status"] == "已确认目标文件完整可用。"
    assert update["latest_model_judgment"] == "已确认目标文件完整可用。"
    assert update["latest_next_action"] == "执行精确修改。"
    assert update["latest_completion_status"] == "working"
