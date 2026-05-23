from __future__ import annotations

from pathlib import Path

from prompt_library import PromptLibraryRegistry
from task_system import TaskWorkflowRegistry


def test_prompt_library_syncs_workflow_prompt_as_stage_role_without_projection_binding(tmp_path: Path) -> None:
    TaskWorkflowRegistry(tmp_path).upsert_workflow(
        workflow_id="workflow.test.node.world_review",
        title="世界观审核",
        compatible_projection_ids=(),
        steps=({"step_id": "review", "title": "审核世界观"},),
        prompt="你是一名世界观审核员。你只负责评审当前世界观设定是否完整、一致、可支撑后续写作。",
        enabled=True,
        metadata={
            "task_id": "task.test.node.world_review",
            "node_id": "world_review",
            "domain_id": "domain.test",
            "task_family": "test_writing",
        },
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
    assert resource.legacy_projection_ids == ()
    assert resource.source_ref == "storage/tasks/task_workflows.json#workflow.test.node.world_review.prompt"
    assert "你是一名世界观审核员" in resource.content

