from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from context_management import ContextResolver
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
    understanding = asdict(analyze_task_understanding(user_goal, active_bindings=active_bindings))
    current_turn = ContextResolver().resolve(
        session_id="session-semantic-boundary",
        task_id=task_id,
        user_message=user_goal,
        memory_runtime_view={
            "state_snapshot": {
                "context_slots": {
                    **dict(context_slots),
                    **({"active_constraints": dict(active_constraints or {})} if active_constraints else {}),
                },
            }
        },
        query_understanding=understanding,
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
    assert any(
        binding["source"] == "session_state"
        and binding["file_kind"] == "pdf"
        and binding["metadata"]["path"] == stale_pdf
        for binding in current_turn["resolved_bindings"]
    )


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
