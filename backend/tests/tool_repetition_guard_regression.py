from __future__ import annotations

from runtime.shared.tool_repetition_guard import ToolRepetitionGuard


def test_tool_repetition_guard_allows_same_tool_with_different_queries() -> None:
    guard = ToolRepetitionGuard(max_repeated_calls=2)

    assert guard.record("web_search", {"query": "北京天气"}) is False
    assert guard.record("web_search", {"query": "上海天气"}) is False
    assert guard.record("web_search", {"query": "广州天气"}) is False


def test_tool_repetition_guard_blocks_same_signature_loop() -> None:
    guard = ToolRepetitionGuard(max_repeated_calls=2)

    assert guard.record("web_search", {"query": "北京天气"}) is False
    assert guard.record("web_search", {"query": "北京天气"}) is False
    assert guard.record("web_search", {"query": "北京天气"}) is True


