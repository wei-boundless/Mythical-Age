from __future__ import annotations

from harness.loop.model_action_protocol import TaskExecutionModelActionRequest
from harness.loop.task_executor import _action_progress_note
from harness.runtime.public_progress import public_action_progress_summary, public_runtime_progress_summary


def test_public_progress_summary_suppresses_generic_control_text() -> None:
    for text in (
        "开始处理",
        "处理完成",
        "正在处理当前请求。",
        "工具调用已完成，正在根据结果继续。",
        "工具返回成功，正在根据结果继续。",
        "正在整理回复。",
    ):
        assert public_runtime_progress_summary(text) == ""


def test_action_progress_note_does_not_fallback_to_action_type() -> None:
    action = TaskExecutionModelActionRequest(
        request_id="model-action:test:no-public-feedback",
        turn_id="taskrun:test:no-public-feedback",
        action_type="tool_call",
        tool_calls=({"tool_name": "read_file", "args": {"path": "README.md"}},),
    )

    assert public_action_progress_summary(action.action_type) == ""
    assert _action_progress_note(action) == ""
