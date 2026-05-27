from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from prompt_library import (
    assemble_runtime_prompt_contract,
    assemble_runtime_prompt_sections,
    build_prompt_manifest_validation,
)

from ..registry.agent_registry import AgentRegistry
from ..identity import normalize_agent_id
from ..profiles.runtime_profile_models import AgentRuntimeProfile
from ..profiles.runtime_profile_registry import AgentRuntimeRegistry
from .runtime_spec_models import AgentRuntimeSpec, TaskBodyOrchestration
from ..profiles.body_registry import BodyProfileRegistry


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
    agent_runtime_profile: AgentRuntimeProfile | None = None,
) -> dict[str, Any]:
    base_dir = Path(base_dir)
    task_contract = dict(task_assembly_bundle.get("task_contract") or {})
    task_execution_assembly = dict(task_assembly_bundle.get("task_execution_assembly") or {})
    task_spec = dict(task_assembly_bundle.get("task_spec") or {})
    selected_recipe = dict(task_assembly_bundle.get("selected_recipe") or {})
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
        operation_requirement=operation_requirement,
        agent_id=agent_id,
        current_turn_context=current_turn_payload,
    )
    prompt_contract_metadata = dict(prompt_contract.get("metadata") or {})
    prompt_selection_context = dict(prompt_contract_metadata.get("prompt_selection_context") or {})
    prompt_assembly_plan = dict(prompt_contract_metadata.get("prompt_assembly_plan") or {})
    prompt_manifest = _prompt_manifest_from_contract(
        base_dir=base_dir,
        session_id=session_id,
        task_id=task_id,
        current_turn_context=current_turn_payload,
        prompt_contract=prompt_contract,
        interaction_mode=str(
            prompt_selection_context.get("interaction_mode")
            or dict(prompt_contract_metadata.get("mode_policy") or {}).get("interaction_mode")
            or ""
        ),
        skill_runtime_views=skill_runtime_views,
        use_shared_contract=bool(getattr(runtime_profile, "use_shared_contract", True)),
    )
    prompt_flow_trace = _prompt_flow_trace(
        prompt_selection_context=prompt_selection_context,
        prompt_assembly_plan=prompt_assembly_plan,
    )
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
        },
        verification_gate_plan={
            "task_constraints": dict(task_execution_assembly.get("task_constraints") or {}),
            "safety_envelope": dict(task_execution_assembly.get("safety_envelope") or {}),
        },
        fallback_plan={
            "runtime_executable_default": True,
            "fallback_policy": "fail_closed",
        },
        prompt_manifest=prompt_manifest,
        diagnostics={
            "builder": "orchestration.build_orchestration_runtime_bundle",
            "soul_runtime_projection_enabled": False,
            "prompt_selection_context": prompt_selection_context,
            "prompt_assembly_plan": prompt_assembly_plan,
            "prompt_flow_trace": prompt_flow_trace,
            "prompt_manifest_ref": str(prompt_manifest.get("manifest_id") or ""),
            "memory_view_ref": str(memory_view.get("view_id") or ""),
            "context_policy_ref": _context_policy_ref(context_policy),
            "runtime_lane": runtime_lane_profile.lane_id,
            "requested_runtime_lane": requested_runtime_lane,
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
            "soul_runtime_projection_enabled": False,
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


def _prompt_manifest_from_contract(
    *,
    base_dir: Path,
    session_id: str,
    task_id: str,
    current_turn_context: dict[str, Any],
    prompt_contract: dict[str, Any],
    interaction_mode: str,
    skill_runtime_views: list[dict[str, Any]],
    use_shared_contract: bool,
) -> dict[str, Any]:
    request = SimpleNamespace(
        task_id=task_id,
        session_id=session_id,
        turn_id=str(current_turn_context.get("turn_id") or ""),
    )
    sections = assemble_runtime_prompt_sections(
        base_dir=base_dir,
        contract=prompt_contract,
        projection=None,
        request=request,
        soul_skill_views=tuple(_attribute_view(item) for item in skill_runtime_views),
        soul_tool_views=(),
        use_shared_contract=use_shared_contract,
    )
    section_payloads = [section.to_dict() if hasattr(section, "to_dict") else dict(section) for section in sections]
    validation = build_prompt_manifest_validation(
        interaction_mode=interaction_mode,
        sections=section_payloads,
    )
    assembly_order = [
        str(item.get("section_id") or "")
        for item in section_payloads
        if str(item.get("section_id") or "")
    ]
    return {
        "authority": "orchestration.prompt_manifest",
        "manifest_id": f"prompt-manifest:{task_id}",
        "task_id": task_id,
        "session_id": session_id,
        "turn_id": str(current_turn_context.get("turn_id") or ""),
        "assembly_order": assembly_order,
        "total_sections": len(section_payloads),
        "total_chars": sum(int(item.get("chars") or len(str(item.get("content") or ""))) for item in section_payloads),
        "sections": section_payloads,
        "validation": validation,
    }


def _attribute_view(payload: dict[str, Any]) -> Any:
    return SimpleNamespace(**dict(payload or {}))


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


