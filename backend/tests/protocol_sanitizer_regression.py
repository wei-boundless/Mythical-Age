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


def test_protocol_sanitizer_preserves_assistant_reasoning_for_deepseek_prompt_history() -> None:
    result = sanitize_messages_for_prompt(
        [
            {"role": "user", "content": "读文件。"},
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "private hidden reasoning",
                "tool_calls": [{"id": "call-read", "name": "read_file", "args": {"path": "README.md"}}],
            },
            {"role": "tool", "tool_call_id": "call-read", "content": "done"},
            {"role": "assistant", "content": "", "reasoning_content": "reasoning-only should be preserved"},
        ],
        source="test",
    )

    messages = [dict(item) for item in result.messages]

    assert [item["role"] for item in messages] == ["user", "assistant", "tool", "assistant"]
    assert messages[1]["reasoning_content"] == "private hidden reasoning"
    assert messages[3]["reasoning_content"] == "reasoning-only should be preserved"
    assert result.diagnostics["dropped_empty_messages"] == 0


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


def test_runtime_compiler_uses_provider_protocol_as_single_append_only_history_prefix() -> None:
    compiler = RuntimeCompiler()
    base_history = [
        {"role": "user", "content": "第一轮。", "message_id": "msg:user:1", "turn_id": "turn:1", "created_at": 1.0},
        {"role": "assistant", "content": "第一轮答复。", "message_id": "msg:assistant:1", "turn_id": "turn:1", "created_at": 4.0},
    ]
    next_history = [
        *base_history,
        {"role": "user", "content": "第二轮。", "message_id": "msg:user:2", "turn_id": "turn:2", "created_at": 5.0},
    ]
    base_api_transcript = [
        base_history[0],
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call-prefix", "name": "search_text", "args": {"query": "prefix"}}],
            "created_at": 2.0,
        },
        {"role": "tool", "tool_call_id": "call-prefix", "content": "prefix result", "created_at": 3.0},
        {**base_history[1], "reasoning_content": "reasoning must stay in provider protocol"},
    ]
    next_api_transcript = [
        *base_api_transcript,
        next_history[-1],
    ]

    first = compiler.compile_single_agent_turn_packet(
        session_id="session:protocol-prefix-lock",
        turn_id="turn:protocol-prefix-lock:1",
        agent_invocation_id="aginvoke:protocol-prefix-lock:1",
        user_message="继续。",
        history=base_history,
        session_context={"api_transcript": base_api_transcript},
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )
    second = compiler.compile_single_agent_turn_packet(
        session_id="session:protocol-prefix-lock",
        turn_id="turn:protocol-prefix-lock:2",
        agent_invocation_id="aginvoke:protocol-prefix-lock:2",
        user_message="继续。",
        history=next_history,
        session_context={"api_transcript": next_api_transcript},
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    first_segments = [dict(item) for item in list(first.packet.segment_plan.get("segments") or [])]
    second_segments = [dict(item) for item in list(second.packet.segment_plan.get("segments") or [])]
    first_kinds = [str(item.get("kind") or "") for item in first_segments]
    second_kinds = [str(item.get("kind") or "") for item in second_segments]

    assert "provider_protocol_history" in first_kinds
    assert "provider_protocol_history" in second_kinds
    assert "session_history_entry" in first_kinds
    assert "session_history_entry" in second_kinds

    first_stable = _stable_prefix_signature(first_segments)
    second_stable = _stable_prefix_signature(second_segments)
    assert first_stable == second_stable[: len(first_stable)]


def _stable_prefix_signature(segments: list[dict]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for segment in segments:
        if str(segment.get("cache_role") or "") not in {"cacheable_prefix", "session_stable"}:
            continue
        if str(segment.get("prefix_tier") or "") in {"volatile", "none"}:
            continue
        result.append((str(segment.get("kind") or ""), str(segment.get("content_hash") or "")))
    return result
