from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query.output_boundary import AssistantOutputBoundary
from query.runtime import QueryRuntime


def test_output_boundary_rejects_no_receipt_query_promise() -> None:
    boundary = AssistantOutputBoundary()
    boundary.ingest_ai_update("岩，我现在立即查询勒布朗·詹姆斯的最新状态。", has_tool_calls=False)
    boundary.finalize_segment(fallback_content="岩，我现在立即查询勒布朗·詹姆斯的最新状态。")
    response = boundary.build_response(
        route="agent",
        execution_posture="bounded_agent",
        user_message="他今年还在打比赛吗",
        tool_name="",
        retrieval_results=[],
    )

    assert response.tool_receipts == []
    assert response.selected_channel == "fallback_answer"
    assert response.fallback_reason == "no_receipt_query_promise"
    assert response.canonical_answer == "当前还没有形成真实查询结果。"


def test_persistence_gate_rewrites_no_receipt_query_promise() -> None:
    runtime = QueryRuntime.__new__(QueryRuntime)
    messages = runtime._build_assistant_messages(
        [{"content": "岩，我现在立即查询勒布朗·詹姆斯的最新状态。", "tool_calls": []}],
        canonical_content="岩，我现在立即查询勒布朗·詹姆斯的最新状态。",
    )

    assert len(messages) == 1
    assert messages[0]["content"] == "当前还没有形成真实查询结果。"


def main() -> None:
    test_output_boundary_rejects_no_receipt_query_promise()
    test_persistence_gate_rewrites_no_receipt_query_promise()
    print("ALL PASSED (procedural promise guard regression)")


if __name__ == "__main__":
    main()
