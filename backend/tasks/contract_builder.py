from __future__ import annotations

from typing import Any

from orchestration import (
    ControlKernel,
    ControlKernelPreviewContext,
    build_blocked_adoption_candidate,
    build_blocked_commit_gate_preview,
    build_directive_only_executor_preview,
    build_execution_graph_preview,
    build_operation_gate_preflight_preview,
    build_preview_adoption_block,
    build_preview_plan_from_task_operation,
    build_preview_runtime_directive_block,
    build_runtime_directive_candidates,
    build_single_agent_topology_preview,
    collect_task_operation_preview_candidates,
    validate_preview_plan,
)
from orchestration.contracts import TaskContract as ControlKernelTaskContract
from operations import (
    RuntimeApprovalContext,
    build_default_operation_registry,
    build_operation_requirement,
    build_resource_policy_preview,
    build_resource_runtime_views,
)
from soul.projection import build_soul_runtime_preview
from understanding import build_understanding_candidates

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
    memory_runtime_view: dict[str, Any] | None = None,
    context_policy_preview: dict[str, Any] | None = None,
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
            _dedupe(
                [
                    "op.model_response",
                    *[
                        operation
                        for definition in definitions
                        for operation in definition.default_operation_requirements
                    ],
                ]
            )
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
    topology_preview, coordination_policy_preview = build_single_agent_topology_preview(
        task_id=contract.task_id,
        reason="single_agent_main_chain_first",
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
    task_contract_payload = contract.to_dict()
    operation_requirement_payload = operation_requirement.to_dict()
    resource_policy_payload = resource_policy.to_dict()
    task_prompt_contract_payload = task_prompt_contract.to_dict()
    prompt_manifest_payload = soul_preview["prompt_manifest"]
    topology_payload = topology_preview.to_dict()
    understanding_candidates = build_understanding_candidates(
        task_id=contract.task_id,
        message=user_goal,
    )
    candidate_set = collect_task_operation_preview_candidates(
        task_contract=task_contract_payload,
        operation_requirement=operation_requirement_payload,
        resource_policy=resource_policy_payload,
        task_prompt_contract=task_prompt_contract_payload,
        prompt_manifest=prompt_manifest_payload,
        topology_preview=topology_payload,
        understanding_candidates=understanding_candidates,
        memory_runtime_view=memory_runtime_view,
        context_policy_preview=context_policy_preview,
    )
    orchestration_plan_preview = build_preview_plan_from_task_operation(
        task_contract=task_contract_payload,
        operation_requirement=operation_requirement_payload,
        resource_policy=resource_policy_payload,
        task_prompt_contract=task_prompt_contract_payload,
        prompt_manifest=prompt_manifest_payload,
        topology_preview=topology_payload,
        candidates=candidate_set,
    )
    plan_validation = validate_preview_plan(
        orchestration_plan_preview,
        resource_policy_preview_only=resource_policy.preview_only,
        resource_policy_adopted=resource_policy.adopted,
    )
    execution_graph_preview = build_execution_graph_preview(orchestration_plan_preview, plan_validation)
    adoption_candidate = build_blocked_adoption_candidate(orchestration_plan_preview)
    adoption_block = build_preview_adoption_block(orchestration_plan_preview)
    runtime_directive_candidates = build_runtime_directive_candidates(orchestration_plan_preview, plan_validation)
    runtime_directive_block = build_preview_runtime_directive_block(
        plan_ref=orchestration_plan_preview.plan_id,
        stage_ref=orchestration_plan_preview.stages[0].stage_id if orchestration_plan_preview.stages else "",
        reason=plan_validation.reason,
    )
    operation_gate_preflight = build_operation_gate_preflight_preview(
        plan=orchestration_plan_preview,
        directive_candidates=runtime_directive_candidates,
    )
    directive_only_executor_preview = build_directive_only_executor_preview(
        plan=orchestration_plan_preview,
        operation_gate_preflight=operation_gate_preflight,
    )
    commit_gate_preview = build_blocked_commit_gate_preview(
        plan=orchestration_plan_preview,
        graph_preview=execution_graph_preview,
        adoption_candidate=adoption_candidate,
        directive_candidates=runtime_directive_candidates,
    )
    control_kernel_result = _build_control_kernel_preview(
        contract=contract,
        operation_requirement=operation_requirement,
        resource_policy=resource_policy,
        topology_preview=topology_preview,
        coordination_policy_preview=coordination_policy_preview,
        candidate_set=candidate_set,
        orchestration_plan_preview=orchestration_plan_preview,
        plan_validation=plan_validation,
        execution_graph_preview=execution_graph_preview,
        adoption_candidate=adoption_candidate,
        adoption_block=adoption_block,
        runtime_directive_candidates=runtime_directive_candidates,
        runtime_directive_block=runtime_directive_block,
        operation_gate_preflight=operation_gate_preflight,
        directive_only_executor_preview=directive_only_executor_preview,
        commit_gate_preview=commit_gate_preview,
        task_prompt_contract=task_prompt_contract,
        prompt_manifest=soul_preview["prompt_manifest"],
    )
    return {
        "task_contract": task_contract_payload,
        "definitions": [definition.to_dict() for definition in definitions],
        "binding": merged_binding.to_dict(),
        "skill_runtime_views": [view.to_dict() for view in skill_views],
        "operation_requirement": operation_requirement_payload,
        "resource_policy": resource_policy_payload,
        "execution_topology_preview": topology_payload,
        "coordination_policy_preview": coordination_policy_preview.to_dict(),
        "agent_seat_plan_previews": [],
        "agent_assignment_candidates": [],
        "resource_runtime_views": [view.to_dict() for view in resource_views],
        "projection_requirement": projection_requirement.to_dict(),
        "task_prompt_contract": task_prompt_contract_payload,
        "soul_runtime_view": soul_preview["runtime_view"],
        "soul_projection_request": soul_preview["projection_request"],
        "prompt_manifest_preview": prompt_manifest_payload,
        "memory_runtime_view": dict(memory_runtime_view or {}),
        "context_policy_preview": dict(context_policy_preview or {}),
        "understanding_candidate_preview": [candidate.to_dict() for candidate in understanding_candidates],
        "candidate_set_preview": candidate_set.to_list(),
        "orchestration_plan_preview": orchestration_plan_preview.to_dict(),
        "plan_validation": plan_validation.to_dict(),
        "execution_graph_preview": execution_graph_preview.to_dict(),
        "adoption_candidate_preview": adoption_candidate.to_dict(),
        "adoption_block": adoption_block.to_dict(),
        "runtime_directive_candidates": [candidate.to_dict() for candidate in runtime_directive_candidates],
        "runtime_directive_block": runtime_directive_block.to_dict(),
        "operation_gate_preflight": operation_gate_preflight.to_dict(),
        "directive_only_executor_preview": directive_only_executor_preview.to_dict(),
        "commit_gate_preview": commit_gate_preview.to_dict(),
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
    topology_preview: Any,
    coordination_policy_preview: Any,
    candidate_set: Any,
    orchestration_plan_preview: Any,
    plan_validation: Any,
    execution_graph_preview: Any,
    adoption_candidate: Any,
    adoption_block: Any,
    runtime_directive_candidates: Any,
    runtime_directive_block: Any,
    operation_gate_preflight: Any,
    directive_only_executor_preview: Any,
    commit_gate_preview: Any,
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
            "execution_topology_ref": topology_preview.topology_id,
            "execution_topology_mode": topology_preview.mode,
            "coordination_policy_ref": coordination_policy_preview.policy_id,
            "orchestration_plan_ref": orchestration_plan_preview.plan_id,
            "plan_validation_ref": plan_validation.validation_id,
            "execution_graph_preview_ref": execution_graph_preview.graph_preview_id,
            "adoption_candidate_ref": adoption_candidate.candidate_id,
            "adoption_block_ref": adoption_block.block_id,
            "runtime_directive_candidate_count": len(runtime_directive_candidates),
            "runtime_directive_block_ref": runtime_directive_block.block_id,
            "operation_gate_preflight_ref": operation_gate_preflight.preflight_id,
            "operation_gate_passed": operation_gate_preflight.operation_gate_passed,
            "directive_only_executor_ref": directive_only_executor_preview.preview_id,
            "executor_dispatch_enabled": directive_only_executor_preview.will_dispatch,
            "commit_gate_ref": commit_gate_preview.gate_id,
            "commit_gate_status": commit_gate_preview.status,
            "commit_allowed": commit_gate_preview.commit_allowed,
            "commit_candidate_count": len(commit_gate_preview.commit_candidates),
        },
    )
    preview_context = ControlKernelPreviewContext(
        task_prompt_contract_ref=task_prompt_contract.contract_id,
        resource_policy_ref=resource_policy.policy_id,
        prompt_manifest_ref=prompt_manifest_ref,
        operation_requirement_ref=operation_requirement.requirement_id,
        denied_operations=tuple(resource_policy.denied_operations),
        requires_approval_operations=tuple(resource_policy.requires_approval_operations),
        refs={
            "execution_topology_ref": topology_preview.topology_id,
            "execution_topology_mode": topology_preview.mode,
            "coordination_policy_ref": coordination_policy_preview.policy_id,
            "multi_agent_enabled": False,
            "agent_seat_count": 0,
            "agent_assignment_count": 0,
            "agent_architecture_prepared": True,
            "orchestration_plan_ref": orchestration_plan_preview.plan_id,
            "plan_validation_ref": plan_validation.validation_id,
            "execution_graph_preview_ref": execution_graph_preview.graph_preview_id,
            "execution_graph_preview_node_count": len(execution_graph_preview.node_previews),
            "adoption_candidate_ref": adoption_candidate.candidate_id,
            "adoption_candidate_status": adoption_candidate.status,
            "adoption_block_ref": adoption_block.block_id,
            "adopted_resource_policy_available": False,
            "runtime_directive_candidate_count": len(runtime_directive_candidates),
            "runtime_directive_block_ref": runtime_directive_block.block_id,
            "runtime_directive_available": False,
            "operation_gate_preflight_ref": operation_gate_preflight.preflight_id,
            "operation_gate_passed": operation_gate_preflight.operation_gate_passed,
            "operation_gate_check_count": len(operation_gate_preflight.checks),
            "directive_only_executor_ref": directive_only_executor_preview.preview_id,
            "executor_dispatch_enabled": directive_only_executor_preview.will_dispatch,
            "executor_accepts_only": directive_only_executor_preview.accepted_input_type,
            "commit_gate_ref": commit_gate_preview.gate_id,
            "commit_gate_status": commit_gate_preview.status,
            "commit_allowed": commit_gate_preview.commit_allowed,
            "commit_candidate_count": len(commit_gate_preview.commit_candidates),
        },
        diagnostics={
            **dict(resource_policy.diagnostics),
            "task_id": contract.task_id,
            "resource_policy_authority": resource_policy.authority,
            "resource_policy_preview_only": resource_policy.preview_only,
            "resource_policy_runtime_executable": resource_policy.runtime_executable,
            "execution_topology_ref": topology_preview.topology_id,
            "execution_topology_mode": topology_preview.mode,
            "coordination_policy_ref": coordination_policy_preview.policy_id,
            "single_agent_main_chain_first": True,
            "multi_agent_enabled": False,
            "agent_seat_count": 0,
            "agent_assignment_count": 0,
            "agent_architecture_prepared": True,
            "candidate_count": len(candidate_set.candidates),
            "orchestration_plan_ref": orchestration_plan_preview.plan_id,
            "orchestration_plan_preview_only": orchestration_plan_preview.preview_only,
            "plan_validation_ref": plan_validation.validation_id,
            "plan_validation_status": plan_validation.status,
            "plan_validation_reason": plan_validation.reason,
            "execution_graph_preview_ref": execution_graph_preview.graph_preview_id,
            "execution_graph_preview_node_count": len(execution_graph_preview.node_previews),
            "adoption_candidate_ref": adoption_candidate.candidate_id,
            "adoption_candidate_status": adoption_candidate.status,
            "adoption_can_adopt_plan": adoption_candidate.can_adopt_plan,
            "adoption_block_ref": adoption_block.block_id,
            "adopted_resource_policy_available": False,
            "runtime_directive_candidate_count": len(runtime_directive_candidates),
            "runtime_directive_block_ref": runtime_directive_block.block_id,
            "runtime_directive_available": False,
            "operation_gate_preflight_ref": operation_gate_preflight.preflight_id,
            "operation_gate_passed": operation_gate_preflight.operation_gate_passed,
            "operation_gate_check_count": len(operation_gate_preflight.checks),
            "directive_only_executor_ref": directive_only_executor_preview.preview_id,
            "executor_dispatch_enabled": directive_only_executor_preview.will_dispatch,
            "executor_accepts_only": directive_only_executor_preview.accepted_input_type,
            "legacy_query_execution_rejected": True,
            "commit_gate_ref": commit_gate_preview.gate_id,
            "commit_gate_status": commit_gate_preview.status,
            "commit_allowed": commit_gate_preview.commit_allowed,
            "commit_candidate_count": len(commit_gate_preview.commit_candidates),
            "writeback_allowed": False,
            "session_write_allowed": False,
            "memory_write_allowed": False,
            "artifact_write_allowed": False,
            "task_result_write_allowed": False,
        },
    )
    return ControlKernel().collect(task=kernel_task, candidates=candidate_set, preview_context=preview_context)


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
