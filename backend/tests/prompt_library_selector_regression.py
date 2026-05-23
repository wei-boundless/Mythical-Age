from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prompt_library import PromptResource, PromptSelector, PromptSelectionContext
from prompt_library.selector import build_prompt_selection_context


def test_prompt_selector_selects_static_default_resource_types_for_matching_context() -> None:
    context = PromptSelectionContext(
        task_id="runtime-task",
        interaction_mode="professional_mode",
        task_goal_type="game_vertical_slice_delivery",
        task_domain="development",
        current_step_id="domain_flow_matching",
        current_step_kind="domain_flow_matching",
    )
    plan = PromptSelector(
        (
            PromptResource(
                resource_id="prompt.default.mode_policy.professional_mode",
                resource_type="mode_policy",
                title="专业模式边界",
                content="当前是专业任务模式。",
                applies_to_modes=("professional_mode",),
            ),
            PromptResource(
                resource_id="prompt.default.flow_matching_policy.goal_profile_binding",
                resource_type="flow_matching_policy",
                title="目标流程匹配规则",
                content="你负责把已经理解出的任务目标绑定到合适的任务流程和目标模板。",
                step_kind="domain_flow_matching",
            ),
            PromptResource(
                resource_id="prompt.default.domain_role.game_vertical_slice_delivery",
                resource_type="domain_role",
                title="浏览器游戏垂直切片开发负责人",
                content="你是一名浏览器游戏垂直切片开发负责人。",
                applies_to_task_goal_types=("game_vertical_slice_delivery",),
                applies_to_domains=("development",),
                applies_to_modes=("professional_mode",),
            ),
        )
    ).select(context)

    selected_by_type = {item.resource_type: item for item in plan.selected}

    assert selected_by_type["mode_policy"].section_id == "mode_policy_section"
    assert selected_by_type["flow_matching_policy"].section_id == "flow_matching_policy_section"
    assert selected_by_type["domain_role"].resource_id == "prompt.default.domain_role.game_vertical_slice_delivery"
    assert "domain_flow_matching_stage" in selected_by_type["flow_matching_policy"].selection_reason


def test_prompt_selector_prefers_workflow_stage_role_over_generic_domain_role() -> None:
    context = PromptSelectionContext(
        task_id="runtime-task",
        user_goal="执行世界观设计节点",
        interaction_mode="professional_mode",
        process_kind="task_graph_node",
        task_goal_type="task_graph_node_execution",
        task_domain="writing",
        workflow_id="workflow.writing.node.world_design",
        node_id="world_design",
        stage_id="world_design",
        current_step_id="world_design",
        current_step_kind="task_graph_node",
        task_graph_node_runtime=True,
        workflow_steps=({"step_id": "world_design", "title": "世界观设计", "step_kind": "task_graph_node"},),
        step_sequence=("world_design",),
    )
    plan = PromptSelector(
        (
            PromptResource(
                resource_id="prompt.generic.writing.stage_role",
                resource_type="stage_role",
                title="通用写作职责",
                content="你是一名通用写作助手。",
                applies_to_domains=("writing",),
                applies_to_modes=("professional_mode",),
                priority=10,
            ),
            PromptResource(
                resource_id="prompt.world_design.stage_role",
                resource_type="stage_role",
                title="世界观设计",
                content="你是一名世界观架构师。你只负责当前世界观设计。",
                workflow_id="workflow.writing.node.world_design",
                node_id="world_design",
                stage_id="world_design",
                applies_to_task_goal_types=("task_graph_node_execution",),
                applies_to_modes=("professional_mode",),
                priority=100,
            ),
        )
    ).select(context)

    stage_items = [item for item in plan.selected if item.resource_type == "stage_role"]

    assert [item.resource_id for item in stage_items] == ["prompt.world_design.stage_role"]
    assert stage_items[0].selection_reason.startswith("workflow_id_exact")
    assert plan.diagnostics["workflow_id"] == "workflow.writing.node.world_design"
    assert plan.diagnostics["current_step_id"] == "world_design"
    assert plan.diagnostics["workflow_step_count"] == 1


def test_prompt_selector_omits_role_prompt_outside_role_mode() -> None:
    context = PromptSelectionContext(
        task_id="runtime-task",
        interaction_mode="professional_mode",
        task_goal_type="code_change",
        task_domain="development",
    )
    plan = PromptSelector(
        (
            PromptResource(
                resource_id="prompt.soul.role",
                resource_type="role_prompt",
                title="角色提示词",
                content="你以某个角色口吻陪伴用户。",
                applies_to_modes=("role_mode", "professional_mode"),
            ),
        )
    ).select(context)

    assert not [item for item in plan.selected if item.resource_type == "role_prompt"]
    omitted = [item for item in plan.omitted if item.resource_id == "prompt.soul.role"]
    assert omitted
    assert omitted[0].omitted_reason == "role_prompt_only_allowed_in_role_mode"


def test_prompt_selector_uses_current_step_kind_when_no_node_resource_exists() -> None:
    context = PromptSelectionContext(
        task_id="runtime-task",
        interaction_mode="professional_mode",
        task_goal_type="frontend_app_delivery",
        task_domain="development",
        current_step_id="verify_result",
        current_step_kind="verify",
        current_step_title="验证结果",
        recipe_steps=(
            {"step_id": "write_artifact", "title": "写入产物", "step_kind": "write"},
            {"step_id": "verify_result", "title": "验证结果", "step_kind": "verify"},
        ),
        step_sequence=("write_artifact", "verify_result"),
    )
    plan = PromptSelector(
        (
            PromptResource(
                resource_id="prompt.stage.verify",
                resource_type="stage_role",
                title="验证阶段",
                content="你是一名交付验证员。你只负责验证产物是否真实可用。",
                step_kind="verify",
                applies_to_modes=("professional_mode",),
                applies_to_domains=("development",),
            ),
        )
    ).select(context)

    stage_items = [item for item in plan.selected if item.resource_type == "stage_role"]

    assert [item.resource_id for item in stage_items] == ["prompt.stage.verify"]
    assert "step_kind_exact" in stage_items[0].selection_reason
    assert plan.diagnostics["step_sequence"] == ["write_artifact", "verify_result"]


def test_prompt_selector_uses_work_mode_and_action_intent_for_verification_and_execution() -> None:
    verification_context = PromptSelectionContext(
        task_id="runtime-task",
        interaction_mode="professional_mode",
        work_mode="verification",
        action_intent="run_command",
        task_goal_type="frontend_app_delivery",
        task_domain="development",
    )
    execution_context = PromptSelectionContext(
        task_id="runtime-task",
        interaction_mode="professional_mode",
        work_mode="implementation",
        action_intent="edit_workspace",
        task_goal_type="frontend_app_delivery",
        task_domain="development",
    )

    resources = (
        PromptResource(
            resource_id="prompt.verify",
            resource_type="verification",
            title="验证规则",
            content="你是一名交付验证员。",
            applies_to_modes=("professional_mode",),
        ),
        PromptResource(
            resource_id="prompt.execute",
            resource_type="stage_role",
            title="执行职责",
            content="你是一名前端实现负责人。",
            applies_to_modes=("professional_mode",),
            applies_to_domains=("development", "implementation", "edit_workspace"),
        ),
    )

    verification_plan = PromptSelector(resources).select(verification_context)
    execution_plan = PromptSelector(resources).select(execution_context)

    assert any(item.resource_id == "prompt.verify" for item in verification_plan.selected)
    execution_stage = next(item for item in execution_plan.selected if item.resource_id == "prompt.execute")
    assert "execution_stage_context" in execution_stage.selection_reason
    assert execution_plan.diagnostics["work_mode"] == "implementation"
    assert verification_plan.diagnostics["action_intent"] == "run_command"


def test_prompt_selector_matches_new_high_value_stage_roles() -> None:
    resources = (
        PromptResource(
            resource_id="prompt.stage.contract_compilation",
            resource_type="stage_role",
            title="任务合同编译员",
            content="你是一名任务合同编译员。",
            step_kind="contract_compilation",
            applies_to_modes=("professional_mode",),
        ),
        PromptResource(
            resource_id="prompt.stage.plan_coverage_review",
            resource_type="stage_role",
            title="计划覆盖审查员",
            content="你是一名计划覆盖审查员。",
            step_kind="plan_coverage_review",
            applies_to_modes=("professional_mode",),
        ),
        PromptResource(
            resource_id="prompt.stage.step_execution",
            resource_type="stage_role",
            title="任务执行员",
            content="你是一名任务执行员。",
            step_kind="step_execution",
            applies_to_modes=("professional_mode",),
        ),
    )

    contract_plan = PromptSelector(resources).select(
        PromptSelectionContext(
            task_id="runtime-task",
            interaction_mode="professional_mode",
            current_step_id="contract_compilation",
            current_step_kind="contract_compilation",
        )
    )
    plan_review_plan = PromptSelector(resources).select(
        PromptSelectionContext(
            task_id="runtime-task",
            interaction_mode="professional_mode",
            current_step_id="plan_coverage_review",
            current_step_kind="plan_coverage_review",
            work_mode="planning",
        )
    )
    execution_plan = PromptSelector(resources).select(
        PromptSelectionContext(
            task_id="runtime-task",
            interaction_mode="professional_mode",
            current_step_id="step_execution.implement_core_gameplay",
            current_step_kind="step_execution",
            work_mode="implementation",
            action_intent="edit_workspace",
        )
    )

    assert any(item.resource_id == "prompt.stage.contract_compilation" for item in contract_plan.selected)
    assert any(item.resource_id == "prompt.stage.plan_coverage_review" for item in plan_review_plan.selected)
    execution_stage = next(item for item in execution_plan.selected if item.resource_id == "prompt.stage.step_execution")
    assert "step_kind_exact" in execution_stage.selection_reason


def test_build_prompt_selection_context_preserves_task_flow_from_runtime_payload() -> None:
    context = build_prompt_selection_context(
        task_id="runtime-task",
        user_goal="继续执行世界观设计",
        task_contract={
            "task_requirement_contract": {
                "task_goal_type": "task_graph_node_execution",
                "domain": "writing",
            },
            "mode_policy": {"interaction_mode": "professional_mode", "runtime_lane": "coordination_task"},
        },
        task_execution_assembly={
            "task_family": "writing",
            "task_mode": "coordination_task",
            "graph_ref": "graph.writing",
            "metadata": {"registered_task_id": "task.writing.node.world_design"},
        },
        selected_recipe={
            "recipe_id": "runtime.recipe.task_graph_node",
            "task_family": "writing",
            "task_mode": "coordination_task",
            "step_blueprints": [{"step_id": "execute_node", "title": "执行节点", "step_kind": "execute"}],
        },
        task_workflow={
            "workflow_id": "workflow.writing.node.world_design",
            "title": "世界观设计",
            "steps": [{"step_id": "world_design", "title": "世界观设计", "step_kind": "task_graph_node"}],
            "metadata": {
                "node_id": "world_design",
                "graph_id": "graph.writing",
                "task_family": "writing",
            },
        },
        registered_task={
            "task_id": "task.writing.node.world_design",
            "metadata": {"node_id": "world_design", "task_graph_node_runtime": True},
            "task_policy": {"task_structure": {"execution_chain_type": "coordination_node"}},
        },
        skill_runtime_views=[],
        active_skill={},
        agent_id="agent:writer",
        current_turn_context={"task_graph_node_runtime": True, "current_step_id": "world_design"},
    )

    assert context.workflow_id == "workflow.writing.node.world_design"
    assert context.graph_id == "graph.writing"
    assert context.node_id == "world_design"
    assert context.stage_id == "world_design"
    assert context.current_step_id == "world_design"
    assert context.task_graph_node_runtime is True
    assert context.workflow_steps[0]["step_id"] == "world_design"
    assert context.step_sequence == ("world_design",)


def test_prompt_selection_context_exposes_goal_and_plan_contracts() -> None:
    context = build_prompt_selection_context(
        task_id="runtime-task",
        user_goal="开发浏览器肉鸽游戏",
        task_contract={
            "task_requirement_contract": {
                "contract_id": "semantic-task:test:runtime-task",
                "task_goal_type": "game_vertical_slice_delivery",
                "domain": "development",
                "diagnostics": {
                    "task_goal_spec": {
                        "task_goal_type": "game_vertical_slice_delivery",
                        "unacceptable_outcomes": ["final_report_only"],
                    },
                    "goal_hypothesis_set": {
                        "hypothesis_set_id": "goalhyp:test",
                        "chosen": {"task_goal_type": "game_vertical_slice_delivery"},
                    },
                },
            },
            "mode_policy": {"interaction_mode": "professional_mode"},
        },
        task_execution_assembly={"task_family": "runtime", "task_mode": "professional_mode", "metadata": {}},
        selected_recipe={
            "recipe_id": "runtime.recipe.professional_task",
            "metadata": {
                "agent_plan_draft": {
                    "plan_id": "agent-plan:runtime-task",
                    "task_goal_type": "game_vertical_slice_delivery",
                    "steps": [{"step_id": "integrate_visual_asset"}],
                },
                "plan_coverage_review": {
                    "review_id": "plan-coverage:runtime-task",
                    "passed": True,
                    "covered_actions": ["integrate_asset"],
                },
            },
        },
        task_workflow={},
        registered_task={},
        skill_runtime_views=[],
        active_skill={},
        agent_id="agent:0",
        current_turn_context={},
    )

    assert context.goal_hypothesis_set["hypothesis_set_id"] == "goalhyp:test"
    assert context.task_goal_spec["unacceptable_outcomes"] == ["final_report_only"]
    assert context.agent_plan_draft["plan_id"] == "agent-plan:runtime-task"
    assert context.plan_coverage_review["passed"] is True
    assert context.metadata["agent_plan_ref"] == "agent-plan:runtime-task"


def test_prompt_selection_context_exposes_model_owned_understanding_inputs() -> None:
    context = build_prompt_selection_context(
        task_id="runtime-task",
        user_goal="重构任务系统并验证",
        task_contract={
            "task_requirement_contract": {
                "contract_id": "semantic-task:test:runtime-task",
                "task_goal_type": "implementation",
                "domain": "development",
            },
            "mode_policy": {"interaction_mode": "professional_mode", "runtime_lane": "professional_task"},
            "bindings": {
                "model_turn_decision": {"decision_id": "decision:test"},
                "action_permit": {"permit_id": "permit:test"},
                "boundary_policy": {"policy_id": "boundary:test"},
                "request_facts": {"explicit_paths": ["frontend/src/app/page.tsx"]},
            },
        },
        task_execution_assembly={"task_family": "runtime", "task_mode": "professional_mode", "metadata": {}},
        selected_recipe={},
        task_workflow={},
        registered_task={},
        skill_runtime_views=[],
        active_skill={},
        agent_id="agent:0",
        current_turn_context={
            "model_turn_decision": {
                "decision_id": "decision:current",
                "interaction_intent": "modify",
                "action_intent": "edit_workspace",
                "work_mode": "implementation",
                "planning_required": True,
                "context_binding_decision": {"kind": "workspace_context"},
            },
            "action_permit": {"permit_id": "permit:current"},
            "boundary_policy": {"policy_id": "boundary:current"},
            "request_facts": {"explicit_paths": ["backend/prompt_library/selector.py"]},
        },
    )

    assert context.work_mode == "implementation"
    assert context.interaction_intent == "modify"
    assert context.action_intent == "edit_workspace"
    assert context.model_turn_decision["decision_id"] == "decision:current"
    assert context.action_permit["permit_id"] == "permit:current"
    assert context.boundary_policy["policy_id"] == "boundary:current"
    assert context.request_facts["explicit_paths"] == ["backend/prompt_library/selector.py"]
    assert context.context_binding["kind"] == "workspace_context"
    assert context.task_requirement_contract["contract_id"] == "semantic-task:test:runtime-task"
