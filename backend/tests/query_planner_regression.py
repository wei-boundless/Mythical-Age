from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from query.planner import QueryPlanner


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

    structured_plan = planner.build_plan(
        session_id="planner-regression",
        message="切到 knowledge/E-commerce Data/inventory.xlsx，哪些仓库缺货？",
        history=[],
    )
    assert structured_plan.query_understanding.route == "tool"
    assert structured_plan.query_understanding.tool_name == "structured_data_analysis"
    assert structured_plan.subqueries == ["切到 knowledge/E-commerce Data/inventory.xlsx，哪些仓库缺货？"]

    compound_plan = planner.build_plan(
        session_id="planner-regression",
        message="请查询哪些商品库存不足/三一重工前三大股东/为什么我在我的帐户中找不到我的订单？",
        history=[],
    )
    assert compound_plan.query_understanding.route == "rag"
    assert compound_plan.subqueries == [
        "哪些商品库存不足",
        "三一重工前三大股东",
        "为什么我在我的帐户中找不到我的订单？",
    ]

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
    assert followup_plan.subqueries == ["回到刚才 PDF，第二部分的结论是什么？"]

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
