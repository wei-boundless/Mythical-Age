from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from understanding.task_understanding import analyze_task_understanding


def main() -> None:
    shortage = analyze_task_understanding("从我的数据库中，查询有哪些货物缺货")
    assert shortage.source_kind == "dataset"
    assert shortage.task_kind == "dataset_query"
    assert shortage.target_object is None
    assert shortage.route_hint == "structured_data"
    assert shortage.execution_posture == "direct_mcp"
    assert shortage.capability_requests == ["dataset_analysis"]
    assert shortage.candidate_tools == []
    assert shortage.preferred_skill == "structured-data-analysis"
    assert shortage.parameters == {"query": "从我的数据库中，查询有哪些货物缺货"}
    assert shortage.structural_signals["explicit_dataset_path"] == ""
    assert shortage.structural_signals["local_knowledge_scope"] is True
    assert shortage.structural_signals["knowledge_source_anchor"] == "我的数据库"
    assert shortage.structural_signals["knowledge_source_anchor_kind"] == "qualified_local_source"

    local_database = analyze_task_understanding("为我搜索本地的数据库，看看有没有缺货情况")
    assert local_database.source_kind == "dataset"
    assert local_database.task_kind == "dataset_query"
    assert local_database.route_hint == "structured_data"
    assert local_database.execution_posture == "direct_mcp"
    assert local_database.capability_requests == ["dataset_analysis"]
    assert local_database.preferred_skill == "structured-data-analysis"
    assert local_database.structural_signals["local_knowledge_scope"] is True
    assert local_database.structural_signals["knowledge_source_anchor"] == "本地的数据库"
    assert local_database.structural_signals["knowledge_source_anchor_kind"] == "qualified_local_source"

    explicit_dataset = analyze_task_understanding("帮我看一下 inventory.xlsx 里哪些货物缺货")
    assert explicit_dataset.source_kind == "dataset"
    assert explicit_dataset.task_kind == "dataset_query"
    assert explicit_dataset.route_hint == "structured_data"
    assert explicit_dataset.capability_requests == ["dataset_analysis"]
    assert explicit_dataset.candidate_tools == []
    assert explicit_dataset.preferred_skill == "structured-data-analysis"
    assert explicit_dataset.direct_route_reason == "explicit_dataset_anchor"
    assert explicit_dataset.parameters == {
        "query": "帮我看一下 inventory.xlsx 里哪些货物缺货",
        "path": "inventory.xlsx",
    }
    assert explicit_dataset.structural_signals["explicit_dataset_path"] == "inventory.xlsx"

    generic_followup = analyze_task_understanding("按仓库展开一下")
    assert generic_followup.source_kind == "knowledge_base"
    assert generic_followup.task_kind == "knowledge_lookup"

    bound_dataset_followup = analyze_task_understanding(
        "按仓库展开一下",
        active_bindings={"active_dataset": "Data/inventory.xlsx"},
    )
    assert bound_dataset_followup.source_kind == "dataset"
    assert bound_dataset_followup.task_kind == "dataset_query"
    assert bound_dataset_followup.route_hint == "structured_data"
    assert bound_dataset_followup.preferred_skill == "structured-data-analysis"
    assert bound_dataset_followup.parameters == {
        "query": "按仓库展开一下",
        "path": "Data/inventory.xlsx",
    }
    assert bound_dataset_followup.direct_route_reason == "bound_dataset_followup"

    pdf_page = analyze_task_understanding("2025年AI治理报告的第三页讲得什么")
    assert pdf_page.source_kind == "document"
    assert pdf_page.task_kind == "document_page"
    assert pdf_page.target_object is None
    assert pdf_page.route_hint == "pdf"
    assert pdf_page.execution_posture == "direct_mcp"
    assert pdf_page.preferred_skill == "pdf-analysis"
    assert pdf_page.capability_requests == ["document_analysis"]
    assert pdf_page.parameters["mode"] == "page"
    assert pdf_page.structural_signals["page_reference"] is True

    pdf_explicit = analyze_task_understanding(
        "现在打开 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，给我一个全文总览。"
    )
    assert pdf_explicit.parameters["path"] == "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"

    bound_pdf_followup = analyze_task_understanding(
        "把这份 PDF 的核心结论压成三条行动建议。",
        active_bindings={"committed_pdf": "knowledge/AI Knowledge/report.pdf"},
    )
    assert bound_pdf_followup.source_kind == "document"
    assert bound_pdf_followup.route_hint == "pdf"
    assert bound_pdf_followup.preferred_skill == "pdf-analysis"
    assert bound_pdf_followup.parameters["path"] == "knowledge/AI Knowledge/report.pdf"
    assert bound_pdf_followup.direct_route_reason == "bound_pdf_followup"

    faq = analyze_task_understanding("为什么我在我的帐户中找不到我的订单？")
    assert faq.source_kind == "knowledge_base"
    assert faq.task_kind == "faq_explanation"
    assert faq.target_object is None
    assert faq.preferred_skill == "rag-skill"
    assert faq.capability_requests == ["faq"]
    assert faq.candidate_tools == []
    assert faq.direct_route_reason == "faq_problem_shape"

    knowledge = analyze_task_understanding("为我讲讲AI吧，你的数据库里有不少AI知识吧")
    assert knowledge.source_kind == "knowledge_base"
    assert knowledge.task_kind == "knowledge_lookup"
    assert knowledge.target_object is None
    assert knowledge.route_hint == "rag"
    assert knowledge.execution_posture == "direct_rag"
    assert knowledge.preferred_skill == "rag-skill"
    assert knowledge.capability_requests == ["knowledge_lookup"]
    assert knowledge.candidate_tools == []

    freshness = analyze_task_understanding("他今年还在打比赛吗")
    assert freshness.route_hint == "agent"
    assert freshness.execution_posture == "bounded_agent"
    assert freshness.capability_requests == ["knowledge_lookup", "latest_information"]
    assert freshness.candidate_tools == []
    assert freshness.preferred_skill is None
    assert freshness.structural_signals["freshness_requirement"] is True

    weather = analyze_task_understanding("北京今天天气怎么样")
    assert weather.source_kind == "external_web"
    assert weather.task_kind == "realtime_lookup"
    assert weather.target_object is None
    assert weather.preferred_skill is None
    assert weather.route_hint == "realtime_network"
    assert weather.execution_posture == "builtin_tool_lane"
    assert weather.capability_requests == ["weather", "latest_information"]
    assert weather.candidate_tools == ["web_search"]
    assert weather.direct_route_reason == "weather_realtime_task"

    explicit_web = analyze_task_understanding("帮我联网查 OpenAI API 最新更新")
    assert explicit_web.route_hint == "realtime_network"
    assert explicit_web.capability_requests == ["latest_information"]
    assert explicit_web.candidate_tools == ["web_search"]
    assert explicit_web.direct_route_reason == "explicit_external_constraint"

    workspace_read = analyze_task_understanding("打开 backend/understanding/task_understanding.py 给我看看源码")
    assert workspace_read.route_hint == "workspace_read"
    assert workspace_read.execution_posture == "builtin_tool_lane"
    assert workspace_read.task_kind == "workspace_file_read"
    assert workspace_read.source_kind == "workspace"
    assert workspace_read.capability_requests == ["workspace_read"]
    assert workspace_read.candidate_tools == ["read_file"]
    assert workspace_read.parameters["path"] == "backend/understanding/task_understanding.py"
    assert workspace_read.direct_route_reason == "explicit_workspace_file_anchor"

    print("ALL PASSED (task understanding)")


if __name__ == "__main__":
    main()
