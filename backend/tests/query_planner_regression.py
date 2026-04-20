from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


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
    assert structured_plan.iter_executions()[0].structured_binding.source == "explicit_path"
    assert structured_plan.iter_executions()[0].structured_binding.explicit_switch is True

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

    history = [
        {"role": "user", "content": "请帮我详细解读 AI治理报告.pdf"},
        {"role": "assistant", "content": "已分析文件：knowledge/reports/AI治理报告.pdf"},
    ]
    with patch(
        "query.continuation_resolver.PdfAnalysisCatalog.resolve_pdf_path_from_history",
        return_value=ROOT / "knowledge" / "reports" / "AI治理报告.pdf",
    ), patch(
        "query.continuation_resolver.PdfAnalysisCatalog.relative_path",
        side_effect=lambda root_dir, path: str(path.relative_to(root_dir)).replace("\\", "/"),
    ):
        followup_plan = planner.build_plan(
            session_id="planner-regression",
            message="回到刚才 PDF，第二部分的结论是什么？",
            history=history,
        )
    assert followup_plan.query_understanding.route == "tool"
    assert followup_plan.query_understanding.tool_name == "pdf_analysis"
    assert followup_plan.query_understanding.tool_input["mode"] == "browse"
    assert followup_plan.iter_executions()[0].tool_input["mode"] == "browse"
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
    assert structured_followup_plan.query_understanding.route == "tool"
    assert structured_followup_plan.query_understanding.tool_name == "structured_data_analysis"
    assert "path" not in promoted_structured.tool_input
    assert structured_followup_plan.iter_executions()[0].tool_input["path"].endswith("inventory.xlsx")
    assert structured_followup_plan.iter_executions()[0].structured_binding is not None
    assert structured_followup_plan.iter_executions()[0].structured_binding.source in {
        "semantic_default",
        "history_fallback",
    }

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

    print("ALL PASSED (query planner regression)")


if __name__ == "__main__":
    main()
