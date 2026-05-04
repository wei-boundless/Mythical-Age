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
    assert orchestration["prompt_manifest"]["manifest_id"]
    assert orchestration["soul_runtime_view"]["sections"]


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
