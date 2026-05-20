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
from understanding.memory_intent import analyze_memory_intent


def _selected_payload(candidates, continuation) -> dict:
    selected = next(candidate for candidate in candidates if candidate.candidate_id == continuation.selected_candidate_id)
    return dict(selected.recall_payload or {})


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

    memory_intent = analyze_memory_intent(message)
    frame = collect_intent_frame(message, memory_intent=memory_intent, memory_runtime_view=memory_view)
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
    payload = _selected_payload(candidates, continuation)
    assert payload["active_dataset"] == "Data/employees.xlsx"
    assert payload["active_subset_handle_id"] == "subset:selection:employees:top5"
    assert payload["active_constraints"]["subset_filter_column"] == "name"
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

    memory_intent = analyze_memory_intent(message)
    frame = collect_intent_frame(message, memory_intent=memory_intent, memory_runtime_view=memory_view)
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
    payload = _selected_payload(candidates, continuation)
    assert payload["active_pdf"] == "knowledge/AI Knowledge/report.pdf"
    assert payload["active_result_handle_id"] == "result:pdf_answer:p3"


def test_pdf_document_followup_widens_previous_page_scope() -> None:
    memory_view = {
        "state_snapshot": {
            "context_slots": {
                "active_pdf": "knowledge/AI Knowledge/report.pdf",
                "active_pdf_mode": "page",
                "active_pdf_pages": [4],
                "active_subset_handle_id": "subset:pdf_pages:p4",
                "active_result_handle_id": "result:pdf_answer:p4",
                "active_constraints": {
                    "active_pdf": "knowledge/AI Knowledge/report.pdf",
                    "source_kind": "pdf",
                    "active_pdf_mode": "page",
                    "active_pdf_pages": [4],
                },
            }
        }
    }
    message = "把这份 PDF 的结论压成三条行动建议，每条都要带行动动词。"

    memory_intent = analyze_memory_intent(message)
    frame = collect_intent_frame(message, memory_intent=memory_intent, memory_runtime_view=memory_view)
    decision = decide_intent(frame)
    candidates = collect_continuation_candidates(
        message=message,
        memory_runtime_view=memory_view,
        intent_frame=frame,
        intent_decision=decision,
    )
    continuation = decide_continuation(candidates=candidates, intent_decision=decision)
    understanding = analyze_task_understanding(message)

    assert continuation.source_kind == "pdf"
    assert continuation.followup_target_kind == "active_pdf"
    payload = _selected_payload(candidates, continuation)
    assert payload["active_pdf"] == "knowledge/AI Knowledge/report.pdf"
    assert payload["active_constraints"]["active_pdf_mode"] == "page"
    assert understanding.route_hint == "agent"
    assert understanding.source_kind == "conversation"
    assert "mode" not in understanding.parameters
    assert "path" not in understanding.parameters


def test_pdf_page_followup_with_memory_signal_uses_memory_to_restore_object_then_read_pdf() -> None:
    memory_view = {
        "state_snapshot": {
            "context_slots": {
                "active_pdf": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
                "committed_pdf": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
                "active_result_handle_id": "result:pdf_answer:p4",
                "active_subset_handle_id": "subset:pdf_pages:p4",
                "active_constraints": {
                    "active_pdf": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
                    "source_kind": "pdf",
                    "active_pdf_mode": "page",
                    "active_pdf_pages": [4],
                },
            }
        },
        "restore_candidates": [
            {
                "candidate_id": "state-restore:session:context_slot:active_pdf",
                "restore_kind": "context_slot",
                "value": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
                "confidence": 0.82,
                "metadata": {"slot_name": "active_pdf"},
            },
            {
                "candidate_id": "state-restore:session:flow:pdf_document_flow:knowledge-ai-knowledge-2025-ai-pdf",
                "restore_kind": "context_slot",
                "value": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
                "confidence": 0.76,
                "metadata": {"slot_name": "committed_pdf"},
            },
        ],
    }
    message = "如果我要把这份报告讲给业务负责人听，第四页最值得摘出来的两到三句是什么？请直接给我摘读重点和原因。"

    memory_intent = analyze_memory_intent(message)
    frame = collect_intent_frame(message, memory_intent=memory_intent, memory_runtime_view=memory_view)
    decision = decide_intent(frame)
    candidates = collect_continuation_candidates(
        message=message,
        memory_runtime_view=memory_view,
        intent_frame=frame,
        intent_decision=decision,
    )
    continuation = decide_continuation(candidates=candidates, intent_decision=decision)
    understanding = analyze_task_understanding(message)

    assert frame.evidence["memory_recall"] is True
    assert decision.primary_action == "refine_scope"
    assert decision.needs_continuation is True
    assert decision.memory_recall_required is False
    assert continuation.source_kind == "pdf"
    assert continuation.followup_target_kind == "active_subset"
    assert continuation.followup_scope == "active_subset"
    payload = _selected_payload(candidates, continuation)
    assert payload["active_pdf"] == "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"
    assert payload["active_constraints"]["active_pdf_mode"] == "page"
    assert payload["active_constraints"]["active_pdf_pages"] == [4]
    assert understanding.route_hint == "pdf"
    assert "path" not in understanding.parameters


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
    assert _selected_payload(candidates, continuation)["active_pdf"] == "knowledge/AI Knowledge/report.pdf"


def test_dataset_followup_can_restore_from_projected_task_summary_refs() -> None:
    memory_view = {
        "state_snapshot": {
            "task_summary_refs": [
                {
                    "task_id": "result:structured:employees:top5",
                    "active_result_handle_id": "result:structured:employees:top5",
                    "active_subset_handle_id": "subset:selection:employees:top5",
                    "summary": "薪资最高前五名员工是 Alice、Bob、Chen、Diaz、Eve。",
                    "task_kind": "structured_data",
                    "key_points": [
                        "dataset=knowledge/E-commerce Data/employees.xlsx",
                    ],
                    "subset_labels": ["Alice", "Bob", "Chen", "Diaz", "Eve"],
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
    payload = _selected_payload(candidates, continuation)
    assert payload["active_dataset"] == "knowledge/E-commerce Data/employees.xlsx"
    assert payload["active_constraints"]["subset_labels"] == [
        "Alice",
        "Bob",
        "Chen",
        "Diaz",
        "Eve",
    ]


def test_dataset_followup_does_not_restore_subset_from_key_points_text() -> None:
    memory_view = {
        "state_snapshot": {
            "task_summary_refs": [
                {
                    "task_id": "result:structured:employees:top5",
                    "summary": "数据源：employees.xlsx 筛选条件：无 查询模式：记录排序 员工编号 E-0074 E-0148。",
                    "task_kind": "structured_data",
                    "key_points": [
                        "dataset=knowledge/E-commerce Data/employees.xlsx",
                        "subset=数据源,筛选条件,员工编号,E-0074,E-0148",
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
    assert continuation.followup_target_kind == "active_dataset"
    payload = _selected_payload(candidates, continuation)
    assert payload["active_dataset"] == "knowledge/E-commerce Data/employees.xlsx"
    assert "active_constraints" not in payload


def test_dataset_analysis_question_continues_active_dataset_without_deictic_wording() -> None:
    memory_view = {
        "state_snapshot": {
            "context_slots": {
                "active_dataset": "knowledge/E-commerce Data/inventory.xlsx",
                "active_result_handle_id": "result:structured:inventory:shortage",
                "active_constraints": {
                    "active_dataset": "knowledge/E-commerce Data/inventory.xlsx",
                    "source_kind": "dataset",
                },
            }
        }
    }
    message = "哪些仓库完全没有缺口？如果没有就直接说没有。"

    frame = collect_intent_frame(message, memory_runtime_view=memory_view)
    decision = decide_intent(frame)
    candidates = collect_continuation_candidates(
        message=message,
        memory_runtime_view=memory_view,
        intent_frame=frame,
        intent_decision=decision,
    )
    continuation = decide_continuation(candidates=candidates, intent_decision=decision)

    assert frame.evidence["dataset_analysis_followup"] is True
    assert decision.primary_action == "continue"
    assert decision.execution_strategy == "specialist_handoff"
    assert continuation.source_kind == "dataset"
    assert continuation.followup_target_kind == "active_dataset"
    assert _selected_payload(candidates, continuation)["active_dataset"] == "knowledge/E-commerce Data/inventory.xlsx"


def test_realtime_request_with_continuation_word_does_not_bind_stale_dataset() -> None:
    memory_view = {
        "state_snapshot": {
            "task_summary_refs": [
                {
                    "task_id": "result:structured_answer:inventory",
                    "summary": "武汉仓、上海仓、深圳仓、广州仓、成都仓、北京仓都没有库存缺口。",
                    "task_kind": "structured_data",
                    "key_points": ["dataset=inventory.xlsx", "subset=武汉仓,上海仓,深圳仓,广州仓,成都仓,北京仓"],
                    "subset_filter_column": "warehouse",
                }
            ]
        }
    }
    message = "再看一下北京今天天气，直接给天气结论和温度范围。"

    frame = collect_intent_frame(message, memory_runtime_view=memory_view)
    decision = decide_intent(frame)
    candidates = collect_continuation_candidates(
        message=message,
        memory_runtime_view=memory_view,
        intent_frame=frame,
        intent_decision=decision,
    )
    continuation = decide_continuation(candidates=candidates, intent_decision=decision)
    understanding = analyze_task_understanding(message)

    assert frame.evidence["weather_domain"] is True
    assert decision.target_domain_hint == "realtime"
    assert decision.needs_continuation is False
    assert candidates == ()
    assert understanding.route_hint == "realtime_network"
    assert "weather" in understanding.capability_requests


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


def test_professional_task_run_is_not_graph_coordination_without_graph_language() -> None:
    message = "帮我追踪这个问题并修复，最好一次性执行完计划。"

    frame = collect_intent_frame(message, memory_runtime_view={})
    decision = decide_intent(frame)
    hint = build_runtime_assembly_hint(intent_frame=frame, intent_decision=decision)

    assert frame.task_complexity == "long_running"
    assert decision.execution_strategy == "professional_task_run"
    assert hint["runtime_mode"] == "professional_task"
    assert hint["interaction_mode"] == "professional_mode"
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
