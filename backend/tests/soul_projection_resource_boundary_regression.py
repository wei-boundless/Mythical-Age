from __future__ import annotations

from operations import build_default_operation_registry, build_operation_requirement, build_resource_policy_preview, build_resource_runtime_views
from soul.projection import build_soul_runtime_preview, soul_tool_view_from_resource_runtime_view
from tasks.runtime_contracts import ProjectionRequirement, TaskPromptContract


def test_resource_runtime_view_maps_to_soul_tool_view_without_execution_authority() -> None:
    registry = build_default_operation_registry()
    requirement = build_operation_requirement(
        task_id="soul-task-1",
        source="task_binding_preview",
        operation_scope=("op.read_file", "op.edit_file"),
    )
    policy = build_resource_policy_preview(requirement, registry)
    views = {view.resource_id: view for view in build_resource_runtime_views(policy, registry)}

    read_tool = soul_tool_view_from_resource_runtime_view(views["op.read_file"])
    edit_tool = soul_tool_view_from_resource_runtime_view(views["op.edit_file"])

    assert read_tool.authorization_owner == "ResourcePolicy"
    assert read_tool.preview_available is True
    assert read_tool.runtime_executable is False
    assert edit_tool.requires_approval is True
    assert edit_tool.preview_available is False
    assert edit_tool.runtime_executable is False


def test_soul_runtime_preview_manifest_marks_resource_section_as_dynamic_policy_owned() -> None:
    registry = build_default_operation_registry()
    requirement = build_operation_requirement(
        task_id="soul-task-2",
        source="task_binding_preview",
        operation_scope=("op.read_file", "op.edit_file"),
    )
    policy = build_resource_policy_preview(requirement, registry)
    resource_views = build_resource_runtime_views(policy, registry)
    task_prompt = TaskPromptContract(
        contract_id="contract-1",
        task_id="soul-task-2",
        definition_id="task.task_execution",
        binding_id="binding-1",
        task_section="Goal: inspect resources",
        method_section="Use bounded methods.",
        resource_section="Available in preview: op.read_file. Requires approval before real execution: op.edit_file.",
        projection_section="Projection role: implementer.",
        output_section="Return preview.",
        guardrail_section="Do not execute.",
        metadata={
            "preview_only": True,
            "resource_policy_ref": policy.policy_id,
            "runtime_directive_enabled": False,
        },
    )

    preview = build_soul_runtime_preview(
        task_prompt_contract=task_prompt,
        projection_requirement=ProjectionRequirement(task_id="soul-task-2", role_type="implementer"),
        skill_views=[],
        resource_views=resource_views,
    )
    manifest_sections = {item["section_id"]: item for item in preview["prompt_manifest"]["sections"]}
    runtime_sections = {item["section_id"]: item for item in preview["runtime_view"]["sections"]}

    assert manifest_sections["resource_section"]["source_type"] == "resource_policy"
    assert manifest_sections["resource_section"]["owner_layer"] == "resource_policy"
    assert manifest_sections["resource_section"]["cache_scope"] == "dynamic"
    assert preview["runtime_view"]["authorization_owner"] == "ResourcePolicy"
    assert "runtime_executable=false" in runtime_sections["resource_section"]["content"]
    assert "Projection must not grant permissions" in runtime_sections["resource_section"]["content"]

