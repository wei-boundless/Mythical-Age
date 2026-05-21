from __future__ import annotations

from pathlib import Path

from orchestration.assembly_builder import build_orchestration_runtime_bundle
from task_system.services.assembly_builder import build_task_execution_assembly_bundle


def _runtime_for_goal(user_goal: str) -> dict:
    task_bundle = build_task_execution_assembly_bundle(
        base_dir=Path("backend"),
        session_id="session-projection-boundary",
        task_id="task-projection-boundary",
        user_goal=user_goal,
        source="test",
        query_understanding={"route": "workspace_read", "source_kind": "workspace"},
        current_turn_context={},
    )
    return build_orchestration_runtime_bundle(
        base_dir=Path("backend"),
        session_id="session-projection-boundary",
        task_id="task-projection-boundary",
        user_goal=user_goal,
        task_assembly_bundle=task_bundle,
        current_turn_context=task_bundle["current_turn_context"],
    )


def test_professional_mode_projection_is_style_only_and_non_authoritative() -> None:
    runtime = _runtime_for_goal(
        "追踪 backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json 的失败原因，修复代码，然后运行 pytest 验证。"
    )
    orchestration = runtime["task_body_orchestration"]
    projection = orchestration["projection_requirement"]
    sections = {section["section_id"]: section for section in orchestration["soul_runtime_view"]["sections"]}

    assert projection["interaction_mode"] == "professional_mode"
    assert projection["projection_strength"] == "style_only"
    assert projection["mode_policy_ref"] == "orchestration.runtime_interaction_mode_policy"
    assert sections["projection_section"]["owner_layer"] == "projection"
    assert sections["semantic_task_section"]["owner_layer"] == "task"
    assert sections["professional_profile_section"]["owner_layer"] == "task"
    assert sections["mode_policy_section"]["owner_layer"] == "task"
    assert "不能覆盖交付物和验证要求" in sections["mode_policy_section"]["content"]
    assert "执行义务" in sections["professional_profile_section"]["content"]


def test_prompt_manifest_tracks_task_and_projection_section_sources() -> None:
    runtime = _runtime_for_goal(
        "分析 backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json 的失败，列出结构性根因。"
    )
    manifest = runtime["task_body_orchestration"]["prompt_manifest"]
    sections = {section["section_id"]: section for section in manifest["sections"]}

    assert sections["semantic_task_section"]["source_type"] == "semantic_task_contract"
    assert sections["semantic_task_section"]["owner_layer"] == "task"
    assert sections["professional_profile_section"]["source_type"] == "professional_prompt_profile"
    assert sections["mode_policy_section"]["source_type"] == "runtime_interaction_mode_policy"
    assert sections["projection_section"]["source_type"] == "projection_requirement"
    assert sections["projection_section"]["owner_layer"] == "projection"
