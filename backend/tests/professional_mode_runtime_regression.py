from __future__ import annotations

from pathlib import Path

from orchestration.assembly_builder import build_orchestration_runtime_bundle
from orchestration.runtime_lane_registry import DEFAULT_RUNTIME_LANE_REGISTRY
from orchestration.runtime_loop.deliverable_validator import validate_deliverable
from orchestration.runtime_loop.evidence_packet import build_evidence_packet
from prompting.professional_profiles import get_professional_prompt_profile
from tasks.assembly_builder import build_task_execution_assembly_bundle


def test_professional_mode_recipe_uses_new_runtime_names() -> None:
    bundle = build_task_execution_assembly_bundle(
        base_dir=Path("backend"),
        session_id="session-professional-recipe",
        task_id="task-professional-recipe",
        user_goal=(
            "分析 backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json "
            "里的失败，输出失败归类、结构性根因和回归测试建议。"
        ),
        source="test",
        query_understanding={"route": "workspace_read", "source_kind": "workspace"},
        current_turn_context={},
    )

    shape = bundle["execution_shape"]
    recipe = bundle["selected_recipe"]
    metadata = recipe["metadata"]

    assert shape["recipe_id"] == "runtime.recipe.professional_task"
    assert shape["execution_kind"] == "professional_mode"
    assert metadata["runtime_driver"] == "professional_task_run"
    assert metadata["interaction_mode"] == "professional_mode"
    assert metadata["runtime_lane_hint"] == "professional_task"
    assert metadata["semantic_task_contract"]["task_goal_type"] == "test_report_triage"
    retired_mode_key = "_".join(("autonomy", "mode"))
    assert retired_mode_key not in metadata


def test_professional_profile_is_injected_into_soul_runtime_view() -> None:
    task_bundle = build_task_execution_assembly_bundle(
        base_dir=Path("backend"),
        session_id="session-professional-prompt",
        task_id="task-professional-prompt",
        user_goal=(
            "分析 backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json "
            "里的失败，输出失败归类、结构性根因和回归测试建议。"
        ),
        source="test",
        query_understanding={"route": "workspace_read", "source_kind": "workspace"},
        current_turn_context={},
    )
    runtime = build_orchestration_runtime_bundle(
        base_dir=Path("backend"),
        session_id="session-professional-prompt",
        task_id="task-professional-prompt",
        user_goal=(
            "分析 backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json "
            "里的失败，输出失败归类、结构性根因和回归测试建议。"
        ),
        task_assembly_bundle=task_bundle,
        current_turn_context=task_bundle["current_turn_context"],
    )

    orchestration = runtime["task_body_orchestration"]
    sections = {
        section["section_id"]: section
        for section in orchestration["soul_runtime_view"]["sections"]
    }

    assert orchestration["projection_requirement"]["interaction_mode"] == "professional_mode"
    assert orchestration["projection_requirement"]["projection_strength"] == "style_only"
    assert "professional_profile_section" in sections
    assert "专业长任务测试报告诊断员" in sections["professional_profile_section"]["content"]
    assert "semantic_task_section" in sections
    assert "test_report_triage" in sections["semantic_task_section"]["content"]


def test_evidence_packet_and_validator_require_triage_deliverables() -> None:
    semantic_contract = {
        "contract_id": "semantic-task:test",
        "task_goal_type": "test_report_triage",
        "materials": [{"path": "failing_sixty_turn_summary.json", "kind": "json", "role": "failure_report"}],
    }
    evidence = build_evidence_packet(
        task_run_id="taskrun:test",
        semantic_contract=semantic_contract,
        observations=[
            {
                "observation_ref": "obs:1",
                "tool_name": "read_structured_file",
                "result": {
                    "run_id": "run-1",
                    "total_turns": 60,
                    "failed_turns": 2,
                    "failures": [
                        {
                            "turn": 17,
                            "check": "output_boundary",
                            "symptom": "missing required response terms",
                            "evidence": "结构、根因、回归缺失",
                        }
                    ],
                },
            }
        ],
    )
    answer = "失败归类：output boundary。结构性根因：语义契约没有进入收口。回归测试：补长跑验收。证据边界：未运行新测试。"

    result = validate_deliverable(
        final_answer=answer,
        semantic_contract=semantic_contract,
        evidence_packet=evidence.to_dict(),
        strict=True,
    )

    assert evidence.facts
    assert evidence.classifications
    assert result.passed is True


def test_deliverable_validator_flags_read_file_tag_leak() -> None:
    result = validate_deliverable(
        final_answer="<read_file>\n<path>outline_review.md</path>\n</read_file>",
        semantic_contract={"task_goal_type": "general"},
    )

    assert result.passed is False
    assert result.protocol_leak_detected is True
    assert "protocol_boundary" in result.missing_deliverables


def test_deliverable_validator_flags_command_tool_markup_leak() -> None:
    result = validate_deliverable(
        final_answer='我将调用 name="command" 运行 pytest。',
        semantic_contract={"task_goal_type": "general"},
    )

    assert result.passed is False
    assert result.protocol_leak_detected is True
    assert "protocol_boundary" in result.missing_deliverables


def test_runtime_lane_registry_exposes_three_modes_and_removes_old_lane() -> None:
    assert DEFAULT_RUNTIME_LANE_REGISTRY.get("role_interaction") is not None
    assert DEFAULT_RUNTIME_LANE_REGISTRY.get("standard_task") is not None
    assert DEFAULT_RUNTIME_LANE_REGISTRY.get("professional_task") is not None
    assert DEFAULT_RUNTIME_LANE_REGISTRY.get("autonomous_task") is None


def test_professional_profile_registry_has_test_report_triage_role_prompt() -> None:
    profile = get_professional_prompt_profile("professional.test_report_triage")

    assert profile is not None
    assert "你是一名专业长任务测试报告诊断员" in profile.prompt
    assert "不负责修改代码" not in profile.prompt
    assert "如果用户本轮明确要求修复或修改" in profile.prompt
