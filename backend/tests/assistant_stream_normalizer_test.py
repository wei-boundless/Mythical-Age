from __future__ import annotations

from runtime.model_gateway.assistant_stream_normalizer import AssistantStreamNormalizer


def test_assistant_stream_policy_controls_pending_utf8_slice_size() -> None:
    default_normalizer = AssistantStreamNormalizer.from_policy(
        stream_ref="stream:default",
        stream_policy={"max_flush_interval_ms": 1000},
    )
    tuned_normalizer = AssistantStreamNormalizer.from_policy(
        stream_ref="stream:tuned",
        stream_policy={
            "max_flush_interval_ms": 1000,
            "max_pending_utf8_bytes": 4,
        },
    )

    assert default_normalizer.observe_delta("abcdef") == []

    events = tuned_normalizer.observe_delta("abcdef")

    assert [event["content"] for event in events] == ["abcd"]


def test_assistant_stream_event_budget_limits_deltas_but_final_flush_drains() -> None:
    normalizer = AssistantStreamNormalizer.from_policy(
        stream_ref="stream:budget",
        stream_policy={
            "max_flush_interval_ms": 1000,
            "max_pending_utf8_bytes": 1,
            "event_budget_per_second": 1,
        },
    )

    first = normalizer.observe_delta("abc")
    second = normalizer.observe_delta("def")
    final = normalizer.flush()

    assert [event["content"] for event in first] == ["a"]
    assert second == []
    assert "".join(event["content"] for event in final) == "bcdef"


def test_assistant_stream_normalizer_reports_emitted_public_text() -> None:
    normalizer = AssistantStreamNormalizer.from_policy(
        stream_ref="stream:public-feedback",
        stream_policy={"max_flush_interval_ms": 0},
    )

    assert normalizer.has_emitted_public_text("我先读取 文件。") is False

    normalizer.observe_delta("我先读取\n文件。")
    normalizer.flush()

    assert normalizer.has_emitted_public_text("我先读取 文件。") is True
    assert normalizer.has_emitted_public_text("我先搜索文件。") is False
