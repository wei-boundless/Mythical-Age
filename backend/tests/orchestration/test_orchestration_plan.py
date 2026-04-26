from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from orchestration.adapters import build_orchestration_plan
from query.models import QueryExecutionPlan, QueryPlan, SubtaskPlan
from understanding import MemoryIntent, QueryUnderstanding


def test_plan_only_orchestration_plan_preserves_legacy_topology() -> None:
    understanding = QueryUnderstanding(
        intent="general_query",
        source_kind="knowledge_base",
        task_kind="knowledge_lookup",
        modality="general",
        route="rag",
        execution_posture="direct_rag",
        capability_requests=["knowledge_lookup"],
        candidate_tools=["search_knowledge"],
        reasons=["test_route"],
    )
    memory_intent = MemoryIntent(intent="general")
    execution = QueryExecutionPlan(
        message="帮我查项目资料",
        history=[],
        memory_intent=memory_intent,
        query_understanding=understanding,
        execution_kind="agent",
        subtask_id="main",
        subtask_goal="帮我查项目资料",
        subtask_title="帮我查项目资料",
    )
    query_plan = QueryPlan(
        session_id="session-a",
        message="帮我查项目资料",
        history=[],
        subqueries=["帮我查项目资料"],
        subtasks=[SubtaskPlan.single("帮我查项目资料")],
        memory_intent=memory_intent,
        query_understanding=understanding,
        execution_mode="single_execution",
        execution_kind="agent",
        executions=[execution],
    )

    plan = build_orchestration_plan(
        session_id="session-a",
        message="帮我查项目资料",
        query_plan=query_plan,
        source="unit-test",
    )
    payload = plan.to_dict()

    assert payload["mode"] == "plan_only"
    assert payload["topology"]["mode"] == "single_execution"
    assert payload["topology"]["route"] == "rag"
    assert payload["topology"]["execution_kind"] == "agent"
    assert payload["diagnostics"]["plan_compatible"] is True
    assert payload["executions"][0]["execution_id"] == "main"
    assert {decision["node_id"] for decision in payload["decisions"]} >= {
        "input",
        "memory-intent",
        "task-understanding",
        "execution-topology",
        "execution",
        "safety",
    }


def test_primary_mode_no_longer_marks_not_cutover_in_plan_shape() -> None:
    understanding = QueryUnderstanding(route="rag", reasons=["test_route"])
    memory_intent = MemoryIntent(intent="general")
    execution = QueryExecutionPlan(
        message="hello",
        history=[],
        memory_intent=memory_intent,
        query_understanding=understanding,
        execution_kind="agent",
    )
    query_plan = QueryPlan(
        session_id="session-a",
        message="hello",
        history=[],
        subqueries=["hello"],
        memory_intent=memory_intent,
        query_understanding=understanding,
        execution_mode="single_execution",
        execution_kind="agent",
        executions=[execution],
    )

    payload = build_orchestration_plan(
        session_id="session-a",
        message="hello",
        query_plan=query_plan,
        mode="primary",
    ).to_dict()

    assert payload["mode"] == "primary"
    assert "primary_mode_not_cutover_to_runtime" not in payload["safety"]["warnings"]


def test_orchestration_plan_records_contract_preview_decision() -> None:
    understanding = QueryUnderstanding(
        route="tool",
        tool_name="pdf_analysis",
        reasons=["direct_tool"],
    )
    memory_intent = MemoryIntent(intent="general")
    execution = QueryExecutionPlan(
        message="分析这个 PDF",
        history=[],
        memory_intent=memory_intent,
        query_understanding=understanding,
        execution_kind="direct_tool",
        tool_input={"query": "分析这个 PDF"},
    )
    query_plan = QueryPlan(
        session_id="session-a",
        message="分析这个 PDF",
        history=[],
        subqueries=["分析这个 PDF"],
        memory_intent=memory_intent,
        query_understanding=understanding,
        execution_mode="single_execution",
        execution_kind="direct_tool",
        executions=[execution],
    )

    payload = build_orchestration_plan(
        session_id="session-a",
        message="分析这个 PDF",
        query_plan=query_plan,
        contract_previews=[
            {
                "tool_name": "pdf_analysis",
                "contract_action": "deny",
                "contract_reason": "missing_required_binding",
                "permission_allowed": True,
            }
        ],
    ).to_dict()
    contract = next(decision for decision in payload["decisions"] if decision["node_id"] == "contract-policy")

    assert payload["diagnostics"]["contract_preview_count"] == 1
    assert contract["status"] == "blocked"
    assert contract["outputs"]["blocked_count"] == 1


def test_orchestration_plan_exports_formal_directive_contract() -> None:
    understanding = QueryUnderstanding(
        intent="document_question",
        source_kind="file",
        task_kind="document_qa",
        modality="pdf",
        route="tool",
        execution_posture="direct_tool",
        tool_name="pdf_analysis",
        candidate_tools=["pdf_analysis"],
        tool_input={"query": "第 4 页讲了什么"},
        reasons=["pdf_question"],
    )
    memory_intent = MemoryIntent(intent="session_lookup", memory_read_mode="session_state")
    execution = QueryExecutionPlan(
        message="第 4 页讲了什么",
        history=[],
        memory_intent=memory_intent,
        query_understanding=understanding,
        execution_kind="direct_tool",
        tool_input={"query": "第 4 页讲了什么"},
        target_handle_kind="pdf",
        target_handle_id="pdf:active",
        search_policy=["local_files"],
    )
    query_plan = QueryPlan(
        session_id="session-a",
        message="第 4 页讲了什么",
        history=[],
        subqueries=["第 4 页讲了什么"],
        memory_intent=memory_intent,
        query_understanding=understanding,
        execution_mode="single_execution",
        execution_kind="direct_tool",
        executions=[execution],
        search_policy=["local_files"],
    )

    payload = build_orchestration_plan(
        session_id="session-a",
        message="第 4 页讲了什么",
        query_plan=query_plan,
        source="unit-test",
    ).to_dict()

    assert payload["intent_frame"]["task_kind"] == "document_qa"
    assert payload["intent_frame"]["source_needs"] == ["local_files", "document"]
    assert payload["memory_policy"]["use_session_state"] is True
    assert payload["context_policy"]["required_handles"] == ["pdf:active"]
    assert payload["resource_policy"]["allowed_sources"] == ["data", "document", "general", "local_files"]
    assert payload["execution_directives"][0]["action"] == "call_tool"
    assert payload["execution_directives"][0]["tool"] == "pdf_analysis"
    assert payload["answer_policy"]["require_citations"] is True
    assert payload["validation"]["status"] == "passed"
    assert "plan-validator" in {decision["node_id"] for decision in payload["decisions"]}


def test_orchestration_plan_validation_blocks_filtered_tool_directive() -> None:
    understanding = QueryUnderstanding(
        route="tool",
        tool_name="web_search",
        candidate_tools=["web_search"],
        structural_signals={"search_policy_blocked_tools": ["web_search"]},
        reasons=["latest_info"],
    )
    memory_intent = MemoryIntent(intent="general")
    execution = QueryExecutionPlan(
        message="查最新消息",
        history=[],
        memory_intent=memory_intent,
        query_understanding=understanding,
        execution_kind="direct_tool",
        search_policy=["rag"],
    )
    query_plan = QueryPlan(
        session_id="session-a",
        message="查最新消息",
        history=[],
        subqueries=["查最新消息"],
        memory_intent=memory_intent,
        query_understanding=understanding,
        execution_mode="single_execution",
        execution_kind="direct_tool",
        executions=[execution],
        search_policy=["rag"],
    )

    payload = build_orchestration_plan(
        session_id="session-a",
        message="查最新消息",
        query_plan=query_plan,
        mode="primary",
    ).to_dict()

    assert payload["validation"]["status"] == "blocked"
    issue_codes = {issue["code"] for issue in payload["validation"]["issues"]}
    assert "tool_blocked_by_search_policy" in issue_codes
    assert "tool_source_not_allowed" in issue_codes
    assert "tool_blocked_by_search_policy" in payload["safety"]["risks"]


def test_orchestration_resource_policy_without_explicit_search_policy_does_not_enable_web_by_default() -> None:
    understanding = QueryUnderstanding(
        route="rag",
        source_kind="knowledge_base",
        task_kind="knowledge_lookup",
        candidate_tools=["search_knowledge"],
        reasons=["knowledge_lookup"],
    )
    memory_intent = MemoryIntent(intent="general")
    execution = QueryExecutionPlan(
        message="查项目资料",
        history=[],
        memory_intent=memory_intent,
        query_understanding=understanding,
        execution_kind="worker",
    )
    query_plan = QueryPlan(
        session_id="session-a",
        message="查项目资料",
        history=[],
        subqueries=["查项目资料"],
        memory_intent=memory_intent,
        query_understanding=understanding,
        execution_mode="single_execution",
        execution_kind="worker",
        executions=[execution],
        search_policy=None,
    )

    payload = build_orchestration_plan(
        session_id="session-a",
        message="查项目资料",
        query_plan=query_plan,
        mode="primary",
    ).to_dict()

    assert "rag" in payload["resource_policy"]["allowed_sources"]
    assert "web" not in payload["resource_policy"]["allowed_sources"]
    assert payload["validation"]["status"] == "passed"
