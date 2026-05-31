from __future__ import annotations

from pathlib import Path

from capability_system.units.mcp.local.retrieval.router import RAGQueryRouter


def test_table_query_builds_table_filter() -> None:
    router = RAGQueryRouter(Path("backend"))

    plan = router.plan("帮我查一下订单表格里的库存")

    assert plan.retrieval_plan is not None
    assert plan.retrieval_plan.intent.intent_type == "table_lookup"
    assert plan.retrieval_plan.filters.modality_any == ("table",)
    assert "table_row_window" in plan.retrieval_plan.filters.unit_type_any
    assert plan.policy["result_granularity"] == "object"


def test_page_query_builds_page_filter() -> None:
    router = RAGQueryRouter(Path("backend"))

    plan = router.plan("请查 sample.pdf 第 12 页提到什么")

    assert plan.retrieval_plan is not None
    assert plan.retrieval_plan.intent.intent_type == "page_grounded_lookup"
    assert plan.retrieval_plan.filters.page_any == (12,)
    assert plan.retrieval_plan.intent.page_hints == (12,)
    assert plan.retrieval_plan.policy.parent_child_expansion is True


def test_page_query_accepts_chinese_numeral_page_filter() -> None:
    router = RAGQueryRouter(Path("backend"))

    plan = router.plan("请查 sample.pdf 第三页提到什么")

    assert plan.retrieval_plan is not None
    assert plan.retrieval_plan.intent.intent_type == "page_grounded_lookup"
    assert plan.retrieval_plan.filters.page_any == (3,)
    assert plan.retrieval_plan.intent.page_hints == (3,)


def test_document_query_uses_hierarchical_policy() -> None:
    router = RAGQueryRouter(Path("backend"))

    plan = router.plan("总结这个 report 文档的关键内容")

    assert plan.retrieval_plan is not None
    assert plan.retrieval_plan.intent.intent_type == "document_lookup"
    assert plan.retrieval_plan.policy.strategy == "hierarchical"
    assert "document_summary" in plan.retrieval_plan.filters.unit_type_any


