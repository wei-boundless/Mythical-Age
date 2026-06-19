from __future__ import annotations

from harness.loop.single_agent_turn import _assistant_stream_continuity_after_event
import runtime.model_gateway.assistant_stream_normalizer as normalizer_module
from runtime.model_gateway.assistant_stream_normalizer import AssistantStreamNormalizer


class _FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def monotonic(self) -> float:
        return self.now

    def advance_ms(self, value: float) -> None:
        self.now += value / 1000.0


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
    assert [event["content"] for event in final] == ["b", "c", "d", "e", "f"]


def test_assistant_stream_typing_strategy_does_not_emit_whole_markdown_line() -> None:
    normalizer = AssistantStreamNormalizer.from_policy(
        stream_ref="stream:typing-markdown",
        stream_policy={
            "chunk_strategy": "typing",
            "max_flush_interval_ms": 0,
            "max_pending_utf8_bytes": 12,
        },
    )

    events = normalizer.observe_delta("- 这是一个很长的 Markdown 列表行，不应该整行吐出。\n")

    assert events
    assert events[0]["content"] != "- 这是一个很长的 Markdown 列表行，不应该整行吐出。\n"
    assert events[0]["content_utf8_bytes"] <= 12


def test_assistant_stream_passthrough_strategy_preserves_model_delta_rhythm() -> None:
    normalizer = AssistantStreamNormalizer.from_policy(
        stream_ref="stream:passthrough",
        stream_policy={
            "chunk_strategy": "passthrough",
            "max_flush_interval_ms": 1000,
            "max_pending_utf8_bytes": 1024,
            "min_event_interval_ms": 0,
            "event_budget_per_second": 0,
        },
    )

    delta = "模型一次返回的这一整段内容应该作为同一帧尽快投影，而不是被模拟打字切碎。"
    events = normalizer.observe_delta(delta)

    assert [event["content"] for event in events] == [delta]


def test_assistant_stream_passthrough_drains_oversized_model_delta_without_waiting() -> None:
    normalizer = AssistantStreamNormalizer.from_policy(
        stream_ref="stream:passthrough-oversized",
        stream_policy={
            "chunk_strategy": "passthrough",
            "max_flush_interval_ms": 1000,
            "max_pending_utf8_bytes": 4,
            "min_event_interval_ms": 0,
            "event_budget_per_second": 0,
        },
    )

    events = normalizer.observe_delta("abcdefghijkl")

    assert [event["content"] for event in events] == ["abcd", "efgh", "ijkl"]
    assert normalizer.flush() == []


def test_assistant_stream_adaptive_buffer_delays_until_first_flush_window(monkeypatch) -> None:
    clock = _FakeClock()
    monkeypatch.setattr(normalizer_module.time, "monotonic", clock.monotonic)
    normalizer = AssistantStreamNormalizer.from_policy(
        stream_ref="stream:adaptive-first",
        stream_policy={
            "chunk_strategy": "adaptive_buffer",
            "first_flush_delay_ms": 70,
            "target_buffer_delay_ms": 150,
            "adaptive_min_buffer_delay_ms": 80,
            "adaptive_max_buffer_delay_ms": 240,
            "max_release_utf8_bytes": 64,
        },
    )

    assert normalizer.observe_delta("你好") == []
    clock.advance_ms(69)
    assert normalizer.drain_due() == []
    clock.advance_ms(2)
    events = normalizer.drain_due()

    assert [event["content"] for event in events] == ["你好"]


def test_assistant_stream_adaptive_due_tick_releases_without_new_provider_chunk(monkeypatch) -> None:
    clock = _FakeClock()
    monkeypatch.setattr(normalizer_module.time, "monotonic", clock.monotonic)
    normalizer = AssistantStreamNormalizer.from_policy(
        stream_ref="stream:adaptive-tick",
        stream_policy={
            "chunk_strategy": "adaptive_buffer",
            "first_flush_delay_ms": 0,
            "adaptive_min_buffer_delay_ms": 80,
            "adaptive_max_buffer_delay_ms": 80,
            "max_release_utf8_bytes": 64,
        },
    )

    assert [event["content"] for event in normalizer.observe_delta("我")] == ["我"]
    clock.advance_ms(50)
    assert normalizer.observe_delta("正在") == []
    clock.advance_ms(79)
    assert normalizer.drain_due() == []
    clock.advance_ms(2)
    events = normalizer.drain_due()

    assert [event["content"] for event in events] == ["正在"]


def test_assistant_stream_adaptive_slices_large_due_delta(monkeypatch) -> None:
    clock = _FakeClock()
    monkeypatch.setattr(normalizer_module.time, "monotonic", clock.monotonic)
    normalizer = AssistantStreamNormalizer.from_policy(
        stream_ref="stream:adaptive-large",
        stream_policy={
            "chunk_strategy": "adaptive_buffer",
            "first_flush_delay_ms": 10,
            "max_release_utf8_bytes": 4,
            "max_pending_utf8_bytes": 64,
        },
    )

    assert normalizer.observe_delta("abcdefghijkl") == []
    clock.advance_ms(10)
    first = normalizer.drain_due()
    second = normalizer.flush()

    assert [event["content"] for event in first] == ["abcd"]
    assert [event["content"] for event in second] == ["efgh", "ijkl"]


def test_assistant_stream_force_flush_keeps_typing_chunk_size() -> None:
    normalizer = AssistantStreamNormalizer.from_policy(
        stream_ref="stream:typing-force",
        stream_policy={
            "chunk_strategy": "typing",
            "max_flush_interval_ms": 1000,
            "max_pending_utf8_bytes": 4,
        },
    )

    first = normalizer.observe_delta("abcdefghijklmnop")
    final = normalizer.flush()

    assert [event["content"] for event in first] == ["abcd"]
    assert [event["content"] for event in final] == ["efgh", "ijkl", "mnop"]


def test_assistant_stream_typing_strategy_respects_min_event_interval() -> None:
    normalizer = AssistantStreamNormalizer.from_policy(
        stream_ref="stream:typing-min-interval",
        stream_policy={
            "chunk_strategy": "typing",
            "max_flush_interval_ms": 0,
            "max_pending_utf8_bytes": 4,
            "min_event_interval_ms": 1000,
        },
    )

    first = normalizer.observe_delta("abcd")
    second = normalizer.observe_delta("efgh")
    final = normalizer.flush()

    assert [event["content"] for event in first] == ["abcd"]
    assert second == []
    assert [event["content"] for event in final] == ["efgh"]


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


def test_assistant_stream_continuity_accumulates_visible_prefix_for_resume() -> None:
    continuity = _assistant_stream_continuity_after_event(
        {},
        {
            "type": "assistant_text_delta",
            "turn_run_id": "turnrun:stream-continuity",
            "stream_ref": "stream:1",
            "message_ref": "turn:1:assistant",
            "sequence": 1,
            "content": "我已经读取",
        },
        turn_id="turn:1",
    )
    continuity = _assistant_stream_continuity_after_event(
        continuity,
        {
            "type": "assistant_text_delta",
            "turn_run_id": "turnrun:stream-continuity",
            "stream_ref": "stream:1",
            "message_ref": "turn:1:assistant",
            "sequence": 2,
            "content": "目标文件，接下来",
        },
        turn_id="turn:1",
    )

    assert continuity["content"] == "我已经读取目标文件，接下来"
    assert continuity["message_ref"] == "turn:1:assistant"
    assert continuity["stream_refs"] == ["stream:1"]
    assert continuity["content_sha256"]
