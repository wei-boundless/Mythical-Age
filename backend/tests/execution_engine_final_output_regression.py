from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.execution_engine import (
    ModelToolCallAccumulator,
    build_runtime_budget_exhausted_message,
    forced_synthesis_answer_metadata,
    forced_tool_synthesis_from_available_evidence,
    select_final_answer_from_context,
)
from runtime.memory.observation_aggregator import ObservationAggregator


def test_execution_engine_final_output_selects_context_answer() -> None:
    assert select_final_answer_from_context({"canonical_answer": "稳定答案"}) == "稳定答案"


def test_execution_engine_final_output_metadata_is_canonical_tool_summary() -> None:
    metadata = forced_synthesis_answer_metadata(source="test.source")

    assert metadata["answer_source"] == "test.source"
    assert metadata["answer_channel"] == "tool_visible_summary"
    assert metadata["answer_persist_policy"] == "persist_canonical"


def test_execution_engine_final_output_synthesizes_from_task_summary_refs() -> None:
    aggregation = ObservationAggregator().snapshot()
    content = forced_tool_synthesis_from_available_evidence(
        user_message="请总结",
        aggregation=aggregation,
        final_task_summary_refs=[{"summary": "已经读取并完成摘要。"}],
        final_main_context={"active_constraints": {"active_pdf": "report.pdf"}},
    )

    assert "report.pdf" in content
    assert "已经读取并完成摘要" in content


def test_execution_engine_final_output_budget_message_mentions_tool_evidence() -> None:
    content = build_runtime_budget_exhausted_message("max_model_calls", tool_observation_count=2)

    assert "模型续写次数达到上限" in content
    assert "已经收到 2 条工具结果" in content


def test_execution_engine_model_tool_call_accumulator_collects_stream_context() -> None:
    accumulator = ModelToolCallAccumulator()

    accumulator.ingest_event(
        {
            "type": "tool_call_requested",
            "tool_call": {"id": "call-1", "name": "read_file"},
            "assistant_content": "需要读取文件",
            "assistant_additional_kwargs": {"tool_calls": [{"id": "call-1"}]},
        }
    )
    accumulator.ingest_event({"type": "content_delta", "content": "ignore"})

    assert accumulator.pending_tool_calls == [{"id": "call-1", "name": "read_file"}]
    assert accumulator.assistant_content == "需要读取文件"
    assert accumulator.assistant_additional_kwargs["tool_calls"] == [{"id": "call-1"}]
