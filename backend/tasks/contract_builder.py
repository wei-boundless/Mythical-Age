from __future__ import annotations

from typing import Any

from orchestration import ControlKernel, ControlKernelPreviewContext
from orchestration.contracts import TaskContract as ControlKernelTaskContract
from operations import (
    RuntimeApprovalContext,
    build_default_operation_registry,
    build_operation_requirement,
    build_resource_policy_preview,
    build_resource_runtime_views,
)
from soul.projection import build_soul_runtime_preview

from .bindings import default_task_binding, merge_task_bindings
from .contracts import build_task_contract
from .definitions import select_task_definitions
from .runtime_contracts import (
    ProjectionRequirement,
    TaskPromptContract,
    skill_runtime_views_for_refs,
)


def build_task_runtime_contract_preview(
    *,
    session_id: str,
    user_goal: str,
    task_id: str = "task-preview",
    source: str = "manual_preview",
    approval_context: RuntimeApprovalContext | None = None,
) -> dict[str, Any]:
    definitions = select_task_definitions(user_goal)
    bindings = [default_task_binding(definition) for definition in definitions]
    merged_binding = merge_task_bindings(bindings)
    task_family = "+".join(_dedupe([definition.task_family for definition in definitions]))
    task_mode = "+".join(definition.task_mode for definition in definitions)
    contract = build_task_contract(
        task_id=task_id,
        session_id=session_id,
        user_goal=user_goal,
        source=source,
        task_family=task_family,
        task_mode=task_mode,
    )
    skill_views = skill_runtime_views_for_refs(merged_binding.skill_scope)
    registry = build_default_operation_registry()
    operation_requirement = build_operation_requirement(
        task_id=contract.task_id,
        source="task_binding_preview",
        operation_scope=merged_binding.operation_scope,
        denied_operations=merged_binding.denied_operations,
        default_operation_requirements=tuple(
            _dedupe([operation for definition in definitions for operation in definition.default_operation_requirements])
        ),
        skill_required_operations=tuple(
            _dedupe([operation for skill in skill_views for operation in skill.required_operations])
        ),
        approval_policy=merged_binding.approval_policy,
        review_policy=merged_binding.review_policy,
        reason="derived from TaskDefinition, TaskBinding, and SkillRuntimeView",
    )
    resource_policy = build_resource_policy_preview(
        operation_requirement,
        registry,
        approval_context=approval_context,
    )
    resource_views = build_resource_runtime_views(resource_policy, registry)
    projection_requirement = ProjectionRequirement(
        task_id=contract.task_id,
        role_type=merged_binding.projection_selector,
        posture_tags=tuple(_projection_tags(task_mode)),
        attention_focus=("resource_boundary", "task_goal", "guardrails"),
        reason="derived from task binding and selected definitions",
    )
    task_prompt_contract = TaskPromptContract(
        contract_id=f"task-prompt:{contract.task_id}:preview",
        task_id=contract.task_id,
        definition_id=merged_binding.definition_id,
        binding_id=merged_binding.binding_id,
        task_section=_task_section(contract.user_goal, definitions),
        method_section=_method_section(skill_views),
        resource_section=_resource_section(resource_views),
        projection_section=_projection_section(projection_requirement),
        output_section=_output_section(definitions),
        guardrail_section=_guardrail_section(merged_binding.review_policy),
        metadata={
            "preview_only": True,
            "resource_policy_ref": resource_policy.policy_id,
            "resource_policy_adopted": False,
            "runtime_directive_enabled": False,
            "runtime_executable": False,
            "section_sources": {
                "task_section": "TaskContract/TaskDefinition",
                "method_section": "SkillRuntimeView",
                "resource_section": "ResourceRuntimeView",
                "projection_section": "ProjectionRequirement",
                "output_section": "TaskDefinition.output_contract",
                "guardrail_section": "TaskBinding.review_policy",
            },
        },
    )
    soul_preview = build_soul_runtime_preview(
        task_prompt_contract=task_prompt_contract,
        projection_requirement=projection_requirement,
        skill_views=skill_views,
        resource_views=resource_views,
    )
    control_kernel_result = _build_control_kernel_preview(
        contract=contract,
        operation_requirement=operation_requirement,
        resource_policy=resource_policy,
        task_prompt_contract=task_prompt_contract,
        prompt_manifest=soul_preview["prompt_manifest"],
    )
    return {
        "task_contract": contract.to_dict(),
        "definitions": [definition.to_dict() for definition in definitions],
        "binding": merged_binding.to_dict(),
        "skill_runtime_views": [view.to_dict() for view in skill_views],
        "operation_requirement": operation_requirement.to_dict(),
        "resource_policy": resource_policy.to_dict(),
        "resource_runtime_views": [view.to_dict() for view in resource_views],
        "projection_requirement": projection_requirement.to_dict(),
        "task_prompt_contract": task_prompt_contract.to_dict(),
        "soul_runtime_view": soul_preview["runtime_view"],
        "soul_projection_request": soul_preview["projection_request"],
        "prompt_manifest_preview": soul_preview["prompt_manifest"],
        "control_kernel_diagnostics": control_kernel_result.diagnostics,
        "control_kernel_result": control_kernel_result.to_dict(),
        "status": "preview_only",
    }


def _task_section(user_goal: str, definitions: list[Any]) -> str:
    definition_ids = ", ".join(definition.definition_id for definition in definitions)
    criteria = "; ".join(
        criterion for definition in definitions for criterion in definition.completion_criteria
    )
    return f"Goal: {user_goal}\nTask definitions: {definition_ids}\nCompletion criteria: {criteria}"


def _method_section(skill_views: list[Any]) -> str:
    if not skill_views:
        return "No method skill is exposed for this preview."
    return "\n".join(f"- {view.title}: {view.method_summary}" for view in skill_views)


def _resource_section(resource_views: list[Any]) -> str:
    available = [view.resource_id for view in resource_views if view.preview_available and not view.requires_approval]
    requires = [view.resource_id for view in resource_views if view.requires_approval]
    denied = [view.resource_id for view in resource_views if view.denied_reason and not view.requires_approval]
    return "\n".join(
        [
            f"Available in preview: {', '.join(available) or 'none'}.",
            f"Requires approval before real execution: {', '.join(requires) or 'none'}.",
            f"Denied: {', '.join(denied) or 'none'}.",
            "This preview does not grant runtime execution permission.",
        ]
    )


def _projection_section(requirement: ProjectionRequirement) -> str:
    return (
        f"Projection role: {requirement.role_type}. "
        f"Posture tags: {', '.join(requirement.posture_tags) or 'none'}."
    )


def _output_section(definitions: list[Any]) -> str:
    modes = ", ".join(definition.task_mode for definition in definitions)
    return f"Output should satisfy task modes: {modes}. Return a concise preview-ready response."


def _guardrail_section(review_policy: str) -> str:
    return "\n".join(
        [
            "Do not execute tools, workers, file writes, shell commands, or memory writes in preview.",
            "Do not treat ResourceRuntimeView.authorized as runtime_executable.",
            f"Review policy: {review_policy}.",
        ]
    )


def _build_control_kernel_preview(
    *,
    contract: Any,
    operation_requirement: Any,
    resource_policy: Any,
    task_prompt_contract: TaskPromptContract,
    prompt_manifest: dict[str, Any],
) -> Any:
    prompt_manifest_ref = str(prompt_manifest.get("manifest_id", ""))
    kernel_task = ControlKernelTaskContract(
        task_id=contract.task_id,
        user_goal=contract.user_goal,
        session_id=contract.session_id,
        task_kind=contract.task_family,
        modality=contract.task_mode,
        source=contract.source,
        constraints=dict(contract.constraints),
        refs={
            **dict(contract.refs),
            "task_contract_authority": contract.authority,
            "task_prompt_contract_ref": task_prompt_contract.contract_id,
        },
    )
    preview_context = ControlKernelPreviewContext(
        task_prompt_contract_ref=task_prompt_contract.contract_id,
        resource_policy_ref=resource_policy.policy_id,
        prompt_manifest_ref=prompt_manifest_ref,
        operation_requirement_ref=operation_requirement.requirement_id,
        denied_operations=tuple(resource_policy.denied_operations),
        requires_approval_operations=tuple(resource_policy.requires_approval_operations),
        diagnostics={
            **dict(resource_policy.diagnostics),
            "task_id": contract.task_id,
            "resource_policy_authority": resource_policy.authority,
            "resource_policy_preview_only": resource_policy.preview_only,
            "resource_policy_runtime_executable": resource_policy.runtime_executable,
        },
    )
    return ControlKernel().collect(task=kernel_task, preview_context=preview_context)


def _projection_tags(task_mode: str) -> list[str]:
    if "information_search" in task_mode:
        return ["evidence-first", "traceability"]
    if "inspection_and_correction" in task_mode:
        return ["risk-review", "consistency"]
    if "local_material_read" in task_mode:
        return ["structure-first", "precise"]
    return ["concise"]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
