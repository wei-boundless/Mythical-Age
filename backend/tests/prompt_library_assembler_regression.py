from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prompt_library.assembler import assemble_runtime_prompt_contract


def test_assembler_only_emits_goal_understanding_section_for_understanding_step() -> None:
    contract = assemble_runtime_prompt_contract(
        base_dir=Path("backend"),
        task_id="task-runtime",
        user_goal="分析并修改任务系统",
        task_contract={
            "user_goal": "分析并修改任务系统",
            "mode_policy": {"interaction_mode": "professional_mode"},
            "task_requirement_contract": {
                "contract_id": "semantic-task:test:task-runtime",
                "task_goal_type": "implementation",
                "domain": "development",
                "diagnostics": {
                    "task_goal_spec": {
                        "task_goal_type": "implementation",
                        "unacceptable_outcomes": ["surface_only_summary"]}
                }}},
        task_execution_assembly={"task_mode": "professional_mode", "requested_outputs": []},
        task_spec={},
        selected_recipe={"metadata": {}},
        task_workflow={},
        binding={},
        registered_task={},
        skill_runtime_views=[],
        operation_requirement={},
        agent_id="agent:0",
        current_turn_context={
            "current_step_kind": "step_execution",
            "model_turn_decision": {
                "work_mode": "implementation",
                "action_intent": "edit_workspace"},
            "task_goal_spec": {
                "task_goal_type": "implementation",
                "unacceptable_outcomes": ["surface_only_summary"]}},
    )

    assert contract["goal_understanding_section"] == ""


def test_assembler_renders_skill_catalog_without_activation_detail() -> None:
    contract = assemble_runtime_prompt_contract(
        base_dir=Path("backend"),
        task_id="task-runtime",
        user_goal="为角色生成立绘",
        task_contract={
            "user_goal": "为角色生成立绘",
            "mode_policy": {"interaction_mode": "professional_mode"},
            "task_requirement_contract": {
                "contract_id": "semantic-task:test:task-runtime",
                "task_goal_type": "artifact_delivery",
                "domain": "visual_design",
            },
        },
        task_execution_assembly={"task_mode": "professional_mode", "requested_outputs": []},
        task_spec={},
        selected_recipe={"metadata": {}},
        task_workflow={},
        binding={},
        registered_task={},
        skill_runtime_views=[
            {
                "skill_id": "skill.image-prompt-design",
                "title": "生图提示词设计",
                "task_reason": "Candidate capability available under current task binding.",
                "method_summary": "用于角色立绘、场景图、封面图和视觉参考图生成。",
                "required_operations": ["op.image_generate"],
                "canonical_path": "capability_system/units/skills/image-prompt-design/SKILL.md",
            }
        ],
        operation_requirement={},
        agent_id="agent:0",
        current_turn_context={
            "model_turn_decision": {
                "work_mode": "implementation",
                "action_intent": "edit_workspace",
                "selected_skill_ids": [],
            }
        },
    )

    assert "候选 Skills（第一阶段）" in contract["skill_catalog_section"]
    assert "skill.image-prompt-design" in contract["skill_catalog_section"]
    assert contract["skill_detail_section"] == ""
    assert contract["metadata"]["activated_skill_ids"] == []


def test_assembler_expands_selected_skill_body_from_canonical_path() -> None:
    contract = assemble_runtime_prompt_contract(
        base_dir=Path("backend"),
        task_id="task-runtime",
        user_goal="为角色生成立绘",
        task_contract={
            "user_goal": "为角色生成立绘",
            "mode_policy": {"interaction_mode": "professional_mode"},
            "task_requirement_contract": {
                "contract_id": "semantic-task:test:task-runtime",
                "task_goal_type": "artifact_delivery",
                "domain": "visual_design",
            },
        },
        task_execution_assembly={"task_mode": "professional_mode", "requested_outputs": []},
        task_spec={},
        selected_recipe={"metadata": {}},
        task_workflow={},
        binding={},
        registered_task={},
        skill_runtime_views=[
            {
                "skill_id": "skill.image-prompt-design",
                "title": "生图提示词设计",
                "task_reason": "Candidate capability available under current task binding.",
                "method_summary": "用于角色立绘、场景图、封面图和视觉参考图生成。",
                "required_operations": ["op.image_generate"],
                "canonical_path": "capability_system/units/skills/image-prompt-design/SKILL.md",
            }
        ],
        operation_requirement={},
        agent_id="agent:0",
        current_turn_context={
            "model_turn_decision": {
                "work_mode": "implementation",
                "action_intent": "edit_workspace",
                "selected_skill_ids": ["skill.image-prompt-design"],
            }
        },
    )

    assert "已激活 Skills（第二阶段）" in contract["skill_detail_section"]
    assert "skill.image-prompt-design" in contract["skill_detail_section"]
    assert "角色立绘" in contract["skill_detail_section"]
    assert contract["metadata"]["activated_skill_ids"] == ["skill.image-prompt-design"]


