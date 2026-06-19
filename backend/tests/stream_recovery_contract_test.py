from __future__ import annotations

from types import SimpleNamespace

from runtime.model_gateway.model_runtime import ModelRuntimeError
from runtime.model_gateway.stream_recovery import (
    VISIBLE_PREFIX_RECOVERY_MODE,
    build_visible_prefix_recovery_messages,
    build_visible_prefix_recovery_segment_plan,
    continuation_after_visible_prefix,
    model_selection_for_visible_prefix_recovery,
    should_recover_partial_visible_stream,
)
from runtime.model_gateway.model_request import ModelRequestBuilder
from runtime.prompt_accounting.serializer import CanonicalPromptSerializer


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


def test_visible_prefix_recovery_segment_plan_covers_appended_recovery_messages() -> None:
    base_segment_plan = {
        "segments": [
            {
                "segment_id": "seg:base:1",
                "kind": "global_static",
                "ordinal": 1,
                "model_message_index": 0,
                "model_message_role": "system",
                "source_ref": "test.system",
                "cache_scope": "global",
                "cache_role": "cacheable_prefix",
                "prefix_tier": "provider_global",
                "compression_role": "preserve",
            },
            {
                "segment_id": "seg:base:2",
                "kind": "volatile_user",
                "ordinal": 2,
                "model_message_index": 1,
                "model_message_role": "user",
                "source_ref": "test.user",
                "cache_scope": "none",
                "cache_role": "volatile",
                "prefix_tier": "volatile",
                "compression_role": "summarize",
            },
        ]
    }
    recovery_messages = build_visible_prefix_recovery_messages(
        [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Continue the report."},
        ],
        visible_prefix="Already visible",
        turn_id="turn:prefix",
        source="test.visible_prefix_recovery",
    )
    recovery_segment_plan = build_visible_prefix_recovery_segment_plan(
        base_segment_plan=base_segment_plan,
        recovery_messages=recovery_messages,
        packet_id="packet:visible-prefix",
        recovery_attempt=1,
        source="test.visible_prefix_recovery",
    )
    model_request = ModelRequestBuilder().build(
        request_id="modelreq:visible-prefix-recovery",
        messages=recovery_messages,
        tools=[],
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=recovery_segment_plan,
    )
    segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id="modelreq:visible-prefix-recovery",
        messages=recovery_messages,
        tools=[],
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=recovery_segment_plan,
        model_request=model_request,
    )
    kinds = [str(item.get("kind") or "") for item in recovery_segment_plan["segments"]]

    assert kinds == [
        "global_static",
        "volatile_user",
        "partial_stream_recovery_instruction",
        "partial_stream_recovery_visible_prefix",
    ]
    assert model_request.diagnostics["unplanned_message_count"] == 0
    assert all(segment.kind != "unknown_unplanned" for segment in segment_map.segments)
    assert segment_map.segments[-2].cache_role == "volatile"
    assert segment_map.segments[-1].cache_role == "volatile"


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
