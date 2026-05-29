from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from context_system.projection.projection import ContextProjection
from runtime.memory.observation_aggregator import ObservationAggregator


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



