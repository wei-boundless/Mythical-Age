from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from context_management import ContextResolver
from continuation import collect_continuation_candidates, decide_continuation
from intent import build_runtime_assembly_hint, collect_intent_frame, decide_intent
from orchestration.assembly_builder import build_orchestration_runtime_bundle
from tasks.assembly_builder import build_task_execution_assembly_bundle
from understanding.task_understanding import analyze_task_understanding


def _assemble(
    *,
    user_goal: str,
    active_bindings: dict,
    context_slots: dict,
    active_constraints: dict | None = None,
    task_id: str,
) -> dict:
    memory_runtime_view = {
        "state_snapshot": {
            "context_slots": {
                **dict(context_slots),
                **({"active_constraints": dict(active_constraints or {})} if active_constraints else {}),
            },
        }
    }
    intent_frame = collect_intent_frame(user_goal, memory_runtime_view=memory_runtime_view)
    intent_decision = decide_intent(intent_frame)
    continuation_candidates = collect_continuation_candidates(
        message=user_goal,
        memory_runtime_view=memory_runtime_view,
        intent_frame=intent_frame,
        intent_decision=intent_decision,
    )
    continuation_decision = decide_continuation(
        candidates=continuation_candidates,
        intent_decision=intent_decision,
    )
    runtime_assembly_hint = build_runtime_assembly_hint(
        intent_frame=intent_frame,
        intent_decision=intent_decision,
    )
    selected_active_bindings = dict(continuation_decision.active_bindings or {})
    if selected_active_bindings.get("active_dataset") or selected_active_bindings.get("active_pdf"):
        active_bindings = selected_active_bindings
    understanding = asdict(analyze_task_understanding(user_goal, active_bindings=active_bindings))
    current_turn = ContextResolver().resolve(
        session_id="session-semantic-boundary",
        task_id=task_id,
        user_message=user_goal,
        memory_runtime_view=memory_runtime_view,
        query_understanding=understanding,
        intent_frame=intent_frame.to_dict(),
        intent_decision=intent_decision.to_dict(),
        runtime_assembly_hint=runtime_assembly_hint,
        continuation_candidates=[item.to_dict() for item in continuation_candidates],
        continuation_decision=continuation_decision.to_dict(),
    )
    return build_task_execution_assembly_bundle(
        base_dir=BACKEND_DIR,
        session_id="session-semantic-boundary",
        task_id=task_id,
        user_goal=user_goal,
        source="test",
        query_understanding=understanding,
        current_turn_context=current_turn.to_dict(),
    )


def test_explicit_dataset_path_beats_stale_pdf_binding_in_main_assembly() -> None:
    stale_pdf = "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"
    bundle = _assemble(
        user_goal="现在切到 knowledge/E-commerce Data/employees.xlsx。找出薪资最高的前五名员工，并带上姓名、部门、薪资。",
        active_bindings={"committed_pdf": stale_pdf, "committed_dataset": "inventory.xlsx"},
        context_slots={"committed_pdf": stale_pdf, "committed_dataset": "inventory.xlsx"},
        task_id="task-semantic-explicit-dataset",
    )

    current_turn = bundle["current_turn_context"]
    explicit_inputs = dict(current_turn["explicit_inputs"])

    assert explicit_inputs["explicit_dataset_path"] == "Data/employees.xlsx"
    assert "bound_pdf_path" not in explicit_inputs
    assert "bound_dataset_path" not in explicit_inputs
    assert bundle["selected_recipe"]["recipe_id"] == "runtime.recipe.structured_data_analysis"
    assert bundle["execution_shape"]["resolution_reasons"] == ["explicit_dataset_route"]
    assert all(binding["source"] != "session_state" for binding in current_turn["resolved_bindings"])
    assert current_turn["intent_decision"]["primary_action"] == "switch_target"


def test_realtime_request_beats_stale_file_bindings_in_main_assembly() -> None:
    bundle = _assemble(
        user_goal="北京今天天气怎么样，直接给温度范围和时间口径。",
        active_bindings={"active_pdf": "report.pdf", "active_dataset": "inventory.xlsx"},
        context_slots={"active_pdf": "report.pdf", "active_dataset": "inventory.xlsx"},
        task_id="task-semantic-realtime",
    )

    explicit_inputs = dict(bundle["current_turn_context"]["explicit_inputs"])

    assert "bound_pdf_path" not in explicit_inputs
    assert "bound_dataset_path" not in explicit_inputs
    assert bundle["selected_recipe"]["recipe_id"] == "runtime.recipe.information_search"
    assert bundle["execution_shape"]["resolution_reasons"] == ["search_route"]


def test_active_subset_followup_is_result_level_contract() -> None:
    bundle = _assemble(
        user_goal="只基于刚才这前五名员工，按部门做一个归类总结，不要回到全表重算。",
        active_bindings={"active_dataset": "Data/employees.xlsx"},
        context_slots={
            "active_dataset": "Data/employees.xlsx",
            "active_result_handle_id": "result:structured:employees:top5",
            "active_subset_handle_id": "subset:selection:employees:top5",
        },
        active_constraints={
            "active_dataset": "Data/employees.xlsx",
            "source_kind": "dataset",
            "subset_labels": ["Alice", "Bob", "Chen", "Diaz", "Eve"],
            "subset_filter_column": "name",
        },
        task_id="task-semantic-active-subset",
    )

    current_turn = bundle["current_turn_context"]
    explicit_inputs = dict(current_turn["explicit_inputs"])

    assert explicit_inputs["followup_target_kind"] == "active_subset"
    assert explicit_inputs["followup_scope"] == "active_subset"
    assert "bound_dataset_path" not in explicit_inputs
    assert current_turn["followup_target_refs"] == [
        "subset:selection:employees:top5",
        "result:structured:employees:top5",
    ]
    assert bundle["task_intent_contract"]["execution_intent"] == "subset_followup"
    assert bundle["task_intent_contract"]["requested_outputs"] == ["final_answer", "task_summary_refs"]
    assert bundle["selected_recipe"]["recipe_id"] == "runtime.recipe.structured_data_analysis"
    assert bundle["execution_shape"]["resolution_reasons"] == ["subset_followup"]
    task_inputs = dict(bundle["task_spec"]["inputs"])
    followup_contract = dict(task_inputs["followup_execution_contract"])
    assert followup_contract["constraint_policy"] == "result_subset_only_do_not_expand_to_full_object"
    assert followup_contract["followup_target_refs"] == [
        "subset:selection:employees:top5",
        "result:structured:employees:top5",
    ]
    assert followup_contract["active_subset_handle_id"] == "subset:selection:employees:top5"
    assert followup_contract["active_result_handle_id"] == "result:structured:employees:top5"
    assert followup_contract["subset_filter_column"] == "name"
    assert followup_contract["subset_labels"] == ["Alice", "Bob", "Chen", "Diaz", "Eve"]
    assert task_inputs["followup_constraint_policy"] == "result_subset_only_do_not_expand_to_full_object"


def test_dataset_subset_followup_rejects_stale_pdf_candidate() -> None:
    stale_pdf = "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"
    bundle = _assemble(
        user_goal="按部门汇总这些人，只总结这前五名，不要扩展回全表。",
        active_bindings={"active_pdf": stale_pdf, "active_dataset": "Data/employees.xlsx"},
        context_slots={
            "active_pdf": stale_pdf,
            "active_dataset": "Data/employees.xlsx",
            "active_result_handle_id": "result:structured:employees:top5",
            "active_subset_handle_id": "subset:selection:employees:top5",
        },
        active_constraints={
            "active_dataset": "Data/employees.xlsx",
            "source_kind": "dataset",
            "subset_labels": ["Alice", "Bob", "Chen", "Diaz", "Eve"],
            "subset_filter_column": "name",
        },
        task_id="task-semantic-turn57-subset",
    )

    current_turn = bundle["current_turn_context"]
    bindings = list(current_turn["resolved_bindings"])
    assert current_turn["intent_decision"]["primary_action"] == "refine_scope"
    assert current_turn["continuation_decision"]["source_kind"] == "dataset"
    assert current_turn["explicit_inputs"]["followup_target_kind"] == "active_subset"
    assert any(binding["file_kind"] == "dataset" and binding["source"] == "continuation_decision" for binding in bindings)
    assert all(binding["file_kind"] != "pdf" for binding in bindings)
    assert any(
        candidate["source_kind"] == "pdf" and candidate["compatible"] is False
        for candidate in current_turn["continuation_candidates"]
    )


def test_pdf_deictic_followup_builds_pdf_continuation_contract() -> None:
    bundle = _assemble(
        user_goal="把这份 PDF 的结论压成三条行动建议，每条都要带行动动词。",
        active_bindings={"active_pdf": "knowledge/AI Knowledge/report.pdf"},
        context_slots={
            "active_pdf": "knowledge/AI Knowledge/report.pdf",
            "active_result_handle_id": "result:pdf_answer:p3",
        },
        task_id="task-semantic-pdf-followup",
    )

    current_turn = bundle["current_turn_context"]
    task_inputs = dict(bundle["task_spec"]["inputs"])
    followup_contract = dict(task_inputs["followup_execution_contract"])
    communication_protocol = dict(task_inputs["agent_communication_protocol"])

    assert current_turn["intent_decision"]["primary_action"] == "continue"
    assert current_turn["continuation_decision"]["source_kind"] == "pdf"
    assert current_turn["explicit_inputs"]["followup_target_kind"] == "active_pdf"
    assert followup_contract["source_kind"] == "pdf"
    assert followup_contract["source_path"] == "knowledge/AI Knowledge/report.pdf"
    assert communication_protocol["transport"] == "runtime_tool:delegate_to_agent"
    assert communication_protocol["target_agent_id"] == "agent:pdf_reader"
    assert communication_protocol["delegation_kind"] == "pdf_reading"
    orchestration_bundle = build_orchestration_runtime_bundle(
        base_dir=BACKEND_DIR,
        session_id="session-semantic-boundary",
        task_id="task-semantic-pdf-followup",
        user_goal="把这份 PDF 的结论压成三条行动建议，每条都要带行动动词。",
        task_assembly_bundle=bundle,
        current_turn_context=current_turn,
    )
    soul_runtime = dict(orchestration_bundle["task_body_orchestration"]["soul_runtime_view"])
    sections = [
        str(section.get("content") or "")
        for section in list(soul_runtime.get("sections") or [])
        if isinstance(section, dict)
    ]
    assert any("Child must return" in section for section in sections)
