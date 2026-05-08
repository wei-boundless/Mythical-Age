from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from orchestration import build_orchestration_runtime_bundle
from tasks.assembly_builder import build_task_execution_assembly_bundle


def test_orchestration_runtime_bundle_builds_formal_objects() -> None:
    task_bundle = build_task_execution_assembly_bundle(
        session_id="session-orch-runtime",
        task_id="taskinst:turn:session-orch-runtime:1:general_response",
        user_goal="请生成一个可以直接运行的网页贪吃蛇小游戏。",
        source="test",
        current_turn_context={
            "authority": "context.current_turn",
            "turn_id": "turn:session-orch-runtime:1",
            "selected_task_id": "task.dev.light_web_game",
        },
    )

    payload = build_orchestration_runtime_bundle(
        base_dir=BACKEND_DIR,
        session_id="session-orch-runtime",
        task_id="taskinst:turn:session-orch-runtime:1:general_response",
        user_goal="请生成一个可以直接运行的网页贪吃蛇小游戏。",
        task_assembly_bundle=task_bundle,
        current_turn_context={
            "authority": "context.current_turn",
            "turn_id": "turn:session-orch-runtime:1",
            "selected_task_id": "task.dev.light_web_game",
        },
        memory_runtime_view={"view_id": "memview:test"},
        context_policy_result={"result_id": "ctxpolicy:test"},
    )

    body = payload["agent_body_profile"]
    prompt = payload["prompt_structure_profile"]
    memory_scope = payload["memory_scope_profile"]
    lane = payload["runtime_lane_profile"]
    output = payload["output_boundary_profile"]
    orchestration = payload["task_body_orchestration"]
    runtime_spec = payload["agent_runtime_spec"]

    assert body["authority"] == "orchestration.agent_body_profile"
    assert prompt["authority"] == "orchestration.prompt_structure_profile"
    assert memory_scope["authority"] == "orchestration.memory_scope_profile"
    assert lane["authority"] == "orchestration.runtime_lane_profile"
    assert output["authority"] == "orchestration.output_boundary_profile"
    assert orchestration["authority"] == "orchestration.task_body_orchestration"
    assert runtime_spec["authority"] == "orchestration.agent_runtime_spec"
    assert orchestration["task_execution_assembly_ref"] == task_bundle["task_execution_assembly"]["assembly_id"]
    assert runtime_spec["task_body_orchestration_ref"] == orchestration["orchestration_id"]
    assert runtime_spec["resource_policy_candidate_ref"] == task_bundle["operation_requirement"]["requirement_id"]
    assert orchestration["projection_requirement"]["role_type"]
    assert orchestration["projection_requirement"]["reason"]
    assert orchestration["projection_requirement"]["projection_optional"] is True
    assert orchestration["projection_requirement"]["resolution_source"] in {"task_requirement", "agent_default", "no_projection"}
    assert orchestration["diagnostics"]["projection_resolution"]["status"] in {"ok", "warning"}
    assert orchestration["prompt_manifest"]["manifest_id"]
    assert orchestration["soul_runtime_view"]["sections"]
    assert orchestration["projection_ref"] == orchestration["projection_requirement"]["projection_id"] or not orchestration["projection_requirement"]["projection_id"]


def test_orchestration_runtime_bundle_uses_selected_task_profiles() -> None:
    task_bundle = build_task_execution_assembly_bundle(
        session_id="session-orch-health",
        task_id="taskinst:turn:session-orch-health:1:health_issue_triage",
        user_goal="请检查这个 health issue 的修复建议。",
        source="test",
        current_turn_context={
            "authority": "context.current_turn",
            "turn_id": "turn:session-orch-health:1",
            "selected_task_id": "task.health.issue_triage",
        },
    )

    payload = build_orchestration_runtime_bundle(
        base_dir=BACKEND_DIR,
        session_id="session-orch-health",
        task_id="taskinst:turn:session-orch-health:1:health_issue_triage",
        user_goal="请检查这个 health issue 的修复建议。",
        task_assembly_bundle=task_bundle,
        current_turn_context={
            "authority": "context.current_turn",
            "turn_id": "turn:session-orch-health:1",
            "selected_task_id": "task.health.issue_triage",
        },
    )

    runtime_spec = payload["agent_runtime_spec"]
    orchestration = payload["task_body_orchestration"]

    assert runtime_spec["runtime_lane"] in {"health_issue_read", "full_interactive"}
    assert orchestration["resource_binding_plan"]["operation_requirement_ref"].startswith("opreq:")
    assert orchestration["verification_gate_plan"]["task_constraints"] == task_bundle["task_execution_assembly"]["task_constraints"]


def test_removed_story_task_selection_falls_back_to_general_runtime() -> None:
    task_bundle = build_task_execution_assembly_bundle(
        session_id="session-orch-story",
        task_id="taskinst:turn:session-orch-story:1:short_story",
        user_goal="请完成一篇短篇小说。",
        source="test",
        current_turn_context={
            "authority": "context.current_turn",
            "turn_id": "turn:session-orch-story:1",
            "selected_task_id": "task.writing.short_story",
        },
    )

    assembly = task_bundle["task_execution_assembly"]

    assert assembly["task_mode"] == "general_task"
    assert assembly["task_family"] == "general"
    assert assembly["flow_contract_id"] == ""
    assert assembly["communication_protocol_ref"] == ""
    assert assembly["coordination_task_ref"] == ""
    assert assembly["topology_template_ref"] == ""


def test_removed_longform_writing_runtime_residue_stays_absent() -> None:
    from tasks.flow_registry import TaskFlowRegistry
    from tasks.template_registry import default_task_templates
    from orchestration.agent_runtime_chain import _align_understanding_with_explicit_task_selection
    from understanding.query_understanding import analyze_query_understanding

    registry = TaskFlowRegistry(BACKEND_DIR)
    templates = {item.template_id for item in default_task_templates()}

    assert "template.writing.longform_novel_project" not in templates
    assert "template.writing.chapter_drafting" not in templates
    assert registry.get_coordination_task("coord.writing.longform_project_bootstrap") is None
    assert registry.get_coordination_task("coord.writing.chapter_pipeline") is None
    assert registry.get_task_communication_protocol("protocol.writing.longform_project_bootstrap") is None
    assert registry.get_task_communication_protocol("protocol.writing.chapter_pipeline") is None
    assert registry.get_specific_task_record("task.writing.chapter_planning") is None
    assert registry.get_specific_task_record("task.writing.chapter_drafting") is None

    message = (
        "这是写作域的真实执行任务，不是文档阅读、文件解读、PDF分析。"
        "请生成第001章到第003章短批次规划，并写入 "
        "docs/系统规划/任务系统实测记录/artifacts/20260506/E5/batches/batch_001_003_plan.md。"
    )
    understanding = analyze_query_understanding(message)
    aligned = _align_understanding_with_explicit_task_selection(
        BACKEND_DIR,
        understanding,
        task_selection={"selected_task_id": "task.writing.chapter_planning"},
    )

    assert aligned.source_kind != "task_system"
    assert aligned.task_kind != "chapter_planning"
