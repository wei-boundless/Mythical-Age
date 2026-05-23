from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prompt_library.assembler import assemble_runtime_prompt_contract
from runtime.professional_runtime.agent_plan import build_agent_plan_draft
from runtime.professional_runtime.plan_coverage import review_plan_coverage
from request_intent.request_signals import build_request_signals
from task_system.services.assembly_builder import build_task_execution_assembly_bundle
from tests.support.runtime_stubs import model_turn_context


def _frontend_contract() -> dict[str, object]:
    return {
        "contract_id": "semantic-task:plan:test",
        "task_goal_type": "frontend_app_delivery",
        "domain": "development",
        "required_actions": [
            "inspect_code",
            "apply_real_change",
            "run_browser_verification",
            "validate_deliverables",
        ],
        "deliverables": [
            "runnable_artifact_refs",
            "workflow_acceptance",
            "verification_evidence",
            "limitations",
        ],
    }


def test_missing_model_plan_is_explicit_scaffold_fallback() -> None:
    plan = build_agent_plan_draft(
        task_id="plan-scaffold",
        semantic_contract=_frontend_contract(),
    ).to_dict()

    assert plan["source"] == "deterministic_scaffold"
    assert plan["plan_status"] == "scaffold_fallback"
    assert plan["diagnostics"]["model_plan_absent"] is True
    assert plan["diagnostics"]["model_plan_authority_used"] is False
    planner_request = plan["diagnostics"]["readonly_planner_request"]
    assert planner_request["authority"] == "runtime.readonly_planner_request"
    assert planner_request["diagnostics"]["request_contract_only"] is True
    assert planner_request["diagnostics"]["model_call_performed"] is False
    assert planner_request["diagnostics"]["readonly"] is True
    assert "你是一名只读任务计划员" in planner_request["role_prompt"]
    assert "不修改文件" in planner_request["role_prompt"]
    assert "deterministic_scaffold_until_model_plan_generation_is_enabled" in plan["assumptions"]


def test_model_agent_plan_draft_is_accepted_when_schema_valid() -> None:
    contract = _frontend_contract()
    model_plan = {
        "authority": "runtime.agent_plan_draft",
        "plan_id": "agent-plan:model-valid",
        "semantic_contract_ref": contract["contract_id"],
        "task_goal_type": "frontend_app_delivery",
        "steps": [
            {
                "step_id": "inspect",
                "title": "Inspect",
                "purpose": "Read frontend structure",
                "required_operations": ["op.read_file"],
                "contract_refs": ["inspect_code"],
                "evidence_expectations": ["source_tree_observation"],
            },
            {
                "step_id": "change",
                "title": "Change",
                "purpose": "Patch frontend code",
                "required_operations": ["op.edit_file"],
                "contract_refs": ["apply_real_change", "runnable_artifact_refs", "workflow_acceptance"],
                "evidence_expectations": ["file_write", "workflow_check"],
            },
            {
                "step_id": "verify",
                "title": "Verify",
                "purpose": "Open browser and verify workflow",
                "required_operations": ["op.shell", "op.browser_control"],
                "contract_refs": ["run_browser_verification", "verification_evidence"],
                "evidence_expectations": ["browser_open", "workflow_check"],
            },
            {
                "step_id": "final",
                "title": "Final",
                "purpose": "Report delivery and limitations",
                "required_operations": ["op.model_response"],
                "contract_refs": ["validate_deliverables", "limitations"],
                "evidence_expectations": ["completion_judgment"],
            },
        ],
    }

    plan = build_agent_plan_draft(
        task_id="plan-model",
        semantic_contract=contract,
        model_agent_plan_draft=model_plan,
    ).to_dict()
    review = review_plan_coverage(
        task_id="plan-model",
        semantic_contract=contract,
        agent_plan_draft=plan,
    ).to_dict()

    assert plan["source"] == "model_agent_plan_draft"
    assert plan["diagnostics"]["model_plan_authority_used"] is True
    assert plan["diagnostics"]["readonly_planner_request"]["diagnostics"]["model_call_performed"] is False
    assert review["passed"] is True
    assert review["gate_status"] == "passed"


def test_plan_coverage_hard_gate_blocks_execution_steps_when_model_plan_misses_contract() -> None:
    message = "请重构前端任务图编辑器，做成可运行的编辑器体验，并用浏览器验证关键工作流。"
    turn_context = model_turn_context(
        action_intent="edit_workspace",
        work_mode="implementation",
        interaction_intent="modify",
        desired_outcome=message,
        deliverables=["runnable_artifact_refs", "workflow_acceptance", "verification_evidence"],
        planning_required=True,
        todo_required=True,
        task_goal_type="frontend_app_delivery",
        task_domain="development",
    )
    query_understanding = {
        **build_request_signals(message).to_dict(),
        "model_turn_decision": dict(turn_context["model_turn_decision"]),
        "request_facts": dict(turn_context["request_facts"]),
        "boundary_policy": dict(turn_context["boundary_policy"]),
        "action_permit": dict(turn_context["action_permit"]),
    }
    bundle = build_task_execution_assembly_bundle(
        base_dir=ROOT,
        session_id="plan-gate-session",
        task_id="plan-gate-task",
        user_goal=message,
        source="test",
        query_understanding=query_understanding,
        current_turn_context={
            **turn_context,
            "interaction_mode": "professional_mode",
            "runtime_interaction_mode": "professional_mode",
            "mode_policy": {
                "execution_strategy": "professional_task_run",
                "interaction_mode": "professional_mode",
                "runtime_lane": "professional_task",
            },
            "model_agent_plan_draft": {
                "authority": "runtime.agent_plan_draft",
                "plan_id": "agent-plan:incomplete",
                "steps": [
                    {
                        "step_id": "inspect_only",
                        "title": "Inspect only",
                        "purpose": "Read current code",
                        "contract_refs": ["inspect_code"],
                        "evidence_expectations": ["source_tree_observation"],
                    }
                ],
            },
        },
    )

    recipe = dict(bundle["selected_recipe"])
    metadata = dict(recipe["metadata"])
    coverage = dict(metadata["plan_coverage_review"])
    step_ids = [str(item.get("step_id") or "") for item in list(recipe["step_blueprints"]) if isinstance(item, dict)]

    assert metadata["agent_plan_draft"]["source"] == "model_agent_plan_draft"
    assert coverage["passed"] is False
    assert coverage["gate_status"] == "blocked_replan_required"
    assert coverage["diagnostics"]["hard_gate"] is True
    assert "apply_real_change" in coverage["missing_actions"]
    assert "step_execution.implement_frontend_changes" not in step_ids
    assert "verification" not in step_ids
    assert step_ids[-1] == "finalization"


def test_prompt_sections_explain_scaffold_and_hard_gate() -> None:
    plan = build_agent_plan_draft(
        task_id="plan-prompt",
        semantic_contract=_frontend_contract(),
    ).to_dict()
    coverage = review_plan_coverage(
        task_id="plan-prompt",
        semantic_contract=_frontend_contract(),
        agent_plan_draft={"plan_id": "agent-plan:empty", "steps": []},
    ).to_dict()

    prompt = assemble_runtime_prompt_contract(
        base_dir=ROOT.parent,
        task_id="plan-prompt",
        user_goal="重构前端",
        task_contract={
            "user_goal": "重构前端",
            "task_requirement_contract": _frontend_contract(),
            "mode_policy": {"interaction_mode": "professional_mode"},
        },
        task_execution_assembly={"task_family": "runtime", "task_mode": "professional_mode", "metadata": {}},
        task_spec={"inputs": {}},
        selected_recipe={
            "recipe_id": "runtime.recipe.professional_task",
            "metadata": {
                "agent_plan_draft": plan,
                "plan_coverage_review": coverage,
            },
        },
        task_workflow={},
        binding={},
        registered_task={},
        skill_runtime_views=[],
        projection_requirement={},
        operation_requirement={"optional_operations": ["op.agent_todo"]},
        active_skill={},
        agent_id="agent:0",
        current_turn_context={},
    )

    assert "没有真实模型生成的执行计划草稿" in prompt["agent_plan_section"]
    assert "硬门状态=blocked_replan_required" in prompt["plan_coverage_section"]
    assert "不能进入执行步骤" in prompt["plan_coverage_section"]
