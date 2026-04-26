from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from query.planner import QueryPlanner
from tools.tool_registry import ToolRegistry


def _planner() -> QueryPlanner:
    return QueryPlanner(
        base_dir=ROOT,
        skill_registry=None,
        tool_runtime=SimpleNamespace(registry=ToolRegistry(ROOT)),
    )


def test_search_policy_can_disable_rag_for_one_turn() -> None:
    plan = _planner().build_plan(
        session_id="search-policy-rag",
        message="从我的数据库中，查询有哪些货物缺货",
        history=[],
        search_policy=["local_files"],
    )

    execution = plan.iter_executions()[0]
    assert execution.query_understanding.route == "agent"
    assert execution.query_understanding.should_skip_rag is True
    assert "search_policy_blocked_rag" in execution.query_understanding.reasons


def test_search_policy_filters_local_file_tools() -> None:
    plan = _planner().build_plan(
        session_id="search-policy-local-files",
        message="打开 backend/understanding/task_understanding.py 给我看看源码",
        history=[],
        search_policy=["rag"],
    )

    execution = plan.iter_executions()[0]
    assert execution.query_understanding.tool_name is None
    assert execution.execution_kind == "agent"
    assert "read_file" in execution.query_understanding.structural_signals["search_policy_blocked_tools"]


def test_local_file_policy_allows_document_and_data_tools() -> None:
    pdf_plan = _planner().build_plan(
        session_id="search-policy-pdf",
        message="请分析 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，先给我全文总览。",
        history=[],
        search_policy=["local_files"],
    )
    pdf_execution = pdf_plan.iter_executions()[0]
    assert pdf_execution.query_understanding.tool_name == "pdf_analysis"
    assert pdf_execution.execution_kind == "worker"

    data_plan = _planner().build_plan(
        session_id="search-policy-data",
        message="切到 knowledge/E-commerce Data/inventory.xlsx，哪些仓库缺货？",
        history=[],
        search_policy=["local_files"],
    )
    data_execution = data_plan.iter_executions()[0]
    assert data_execution.query_understanding.tool_name == "structured_data_analysis"
    assert data_execution.execution_kind == "direct_tool"


def test_search_policy_filters_web_tools() -> None:
    blocked_plan = _planner().build_plan(
        session_id="search-policy-web-blocked",
        message="帮我联网搜索 OpenAI 最新模型",
        history=[],
        search_policy=["local_files"],
    )
    blocked_execution = blocked_plan.iter_executions()[0]
    assert blocked_execution.query_understanding.tool_name is None
    assert blocked_execution.execution_kind == "agent"
    assert "web_search" in blocked_execution.query_understanding.structural_signals["search_policy_blocked_tools"]

    allowed_plan = _planner().build_plan(
        session_id="search-policy-web-allowed",
        message="帮我联网搜索 OpenAI 最新模型",
        history=[],
        search_policy=["web"],
    )
    allowed_execution = allowed_plan.iter_executions()[0]
    assert allowed_execution.query_understanding.tool_name == "web_search"
    assert allowed_execution.execution_kind == "direct_tool"


def test_missing_search_policy_keeps_legacy_behavior() -> None:
    plan = _planner().build_plan(
        session_id="search-policy-legacy",
        message="打开 backend/understanding/task_understanding.py 给我看看源码",
        history=[],
    )

    execution = plan.iter_executions()[0]
    assert execution.query_understanding.tool_name == "read_file"
    assert execution.execution_kind == "direct_tool"
