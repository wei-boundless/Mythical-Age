from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prompt_library import PromptResource, PromptSelector, PromptSelectionContext
from prompt_library.selector import build_prompt_selection_context


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


def test_build_prompt_selection_context_preserves_task_flow_from_runtime_payload() -> None:
    context = build_prompt_selection_context(
        task_id="runtime-task",
        user_goal="继续执行世界观设计",
        task_contract={
            "semantic_task_contract": {
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
            "semantic_task_contract": {
                "contract_id": "semantic-task:test:runtime-task",
                "task_goal_type": "game_vertical_slice_delivery",
                "domain": "development",
                "diagnostics": {
                    "task_goal_frame": {
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
    assert context.task_goal_frame["unacceptable_outcomes"] == ["final_report_only"]
    assert context.agent_plan_draft["plan_id"] == "agent-plan:runtime-task"
    assert context.plan_coverage_review["passed"] is True
    assert context.metadata["agent_plan_ref"] == "agent-plan:runtime-task"
