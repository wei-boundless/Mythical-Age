from __future__ import annotations

from harness.loop.model_action_protocol import task_execution_action_request_from_payload


def test_task_execution_accepts_canonical_tool_calls_array() -> None:
    action, diagnostics = task_execution_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:test:batch",
            "turn_id": "taskrun:test:batch",
            "action_type": "tool_call",
            "public_progress_note": "准备并行读取相关文件。",
            "public_action_state": {
                "current_judgment": "需要先查看两个文件。",
                "next_action": "读取 README.md 和 pyproject.toml。",
            },
            "tool_calls": [
                {"tool_name": "read_file", "args": {"path": "README.md"}},
                {"tool_name": "read_file", "args": {"path": "pyproject.toml"}},
            ],
        },
        turn_id="taskrun:test:batch",
        allowed_action_types=("respond", "ask_user", "tool_call", "block"),
    )

    assert diagnostics["status"] == "accepted"
    assert action is not None
    assert len(action.tool_calls) == 2
    assert action.tool_call["tool_name"] == "read_file"
    assert action.tool_calls[1]["args"]["path"] == "pyproject.toml"
    assert len(action.to_dict()["tool_calls"]) == 2


def test_task_execution_rejects_single_tool_call_without_tool_calls_array() -> None:
    action, diagnostics = task_execution_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:test:single",
            "turn_id": "taskrun:test:single",
            "action_type": "tool_call",
            "public_progress_note": "准备读取文件。",
            "public_action_state": {
                "current_judgment": "需要读取文件。",
                "next_action": "调用 read_file。",
            },
            "tool_call": {"tool_name": "read_file", "args": {"path": "README.md"}},
        },
        turn_id="taskrun:test:single",
        allowed_action_types=("respond", "ask_user", "tool_call", "block"),
    )

    assert action is None
    assert diagnostics["status"] == "invalid"
    assert "tool_calls_required_for_tool_call" in diagnostics["validation_errors"]


def test_task_execution_rejects_any_single_tool_call_shadow_when_tool_calls_array_is_present() -> None:
    action, diagnostics = task_execution_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:test:conflict",
            "turn_id": "taskrun:test:conflict",
            "action_type": "tool_call",
            "public_progress_note": "准备读取文件。",
            "public_action_state": {
                "current_judgment": "需要读取文件。",
                "next_action": "调用 read_file。",
            },
            "tool_call": {"tool_name": "read_file", "args": {"path": "README.md"}},
            "tool_calls": [{"tool_name": "read_file", "args": {"path": "README.md"}}],
        },
        turn_id="taskrun:test:conflict",
        allowed_action_types=("respond", "ask_user", "tool_call", "block"),
    )

    assert action is None
    assert diagnostics["status"] == "invalid"
    assert "tool_call_and_tool_calls_cannot_both_be_present" in diagnostics["validation_errors"]
