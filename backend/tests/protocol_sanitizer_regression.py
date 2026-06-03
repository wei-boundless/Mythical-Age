from __future__ import annotations

from harness.runtime import RuntimeCompiler
from runtime.model_gateway.protocol_sanitizer import sanitize_messages_for_prompt


def test_protocol_sanitizer_injects_aborted_output_for_missing_tool_result() -> None:
    result = sanitize_messages_for_prompt(
        [
            {"role": "user", "content": "查一下日期。"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call-date", "name": "get_date", "args": {}}],
            },
            {"role": "assistant", "content": "我不能继续假装工具已返回。"},
        ],
        turn_id="turn:test:protocol",
        source="test",
    )

    messages = [dict(item) for item in result.messages]
    tool_message = messages[2]

    assert [item["role"] for item in messages] == ["user", "assistant", "tool", "assistant"]
    assert tool_message["tool_call_id"] == "call-date"
    assert tool_message["protocol_status"] == "aborted"
    assert result.diagnostics["injected_aborted_tool_outputs"] == 1


def test_protocol_sanitizer_drops_orphan_tool_output() -> None:
    result = sanitize_messages_for_prompt(
        [
            {"role": "user", "content": "你好。"},
            {"role": "tool", "tool_call_id": "orphan", "content": "孤儿结果"},
            {"role": "assistant", "content": "你好。"},
        ],
        source="test",
    )

    messages = [dict(item) for item in result.messages]

    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert "孤儿结果" not in str(messages)
    assert result.diagnostics["dropped_orphan_tool_outputs"] == 1


def test_runtime_compiler_sanitizes_provider_protocol_history() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:protocol-sanitizer",
        turn_id="turn:protocol-sanitizer:1",
        agent_invocation_id="aginvoke:protocol-sanitizer",
        user_message="继续。",
        history=[],
        session_context={
            "api_transcript": [
                {"role": "user", "content": "查杭州天气。"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": "call-weather", "name": "weather", "args": {"city": "杭州"}}],
                },
                {"role": "tool", "tool_call_id": "orphan", "content": "不应进入模型。"},
            ]
        },
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    messages = result.packet.model_messages
    protocol_roles = [str(item.get("role") or "") for item in messages if item.get("role") in {"assistant", "tool"}]
    tool_messages = [dict(item) for item in messages if item.get("role") == "tool"]

    assert protocol_roles == ["assistant", "tool"]
    assert tool_messages[0]["tool_call_id"] == "call-weather"
    assert "aborted" in tool_messages[0]["content"]
    assert "不应进入模型" not in str(messages)
    assert result.packet.diagnostics["protocol_sanitizer"]["dropped_orphan_tool_outputs"] == 0
