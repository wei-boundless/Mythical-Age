from __future__ import annotations

from capability_system import build_default_operation_registry, build_operation_requirement, build_resource_policy_candidate, build_resource_runtime_views
from soul.runtime_assembly import build_soul_runtime_view
from soul.view_mapping import soul_tool_view_from_resource_runtime_view
from tasks.runtime_contracts import ProjectionRequirement, TaskPromptContract


def test_resource_runtime_view_maps_to_soul_tool_view_without_execution_authority() -> None:
    registry = build_default_operation_registry()
    requirement = build_operation_requirement(
        task_id="soul-task-1",
        source="task_binding_preview",
        operation_scope=("op.read_file", "op.edit_file"),
    )
    policy = build_resource_policy_candidate(requirement, registry)
    views = {view.resource_id: view for view in build_resource_runtime_views(policy, registry)}

    read_tool = soul_tool_view_from_resource_runtime_view(views["op.read_file"])
    edit_tool = soul_tool_view_from_resource_runtime_view(views["op.edit_file"])

    assert read_tool.authorization_owner == "ResourcePolicy"
    assert read_tool.available_to_model is True
    assert read_tool.runtime_executable is False
    assert edit_tool.requires_approval is True
    assert edit_tool.available_to_model is False
    assert edit_tool.runtime_executable is False


def test_soul_runtime_view_exposes_only_authorized_tool_sections() -> None:
    registry = build_default_operation_registry()
    requirement = build_operation_requirement(
        task_id="soul-task-2",
        source="task_binding_preview",
        operation_scope=("op.read_file", "op.edit_file"),
    )
    policy = build_resource_policy_candidate(requirement, registry)
    resource_views = build_resource_runtime_views(policy, registry)
    task_prompt = TaskPromptContract(
        contract_id="contract-1",
        task_id="soul-task-2",
        definition_id="task.task_execution",
        binding_id="binding-1",
        task_section="Goal: inspect resources",
        workflow_section="Workflow: bounded inspection.",
        resource_section="",
        projection_section="Projection role: implementer.",
        output_section="Return preview.",
        guardrail_section="Review policy: required.",
        metadata={
            "resource_policy_ref": policy.policy_id,
            "runtime_directive_enabled": True,
        },
    )

    runtime = build_soul_runtime_view(
        task_prompt_contract=task_prompt,
        projection_requirement=ProjectionRequirement(task_id="soul-task-2", role_type="implementer"),
        skill_views=[],
        resource_views=resource_views,
    )
    manifest_sections = {item["section_id"]: item for item in runtime["prompt_manifest"]["sections"]}
    runtime_sections = {item["section_id"]: item for item in runtime["runtime_view"]["sections"]}

    assert "resource_section" not in manifest_sections
    assert "guardrail_section" in manifest_sections
    assert runtime["runtime_view"]["authorization_owner"] == "ResourcePolicy"
    assert "resource_section" not in runtime_sections

    bundle = runtime["agent_prompt_bundle"]
    bundle_sections = {item["section_id"]: item for item in bundle["sections"]}
    assert bundle["authority"] == "soul.agent_prompt_bundle"
    assert "runtime_executable" not in bundle
    assert "resource_policy_ref" not in bundle["refs"]
    assert "resource_section" not in bundle_sections
    assert bundle_sections["guardrail_section"]["owner_layer"] == "task"


def test_soul_runtime_view_carries_projection_identity_anchor_separately() -> None:
    task_prompt = TaskPromptContract(
        contract_id="contract-anchor-1",
        task_id="soul-task-anchor",
        definition_id="task.task_execution",
        binding_id="binding-anchor-1",
        task_section="Goal: write chapters",
        workflow_section="Workflow: stable chapter pipeline.",
        resource_section="",
        projection_section="Projection role: chapter_drafting.",
        output_section="Return chapter draft.",
        guardrail_section="Respect task boundary.",
        metadata={"runtime_directive_enabled": True},
    )

    runtime = build_soul_runtime_view(
        task_prompt_contract=task_prompt,
        projection_requirement=ProjectionRequirement(
            task_id="soul-task-anchor",
            role_type="chapter_drafting",
            identity_anchor="你是长篇正文执行投影，不是灵魂本体。",
            projection_title="正文投影",
            projection_prompt="优先完成场景落稿。",
        ),
        skill_views=[],
        resource_views=[],
    )

    runtime_sections = {item["section_id"]: item for item in runtime["runtime_view"]["sections"]}

    assert "projection_section" in runtime_sections
    assert "你是长篇正文执行投影，不是灵魂本体。" in runtime_sections["projection_section"]["content"]
