from __future__ import annotations

from pathlib import Path

from agent_system.assembly.runtime_bundle_builder import build_orchestration_runtime_bundle
from request_intent.request_signals import build_request_signals
from task_system.services.assembly_builder import build_task_execution_assembly_bundle
from tests.support.runtime_stubs import model_turn_context


def _runtime_for_goal(user_goal: str) -> dict:
    is_repair = "修复代码" in user_goal or "pytest" in user_goal
    turn_context = model_turn_context(
        action_intent="edit_workspace" if is_repair else "read_context",
        work_mode="implementation" if is_repair else "read_only_analysis",
        interaction_intent="modify" if is_repair else "review",
        target_objects=["backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json"],
        desired_outcome=user_goal,
        task_goal_type="code_fix_execution" if is_repair else "test_report_triage",
        task_domain="testing",
    )
    task_bundle = build_task_execution_assembly_bundle(
        base_dir=Path("backend"),
        session_id="session-projection-boundary",
        task_id="task-projection-boundary",
        user_goal=user_goal,
        source="test",
        query_understanding={
            **build_request_signals(user_goal).to_dict(),
            "model_turn_decision": dict(turn_context["model_turn_decision"]),
            "request_facts": dict(turn_context["request_facts"]),
            "boundary_policy": dict(turn_context["boundary_policy"]),
            "action_permit": dict(turn_context["action_permit"]),
        },
        current_turn_context=turn_context,
    )
    return build_orchestration_runtime_bundle(
        base_dir=Path("backend"),
        session_id="session-projection-boundary",
        task_id="task-projection-boundary",
        user_goal=user_goal,
        task_assembly_bundle=task_bundle,
        current_turn_context=task_bundle["current_turn_context"],
    )


def test_professional_code_task_projection_is_style_only_and_non_authoritative() -> None:
    runtime = _runtime_for_goal(
        "追踪 backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json 的失败原因，修复代码，然后运行 pytest 验证。"
    )
    orchestration = runtime["task_body_orchestration"]
    projection = orchestration["projection_requirement"]
    sections = {section["section_id"]: section for section in orchestration["soul_runtime_view"]["sections"]}

    assert projection["interaction_mode"] == "professional_mode"
    assert projection["projection_strength"] == "style_only"
    assert projection["mode_policy_ref"] == "orchestration.runtime_interaction_mode_policy"
    assert "projection_section" not in sections
    assert sections["semantic_task_section"]["owner_layer"] == "task"
    assert sections["professional_profile_section"]["owner_layer"] == "task"
    assert sections["mode_policy_section"]["owner_layer"] == "task"
    assert "专业任务职责" in sections["mode_policy_section"]["content"]
    assert "真实变更" in sections["mode_policy_section"]["content"]
    assert "code_fix_execution" in sections["semantic_task_section"]["content"]
    assert "你是一名专业代码任务执行员" in sections["professional_profile_section"]["content"]
    assert "必须优先阅读当前项目的真实目录结构" in sections["professional_profile_section"]["content"]
    assert "专业长任务测试报告诊断员" not in sections["professional_profile_section"]["content"]


def test_prompt_manifest_tracks_task_and_projection_section_sources() -> None:
    runtime = _runtime_for_goal(
        "分析 backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json 的失败，列出结构性根因。"
    )
    manifest = runtime["task_body_orchestration"]["prompt_manifest"]
    sections = {section["section_id"]: section for section in manifest["sections"]}

    assert sections["semantic_task_section"]["source_type"] == "task_requirement_contract"
    assert sections["semantic_task_section"]["owner_layer"] == "task"
    assert sections["professional_profile_section"]["source_type"] == "professional_prompt_profile"
    assert sections["mode_policy_section"]["source_type"] == "runtime_interaction_mode_policy"
    assert manifest["validation"]["interaction_mode"] == "professional_mode"
    assert manifest["validation"]["passed"] is True
    assert "projection_section" not in sections
