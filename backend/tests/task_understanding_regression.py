from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from understanding.task_understanding import analyze_task_understanding


def main() -> None:
    shortage = analyze_task_understanding("从我的数据库中，查询有哪些货物缺货")
    assert shortage.source_kind == "knowledge_base"
    assert shortage.task_kind == "knowledge_lookup"
    assert shortage.target_object is None
    assert shortage.route_hint == "agent"
    assert shortage.execution_posture == "bounded_agent"
    assert shortage.candidate_tools == ["search_knowledge"]
    assert shortage.preferred_skill is None
    assert shortage.parameters == {"query": "从我的数据库中，查询有哪些货物缺货"}

    explicit_dataset = analyze_task_understanding("帮我看一下 inventory.xlsx 里哪些货物缺货")
    assert explicit_dataset.source_kind == "dataset"
    assert explicit_dataset.task_kind == "dataset_query"
    assert explicit_dataset.route_hint == "tool"
    assert explicit_dataset.preferred_skill == "structured-data-analysis"
    assert explicit_dataset.parameters == {
        "query": "帮我看一下 inventory.xlsx 里哪些货物缺货",
        "path": "inventory.xlsx",
    }

    generic_followup = analyze_task_understanding("按仓库展开一下")
    assert generic_followup.source_kind == "knowledge_base"
    assert generic_followup.task_kind == "knowledge_lookup"

    pdf_page = analyze_task_understanding("2025年AI治理报告的第三页讲得什么")
    assert pdf_page.source_kind == "document"
    assert pdf_page.task_kind == "document_page"
    assert pdf_page.target_object is None
    assert pdf_page.preferred_skill == "pdf-analysis"
    assert pdf_page.parameters["mode"] == "page"

    pdf_explicit = analyze_task_understanding(
        "现在打开 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，给我一个全文总览。"
    )
    assert pdf_explicit.parameters["path"] == "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"

    faq = analyze_task_understanding("为什么我在我的帐户中找不到我的订单？")
    assert faq.source_kind == "knowledge_base"
    assert faq.task_kind == "faq_explanation"
    assert faq.target_object is None
    assert faq.preferred_skill == "rag-skill"
    assert faq.candidate_tools == ["search_knowledge"]

    knowledge = analyze_task_understanding("为我讲讲AI吧，你的数据库里有不少AI知识吧")
    assert knowledge.source_kind == "knowledge_base"
    assert knowledge.task_kind == "knowledge_lookup"
    assert knowledge.target_object is None
    assert knowledge.route_hint == "rag"
    assert knowledge.execution_posture == "direct_rag"
    assert knowledge.preferred_skill == "rag-skill"

    freshness = analyze_task_understanding("他今年还在打比赛吗")
    assert freshness.route_hint == "agent"
    assert freshness.execution_posture == "bounded_agent"
    assert freshness.candidate_tools == ["search_knowledge", "web_search"]
    assert freshness.preferred_skill is None

    weather = analyze_task_understanding("北京今天天气怎么样")
    assert weather.source_kind == "external_web"
    assert weather.task_kind == "realtime_lookup"
    assert weather.target_object is None
    assert weather.preferred_skill == "get-weather"

    print("ALL PASSED (task understanding)")


if __name__ == "__main__":
    main()
