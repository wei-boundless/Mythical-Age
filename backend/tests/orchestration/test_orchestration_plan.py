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
    assert payload["diagnostics"]["intent_authority"]["state"] == "candidate_projected"
    assert payload["diagnostics"]["intent_authority"]["legacy_still_executes"] is True
    assert payload["diagnostics"]["intent_candidates"][0]["authority"] == "candidate_only"
    assert payload["diagnostics"]["restore_authority"]["phase"] == "7F"
    assert payload["diagnostics"]["restore_authority"]["state"] == "candidate_projected"
    assert payload["diagnostics"]["restore_authority"]["current_turn_override_allowed"] is False
    assert payload["diagnostics"]["restore_authority"]["candidates"] == []
    assert payload["executions"][0]["execution_id"] == "main"
    decision_by_id = {decision["node_id"]: decision for decision in payload["decisions"]}
    assert decision_by_id["task-understanding"]["status"] == "candidate"
    assert decision_by_id["task-understanding"]["outputs"]["authority"] == "candidate_only"
    assert set(decision_by_id) >= {
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
    assert payload["diagnostics"]["restore_authority"]["memory_candidates"] == ["session_state"]
    assert payload["diagnostics"]["restore_authority"]["handle_candidates"] == ["pdf:active"]
    assert "session_state_restore_candidate" in payload["diagnostics"]["restore_authority"]["blockers"]
    restore_candidates = payload["diagnostics"]["restore_authority"]["candidates"]
    assert payload["diagnostics"]["restore_authority"]["candidate_count"] == 2
    assert {item["candidate_type"] for item in restore_candidates} == {"session_state", "target_handle"}
    assert all(item["adoption_state"] == "adopted_by_legacy" for item in restore_candidates)
    assert all(item["can_override_current_intent"] is False for item in restore_candidates)
    handle_candidate = next(item for item in restore_candidates if item["candidate_type"] == "target_handle")
    assert handle_candidate["owner_module"] == "query.runtime_context_state"
    assert handle_candidate["value"] == "pdf:active"
    adoption_gate = payload["diagnostics"]["restore_authority"]["adoption_gate"]
    adoption_decisions = payload["diagnostics"]["restore_authority"]["adoption_decisions"]
    cutover_plan = payload["diagnostics"]["restore_authority"]["cutover_plan"]
    dry_run_comparison = payload["diagnostics"]["restore_authority"]["dry_run_comparison"]
    formal_review = payload["diagnostics"]["restore_authority"]["formal_adoption_review"]
    assert {item["decision"] for item in adoption_decisions} == {"blocked"}
    assert all(item["validator"] == "phase7g_restore_adoption_preview" for item in adoption_decisions)
    assert {item["memory_context_validation"]["status"] for item in adoption_decisions} == {"passed"}
    assert adoption_gate["phase"] == "7G"
    assert adoption_gate["state"] == "blocked"
    assert adoption_gate["blocked_decision_count"] == 2
    assert adoption_gate["validator_blocked_count"] == 0
    assert "restore_candidates_still_adopted_by_legacy" in adoption_gate["blockers"]
    assert adoption_gate["current_turn_override_allowed"] is False
    assert cutover_plan["phase"] == "7H"
    assert cutover_plan["state"] == "blocked"
    assert cutover_plan["delete_allowed"] is False
    assert set(cutover_plan["candidate_types"]) == {"session_state", "target_handle"}
    assert "adoption_gate:blocked" in cutover_plan["blockers"]
    assert dry_run_comparison["phase"] == "7H"
    assert dry_run_comparison["state"] == "observed_delta"
    assert dry_run_comparison["delta_count"] == 2
    assert {item["alignment"] for item in dry_run_comparison["comparisons"]} == {"expected_legacy_delta"}
    assert formal_review["phase"] == "8A"
    assert formal_review["mode"] == "diagnostic_only"
    assert formal_review["state"] == "candidate_decisions_ready"
    assert formal_review["accepted_count"] == 2
    assert formal_review["rejected_count"] == 0
    assert {item["decision"] for item in formal_review["decisions"]} == {"accepted"}
    assert {item["alignment"] for item in formal_review["comparison"]["items"]} == {"legacy_matches_formal_acceptance"}
    assert formal_review["takeover_allowed"] is False
    output_authority = payload["diagnostics"]["output_authority"]
    assert output_authority["phase"] == "7I"
    assert output_authority["state"] == "candidate_projected"
    assert output_authority["legacy_still_executes"] is True
    assert output_authority["answer_channel"] == "runtime_output_boundary"
    assert "legacy_present_still_executes" in output_authority["blockers"]
    assert "legacy_persist_still_executes" in output_authority["blockers"]
    assert output_authority["cutover_plan"]["delete_allowed"] is False
    dispatch_authority = payload["diagnostics"]["dispatch_authority"]
    assert dispatch_authority["phase"] == "7J"
    assert dispatch_authority["state"] == "candidate_projected"
    assert dispatch_authority["legacy_still_executes"] is True
    assert dispatch_authority["tool_directive_count"] == 1
    assert "legacy_decide_still_executes" in dispatch_authority["blockers"]
    assert "legacy_execute_still_executes" in dispatch_authority["blockers"]
    assert dispatch_authority["cutover_plan"]["delete_allowed"] is False
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
