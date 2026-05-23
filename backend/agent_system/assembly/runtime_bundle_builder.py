from __future__ import annotations

from pathlib import Path
from typing import Any

from capability_system import build_default_operation_registry
from prompt_library import assemble_runtime_prompt_contract
from soul import SoulFacade
from soul.projection_store import get_projection_card

from ..registry.agent_registry import AgentRegistry
from ..identity import normalize_agent_id
from ..profiles.runtime_profile_models import AgentRuntimeProfile
from ..profiles.runtime_profile_registry import AgentRuntimeRegistry
from .runtime_spec_models import AgentRuntimeSpec, TaskBodyOrchestration
from ..profiles.body_registry import BodyProfileRegistry
from permissions.resource_policy_builder import build_resource_policy_candidate
from orchestration.resource_runtime_view import build_resource_runtime_views


def build_orchestration_runtime_bundle(
    *,
    base_dir: Path,
    session_id: str,
    task_id: str,
    user_goal: str,
    task_assembly_bundle: dict[str, Any],
    memory_runtime_view: dict[str, Any] | None = None,
    context_policy_result: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
    active_skill: dict[str, Any] | None = None,
    agent_runtime_profile: AgentRuntimeProfile | None = None,
) -> dict[str, Any]:
    base_dir = Path(base_dir)
    task_contract = dict(task_assembly_bundle.get("task_contract") or {})
    task_execution_assembly = dict(task_assembly_bundle.get("task_execution_assembly") or {})
    task_spec = dict(task_assembly_bundle.get("task_spec") or {})
    selected_recipe = dict(task_assembly_bundle.get("selected_recipe") or {})
    projection_selection = dict(task_assembly_bundle.get("projection_selection") or {})
    task_workflow = dict(task_assembly_bundle.get("_task_workflow_obj") or {})
    binding = dict(task_assembly_bundle.get("binding") or {})
    operation_requirement = dict(task_assembly_bundle.get("operation_requirement") or {})
    memory_request_profile = dict(task_assembly_bundle.get("task_memory_request_profile") or {})
    skill_runtime_views = [
        dict(item)
        for item in list(task_assembly_bundle.get("skill_runtime_views") or ())
        if isinstance(item, dict)
    ]
    registered_task = dict(task_assembly_bundle.get("registered_task") or {})
    current_turn_payload = dict(current_turn_context or task_assembly_bundle.get("current_turn_context") or {})
    active_skill_payload = dict(active_skill or task_assembly_bundle.get("active_skill") or {})
    memory_view = dict(memory_runtime_view or {})
    context_policy = dict(context_policy_result or {})

    explicit_context_agent_id = normalize_agent_id(str(current_turn_payload.get("agent_id") or "").strip())
    if explicit_context_agent_id:
        current_turn_payload["agent_id"] = explicit_context_agent_id
    agent_id = normalize_agent_id(str(getattr(agent_runtime_profile, "agent_id", "") or explicit_context_agent_id or "").strip())
    if explicit_context_agent_id and not agent_id:
        raise ValueError(f"TaskGraph node agent has no runtime profile: {explicit_context_agent_id}")
    runtime_profile = agent_runtime_profile or AgentRuntimeRegistry(base_dir).get_profile(agent_id)
    if explicit_context_agent_id:
        if runtime_profile is None:
            raise ValueError(f"TaskGraph node agent has no runtime profile: {explicit_context_agent_id}")
        if normalize_agent_id(str(getattr(runtime_profile, "agent_id", "") or "").strip()) != explicit_context_agent_id:
            raise ValueError(
                "TaskGraph node agent profile mismatch: "
                f"requested {explicit_context_agent_id}, got {getattr(runtime_profile, 'agent_id', '')}"
            )
    agent_id = str(getattr(runtime_profile, "agent_id", "") or agent_id).strip() or "agent:0"
    descriptor = AgentRegistry(base_dir).get_agent(agent_id)
    profile_registry = BodyProfileRegistry(base_dir)

    body_profile = profile_registry.build_agent_body_profile(
        agent_id=agent_id,
        runtime_profile=runtime_profile,
    )
    prompt_profile = profile_registry.build_prompt_structure_profile(
        agent_id=agent_id,
        task_mode=str(task_execution_assembly.get("task_mode") or ""),
        output_contract_id=str(task_execution_assembly.get("output_contract_id") or ""),
    )
    memory_scope_profile = profile_registry.build_memory_scope_profile(
        agent_id=agent_id,
        runtime_profile=runtime_profile,
        memory_request_profile=memory_request_profile,
    )
    requested_runtime_lane = _requested_runtime_lane(
        binding=binding,
        registered_task=registered_task,
        task_execution_assembly=task_execution_assembly,
        current_turn_context=current_turn_payload,
    )
    runtime_lane_profile = profile_registry.build_runtime_lane_profile(
        agent_id=agent_id,
        runtime_profile=runtime_profile,
        task_mode=str(task_execution_assembly.get("task_mode") or ""),
        requested_runtime_lane=requested_runtime_lane,
    )
    output_boundary_profile = profile_registry.build_output_boundary_profile(
        agent_id=agent_id,
        runtime_profile=runtime_profile,
        output_contract_id=str(task_execution_assembly.get("output_contract_id") or ""),
    )

    projection_requirement = _build_projection_requirement(
        base_dir=base_dir,
        task_id=task_id,
        projection_selection=projection_selection,
        agent_descriptor=descriptor,
        task_mode=str(task_execution_assembly.get("task_mode") or ""),
        task_contract=task_contract,
        task_execution_assembly=task_execution_assembly,
        selected_recipe=selected_recipe,
    )
    projection_diagnostics = _projection_resolution_diagnostics(projection_requirement)
    prompt_contract = assemble_runtime_prompt_contract(
        base_dir=base_dir,
        task_id=task_id,
        user_goal=user_goal,
        task_contract=task_contract,
        task_execution_assembly=task_execution_assembly,
        task_spec=task_spec,
        selected_recipe=selected_recipe,
        task_workflow=task_workflow,
        binding=binding,
        registered_task=registered_task,
        skill_runtime_views=skill_runtime_views,
        projection_requirement=projection_requirement,
        operation_requirement=operation_requirement,
        active_skill=active_skill_payload,
        agent_id=agent_id,
        current_turn_context=current_turn_payload,
    )
    prompt_contract_metadata = dict(prompt_contract.get("metadata") or {})
    prompt_selection_context = dict(prompt_contract_metadata.get("prompt_selection_context") or {})
    prompt_assembly_plan = dict(prompt_contract_metadata.get("prompt_assembly_plan") or {})
    prompt_flow_trace = _prompt_flow_trace(
        prompt_selection_context=prompt_selection_context,
        prompt_assembly_plan=prompt_assembly_plan,
    )
    operation_registry = build_default_operation_registry()
    candidate_policy = build_resource_policy_candidate(
        _operation_requirement_from_payload(operation_requirement),
        operation_registry,
    )
    resource_views = [item.to_dict() for item in build_resource_runtime_views(candidate_policy, operation_registry)]
    soul_runtime = SoulFacade(base_dir).build_runtime_view(
        task_prompt_contract=prompt_contract,
        projection_requirement=projection_requirement,
        skill_views=skill_runtime_views,
        resource_views=resource_views,
        soul_id=str(projection_requirement.get("soul_id") or getattr(descriptor, "default_soul_id", "") or "runtime"),
        agent_profile_id=str(getattr(runtime_profile, "agent_profile_id", "") or "runtime_agent"),
        use_shared_contract=bool(getattr(runtime_profile, "use_shared_contract", True)),
    )
    soul_runtime_view = dict(soul_runtime.get("runtime_view") or {})
    prompt_manifest = dict(soul_runtime.get("prompt_manifest") or {})
    projection_ref = str(soul_runtime.get("projection_id") or prompt_manifest.get("projection_id") or "")
    prompt_manifest_ref = str(prompt_manifest.get("manifest_id") or "")

    orchestration = TaskBodyOrchestration(
        orchestration_id=f"orchestration:{task_id}",
        task_id=task_id,
        agent_id=agent_id,
        task_execution_assembly_ref=str(task_execution_assembly.get("assembly_id") or ""),
        body_profile_ref=body_profile.body_profile_id,
        prompt_structure_profile_ref=prompt_profile.profile_id,
        memory_scope_profile_ref=memory_scope_profile.profile_id,
        runtime_lane_profile_ref=runtime_lane_profile.profile_id,
        output_boundary_profile_ref=output_boundary_profile.profile_id,
        stage_plan={
            "stage_owner": "orchestration",
            "section_order": list(prompt_profile.section_order),
            "projection_policy": prompt_profile.stage_projection_policy,
            "current_turn_ref": str(current_turn_payload.get("turn_id") or ""),
            "prompt_flow_trace": prompt_flow_trace,
        },
        resource_binding_plan={
            "operation_requirement_ref": str(operation_requirement.get("requirement_id") or ""),
            "required_operations": list(operation_requirement.get("required_operations") or ()),
            "optional_operations": list(operation_requirement.get("optional_operations") or ()),
            "approval_policy": str(dict(operation_requirement.get("metadata") or {}).get("approval_policy") or "default"),
            "intent_runtime_assembly_hint": dict(current_turn_payload.get("runtime_assembly_hint") or {}),
        },
        verification_gate_plan={
            "task_constraints": dict(task_execution_assembly.get("task_constraints") or {}),
            "safety_envelope": dict(task_execution_assembly.get("safety_envelope") or {}),
        },
        fallback_plan={
            "runtime_executable_default": True,
            "fallback_policy": "fail_closed",
            "on_projection_gap": "continue_with_minimal_projection",
        },
        projection_requirement=projection_requirement,
        soul_runtime_view=soul_runtime_view,
        prompt_manifest=prompt_manifest,
        projection_ref=projection_ref,
        prompt_manifest_ref=prompt_manifest_ref,
        diagnostics={
            "builder": "orchestration.build_orchestration_runtime_bundle",
            "projection_provider": "soul.build_soul_runtime_view",
            "projection_resolution": projection_diagnostics,
            "prompt_selection_context": prompt_selection_context,
            "prompt_assembly_plan": prompt_assembly_plan,
            "prompt_flow_trace": prompt_flow_trace,
            "memory_view_ref": str(memory_view.get("view_id") or ""),
            "context_policy_ref": _context_policy_ref(context_policy),
            "runtime_lane": runtime_lane_profile.lane_id,
            "requested_runtime_lane": requested_runtime_lane,
            "active_skill_name": str(active_skill_payload.get("name") or ""),
            "intent_decision": dict(current_turn_payload.get("intent_decision") or {}),
            "runtime_assembly_hint": dict(current_turn_payload.get("runtime_assembly_hint") or {}),
            "continuation_decision": dict(current_turn_payload.get("continuation_decision") or {}),
        },
    )
    runtime_spec = AgentRuntimeSpec(
        runtime_spec_id=f"rtspec:{task_id}",
        task_id=task_id,
        session_id=session_id,
        agent_id=agent_id,
        task_execution_assembly_ref=str(task_execution_assembly.get("assembly_id") or ""),
        task_body_orchestration_ref=orchestration.orchestration_id,
        context_input_refs=tuple(
            item
            for item in (
                str(memory_view.get("view_id") or ""),
                _context_policy_ref(context_policy),
                str(current_turn_payload.get("turn_id") or ""),
            )
            if item
        ),
        projection_snapshot_ref=f"stageproj:{task_id}",
        resource_policy_candidate_ref=str(operation_requirement.get("requirement_id") or ""),
        input_contract_ref=str(task_execution_assembly.get("input_contract_id") or task_contract.get("input_contract_id") or ""),
        output_contract_ref=str(task_execution_assembly.get("output_contract_id") or task_contract.get("output_contract_id") or ""),
        runtime_lane=runtime_lane_profile.lane_id,
        runtime_executable=True,
        diagnostics={
            "builder": "orchestration.build_orchestration_runtime_bundle",
            "body_profile_ref": body_profile.body_profile_id,
            "prompt_structure_profile_ref": prompt_profile.profile_id,
            "memory_scope_profile_ref": memory_scope_profile.profile_id,
            "runtime_lane_profile_ref": runtime_lane_profile.profile_id,
            "requested_runtime_lane": requested_runtime_lane,
            "output_boundary_profile_ref": output_boundary_profile.profile_id,
            "projection_resolution": projection_diagnostics,
            "intent_decision": dict(current_turn_payload.get("intent_decision") or {}),
            "runtime_assembly_hint": dict(current_turn_payload.get("runtime_assembly_hint") or {}),
            "continuation_decision": dict(current_turn_payload.get("continuation_decision") or {}),
        },
    )
    return {
        "agent_body_profile": body_profile.to_dict(),
        "prompt_structure_profile": prompt_profile.to_dict(),
        "memory_scope_profile": memory_scope_profile.to_dict(),
        "runtime_lane_profile": runtime_lane_profile.to_dict(),
        "output_boundary_profile": output_boundary_profile.to_dict(),
        "task_body_orchestration": orchestration.to_dict(),
        "agent_runtime_spec": runtime_spec.to_dict(),
        "runtime_executable": True,
    }


def _requested_runtime_lane(
    *,
    binding: dict[str, Any],
    registered_task: dict[str, Any],
    task_execution_assembly: dict[str, Any],
    current_turn_context: dict[str, Any] | None = None,
) -> str:
    turn_context = dict(current_turn_context or {})
    explicit_lane = str(turn_context.get("runtime_lane") or "").strip()
    if explicit_lane:
        return explicit_lane
    binding_lane = str(binding.get("runtime_lane") or "").strip()
    if binding_lane:
        return binding_lane
    task_policy = dict(registered_task.get("task_policy") or {})
    task_structure = dict(task_policy.get("task_structure") or {})
    policy_lane = str(task_structure.get("runtime_lane_hint") or "").strip()
    if policy_lane:
        return policy_lane
    metadata = dict(task_execution_assembly.get("metadata") or {})
    metadata_lane = str(metadata.get("runtime_lane_hint") or metadata.get("default_runtime_lane") or "").strip()
    if metadata_lane:
        return metadata_lane
    return str(task_execution_assembly.get("runtime_lane") or "").strip()


def _build_projection_requirement(
    *,
    base_dir: Path,
    task_id: str,
    projection_selection: dict[str, Any],
    agent_descriptor: Any | None,
    task_mode: str,
    task_contract: dict[str, Any] | None = None,
    task_execution_assembly: dict[str, Any] | None = None,
    selected_recipe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = dict(task_contract or {})
    assembly = dict(task_execution_assembly or {})
    recipe = dict(selected_recipe or {})
    metadata = {
        **dict(recipe.get("metadata") or {}),
        **dict(assembly.get("metadata") or {}),
    }
    mode_policy = dict(
        contract.get("mode_policy")
        or metadata.get("mode_policy")
        or {}
    )
    semantic_contract = dict(
        contract.get("semantic_task_contract")
        or metadata.get("semantic_task_contract")
        or {}
    )
    selected_projection_id = str(projection_selection.get("selected_projection_id") or "").strip()
    default_projection_id = str(getattr(agent_descriptor, "default_projection_id", "") or "").strip()
    default_soul_id = str(getattr(agent_descriptor, "default_soul_id", "") or "").strip()
    selection_source = str(projection_selection.get("selection_source") or "task_binding").strip() or "task_binding"
    reason = str(projection_selection.get("selection_reason") or "").strip() or "derived from task-side projection selection"
    resolved_projection_id = selected_projection_id or default_projection_id
    issue = ""
    if selected_projection_id:
        resolution_source = "task_requirement"
        if default_projection_id and default_projection_id != selected_projection_id:
            issue = "task_projection_overrides_agent_default"
    elif default_projection_id:
        resolution_source = "agent_default"
    else:
        resolution_source = "no_projection"
    projection_card = get_projection_card(base_dir, resolved_projection_id) if resolved_projection_id else None
    return {
        "task_id": task_id,
        "role_type": str((projection_card or {}).get("role_type") or projection_selection.get("role_type") or "task_default"),
        "posture_tags": list((projection_card or {}).get("posture_tags") or projection_selection.get("posture_tags") or ("concise",)),
        "expression_density": str((projection_card or {}).get("expression_density") or "normal"),
        "attention_focus": list((projection_card or {}).get("attention_focus") or ["task_goal", "workflow", "output"]),
        "projection_id": resolved_projection_id,
        "selected_projection_id": selected_projection_id,
        "agent_default_projection_id": default_projection_id,
        "resolution_source": resolution_source,
        "issue": issue,
        "projection_optional": True,
        "soul_id": str((projection_card or {}).get("soul_id") or default_soul_id),
        "projection_title": str((projection_card or {}).get("title") or ""),
        "identity_anchor": str((projection_card or {}).get("identity_anchor") or ""),
        "projection_prompt": str((projection_card or {}).get("projection_prompt") or ""),
        "reason": reason,
        "selection_source": selection_source,
        "task_mode": task_mode,
        "interaction_mode": str(mode_policy.get("interaction_mode") or metadata.get("interaction_mode") or ""),
        "projection_strength": str(mode_policy.get("projection_strength") or metadata.get("projection_strength") or ""),
        "runtime_lane": str(mode_policy.get("runtime_lane") or metadata.get("runtime_lane_hint") or ""),
        "professional_profile_id": str(
            semantic_contract.get("professional_profile_id")
            or metadata.get("professional_profile_id")
            or ""
        ),
        "semantic_task_type": str(semantic_contract.get("task_goal_type") or metadata.get("semantic_task_type") or ""),
        "mode_policy_ref": str(mode_policy.get("authority") or ""),
    }


def _projection_resolution_diagnostics(projection_requirement: dict[str, Any]) -> dict[str, Any]:
    issue = str(projection_requirement.get("issue") or "").strip()
    return {
        "authority": "orchestration.projection_resolution",
        "status": "warning" if issue else "ok",
        "projection_optional": True,
        "resolution_source": str(projection_requirement.get("resolution_source") or "no_projection"),
        "selected_projection_id": str(projection_requirement.get("selected_projection_id") or ""),
        "agent_default_projection_id": str(projection_requirement.get("agent_default_projection_id") or ""),
        "resolved_projection_id": str(projection_requirement.get("projection_id") or ""),
        "issue": issue,
    }


def _prompt_flow_trace(
    *,
    prompt_selection_context: dict[str, Any],
    prompt_assembly_plan: dict[str, Any],
) -> dict[str, Any]:
    context = dict(prompt_selection_context or {})
    plan = dict(prompt_assembly_plan or {})
    diagnostics = dict(plan.get("diagnostics") or {})
    selected = [
        dict(item)
        for item in list(plan.get("selected") or [])
        if isinstance(item, dict) and not str(item.get("resource_id") or "").startswith("builtin:")
    ]
    return {
        "authority": "prompt_library.flow_trace",
        "selector": str(diagnostics.get("selector") or ""),
        "workflow_id": str(context.get("workflow_id") or diagnostics.get("workflow_id") or ""),
        "graph_id": str(context.get("graph_id") or diagnostics.get("graph_id") or ""),
        "node_id": str(context.get("node_id") or diagnostics.get("node_id") or ""),
        "stage_id": str(context.get("stage_id") or diagnostics.get("stage_id") or ""),
        "phase_id": str(context.get("phase_id") or diagnostics.get("phase_id") or ""),
        "current_step_id": str(context.get("current_step_id") or diagnostics.get("current_step_id") or ""),
        "current_step_kind": str(context.get("current_step_kind") or diagnostics.get("current_step_kind") or ""),
        "task_graph_node_runtime": bool(context.get("task_graph_node_runtime") or diagnostics.get("task_graph_node_runtime")),
        "step_sequence": list(context.get("step_sequence") or diagnostics.get("step_sequence") or []),
        "selected_prompt_resources": [
            {
                "section_id": str(item.get("section_id") or ""),
                "resource_id": str(item.get("resource_id") or ""),
                "resource_type": str(item.get("resource_type") or ""),
                "selection_reason": str(item.get("selection_reason") or ""),
            }
            for item in selected
        ],
    }


def _context_policy_ref(context_policy_result: dict[str, Any]) -> str:
    package = dict(context_policy_result.get("package") or {})
    return str(
        context_policy_result.get("result_id")
        or package.get("package_id")
        or package.get("id")
        or package.get("rebuild_reason")
        or ""
    )


def _operation_requirement_from_payload(payload: dict[str, Any]):
    from task_system.contracts.capability_requirements import OperationRequirement

    return OperationRequirement(
        requirement_id=str(payload.get("requirement_id") or ""),
        task_id=str(payload.get("task_id") or ""),
        source=str(payload.get("source") or ""),
        required_operations=tuple(str(item) for item in list(payload.get("required_operations") or []) if str(item)),
        optional_operations=tuple(str(item) for item in list(payload.get("optional_operations") or []) if str(item)),
        denied_operations=tuple(str(item) for item in list(payload.get("denied_operations") or []) if str(item)),
        reason=str(payload.get("reason") or ""),
        authority=str(payload.get("authority") or "candidate_only"),
        metadata=dict(payload.get("metadata") or {}),
    )
