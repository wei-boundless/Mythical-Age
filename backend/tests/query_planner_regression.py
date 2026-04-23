from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from query.continuation_resolver import QueryContinuationResolver
from query.planner import QueryPlanner
from understanding.query_understanding import QueryUnderstanding


def main() -> None:
    planner = QueryPlanner(
        base_dir=ROOT,
        skill_registry=None,
        tool_runtime=SimpleNamespace(registry=None),
    )

    pdf_plan = planner.build_plan(
        session_id="planner-regression",
        message="请分析 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，先给我全文总览。",
        history=[],
    )
    assert pdf_plan.query_understanding.route == "tool"
    assert pdf_plan.query_understanding.tool_name == "pdf_analysis"
    assert pdf_plan.subqueries == ["请分析 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，先给我全文总览。"]
    assert len(pdf_plan.iter_executions()) == 1
    assert pdf_plan.iter_executions()[0].execution_kind == "direct_tool"
    assert pdf_plan.iter_executions()[0].tool_input["path"].endswith(".pdf")
    assert pdf_plan.iter_executions()[0].structured_binding is None

    structured_plan = planner.build_plan(
        session_id="planner-regression",
        message="切到 knowledge/E-commerce Data/inventory.xlsx，哪些仓库缺货？",
        history=[],
    )
    assert structured_plan.query_understanding.route == "tool"
    assert structured_plan.query_understanding.tool_name == "structured_data_analysis"
    assert structured_plan.subqueries == ["切到 knowledge/E-commerce Data/inventory.xlsx，哪些仓库缺货？"]
    assert structured_plan.iter_executions()[0].structured_binding is not None
    assert structured_plan.iter_executions()[0].structured_binding.dataset_path.endswith("inventory.xlsx")
    assert structured_plan.iter_executions()[0].structured_binding.source == "prebound_tool_input"
    assert structured_plan.iter_executions()[0].structured_binding.explicit_switch is True

    structured_compound_plan = planner.build_plan(
        session_id="planner-regression",
        message="切到 knowledge/E-commerce Data/inventory.xlsx，先按仓库汇总，再按部门排序，最后给我缺货前五。",
        history=[],
    )
    assert structured_compound_plan.query_understanding.route == "compound"
    assert structured_compound_plan.subqueries == [
        "切到 knowledge/E-commerce Data/inventory.xlsx",
        "按仓库汇总",
        "按部门排序",
        "给我缺货前五",
    ]
    structured_compound_executions = structured_compound_plan.iter_executions()
    assert len(structured_compound_executions) == 4
    assert all(execution.query_understanding.tool_name == "structured_data_analysis" for execution in structured_compound_executions)
    assert structured_compound_executions[0].structured_binding is not None
    assert structured_compound_executions[0].structured_binding.source == "prebound_tool_input"
    assert structured_compound_executions[1].structured_binding is not None
    assert structured_compound_executions[1].structured_binding.source == "compound_authority"
    assert structured_compound_executions[2].structured_binding is not None
    assert structured_compound_executions[2].structured_binding.source == "compound_authority"
    assert structured_compound_executions[3].structured_binding is not None
    assert structured_compound_executions[3].structured_binding.source == "compound_authority"
    assert all(execution.tool_input.get("path", "").endswith("inventory.xlsx") for execution in structured_compound_executions)

    structured_mixed_compound_plan = planner.build_plan(
        session_id="planner-regression",
        message="切到 knowledge/E-commerce Data/inventory.xlsx，先按仓库汇总，最后查北京天气。",
        history=[],
    )
    structured_mixed_executions = structured_mixed_compound_plan.iter_executions()
    assert [execution.message for execution in structured_mixed_executions] == [
        "切到 knowledge/E-commerce Data/inventory.xlsx",
        "按仓库汇总",
        "查北京天气",
    ]
    assert structured_mixed_executions[0].query_understanding.tool_name == "structured_data_analysis"
    assert structured_mixed_executions[1].query_understanding.tool_name == "structured_data_analysis"
    assert structured_mixed_executions[2].query_understanding.tool_name == "get_weather"
    assert not structured_mixed_executions[2].tool_input.get("path", "")

    compound_plan = planner.build_plan(
        session_id="planner-regression",
        message="请查询哪些商品库存不足/三一重工前三大股东/为什么我在我的帐户中找不到我的订单？",
        history=[],
    )
    assert compound_plan.query_understanding.route == "compound"
    assert compound_plan.query_understanding.tool_name is None
    assert compound_plan.subqueries == [
        "哪些商品库存不足",
        "三一重工前三大股东",
        "为什么我在我的帐户中找不到我的订单？",
    ]
    assert [execution.message for execution in compound_plan.iter_executions()] == compound_plan.subqueries

    sequential_plan = planner.build_plan(
        session_id="planner-regression",
        message="先总结 AI 治理报告第三页，再告诉我 inventory.xlsx 缺货前五，最后查北京天气。",
        history=[],
    )
    assert sequential_plan.query_understanding.route == "compound"
    assert sequential_plan.query_understanding.tool_name is None
    assert sequential_plan.subqueries == [
        "总结 AI 治理报告第三页",
        "告诉我 inventory.xlsx 缺货前五",
        "查北京天气",
    ]
    sequential_executions = sequential_plan.iter_executions()
    assert len(sequential_executions) == 3
    assert sequential_executions[0].query_understanding.tool_name == "pdf_analysis"
    assert sequential_executions[1].query_understanding.tool_name == "structured_data_analysis"
    assert sequential_executions[2].query_understanding.tool_name == "get_weather"

    nested_sequential_plan = planner.build_plan(
        session_id="planner-regression",
        message="先总结 PDF 第三页，再给我 inventory.xlsx 最缺货的前三个仓库，最后补一句北京天气。",
        history=[],
    )
    assert nested_sequential_plan.query_understanding.route == "compound"
    assert nested_sequential_plan.subqueries == [
        "总结 PDF 第三页",
        "给我 inventory.xlsx 最缺货的前三个仓库",
        "补一句北京天气",
    ]
    nested_executions = nested_sequential_plan.iter_executions()
    assert len(nested_executions) == 3
    assert nested_executions[0].query_understanding.tool_name == "pdf_analysis"
    assert nested_executions[1].query_understanding.tool_name == "structured_data_analysis"
    assert nested_executions[2].query_understanding.tool_name == "get_weather"

    pdf_compound_plan = planner.build_plan(
        session_id="planner-regression",
        message="打开 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，然后总结第三页，最后查北京天气。",
        history=[],
    )
    assert pdf_compound_plan.query_understanding.route == "compound"
    assert pdf_compound_plan.subqueries == [
        "打开 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
        "总结第三页",
        "查北京天气",
    ]
    pdf_compound_executions = pdf_compound_plan.iter_executions()
    assert len(pdf_compound_executions) == 3
    assert pdf_compound_executions[0].query_understanding.tool_name == "pdf_analysis"
    assert pdf_compound_executions[1].query_understanding.tool_name == "pdf_analysis"
    assert pdf_compound_executions[2].query_understanding.tool_name == "get_weather"
    assert pdf_compound_executions[0].tool_input.get("path", "").endswith(".pdf")
    assert pdf_compound_executions[1].tool_input.get("path", "").endswith(".pdf")
    assert not pdf_compound_executions[2].tool_input.get("path", "")
    assert pdf_compound_executions[1].tool_input.get("mode") == "page"

    section_plan = planner.build_plan(
        session_id="planner-regression",
        message="回到刚才 PDF，第二部分的结论是什么？",
        history=[],
    )
    assert section_plan.query_understanding.tool_name == "pdf_analysis"
    assert section_plan.iter_executions()[0].tool_input["mode"] == "section"

    history = [
        {"role": "user", "content": "请帮我详细解读 AI治理报告.pdf"},
        {"role": "assistant", "content": "已分析文件：knowledge/reports/AI治理报告.pdf"},
    ]
    followup_plan = planner.build_plan(
        session_id="planner-regression",
        message="回到刚才 PDF，第二部分的结论是什么？",
        history=history,
    )
    assert followup_plan.query_understanding.route == "tool"
    assert followup_plan.query_understanding.tool_name == "pdf_analysis"
    assert "path" not in followup_plan.query_understanding.tool_input
    assert "path" not in followup_plan.iter_executions()[0].tool_input
    assert followup_plan.iter_executions()[0].tool_input["mode"] == "section"
    assert followup_plan.subqueries == ["回到刚才 PDF，第二部分的结论是什么？"]

    structured_followup_history = [
        {"role": "user", "content": "给我 inventory.xlsx 最缺货的前三个仓库"},
        {"role": "assistant", "content": "已完成 inventory 分析。"},
    ]
    continuation_resolver = QueryContinuationResolver(base_dir=ROOT)
    structured_followup_plan = planner.build_plan(
        session_id="planner-regression",
        message="再按仓库展开一下",
        history=structured_followup_history,
    )
    promoted_structured = continuation_resolver.promote_structured_query(
        "再按仓库展开一下",
        structured_followup_history,
        QueryUnderstanding(),
    )
    assert structured_followup_plan.query_understanding.tool_name != "structured_data_analysis"
    assert promoted_structured.route != "tool"
    structured_followup_execution = structured_followup_plan.iter_executions()[0]
    assert structured_followup_execution.structured_binding is None
    assert not structured_followup_execution.tool_input.get("path", "")

    non_structured_followup_plan = planner.build_plan(
        session_id="planner-regression",
        message="把刚才那三类风险压成适合管理层汇报的三条。",
        history=structured_followup_history,
    )
    assert non_structured_followup_plan.query_understanding.tool_name != "structured_data_analysis"
    non_structured_execution = non_structured_followup_plan.iter_executions()[0]
    assert non_structured_execution.structured_binding is None
    assert not non_structured_execution.tool_input.get("path", "")

    summary_history = [
        {"role": "user", "content": "请分析 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，先给我全文总览。"},
        {"role": "assistant", "content": "已完成 PDF 总览。"},
        {"role": "user", "content": "切到 knowledge/E-commerce Data/inventory.xlsx，哪些仓库缺货？"},
        {"role": "assistant", "content": "已完成 inventory 分析。"},
        {"role": "user", "content": "北京今天天气怎么样？"},
        {"role": "assistant", "content": "已完成天气查询。"},
    ]
    summary_plan = planner.build_plan(
        session_id="planner-regression",
        message="把今天这几个任务分成 PDF、数据表、实时查询三段总结。",
        history=summary_history,
    )
    assert summary_plan.query_understanding.route == "memory"
    assert summary_plan.query_understanding.intent == "session_summary_query"
    assert summary_plan.subqueries == ["把今天这几个任务分成 PDF、数据表、实时查询三段总结。"]

    ops_summary_plan = planner.build_plan(
        session_id="planner-regression",
        message="把库存、员工、黄金和天气这四块信息分开给我一个运营摘要。",
        history=summary_history,
    )
    assert ops_summary_plan.query_understanding.route == "memory"
    assert ops_summary_plan.query_understanding.intent == "session_summary_query"
    assert ops_summary_plan.query_understanding.tool_name is None
    assert ops_summary_plan.subqueries == ["把库存、员工、黄金和天气这四块信息分开给我一个运营摘要。"]

    protected_summary_understanding = continuation_resolver.apply_authoritative_context(
        message="把刚才这几块信息压成适合管理层汇报的三条。",
        understanding=QueryUnderstanding(route="rag", task_kind="knowledge_lookup", source_kind="knowledge_base"),
        authority_context={"active_pdf": "knowledge/reports/test.pdf"},
    )
    assert protected_summary_understanding.route == "rag"
    assert protected_summary_understanding.tool_name is None

    print("ALL PASSED (query planner regression)")


if __name__ == "__main__":
    main()
