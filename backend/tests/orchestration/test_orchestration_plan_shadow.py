from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from orchestration.adapters import build_shadow_orchestration_plan
from query.models import QueryExecutionPlan, QueryPlan, SubtaskPlan
from understanding import MemoryIntent, QueryUnderstanding


def test_shadow_orchestration_plan_preserves_legacy_topology() -> None:
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

    plan = build_shadow_orchestration_plan(
        session_id="session-a",
        message="帮我查项目资料",
        query_plan=query_plan,
        source="unit-test",
    )
    payload = plan.to_dict()

    assert payload["mode"] == "shadow"
    assert payload["topology"]["mode"] == "single_execution"
    assert payload["topology"]["route"] == "rag"
    assert payload["topology"]["execution_kind"] == "agent"
    assert payload["diagnostics"]["shadow_compatible"] is True
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

    payload = build_shadow_orchestration_plan(
        session_id="session-a",
        message="hello",
        query_plan=query_plan,
        mode="primary",
    ).to_dict()

    assert payload["mode"] == "primary"
    assert "primary_mode_not_cutover_to_runtime" not in payload["safety"]["warnings"]


def test_shadow_orchestration_plan_records_contract_preview_decision() -> None:
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

    payload = build_shadow_orchestration_plan(
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
