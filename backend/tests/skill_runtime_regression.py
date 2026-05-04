from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capability_system.skill_policy import SkillPolicyResolver
from capability_system.skill_registry import SkillRegistry
from understanding.query_understanding import analyze_query_understanding


def _load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _assert_bounded_lookup(result, query: str) -> None:
    assert result.route == "agent"
    assert result.execution_posture == "bounded_agent"
    assert result.skill_name is None
    assert result.tool_name is None
    assert result.task_kind == "knowledge_lookup"
    assert result.target_object is None
    assert result.candidate_tools == []
    assert result.tool_input == {"query": query}
    assert "fallback_bounded_lookup" in result.reasons


def main() -> None:
    scanner = _load_module(ROOT / "capability_system" / "skill_scanner.py", "skills_scanner_runtime_test")
    tool_registry_module = _load_module(ROOT / "capability_system" / "tool_registry.py", "tool_registry_runtime_test")
    scanner.refresh_snapshot(ROOT)
    tool_registry_module.refresh_tool_registry(ROOT)

    skill_registry = SkillRegistry(ROOT)
    skill_resolver = SkillPolicyResolver(skill_registry)
    tool_registry = tool_registry_module.ToolRegistry(ROOT)

    weather = analyze_query_understanding(
        "北京今天天气怎么样",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert weather.route == "tool"
    assert weather.skill_name is None
    assert skill_resolver.resolve(task_frame=weather) is None
    assert weather.tool_name == "get_weather"
    assert weather.target_object is None
    assert weather.candidate_tools == ["get_weather"]

    structured = analyze_query_understanding(
        "销售前五的有哪些",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert structured.route == "tool"
    assert structured.skill_name is None
    assert skill_resolver.resolve(task_frame=structured).name == "structured-data-analysis"
    assert structured.tool_name == "structured_data_analysis"
    assert structured.tool_input == {"query": "销售前五的有哪些"}

    shortage = analyze_query_understanding(
        "从我的数据库中，查询有哪些货物缺货",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert shortage.route == "tool"
    assert shortage.execution_posture == "direct_tool"
    assert shortage.skill_name is None
    assert skill_resolver.resolve(task_frame=shortage).name == "structured-data-analysis"
    assert shortage.tool_name == "structured_data_analysis"
    assert shortage.candidate_tools == ["structured_data_analysis"]

    local_database = analyze_query_understanding(
        "为我搜索本地的数据库，看看有没有缺货情况",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert local_database.route == "tool"
    assert local_database.execution_posture == "direct_tool"
    assert skill_resolver.resolve(task_frame=local_database).name == "structured-data-analysis"
    assert local_database.tool_name == "structured_data_analysis"
    assert local_database.candidate_tools == ["structured_data_analysis"]

    abundance = analyze_query_understanding(
        "我不是要知道缺货情况，我要你分析哪些地方货物最充足",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert abundance.route == "tool"
    assert abundance.tool_name == "structured_data_analysis"

    shortage_places = analyze_query_understanding(
        "哪些地方货物不够",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert shortage_places.route == "tool"
    assert shortage_places.tool_name == "structured_data_analysis"

    non_shortage_places = analyze_query_understanding(
        "哪些地方不缺货",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert non_shortage_places.route == "tool"
    assert non_shortage_places.tool_name == "structured_data_analysis"

    explicit_structured = analyze_query_understanding(
        "帮我看一下 inventory.xlsx 里销量前五的有哪些",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert explicit_structured.route == "tool"
    assert explicit_structured.skill_name is None
    assert skill_resolver.resolve(task_frame=explicit_structured).name == "structured-data-analysis"
    assert explicit_structured.tool_name == "structured_data_analysis"
    assert explicit_structured.tool_input == {
        "query": "帮我看一下 inventory.xlsx 里销量前五的有哪些",
        "path": "inventory.xlsx",
    }

    bound_structured = analyze_query_understanding(
        "按仓库汇总前五。",
        active_bindings={"active_dataset": "Data/inventory.xlsx"},
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert bound_structured.route == "tool"
    assert bound_structured.tool_name == "structured_data_analysis"
    assert bound_structured.tool_input == {
        "query": "按仓库汇总前五。",
        "path": "Data/inventory.xlsx",
    }
    assert "bound_dataset_followup" in bound_structured.reasons

    pdf = analyze_query_understanding(
        "2025年AI治理报告的第三页讲得什么",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert pdf.route == "tool"
    assert pdf.skill_name is None
    assert skill_resolver.resolve(task_frame=pdf).name == "pdf-analysis"
    assert pdf.tool_name == "pdf_analysis"
    assert pdf.target_object is None
    assert pdf.tool_input.get("mode") == "page"

    bound_pdf = analyze_query_understanding(
        "把这份 PDF 的核心结论压成三条行动建议。",
        active_bindings={"committed_pdf": "knowledge/AI Knowledge/report.pdf"},
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert bound_pdf.route == "tool"
    assert bound_pdf.tool_name == "pdf_analysis"
    assert bound_pdf.tool_input == {
        "query": "把这份 PDF 的核心结论压成三条行动建议。",
        "mode": "document",
        "path": "knowledge/AI Knowledge/report.pdf",
    }
    assert "bound_pdf_followup" in bound_pdf.reasons

    faq = analyze_query_understanding(
        "为什么我在我的帐户中找不到我的订单？",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert faq.route == "rag"
    assert faq.skill_name is None
    assert skill_resolver.resolve(task_frame=faq).name == "rag-skill"
    assert faq.task_kind == "faq_explanation"
    assert faq.target_object is None
    assert faq.tool_name is None
    assert faq.candidate_tools == ["search_knowledge"]

    rag = analyze_query_understanding(
        "为我讲讲AI吧，你的数据库里有不少AI知识吧",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert rag.route == "rag"
    assert rag.skill_name is None
    assert skill_resolver.resolve(task_frame=rag).name == "rag-skill"
    assert rag.target_object is None
    assert rag.tool_name is None
    assert rag.candidate_tools == ["search_knowledge"]

    web = analyze_query_understanding(
        "帮我联网查 OpenAI API 最新更新",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert web.route == "tool"
    assert web.skill_name is None
    assert skill_resolver.resolve(task_frame=web).name == "web-search"
    assert web.target_object is None
    assert web.tool_name == "web_search"

    gold = analyze_query_understanding(
        "查询黄金价格",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert gold.route == "tool"
    assert gold.skill_name is None
    assert skill_resolver.resolve(task_frame=gold) is None
    assert gold.tool_name == "get_gold_price"
    assert gold.target_object is None
    assert gold.candidate_tools == ["get_gold_price"]

    workspace_read = analyze_query_understanding(
        "打开 backend/understanding/task_understanding.py 给我看看源码",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert workspace_read.route == "tool"
    assert workspace_read.skill_name is None
    assert workspace_read.tool_name == "read_file"
    assert workspace_read.task_kind == "workspace_file_read"
    assert workspace_read.tool_input == {
        "path": "backend/understanding/task_understanding.py",
    }

    print("ALL PASSED (skill runtime)")


if __name__ == "__main__":
    main()
