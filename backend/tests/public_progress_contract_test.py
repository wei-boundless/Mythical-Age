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


def test_public_progress_summary_suppresses_raw_line_numbered_tool_output() -> None:
    raw_output = "  1 | # LangChain-Agent 项目代码审查报告\n  2 | 这是工具读取的文件原文。"

    assert public_runtime_progress_summary(raw_output) == ""


def test_public_progress_summary_suppresses_runtime_private_artifact_paths() -> None:
    private_texts = (
        r"D:\AI应用\langchain-agent\backend\storage\task_environments\general\workspace\runtime_state\dynamic_context\replacements\replacement_4ce5ea91846e3d4e34ff823e.json",
        "storage/runtime_context/tool_results/session-fad8ee446.txt",
        "runtime_context/tool-results/session-fad8ee446.txt",
        "runtime_state/tool_results/session/content-secret.txt",
        "backend/mythical-agent/sessions/session-123/environments/coding/vibe-workspace/runtime_state/dynamic_context/replacements/replacement_e21050df8baca858bdde6a4d.json",
        "replacement_e21050df8baca858bdde6a4d.json",
        "replacement:e21050df8baca858bdde6a4d",
    )

    for text in private_texts:
        assert public_runtime_progress_summary(text) == ""


def test_public_progress_summary_suppresses_whole_tool_failure_text() -> None:
    tool_failures = (
        "Edit failed: old_text not found",
        "Edit failed: file does not exist",
        "Write failed: expected_previous_sha256 does not match current file",
        "Read failed: file does not exist",
        "tool_policy_rejection: Policy rejected before execution: requested_tool=write_file",
    )

    for text in tool_failures:
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
