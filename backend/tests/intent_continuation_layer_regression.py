from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from continuation import collect_continuation_candidates, decide_continuation
from continuation.profile_registry import default_continuation_profiles
from intent import build_runtime_assembly_hint, collect_intent_frame, decide_intent
from intent.profile_registry import default_intent_profiles
from understanding.task_understanding import analyze_task_understanding


def test_turn57_intent_selects_dataset_subset_and_rejects_pdf_candidate() -> None:
    memory_view = {
        "state_snapshot": {
            "context_slots": {
                "active_pdf": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
                "active_dataset": "Data/employees.xlsx",
                "active_result_handle_id": "result:structured:employees:top5",
                "active_subset_handle_id": "subset:selection:employees:top5",
                "active_constraints": {
                    "active_dataset": "Data/employees.xlsx",
                    "source_kind": "dataset",
                    "subset_labels": ["Alice", "Bob", "Chen", "Diaz", "Eve"],
                    "subset_filter_column": "name",
                },
            }
        }
    }
    message = "按部门汇总这些人，只总结这前五名，不要扩展回全表。"

    frame = collect_intent_frame(message, memory_runtime_view=memory_view)
    decision = decide_intent(frame)
    candidates = collect_continuation_candidates(
        message=message,
        memory_runtime_view=memory_view,
        intent_frame=frame,
        intent_decision=decision,
    )
    continuation = decide_continuation(candidates=candidates, intent_decision=decision)

    assert decision.primary_action == "refine_scope"
    assert decision.needs_continuation is True
    assert continuation.followup_target_kind == "active_subset"
    assert continuation.source_kind == "dataset"
    assert continuation.active_bindings["active_dataset"] == "Data/employees.xlsx"
    assert continuation.active_bindings["delegation_kind"] == "table_analysis"
    assert continuation.active_bindings["target_agent_id"] == "agent:table_analyst"
    assert any(candidate.source_kind == "pdf" and candidate.compatible is False for candidate in candidates)


def test_deictic_pdf_followup_uses_continuation_not_switch_target() -> None:
    memory_view = {
        "state_snapshot": {
            "context_slots": {
                "active_pdf": "knowledge/AI Knowledge/report.pdf",
                "active_pdf_mode": "page",
                "active_pdf_pages": [3],
                "active_result_handle_id": "result:pdf_answer:p3",
            }
        }
    }
    message = "把这份 PDF 的结论压成三条行动建议。"

    frame = collect_intent_frame(message, memory_runtime_view=memory_view)
    decision = decide_intent(frame)
    candidates = collect_continuation_candidates(
        message=message,
        memory_runtime_view=memory_view,
        intent_frame=frame,
        intent_decision=decision,
    )
    continuation = decide_continuation(candidates=candidates, intent_decision=decision)

    assert decision.primary_action == "continue"
    assert decision.needs_continuation is True
    assert continuation.source_kind == "pdf"
    assert continuation.followup_target_kind == "active_pdf"
    assert continuation.active_bindings["target_agent_id"] == "agent:pdf_reader"
    assert continuation.active_bindings["delegation_kind"] == "pdf_reading"


def test_deictic_pdf_followup_uses_committed_pdf_when_active_slot_is_absent() -> None:
    memory_view = {
        "state_snapshot": {
            "context_slots": {
                "committed_pdf": "knowledge/AI Knowledge/report.pdf",
                "committed_pdf_owner_task_id": "result:pdf_answer:overview",
            }
        },
        "restore_candidates": [
            {
                "candidate_id": "state-restore:session:context_slot:committed_pdf",
                "restore_kind": "context_slot",
                "value": "knowledge/AI Knowledge/report.pdf",
                "confidence": 0.72,
                "metadata": {"slot_name": "committed_pdf"},
            }
        ],
    }
    message = "把这份 PDF 的结论压成三条行动建议。"

    frame = collect_intent_frame(message, memory_runtime_view=memory_view)
    decision = decide_intent(frame)
    candidates = collect_continuation_candidates(
        message=message,
        memory_runtime_view=memory_view,
        intent_frame=frame,
        intent_decision=decision,
    )
    continuation = decide_continuation(candidates=candidates, intent_decision=decision)

    assert decision.needs_continuation is True
    assert continuation.source_kind == "pdf"
    assert continuation.active_bindings["active_pdf"] == "knowledge/AI Knowledge/report.pdf"


def test_dataset_followup_can_restore_from_projected_task_summary_refs() -> None:
    memory_view = {
        "state_snapshot": {
            "task_summary_refs": [
                {
                    "task_id": "result:structured:employees:top5",
                    "summary": "薪资最高前五名员工是 Alice、Bob、Chen、Diaz、Eve。",
                    "task_kind": "structured_data",
                    "key_points": [
                        "dataset=knowledge/E-commerce Data/employees.xlsx",
                        "subset=Alice,Bob,Chen,Diaz,Eve",
                    ],
                    "subset_filter_column": "name",
                }
            ]
        }
    }
    message = "按部门汇总这些人，只总结这前五名，不要扩展回全表。"

    frame = collect_intent_frame(message, memory_runtime_view=memory_view)
    decision = decide_intent(frame)
    candidates = collect_continuation_candidates(
        message=message,
        memory_runtime_view=memory_view,
        intent_frame=frame,
        intent_decision=decision,
    )
    continuation = decide_continuation(candidates=candidates, intent_decision=decision)

    assert decision.primary_action == "refine_scope"
    assert continuation.source_kind == "dataset"
    assert continuation.followup_target_kind == "active_subset"
    assert continuation.active_bindings["active_dataset"] == "knowledge/E-commerce Data/employees.xlsx"
    assert continuation.active_bindings["active_constraints"]["subset_labels"] == [
        "Alice",
        "Bob",
        "Chen",
        "Diaz",
        "Eve",
    ]


def test_local_knowledge_request_uses_rag_runtime_strategy_not_text_search() -> None:
    message = "基于本地知识库，告诉我 AI 治理里最常见的三类风险。"

    frame = collect_intent_frame(message, memory_runtime_view={})
    decision = decide_intent(frame)
    hint = build_runtime_assembly_hint(intent_frame=frame, intent_decision=decision)
    understanding = analyze_task_understanding(message)

    assert decision.primary_action == "retrieve_knowledge"
    assert hint["execution_strategy"] == "retrieval_augmented_answer"
    assert understanding.route_hint == "rag"
    assert understanding.execution_posture == "direct_rag"
    assert understanding.preferred_skill == "rag-skill"
    assert understanding.candidate_tools == []


def test_single_agent_long_task_is_not_graph_coordination_without_graph_language() -> None:
    message = "帮我追踪这个问题并修复，最好一次性执行完计划。"

    frame = collect_intent_frame(message, memory_runtime_view={})
    decision = decide_intent(frame)
    hint = build_runtime_assembly_hint(intent_frame=frame, intent_decision=decision)

    assert frame.task_complexity == "long_running"
    assert decision.execution_strategy == "single_agent_long_run"
    assert hint["runtime_mode"] == "single_agent_long"
    assert hint["graph_coordination_allowed"] is False


def test_graph_coordination_requires_explicit_multi_agent_or_graph_language() -> None:
    message = "让规划、执行、审核三个 Agent 按阶段协作完成这个任务。"

    frame = collect_intent_frame(message, memory_runtime_view={})
    decision = decide_intent(frame)
    hint = build_runtime_assembly_hint(intent_frame=frame, intent_decision=decision)

    assert decision.execution_strategy == "graph_coordination_run"
    assert hint["runtime_mode"] == "graph_coordination"
    assert hint["graph_coordination_allowed"] is True


def test_intent_and_continuation_profiles_are_configured_not_file_only() -> None:
    intent_profiles = {profile.domain_id: profile for profile in default_intent_profiles()}
    continuation_profiles = {profile.domain_id: profile for profile in default_continuation_profiles()}

    assert "workflow_graph" in intent_profiles
    assert intent_profiles["workflow_graph"].execution_strategy_candidates[0] == "graph_coordination_run"
    assert "task_bundle" in continuation_profiles
    assert continuation_profiles["task_bundle"].source_kind == "bundle_result"
    assert continuation_profiles["dataset"].target_agent_id == "agent:table_analyst"
