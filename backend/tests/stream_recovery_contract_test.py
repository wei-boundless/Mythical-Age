from __future__ import annotations

from types import SimpleNamespace

from runtime.model_gateway.model_runtime import ModelRuntimeError
from runtime.model_gateway.stream_recovery import (
    VISIBLE_PREFIX_RECOVERY_MODE,
    build_visible_prefix_recovery_messages,
    continuation_after_visible_prefix,
    model_selection_for_visible_prefix_recovery,
    should_recover_partial_visible_stream,
)


def test_visible_prefix_recovery_messages_end_with_assistant_prefix() -> None:
    messages = build_visible_prefix_recovery_messages(
        [
            {"role": "system", "content": "You are helpful."},
            SimpleNamespace(type="human", content="Continue the report."),
        ],
        visible_prefix="Already visible",
        turn_id="turn:prefix",
        source="test.visible_prefix_recovery",
    )

    assert messages[-1] == {
        "role": "assistant",
        "content": "Already visible",
        "turn_id": "turn:prefix",
        "prefix": True,
    }
    assert "不要重复已经公开的文字" in messages[-2]["content"]


def test_visible_prefix_recovery_model_selection_uses_deepseek_chat_prefix_and_disables_streaming() -> None:
    selection = model_selection_for_visible_prefix_recovery(
        {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "response_format": {"type": "json_object"},
            "structured_output": "json_object",
            "stream_policy": {"enabled": True, "max_flush_interval_ms": 16},
        }
    )

    assert "response_format" not in selection
    assert "structured_output" not in selection
    assert selection["stream_policy"] == {"enabled": False, "max_flush_interval_ms": 16}
    assert selection["completion_profile"] == {
        "mode": "chat_prefix",
        "provider_mode": "deepseek_chat_prefix",
        "source": "partial_stream_recovery",
    }


def test_visible_prefix_recovery_model_selection_can_override_default_model_spec() -> None:
    selection = model_selection_for_visible_prefix_recovery(None)

    assert selection["stream_policy"] == {"enabled": False}
    assert selection["completion_profile"]["mode"] == "chat_prefix"


def test_visible_prefix_recovery_requires_visible_plain_text_and_retryable_error() -> None:
    retryable_error = ModelRuntimeError(
        code="provider_unavailable",
        provider="deepseek",
        model="deepseek-chat",
        detail="stream disconnected",
        retryable=True,
        user_message="stream disconnected",
    )
    terminal_error = ModelRuntimeError(
        code="bad_request",
        provider="deepseek",
        model="deepseek-chat",
        detail="bad request",
        retryable=False,
        user_message="bad request",
    )

    assert should_recover_partial_visible_stream(
        {"partial_stream_recovery": VISIBLE_PREFIX_RECOVERY_MODE},
        raw_content="Already visible",
        emit_assistant_text_delta=True,
        require_json_action=False,
        error=retryable_error,
    ) is True
    assert should_recover_partial_visible_stream(
        {"partial_stream_recovery": VISIBLE_PREFIX_RECOVERY_MODE},
        raw_content="Already visible",
        emit_assistant_text_delta=True,
        require_json_action=False,
        error=terminal_error,
    ) is False
    assert should_recover_partial_visible_stream(
        {"partial_stream_recovery": VISIBLE_PREFIX_RECOVERY_MODE},
        raw_content='{"action_type":"respond"}',
        emit_assistant_text_delta=True,
        require_json_action=False,
        error=retryable_error,
    ) is False
    assert should_recover_partial_visible_stream(
        {"partial_stream_recovery": VISIBLE_PREFIX_RECOVERY_MODE},
        raw_content="Already visible",
        emit_assistant_text_delta=True,
        require_json_action=True,
        error=retryable_error,
    ) is False


def test_continuation_after_visible_prefix_removes_exact_or_overlap_prefix() -> None:
    assert continuation_after_visible_prefix("abc", "abcdef") == "def"
    assert continuation_after_visible_prefix("abc", "cdef") == "def"
    assert continuation_after_visible_prefix("abc", "xyz") == "xyz"
