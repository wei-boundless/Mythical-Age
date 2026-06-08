from __future__ import annotations

from runtime.model_gateway.assistant_stream_frame import content_sha256, utf8_byte_length
from runtime.model_gateway.assistant_stream_normalizer import AssistantStreamNormalizer


def test_assistant_stream_normalizer_uses_utf8_offsets_for_cjk_and_emoji() -> None:
    normalizer = AssistantStreamNormalizer(
        stream_ref="modelreq:test",
        message_ref="turn:test:assistant",
        max_flush_interval_ms=0,
    )

    events = normalizer.observe_delta("你好🙂，")

    assert [event["type"] for event in events] == ["assistant_text_delta"]
    frame = events[0]
    assert frame["content"] == "你好🙂，"
    assert frame["content_utf8_start"] == 0
    assert frame["content_utf8_end"] == utf8_byte_length("你好🙂，")
    assert frame["accumulated_utf8_bytes"] == utf8_byte_length("你好🙂，")
    assert frame["accumulated_sha256"] == content_sha256("你好🙂，")


def test_assistant_stream_normalizer_blocks_json_action_prefix() -> None:
    normalizer = AssistantStreamNormalizer(
        stream_ref="modelreq:test",
        message_ref="turn:test:assistant",
        max_flush_interval_ms=0,
    )

    assert normalizer.observe_delta('{"action_type": "respond", ') == []
    assert normalizer.observe_delta('"final_answer": "不要提前显示"}') == []
    assert normalizer.diagnostics().safety_gate_blocked_total == 1


def test_assistant_stream_normalizer_flushes_pending_text_without_ui_sleep() -> None:
    normalizer = AssistantStreamNormalizer(
        stream_ref="modelreq:test",
        message_ref="turn:test:assistant",
        max_flush_interval_ms=10_000,
    )

    assert normalizer.observe_delta("这是一个没有标点的短句") != []
    assert normalizer.flush() != []
    assert normalizer.emitted_content == "这是一个没有标点的短句"
