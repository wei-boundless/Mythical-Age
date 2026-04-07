from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skill_system import SkillRegistry
from understanding.query_understanding import analyze_query_understanding


def _load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    scanner = _load_module(ROOT / "tools" / "skills_scanner.py", "skills_scanner_runtime_test")
    tool_registry_module = _load_module(ROOT / "tools" / "tool_registry.py", "tool_registry_runtime_test")
    scanner.refresh_snapshot(ROOT)
    tool_registry_module.refresh_tool_registry(ROOT)

    skill_registry = SkillRegistry(ROOT)
    tool_registry = tool_registry_module.ToolRegistry(ROOT)

    weather = analyze_query_understanding(
        "北京今天天气怎么样",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert weather.route == "tool"
    assert weather.skill_name == "get-weather"
    assert weather.tool_name == "get_weather"
    assert weather.candidate_tools == ["get_weather"]

    structured = analyze_query_understanding(
        "销售前五的有哪些",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert structured.route == "tool"
    assert structured.skill_name == "structured-data-analysis"
    assert structured.tool_name == "structured_data_analysis"
    assert "structured_data_analysis" in structured.candidate_tools

    shortage = analyze_query_understanding(
        "从我的数据库中，查询有哪些货物缺货",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert shortage.route == "tool"
    assert shortage.skill_name == "structured-data-analysis"
    assert shortage.tool_name == "structured_data_analysis"
    assert shortage.task_kind == "dataset_filter"
    assert shortage.target_object == "inventory"
    assert shortage.tool_input.get("analysis_type") == "inventory_shortage"
    assert shortage.tool_input.get("semantic_hints", {}).get("state_kind") == "shortage"

    abundance = analyze_query_understanding(
        "我不是要知道缺货情况，我要你分析哪些地方货物最充足",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert abundance.route == "tool"
    assert abundance.skill_name == "structured-data-analysis"
    assert abundance.tool_name == "structured_data_analysis"
    assert abundance.task_kind == "dataset_top_n"
    assert abundance.target_object == "inventory"
    assert abundance.tool_input.get("analysis_type") == "top_n"
    assert abundance.tool_input.get("semantic_hints", {}).get("state_kind") == "abundance"
    assert abundance.tool_input.get("semantic_hints", {}).get("group_hint") == "warehouse"

    shortage_places = analyze_query_understanding(
        "哪些地方货物不够",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert shortage_places.route == "tool"
    assert shortage_places.skill_name == "structured-data-analysis"
    assert shortage_places.tool_name == "structured_data_analysis"
    assert shortage_places.task_kind == "dataset_top_n"
    assert shortage_places.target_object == "inventory"
    assert shortage_places.tool_input.get("analysis_type") == "top_n"
    assert shortage_places.tool_input.get("semantic_hints", {}).get("state_kind") == "shortage"
    assert shortage_places.tool_input.get("semantic_hints", {}).get("metric_hint") == "shortage_qty"

    non_shortage_places = analyze_query_understanding(
        "哪些地方不缺货",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert non_shortage_places.route == "tool"
    assert non_shortage_places.skill_name == "structured-data-analysis"
    assert non_shortage_places.tool_name == "structured_data_analysis"
    assert non_shortage_places.task_kind == "dataset_top_n"
    assert non_shortage_places.target_object == "inventory"
    assert non_shortage_places.tool_input.get("analysis_type") == "top_n"
    assert non_shortage_places.tool_input.get("semantic_hints", {}).get("state_kind") == "non_shortage"

    pdf = analyze_query_understanding(
        "2025年AI治理报告的第三页讲得什么",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert pdf.route == "tool"
    assert pdf.skill_name == "pdf-analysis"
    assert pdf.tool_name == "pdf_analysis"
    assert pdf.tool_input.get("mode") == "page_read"

    faq = analyze_query_understanding(
        "为什么我在我的帐户中找不到我的订单？",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert faq.route == "rag"
    assert faq.skill_name == "rag-skill"
    assert faq.task_kind == "faq_explanation"
    assert faq.tool_name is None
    assert faq.candidate_tools == ["search_knowledge"]

    rag = analyze_query_understanding(
        "为我讲讲AI吧，你的数据库里有不少AI知识吧",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert rag.route == "rag"
    assert rag.skill_name == "rag-skill"
    assert rag.tool_name is None

    web = analyze_query_understanding(
        "帮我联网查 OpenAI API 最新更新",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert web.route == "tool"
    assert web.skill_name == "web-search"
    assert web.tool_name == "web_search"

    gold = analyze_query_understanding(
        "查询黄金价格",
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    assert gold.route == "tool"
    assert gold.skill_name == "gold-price"
    assert gold.tool_name == "get_gold_price"
    assert gold.candidate_tools == ["get_gold_price"]

    print("ALL PASSED (skill runtime)")


if __name__ == "__main__":
    main()
