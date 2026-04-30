from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from query.continuation_resolver import QueryContinuationResolver
from query.planner import QueryPlanner
from tools.tool_registry import ToolRegistry
from understanding.query_understanding import QueryUnderstanding


def _assert_pdf_worker(execution, *, path_suffix: str | None = None, mode: str | None = None) -> None:
    assert execution.query_understanding.tool_name == "pdf_analysis"
    assert execution.execution_kind == "worker"
    assert execution.worker_plan is not None
    assert execution.worker_plan.worker_route == "pdf"
    assert execution.worker_plan.request is not None
    if path_suffix is not None:
        assert str(execution.worker_plan.request.bindings.get("active_pdf", "")).endswith(path_suffix)
    if mode is not None:
        assert execution.worker_plan.request.constraints.get("mode") == mode


def main() -> None:
    planner = QueryPlanner(
        base_dir=ROOT,
        skill_registry=None,
        tool_runtime=SimpleNamespace(registry=ToolRegistry(ROOT)),
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
    _assert_pdf_worker(pdf_plan.iter_executions()[0], path_suffix=".pdf")
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

    workspace_read_plan = planner.build_plan(
        session_id="planner-regression",
        message="打开 backend/understanding/task_understanding.py 给我看看源码",
        history=[],
    )
    assert workspace_read_plan.query_understanding.route == "tool"
    assert workspace_read_plan.query_understanding.tool_name == "read_file"
    assert workspace_read_plan.iter_executions()[0].execution_kind == "direct_tool"
    assert workspace_read_plan.iter_executions()[0].tool_input["path"] == "understanding/task_understanding.py"
    assert workspace_read_plan.iter_executions()[0].structured_binding is None

    structured_compound_plan = planner.build_plan(
        session_id="planner-regression",
        message="切到 knowledge/E-commerce Data/inventory.xlsx，先按仓库汇总，再按部门排序，最后给我缺货前五。",
        history=[],
    )
    assert structured_compound_plan.query_understanding.route == "tool"
    assert structured_compound_plan.subqueries == ["切到 knowledge/E-commerce Data/inventory.xlsx，先按仓库汇总，再按部门排序，最后给我缺货前五。"]
    assert len(structured_compound_plan.subtasks) == 1
    assert structured_compound_plan.subtasks[0].subtask_id == "main"
    structured_compound_executions = structured_compound_plan.iter_executions()
    assert len(structured_compound_executions) == 1
    assert all(execution.query_understanding.tool_name == "structured_data_analysis" for execution in structured_compound_executions)
    assert structured_compound_executions[0].structured_binding is not None
    assert structured_compound_executions[0].structured_binding.source == "prebound_tool_input"
    assert all(execution.tool_input.get("path", "").endswith("inventory.xlsx") for execution in structured_compound_executions)

    structured_mixed_compound_plan = planner.build_plan(
        session_id="planner-regression",
        message="切到 knowledge/E-commerce Data/inventory.xlsx，先按仓库汇总，最后查北京天气。",
        history=[],
    )
    structured_mixed_executions = structured_mixed_compound_plan.iter_executions()
    assert structured_mixed_compound_plan.execution_mode == "bundle_execution"
    assert structured_mixed_compound_plan.bundle_plan is not None
    assert len(structured_mixed_compound_plan.bundle_plan.items) == 2
    assert len(structured_mixed_executions) == 2
    assert [execution.query_understanding.tool_name for execution in structured_mixed_executions] == [
        "structured_data_analysis",
        "get_weather",
    ]

    compound_plan = planner.build_plan(
        session_id="planner-regression",
        message="请查询哪些商品库存不足/三一重工前三大股东/为什么我在我的帐户中找不到我的订单？",
        history=[],
    )
    assert compound_plan.query_understanding.route != "compound"
    assert compound_plan.subqueries == ["请查询哪些商品库存不足/三一重工前三大股东/为什么我在我的帐户中找不到我的订单？"]
    assert [execution.message for execution in compound_plan.iter_executions()] == compound_plan.subqueries

    sequential_plan = planner.build_plan(
        session_id="planner-regression",
        message="先总结 AI 治理报告第三页，再告诉我 inventory.xlsx 缺货前五，最后查北京天气。",
        history=[],
    )
    assert sequential_plan.execution_mode == "bundle_execution"
    sequential_executions = sequential_plan.iter_executions()
    assert len(sequential_executions) == 3
    assert [execution.worker_plan.worker_route if execution.worker_plan else execution.query_understanding.tool_name for execution in sequential_executions] == [
        "pdf",
        "structured_data_analysis",
        "get_weather",
    ]
    _assert_pdf_worker(sequential_executions[0])

    nested_sequential_plan = planner.build_plan(
        session_id="planner-regression",
        message="先总结 PDF 第三页，再给我 inventory.xlsx 最缺货的前三个仓库，最后补一句北京天气。",
        history=[],
    )
    assert nested_sequential_plan.execution_mode == "bundle_execution"
    assert nested_sequential_plan.bundle_plan is not None
    assert len(nested_sequential_plan.bundle_plan.items) == 3
    nested_executions = nested_sequential_plan.iter_executions()
    assert len(nested_executions) == 3
    assert [execution.worker_plan.worker_route if execution.worker_plan else execution.query_understanding.tool_name for execution in nested_executions] == [
        "pdf",
        "structured_data_analysis",
        "get_weather",
    ]
    _assert_pdf_worker(nested_executions[0])
    assert all(execution.bundle_id for execution in nested_executions)
    assert [execution.bundle_item_index for execution in nested_executions] == [1, 2, 3]

    pdf_compound_plan = planner.build_plan(
        session_id="planner-regression",
        message="打开 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，然后总结第三页，最后查北京天气。",
        history=[],
    )
    assert pdf_compound_plan.execution_mode == "bundle_execution"
    pdf_compound_executions = pdf_compound_plan.iter_executions()
    assert len(pdf_compound_executions) == 2
    assert [execution.worker_plan.worker_route if execution.worker_plan else execution.query_understanding.tool_name for execution in pdf_compound_executions] == [
        "pdf",
        "get_weather",
    ]
    _assert_pdf_worker(pdf_compound_executions[0])

    section_plan = planner.build_plan(
        session_id="planner-regression",
        message="回到刚才 PDF，第二部分的结论是什么？",
        history=[],
    )
    _assert_pdf_worker(section_plan.iter_executions()[0], mode="section")

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
    assert "path" not in followup_plan.iter_executions()[0].worker_plan.request.bindings
    _assert_pdf_worker(followup_plan.iter_executions()[0], mode="section")
    assert followup_plan.subqueries == ["回到刚才 PDF，第二部分的结论是什么？"]

    session_pdf_authority_plan = planner.build_plan(
        session_id="planner-regression",
        message="回到刚才那份 PDF，第二部分的结论是什么？",
        history=[],
        authority_context={"active_pdf": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"},
    )
    session_pdf_execution = session_pdf_authority_plan.iter_executions()[0]
    assert session_pdf_authority_plan.query_understanding.tool_name == "pdf_analysis"
    if session_pdf_execution.worker_plan is not None:
        assert "active_pdf" not in session_pdf_execution.worker_plan.request.bindings
    assert "path" not in session_pdf_execution.tool_input

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
    assert structured_followup_plan.query_understanding.tool_name == "structured_data_analysis"
    assert promoted_structured.route == "tool"
    assert promoted_structured.tool_name == "structured_data_analysis"
    structured_followup_execution = structured_followup_plan.iter_executions()[0]
    assert structured_followup_execution.structured_binding is not None
    assert structured_followup_execution.tool_input.get("path", "").endswith("inventory.xlsx")

    session_structured_authority_plan = planner.build_plan(
        session_id="planner-regression",
        message="按仓库汇总前五。",
        history=[],
        authority_context={"active_dataset": "knowledge/E-commerce Data/inventory.xlsx"},
    )
    session_structured_execution = session_structured_authority_plan.iter_executions()[0]
    assert session_structured_authority_plan.query_understanding.tool_name != "structured_data_analysis"
    assert not session_structured_execution.tool_input.get("path", "")
    assert session_structured_execution.structured_binding is None

    non_structured_followup_plan = planner.build_plan(
        session_id="planner-regression",
        message="把刚才那三类风险压成适合管理层汇报的三条。",
        history=structured_followup_history,
    )
    assert non_structured_followup_plan.query_understanding.tool_name != "structured_data_analysis"
    non_structured_execution = non_structured_followup_plan.iter_executions()[0]
    assert non_structured_execution.structured_binding is None
    assert not non_structured_execution.tool_input.get("path", "")

    knowledge_followup_history = [
        {"role": "user", "content": "为我搜下本地的数据库，里面有没有关于AI的内容"},
        {
            "role": "assistant",
            "content": "本地数据库中包含《职业教育人工智能应用发展报告（2024-2025）》和《2025全球人工智能技术应用洞察报告》等 AI 报告。",
            "answer_source": "rag_answer_finalization",
        },
    ]
    knowledge_followup_plan = planner.build_plan(
        session_id="planner-regression",
        message="你可以找一篇具体为我说说吗",
        history=knowledge_followup_history,
    )
    knowledge_followup_execution = knowledge_followup_plan.iter_executions()[0]
    assert knowledge_followup_plan.query_understanding.route == "rag"
    assert knowledge_followup_plan.query_understanding.direct_route_reason == "knowledge_followup_context"
    assert knowledge_followup_execution.execution_kind == "worker"
    assert knowledge_followup_execution.worker_plan is not None
    assert knowledge_followup_execution.worker_plan.worker_route == "retrieval"
    assert "职业教育人工智能应用发展报告" in knowledge_followup_execution.worker_plan.request.query

    summary_history = [
        {"role": "user", "content": "请分析 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，先给我全文总览。"},
        {"role": "assistant", "content": "已完成 PDF 总览。"},
        {"role": "user", "content": "切到 knowledge/E-commerce Data/inventory.xlsx，哪些仓库缺货？"},
        {"role": "assistant", "content": "已完成 inventory 分析。"},
        {"role": "user", "content": "北京今天天气怎么样？"},
        {"role": "assistant", "content": "已完成天气查询。"},
    ]
    history_protected_bundle_plan = planner.build_plan(
        session_id="planner-regression",
        message="先总结 PDF 第三页，再给我 inventory.xlsx 最缺货的前三个仓库，最后补一句北京天气。",
        history=summary_history,
    )
    assert history_protected_bundle_plan.execution_mode == "bundle_execution"
    assert history_protected_bundle_plan.bundle_plan is not None
    assert len(history_protected_bundle_plan.bundle_plan.items) == 3
    history_protected_executions = history_protected_bundle_plan.iter_executions()
    assert [execution.worker_plan.worker_route if execution.worker_plan else execution.query_understanding.tool_name for execution in history_protected_executions] == [
        "pdf",
        "structured_data_analysis",
        "get_weather",
    ]
    assert history_protected_bundle_plan.query_understanding.route == "bundle"

    authority_protected_bundle_plan = planner.build_plan(
        session_id="planner-regression",
        message="先总结 PDF 第三页，再给我 inventory.xlsx 最缺货的前三个仓库，最后补一句北京天气。",
        history=summary_history,
        authority_context={"active_pdf": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"},
    )
    assert authority_protected_bundle_plan.execution_mode == "bundle_execution"
    authority_protected_executions = authority_protected_bundle_plan.iter_executions()
    _assert_pdf_worker(authority_protected_executions[0])
    assert "active_pdf" not in authority_protected_executions[0].worker_plan.request.bindings

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

    print("ALL PASSED (query planner regression)")


if __name__ == "__main__":
    main()
