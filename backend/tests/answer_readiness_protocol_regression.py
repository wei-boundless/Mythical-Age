from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from context_management.projection import ContextProjection
from orchestration.runtime_loop.observation_aggregator import ObservationAggregator
from orchestration.runtime_loop.task_run_loop import _build_answer_readiness_judge_message


def test_observation_aggregator_builds_evidence_items_without_losing_projection() -> None:
    aggregator = ObservationAggregator()

    aggregator.add_projection(
        ContextProjection(main_context={"answer_source": "tool"}),
        tool_name="web_search",
    )
    snapshot = aggregator.add_tool_observation(
        {
            "tool_name": "web_search",
            "tool_args": {"query": "北京今天天气"},
            "result": "查询：北京今天天气\n关键信息：北京今日晴，温度 16-25°C。",
        },
        observation_ref="rtobs:test",
    )

    assert snapshot.projection.main_context["answer_source"] == "tool"
    assert snapshot.tool_result_count == 1
    assert snapshot.evidence_items
    assert snapshot.evidence_items[0]["tool_name"] == "web_search"
    assert "北京今日晴" in snapshot.evidence_items[0]["result_preview"]


def test_answer_readiness_message_asks_model_to_judge_before_more_tools() -> None:
    aggregator = ObservationAggregator()
    aggregator.add_tool_observation(
        {
            "tool_name": "web_search",
            "tool_args": {"query": "黄金价格"},
            "result": "查询：黄金价格\n关键信息：现货黄金报价为 2350 美元/盎司，时间口径为今日。",
        }
    )

    message = _build_answer_readiness_judge_message(
        user_message="顺便查一下黄金价格，直接给结论和时间口径。",
        aggregation=aggregator.snapshot(),
        current_bundle_items=[],
        remaining_model_calls=3,
    )

    assert "先判断证据是否足够" in message
    assert "请直接收口回答" in message
    assert "不要为了确认已经足够的信息而重复查询同类工具" in message
    assert "现货黄金报价" in message
