from __future__ import annotations

import json
from pathlib import Path

from prompt_library import PromptLibraryRegistry, PromptResource, list_default_prompt_resources
from task_system import TaskWorkflowRegistry


def test_prompt_library_lists_default_static_resources_without_storage_file(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)

    resources = registry.list_resources(sync_workflow_prompts=False)
    resource_by_id = {item.resource_id: item for item in resources}

    assert resource_by_id["prompt.default.common_contract.core"].resource_type == "common_contract"
    assert resource_by_id["prompt.default.understanding_policy.goal_first"].resource_type == "understanding_policy"
    assert resource_by_id["prompt.default.flow_matching_policy.goal_profile_binding"].step_kind == "domain_flow_matching"
    assert not [item for item in resources if item.resource_type == "mode_policy"]
    assert resource_by_id["prompt.default.stage_role.task_goal_understanding"].step_kind == "task_goal_understanding"
    assert resource_by_id["prompt.default.stage_role.contract_compilation"].step_kind == "contract_compilation"
    assert resource_by_id["prompt.default.stage_role.plan_coverage_review"].step_kind == "plan_coverage_review"
    assert resource_by_id["prompt.default.stage_role.step_execution"].step_kind == "step_execution"
    assert resource_by_id["prompt.default.task_goal_role.game_vertical_slice_delivery"].resource_type == "task_goal_role"
    assert resource_by_id["prompt.default.task_goal_role.code_fix_execution"].title == "专业代码任务执行员"
    assert "必须先理解真实项目结构" in resource_by_id["prompt.default.task_goal_role.code_fix_execution"].content
    assert resource_by_id["prompt.default.skill_prompt.image_prompt_design"].resource_type == "skill_prompt"
    assert not (tmp_path / "storage" / "prompt_library" / "prompt_resources.json").exists()


def test_prompt_library_upsert_does_not_persist_all_default_resources(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)
    registry.upsert_resource(
        PromptResource(
            resource_id="prompt.user.custom.output",
            resource_type="output_boundary",
            title="用户自定义输出边界",
            content="你需要用用户指定的格式收口。",
            source_ref="test",
        )
    )

    storage_path = tmp_path / "storage" / "prompt_library" / "prompt_resources.json"
    payload = json.loads(storage_path.read_text(encoding="utf-8"))
    stored_ids = {str(item.get("resource_id") or "") for item in list(payload.get("resources") or [])}

    assert "prompt.user.custom.output" in stored_ids
    assert "prompt.default.common_contract.core" not in stored_ids
    assert len(stored_ids) == 1
    assert registry.get_resource("prompt.default.common_contract.core") is not None


def test_prompt_library_stored_resource_overrides_default_resource(tmp_path: Path) -> None:
    default_resource = next(
        item
        for item in list_default_prompt_resources()
        if item.resource_id == "prompt.default.output_boundary.default"
    )
    registry = PromptLibraryRegistry(tmp_path)
    registry.upsert_resource(
        PromptResource(
            resource_id=default_resource.resource_id,
            resource_type=default_resource.resource_type,
            title="覆盖后的默认输出边界",
            content="这是用户覆盖后的输出边界。",
            applies_to_modes=default_resource.applies_to_modes,
            source_ref="test.override",
            priority=1,
        )
    )

    resource = registry.get_resource(default_resource.resource_id)

    assert resource is not None
    assert resource.title == "覆盖后的默认输出边界"
    assert resource.content == "这是用户覆盖后的输出边界。"
    assert resource.source_ref == "test.override"


def test_prompt_library_syncs_workflow_prompt_as_stage_role_without_projection_binding(tmp_path: Path) -> None:
    TaskWorkflowRegistry(tmp_path).upsert_workflow(
        workflow_id="workflow.test.node.world_review",
        title="世界观审核",
        steps=({"step_id": "review", "title": "审核世界观"},),
        prompt="你是一名世界观审核员。你只负责评审当前世界观设定是否完整、一致、可支撑后续写作。",
        enabled=True,
        metadata={
            "task_id": "task.test.node.world_review",
            "node_id": "world_review",
            "domain_id": "domain.test"},
    )

    registry = PromptLibraryRegistry(tmp_path)
    resource = registry.resolve_stage_role(
        workflow_id="workflow.test.node.world_review",
        task_id="task.test.node.world_review",
        node_id="world_review",
    )

    assert resource is not None
    assert resource.resource_type == "stage_role"
    assert resource.workflow_id == "workflow.test.node.world_review"
    assert resource.task_id == "task.test.node.world_review"
    assert resource.node_id == "world_review"
    assert resource.source_ref == "storage/tasks/task_workflows.json#workflow.test.node.world_review.prompt"
    assert "你是一名世界观审核员" in resource.content


