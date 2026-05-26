from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_system.profiles.runtime_profile_models import AgentRuntimeProfile
from capability_system.skill_registry import SkillRegistry
from permissions.resource_policy_builder import RuntimeApprovalContext
from request_intent.frame_access import capability_needs
from request_intent.frame_access import material_kinds
from task_system.contracts.capability_requirements import build_operation_requirement

from task_system.services.assembly_models import ProjectionSelectionResult, TaskExecutionAssembly
from task_system.services.assembly_support import (
    _align_runtime_definitions,
    _align_task_binding_with_template,
    _build_bundle_spec,
    _build_task_safety_envelope,
    _build_task_spec,
    build_runtime_task_intent_contract,
    _dedupe,
    _projection_tags,
    _resolve_operation_approval_policy,
    _resolve_registered_task,
    _resolve_task_mode,
    _resolve_task_workflow,
    _task_contract_execution_mode,
)
from task_system.services.bindings import default_task_binding, merge_task_bindings
from task_system.contracts.contracts import build_task_contract
from task_system.tasks.definitions import select_runtime_task_definitions
from task_system.tasks import SpecificTaskAssemblyPolicy, resolve_specific_task_assembly_policy
from task_system.planning.execution_recipe_builder import build_execution_recipe
from task_system.planning.execution_shape_resolver import resolve_execution_shape
from task_system.registry.flow_registry import TaskFlowRegistry
from task_system.contracts.runtime_contracts import SkillRuntimeView, skill_runtime_views_from_registry
from task_system.registry.workflow_registry import TaskWorkflowRegistry


def build_task_execution_assembly_bundle(
    *,
    base_dir: Path | None = None,
    session_id: str,
    user_goal: str,
    task_id: str = "task-runtime",
    source: str = "runtime",
    approval_context: RuntimeApprovalContext | None = None,
    query_understanding: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
    runtime_required_operations: tuple[str, ...] | list[str] | None = None,
    agent_runtime_profile: AgentRuntimeProfile | None = None,
) -> dict[str, Any]:
    _ = approval_context
    registry_base_dir = Path(base_dir) if base_dir is not None else _registry_base_dir()
    definitions = select_runtime_task_definitions(
        user_goal,
        query_understanding=query_understanding,
    )
    current_turn_payload = dict(current_turn_context or {})
    flow_registry = TaskFlowRegistry(registry_base_dir)
    workflow_registry = TaskWorkflowRegistry(registry_base_dir)
    skill_registry = SkillRegistry(registry_base_dir)
    registered_task = _resolve_registered_task(
        flow_registry=flow_registry,
        current_turn_context=current_turn_payload,
    )
    current_turn_payload = _normalize_current_turn_for_registered_task(
        current_turn_payload=current_turn_payload,
        registered_task=registered_task,
    )
    if not dict(current_turn_payload.get("model_turn_decision") or {}):
        raise RuntimeError("ModelTurnDecision is required before task assembly")
    if not dict(current_turn_payload.get("task_goal_spec") or current_turn_payload.get("goal_frame") or {}):
        raise RuntimeError("Task goal projection must be produced from ModelTurnDecision before task assembly")
    specific_task_record = (
        flow_registry.get_specific_task_record(str(registered_task.get("task_id") or ""))
        if registered_task and str(registered_task.get("task_type") or "") == "specific_task"
        else None
    )
    explicit_task_id = str(
        current_turn_payload.get("selected_task_id")
        or current_turn_payload.get("task_id")
        or current_turn_payload.get("specific_task_id")
        or ""
    ).strip()
    registered_task_id = str((registered_task or {}).get("task_id") or "").strip()
    binding_task_id = ""
    if explicit_task_id.startswith("task."):
        binding_task_id = explicit_task_id
    elif registered_task_id.startswith("task."):
        binding_task_id = registered_task_id
    else:
        binding_task_id = str(explicit_task_id or registered_task_id or task_id).strip()
    execution_policy = flow_registry.get_task_execution_policy(binding_task_id)
    specific_task_policy = (
        resolve_specific_task_assembly_policy(
            task_record=specific_task_record,
            execution_policy=execution_policy,
            task_selection=current_turn_payload,
        )
        if specific_task_record is not None
        else None
    )
    task_intent_contract = build_runtime_task_intent_contract(
        session_id=session_id,
        task_id=task_id,
        user_goal=user_goal,
        query_understanding=query_understanding,
        current_turn_context=current_turn_payload,
    )
    task_requirement_contract = dict(task_intent_contract.task_requirement_contract or {})
    mode_policy = dict(task_intent_contract.mode_policy or {})
    execution_shape = resolve_execution_shape(
        task_intent_contract=task_intent_contract,
        query_understanding=query_understanding,
        current_turn_context=current_turn_payload,
        definitions=definitions,
        registered_task=registered_task,
    )
    selected_recipe = build_execution_recipe(
        base_dir=registry_base_dir,
        execution_shape=execution_shape,
    )
    definitions = _align_runtime_definitions(
        definitions=definitions,
        registered_task=registered_task,
        selected_recipe=selected_recipe,
    )
    bundle_spec = _build_bundle_spec(
        task_id=task_id,
        current_turn_context=current_turn_payload,
    )
    bindings = [default_task_binding(definition) for definition in definitions]
    merged_binding = _align_task_binding_with_template(
        merge_task_bindings(bindings),
        selected_recipe=selected_recipe,
    )
    merged_binding = _augment_skill_scope_from_runtime_intent(
        merged_binding=merged_binding,
        query_understanding=dict(query_understanding or {}),
        current_turn_context=current_turn_payload,
    )
    merged_binding = _apply_specific_task_policy_to_binding(
        merged_binding=merged_binding,
        specific_task_policy=specific_task_policy,
    )
    task_mode = _resolve_task_mode(
        registered_task=registered_task,
        selected_recipe=selected_recipe,
        definitions=definitions,
    )
    task_contract = build_task_contract(
        task_id=task_id,
        session_id=session_id,
        user_goal=user_goal,
        source=source,
        recipe_id=selected_recipe.recipe_id,
        task_mode=task_mode,
        task_spec_ref=f"taskspec:{task_id}",
    )
    skill_views = _skill_views_for_task_binding(
        skill_registry=skill_registry,
        merged_binding=merged_binding,
    )
    runtime_operations = _dedupe(list(runtime_required_operations or ()))
    resolved_runtime_operations = _resolve_runtime_recipe_operations(
        selected_recipe=selected_recipe,
        agent_runtime_profile=agent_runtime_profile,
    )
    operation_policy = _resolve_task_operation_policy(
        selected_recipe=selected_recipe,
        registered_task=registered_task,
        current_turn_context=current_turn_payload,
        specific_task_policy=specific_task_policy,
    )
    allowed_operations = {
        str(item or "").strip()
        for item in list(operation_policy.get("allowed_operations") or [])
        if str(item or "").strip()
    }
    policy_denied_operations = _dedupe(
        [
            *list(merged_binding.denied_operations),
            *list(operation_policy.get("denied_operations") or []),
        ]
    )
    policy_required_operations = _dedupe(list(operation_policy.get("required_operations") or []))
    policy_optional_operations = _dedupe(list(operation_policy.get("optional_operations") or []))
    default_operations = _dedupe(
        [
            "op.model_response",
            *runtime_operations,
            *list(resolved_runtime_operations.get("required_operations") or ()),
            *policy_required_operations,
            *[
                operation
                for definition in definitions
                for operation in definition.default_operation_requirements
            ],
        ]
    )
    skill_operations = _dedupe(
        [
            *list(resolved_runtime_operations.get("optional_operations") or ()),
            *policy_optional_operations,
            *_agent_profile_capability_operations(agent_runtime_profile),
            *[operation for skill in skill_views for operation in skill.required_operations],
        ]
    )
    if str(resolved_runtime_operations.get("execution_mode") or "").strip() == "delegate":
        delegated_specialist_ops = {
            str(item).strip()
            for skill in skill_views
            for item in list(skill.required_operations or ())
            if str(item).strip() and str(item).strip() != "op.delegate_to_agent"
        }
        skill_operations = [
            operation
            for operation in skill_operations
            if operation not in delegated_specialist_ops
        ]
    if allowed_operations:
        default_operations = [
            operation
            for operation in default_operations
            if operation == "op.model_response" or operation in allowed_operations
        ]
        skill_operations = [
            operation
            for operation in skill_operations
            if operation in allowed_operations
        ]
    if _profile_is_text_artifact_runtime_agent(agent_runtime_profile):
        text_runtime_allowed = _text_artifact_runtime_allowed_operations(agent_runtime_profile)
        default_operations = [
            operation
            for operation in default_operations
            if operation == "op.model_response" or operation in text_runtime_allowed
        ]
        skill_operations = [
            operation
            for operation in skill_operations
            if operation in text_runtime_allowed
        ]
        policy_denied_operations = _dedupe(
            [
                *policy_denied_operations,
                "op.read_file",
                "op.search_files",
                "op.search_text",
                "op.read_structured_file",
                "op.web_search",
                "op.fetch_url",
                "op.delegate_to_agent",
                "op.write_file",
                "op.edit_file",
                "op.shell",
                "op.python_repl",
            ]
        )
    operation_requirement = build_operation_requirement(
        task_id=task_contract.task_id,
        source="task_binding",
        required_task_operations=tuple(
            operation
            for operation in list(merged_binding.required_operations)
            if not allowed_operations or operation in allowed_operations
        ),
        denied_operations=tuple(policy_denied_operations),
        default_operation_requirements=tuple(default_operations),
        capability_operations=tuple(skill_operations),
        approval_policy=_resolve_operation_approval_policy(
            merged_binding=merged_binding,
            selected_recipe=selected_recipe,
            registered_task=registered_task,
        ),
        review_policy=merged_binding.review_policy,
        safety_envelope=_build_task_safety_envelope(
            selected_recipe=selected_recipe,
            registered_task=registered_task,
            current_turn_context=current_turn_payload,
        ),
        extra_metadata={
            "runtime_operation_resolution": dict(resolved_runtime_operations),
            **(
                {
                    "specific_task_assembly_policy_ref": specific_task_policy.policy_id,
                    "specific_task_environment_id": specific_task_policy.environment_id,
                }
                if specific_task_policy is not None
                else {}
            ),
        },
        reason="derived from runtime recipe, TaskDefinition, TaskBinding, task-side skill scope, and task operation policy",
    )
    task_spec = _build_task_spec(
        task_id=task_id,
        session_id=session_id,
        user_goal=user_goal,
        selected_recipe=selected_recipe,
        registered_task=registered_task,
        task_intent_contract=task_intent_contract,
        bundle_spec=bundle_spec,
        definitions=definitions,
        current_turn_context=current_turn_payload,
        query_understanding=dict(query_understanding or {}),
        operation_requirement_ref=operation_requirement.requirement_id,
        skill_runtime_views=skill_views,
        operation_requirement=operation_requirement.to_dict(),
    )
    task_workflow = _resolve_task_workflow(
        flow_registry=flow_registry,
        workflow_registry=workflow_registry,
        registered_task=registered_task,
        selected_recipe=selected_recipe,
        definitions=definitions,
        current_turn_context=current_turn_payload,
        task_mode=task_mode,
    )
    projection_selection = _build_projection_selection_result(
        task_id=task_contract.task_id,
        task_mode=task_mode,
        registered_task=registered_task,
        current_turn_context=current_turn_payload,
        task_workflow=task_workflow,
        merged_binding=merged_binding,
    )
    projection_binding = flow_registry.get_projection_binding(binding_task_id)
    flow_contract_binding = flow_registry.get_flow_contract_binding(binding_task_id)
    memory_request_profile = flow_registry.get_task_memory_request_profile(binding_task_id)
    memory_request_profile_payload = _memory_request_profile_payload(
        memory_request_profile,
        task_id=binding_task_id or task_contract.task_id,
        task_mode=task_mode,
        query_understanding=dict(query_understanding or {}),
    )
    projection_selection = _align_projection_selection_with_binding(
        projection_selection=projection_selection,
        projection_binding=projection_binding,
    )
    runtime_limits = dict(task_spec.constraints or {}).get("runtime_limits") or {}
    communication_protocol = _select_communication_protocol(
        flow_registry=flow_registry,
        registered_task=registered_task,
        current_turn_context=current_turn_payload,
    )
    coordination_request_brief = dict(task_spec.inputs.get("coordination_request_brief") or {})
    task_graph = _select_task_graph(
        flow_registry=flow_registry,
        registered_task=registered_task,
        current_turn_context=current_turn_payload,
    )
    task_contract_payload = task_contract.to_dict()
    if current_turn_payload:
        task_contract_payload["execution_mode"] = _task_contract_execution_mode(current_turn_payload)
        task_contract_payload["current_turn_context_ref"] = str(
            current_turn_payload.get("authority") or "context.current_turn"
        )
        task_contract_payload["bindings"] = {
            **dict(task_contract_payload.get("bindings") or {}),
            "current_turn": current_turn_payload,
        }
    task_contract_payload["task_intent_ref"] = task_intent_contract.task_intent_id
    task_contract_payload["task_requirement_contract"] = task_requirement_contract
    task_contract_payload["mode_policy"] = mode_policy
    task_contract_payload["selected_recipe_id"] = selected_recipe.recipe_id
    task_contract_payload["bundle_spec_ref"] = bundle_spec.bundle_id if bundle_spec is not None else ""
    task_contract_payload["requested_outputs"] = list(task_spec.requested_outputs)
    execution_chain_type = "single_agent_chain"
    if task_graph is not None:
        execution_chain_type = "coordination_chain"
    elif bool(getattr(execution_policy, "allow_worker_agent_spawn", False)):
        execution_chain_type = "coordination_chain"
    graph_ref = str(getattr(task_graph, "graph_id", "") or "").strip()
    task_graph_record = flow_registry.get_task_graph(graph_ref) if graph_ref.startswith("graph.") else None
    task_policy = dict((registered_task or {}).get("task_policy") or {})
    task_graph_node_runtime = _registered_task_is_task_graph_node_runtime(registered_task)
    runtime_lane_hint = str(
        task_mode if task_graph_node_runtime else mode_policy.get("runtime_lane") or ""
    ).strip()
    assembly = TaskExecutionAssembly(
        assembly_id=f"taskasm:{task_id}",
        task_id=task_contract.task_id,
        session_id=session_id,
        task_mode=task_mode,
        task_kind=str((registered_task or {}).get("task_type") or "conversation_entry_policy"),
        task_intent_ref=task_intent_contract.task_intent_id,
        task_spec_ref=task_spec.task_spec_ref,
        bundle_spec_ref=bundle_spec.bundle_id if bundle_spec is not None else "",
        workflow_id=str((task_workflow or {}).get("workflow_id") or ""),
        projection_selection_ref=f"taskproj:{task_id}",
        projection_binding_ref=str(getattr(projection_binding, "binding_id", "") or ""),
        projection_id=str(projection_selection.selected_projection_id or getattr(projection_binding, "default_projection_id", "") or ""),
        flow_contract_binding_ref=str(getattr(flow_contract_binding, "binding_id", "") or ""),
        flow_contract_id=str(getattr(flow_contract_binding, "flow_contract_id", "") or str((registered_task or {}).get("flow_id") or "")),
        execution_chain_type=execution_chain_type,
        task_execution_policy_ref=str(getattr(execution_policy, "policy_id", "") or ""),
        memory_request_profile_ref=str(getattr(memory_request_profile, "profile_id", "") or ""),
        communication_protocol_ref=str(getattr(communication_protocol, "protocol_id", "") or ""),
        graph_ref=graph_ref,
        topology_template_ref=str(getattr(task_graph, "topology_template_id", "") or ""),
        operation_requirement_ref=operation_requirement.requirement_id,
        input_contract_id=str((registered_task or {}).get("input_contract_id") or ""),
        output_contract_id=str((registered_task or {}).get("output_contract_id") or ""),
        safety_envelope=dict(task_spec.safety_envelope or {}),
        task_constraints=dict(task_spec.constraints or {}),
        requested_outputs=tuple(task_spec.requested_outputs),
        metadata={
            "stream_policy": dict(task_policy.get("stream_policy") or {}),
            "artifact_policy": dict(task_policy.get("artifact_policy") or {}),
            "recipe_id": selected_recipe.recipe_id,
            "execution_kind": selected_recipe.execution_kind,
            "source_kind": selected_recipe.source_kind,
            "interaction_mode": str(mode_policy.get("interaction_mode") or ""),
            "runtime_lane_hint": runtime_lane_hint,
            "projection_strength": str(mode_policy.get("projection_strength") or ""),
            "semantic_task_type": str(task_requirement_contract.get("task_goal_type") or ""),
            "professional_profile_id": str(task_requirement_contract.get("professional_profile_id") or ""),
            "mode_policy": mode_policy,
            "task_requirement_contract": task_requirement_contract,
            "registered_task_id": registered_task_id,
            "binding_task_id": binding_task_id,
            "registered_task_type": str((registered_task or {}).get("task_type") or ""),
            "specific_task_title": str(getattr(specific_task_record, "task_title", "") or ""),
            "specific_task_assembly_policy": specific_task_policy.to_dict() if specific_task_policy is not None else {},
            "task_environment_id": str(specific_task_policy.environment_id if specific_task_policy is not None else ""),
            "workflow_title": str((task_workflow or {}).get("title") or ""),
            "projection_source": projection_selection.selection_source,
            "memory_layers": list(memory_request_profile_payload.get("requested_memory_layers") or ()),
            "memory_topics": list(memory_request_profile_payload.get("requested_topics") or ()),
            "execution_policy_mode": str(getattr(execution_policy, "execution_mode", "") or ""),
            "runtime_limits": dict(runtime_limits),
            "operation_policy": dict(operation_policy),
            **({"coordination_request_ref": coordination_request_brief.get("brief_id")} if coordination_request_brief else {}),
            "final_answer_requirements": list(
                dict(getattr(selected_recipe, "metadata", {}) or {}).get("final_answer_requirements") or []
            ),
            "forbidden_final_states": list(
                dict(getattr(selected_recipe, "metadata", {}) or {}).get("forbidden_final_states") or []
            ),
        },
    )
    return {
        "task_contract": task_contract_payload,
        "definitions": [definition.to_dict() for definition in definitions],
        "task_intent_contract": task_intent_contract.to_dict(),
        "execution_shape": execution_shape.to_dict(),
        "selected_recipe": selected_recipe.to_dict(),
        "bundle_spec": bundle_spec.to_dict() if bundle_spec is not None else {},
        "task_spec": task_spec.to_dict(),
        "coordination_request_brief": coordination_request_brief,
        "binding": merged_binding.to_dict(),
        "skill_runtime_views": [view.to_dict() for view in skill_views],
        "operation_requirement": operation_requirement.to_dict(),
        "projection_selection": projection_selection.to_dict(),
        "task_execution_assembly": assembly.to_dict(),
        "specific_task_record": specific_task_record.to_dict() if specific_task_record is not None else {},
        "specific_task_assembly_policy": specific_task_policy.to_dict() if specific_task_policy is not None else {},
        "task_environment": _task_environment_payload(specific_task_policy),
        "task_projection_binding": projection_binding.to_dict() if projection_binding is not None else {},
        "task_flow_contract_binding": flow_contract_binding.to_dict() if flow_contract_binding is not None else {},
        "task_execution_policy": execution_policy.to_dict() if execution_policy is not None else {},
        "task_memory_request_profile": memory_request_profile_payload,
        "task_communication_protocol": communication_protocol.to_dict() if communication_protocol is not None else {},
        "graph_record": task_graph.to_dict() if task_graph is not None else {},
        "task_graph_record": task_graph_record.to_dict() if task_graph_record is not None else {},
        "registered_task": dict(registered_task or {}),
        "query_understanding": dict(query_understanding or {}),
        "current_turn_context": current_turn_payload,
        "status": "assembled",
        "_definitions_obj": definitions,
        "_selected_recipe_obj": selected_recipe,
        "_merged_binding_obj": merged_binding,
        "_task_workflow_obj": task_workflow,
        "_task_spec_obj": task_spec,
        "_operation_requirement_obj": operation_requirement,
        "_projection_selection_obj": projection_selection,
    }


def _profile_is_text_artifact_runtime_agent(agent_runtime_profile: AgentRuntimeProfile | None) -> bool:
    metadata = dict(getattr(agent_runtime_profile, "metadata", {}) or {}) if agent_runtime_profile is not None else {}
    return str(metadata.get("agent_mode") or metadata.get("runtime_mode") or "").strip() in {
        "text_artifact_worker",
        "text_artifact_runtime",
    } or bool(metadata.get("text_artifact_runtime") is True)


def _text_artifact_runtime_allowed_operations(agent_runtime_profile: AgentRuntimeProfile | None) -> set[str]:
    if agent_runtime_profile is None:
        return {"op.model_response"}
    allowed = {
        str(item or "").strip()
        for item in tuple(getattr(agent_runtime_profile, "allowed_operations", ()) or ())
        if str(item or "").strip()
    }
    blocked = {
        str(item or "").strip()
        for item in tuple(getattr(agent_runtime_profile, "blocked_operations", ()) or ())
        if str(item or "").strip()
    }
    return {item for item in allowed if item not in blocked and item in {"op.model_response", "op.memory_read", "op.text_metric"}}


def _agent_profile_capability_operations(agent_runtime_profile: AgentRuntimeProfile | None) -> list[str]:
    if agent_runtime_profile is None:
        return []
    blocked = {
        str(item or "").strip()
        for item in tuple(getattr(agent_runtime_profile, "blocked_operations", ()) or ())
        if str(item or "").strip()
    }
    return _dedupe(
        [
            operation
            for operation in [
                str(item or "").strip()
                for item in tuple(getattr(agent_runtime_profile, "allowed_operations", ()) or ())
            ]
            if operation and operation != "op.model_response" and operation not in blocked
        ]
    )


def _normalize_current_turn_for_registered_task(
    *,
    current_turn_payload: dict[str, Any],
    registered_task: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(current_turn_payload or {})
    if not _registered_task_is_task_graph_node_runtime(registered_task):
        return payload
    task_policy = dict((registered_task or {}).get("task_policy") or {})
    task_structure = dict(task_policy.get("task_structure") or {})
    metadata = dict((registered_task or {}).get("metadata") or {})
    task_id = str((registered_task or {}).get("task_id") or "").strip()
    runtime_lane = str(
        (registered_task or {}).get("task_mode")
        or task_structure.get("runtime_lane_hint")
        or metadata.get("runtime_lane_hint")
        or "coordination_task"
    ).strip()
    interaction_mode = str(
        payload.get("interaction_mode")
        or payload.get("runtime_interaction_mode")
        or task_structure.get("runtime_interaction_mode")
        or metadata.get("runtime_interaction_mode")
        or metadata.get("interaction_mode")
        or "role_mode"
    ).strip()
    if task_id:
        payload["selected_task_id"] = task_id
        payload["task_id"] = task_id
        payload["specific_task_id"] = task_id
    if runtime_lane:
        payload["runtime_lane"] = runtime_lane
    if interaction_mode:
        payload["interaction_mode"] = interaction_mode
        payload["runtime_interaction_mode"] = interaction_mode
    payload["task_graph_node_runtime"] = True
    payload["suppress_bundle_projection"] = True
    payload.setdefault("semantic_task_type", "task_graph_node_execution")
    payload.setdefault("task_goal_type", "task_graph_node_execution")
    payload.setdefault("execution_obligation_policy", "orchestration_owns_task_graph_node_side_effects")
    return payload


def _augment_skill_scope_from_runtime_intent(
    *,
    merged_binding: Any,
    query_understanding: dict[str, Any],
    current_turn_context: dict[str, Any],
):
    needs = capability_needs(query_understanding)
    kinds = material_kinds(query_understanding)
    action_intent = str(dict(current_turn_context.get("model_turn_decision") or {}).get("action_intent") or "").strip()
    target_objects = [
        str(item).strip().lower()
        for item in list(dict(current_turn_context.get("model_turn_decision") or {}).get("target_objects") or [])
        if str(item).strip()
    ]
    additions: list[str] = []
    if "knowledge_lookup" in needs:
        additions.append("skill.rag-skill")
    if (
        "dataset_analysis" in needs
        or "dataset" in kinds
        or any(item.endswith((".csv", ".tsv", ".xlsx", ".xls", ".parquet", ".json")) for item in target_objects)
    ):
        additions.append("skill.structured-data-analysis")
    if "document_analysis" in needs or "pdf" in kinds or any(item.endswith(".pdf") for item in target_objects):
        additions.append("skill.pdf-analysis")
    if action_intent in {"run_browser_verification", "open_browser"}:
        additions.append("skill.browser-operation")
    current_scope = [str(item).strip() for item in list(getattr(merged_binding, "skill_scope", ()) or ()) if str(item).strip()]
    merged_scope = tuple(_dedupe([*current_scope, *additions]))
    if merged_scope == tuple(current_scope):
        return merged_binding
    return merged_binding.__class__(
        **{
            **merged_binding.to_dict(),
            "skill_scope": merged_scope,
        }
    )


def _apply_specific_task_policy_to_binding(
    *,
    merged_binding: Any,
    specific_task_policy: SpecificTaskAssemblyPolicy | None,
):
    if specific_task_policy is None:
        return merged_binding
    current = merged_binding.to_dict()
    skill_requirements = specific_task_policy.skill_requirements
    agent_selection = specific_task_policy.agent_selection
    output_contract_ref = str(specific_task_policy.output_contract_ref or "").strip()
    skill_scope = tuple(
        _dedupe(
            [
                *list(current.get("skill_scope") or ()),
                *list(skill_requirements.required_refs),
                *list(skill_requirements.optional_refs),
            ]
        )
    )
    denied_skills = tuple(
        _dedupe(
            [
                *list(current.get("denied_skills") or ()),
                *list(skill_requirements.denied_refs),
            ]
        )
    )
    return merged_binding.__class__(
        **{
            **current,
            "agent_profile_id": str(agent_selection.agent_profile_ref or current.get("agent_profile_id") or ""),
            "skill_scope": skill_scope,
            "denied_skills": denied_skills,
            "output_contract_id": output_contract_ref or str(current.get("output_contract_id") or ""),
            "metadata": {
                **dict(current.get("metadata") or {}),
                "specific_task_assembly_policy_ref": specific_task_policy.policy_id,
                "specific_task_agent_selection": agent_selection.to_dict(),
                "specific_task_prompt_requirements": specific_task_policy.prompt_requirements.to_dict(),
            },
        }
    )


def _registered_task_is_task_graph_node_runtime(registered_task: dict[str, Any] | None) -> bool:
    item = dict(registered_task or {})
    if not item:
        return False
    metadata = dict(item.get("metadata") or {})
    task_policy = dict(item.get("task_policy") or {})
    task_structure = dict(task_policy.get("task_structure") or {})
    return bool(
        metadata.get("task_graph_node_runtime") is True
        or metadata.get("suppress_bundle_projection") is True
        or task_structure.get("suppress_bundle_projection") is True
        or str(task_structure.get("execution_chain_type") or "").strip() == "coordination_node"
    )


def _resolve_runtime_recipe_operations(
    *,
    selected_recipe,
    agent_runtime_profile: AgentRuntimeProfile | None,
) -> dict[str, Any]:
    metadata = dict(getattr(selected_recipe, "metadata", {}) or {})
    strategy = str(metadata.get("execution_strategy") or "").strip()
    if strategy != "delegate_preferred":
        return {
            "strategy": "direct",
            "required_operations": tuple(getattr(selected_recipe, "required_operations", ()) or ()),
            "optional_operations": tuple(getattr(selected_recipe, "optional_operations", ()) or ()),
        }
    fallback_operation = str(metadata.get("fallback_operation") or "").strip()
    target_agent_id = str(metadata.get("delegate_target_agent_id") or "").strip()
    if _can_profile_delegate_to_target(
        agent_runtime_profile,
        target_agent_id=target_agent_id,
    ):
        return {
            "strategy": "delegate_preferred",
            "execution_mode": "delegate",
            "required_operations": ("op.model_response", "op.delegate_to_agent"),
            "optional_operations": (),
            "delegate_target_agent_id": target_agent_id,
            "delegation_kind": str(metadata.get("delegation_kind") or "").strip(),
            "delegate_context_policy": str(getattr(agent_runtime_profile, "delegate_context_policy", "") or "").strip(),
            "fallback_operation": fallback_operation,
        }
    return {
        "strategy": "delegate_preferred",
        "execution_mode": "direct_fallback",
        "required_operations": tuple(_dedupe(["op.model_response", fallback_operation])),
        "optional_operations": tuple(getattr(selected_recipe, "optional_operations", ()) or ()),
        "delegate_target_agent_id": target_agent_id,
        "delegation_kind": str(metadata.get("delegation_kind") or "").strip(),
        "fallback_operation": fallback_operation,
    }


def _can_profile_delegate_to_target(
    profile: AgentRuntimeProfile | None,
    *,
    target_agent_id: str,
) -> bool:
    if profile is None or not bool(getattr(profile, "can_delegate_to_agents", False)):
        return False
    allowed_operations = {
        str(item).strip()
        for item in tuple(getattr(profile, "allowed_operations", ()) or ())
        if str(item).strip()
    }
    blocked_operations = {
        str(item).strip()
        for item in tuple(getattr(profile, "blocked_operations", ()) or ())
        if str(item).strip()
    }
    if "op.delegate_to_agent" not in allowed_operations or "op.delegate_to_agent" in blocked_operations:
        return False
    allowed_ids = {
        str(item).strip()
        for item in tuple(getattr(profile, "allowed_delegate_agent_ids", ()) or ())
        if str(item).strip()
    }
    if allowed_ids and target_agent_id and target_agent_id not in allowed_ids:
        return False
    return True


def _memory_request_profile_payload(
    memory_request_profile: Any,
    *,
    task_id: str,
    task_mode: str,
    query_understanding: dict[str, Any],
) -> dict[str, Any]:
    payload = memory_request_profile.to_dict() if memory_request_profile is not None else {}
    needs = capability_needs(query_understanding)
    model_turn_decision = dict(dict(query_understanding or {}).get("model_turn_decision") or {})
    action_intent = str(model_turn_decision.get("action_intent") or "").strip()
    work_mode = str(model_turn_decision.get("work_mode") or "").strip()
    if (
        not payload
        and (
            task_mode in {"short_realtime_lookup", "information_search"}
            or action_intent == "search_external"
            or bool(needs & {"latest_information", "weather", "gold_price"})
        )
    ):
        payload.update(
            {
                "profile_id": f"taskmem:{task_id}:search",
                "task_id": task_id,
                "requested_memory_layers": ["conversation"],
                "requested_topics": ["current_conversation", task_mode or "search"],
                "memory_priority": "normal",
                "writeback_policy": "task_default",
                "allow_long_term_memory": False,
                "memory_scope_hint": "search_current_conversation",
                "authority": "task_system.task_memory_request_profile",
                "metadata": {"derived_from": "runtime_search_route"},
            }
        )
    if (
        not payload
        and (
            task_mode in {"capability_execution", "knowledge_retrieval"}
            or action_intent in {"read_context", "edit_workspace", "run_command"}
            or work_mode in {"read_only_analysis", "implementation", "verification"}
            or bool(needs & {"dataset_analysis", "document_analysis", "workspace_material"})
        )
    ):
        payload.update(
            {
                "profile_id": f"taskmem:{task_id}:capability",
                "task_id": task_id,
                "requested_memory_layers": ["conversation"],
                "requested_topics": ["current_conversation", task_mode or "capability"],
                "memory_priority": "normal",
                "writeback_policy": "task_default",
                "allow_long_term_memory": False,
                "memory_scope_hint": "capability_current_conversation",
                "authority": "task_system.task_memory_request_profile",
                "metadata": {"derived_from": "runtime_capability_route"},
            }
        )
    if (
        task_mode == "memory_recall"
        or action_intent == "read_context"
        or "memory_recall" in needs
    ):
        requested_layers = _dedupe(
            [
                *list(payload.get("requested_memory_layers") or ()),
                "conversation",
                "state",
                "long_term",
            ]
        )
        requested_topics = _dedupe(
            [
                *list(payload.get("requested_topics") or ()),
                "user_preference",
                "memory_recall",
            ]
        )
        payload.update(
            {
                "profile_id": str(payload.get("profile_id") or f"taskmem:{task_id}:memory"),
                "task_id": str(payload.get("task_id") or task_id),
                "requested_memory_layers": requested_layers,
                "requested_topics": requested_topics,
                "memory_priority": str(payload.get("memory_priority") or "high"),
                "writeback_policy": str(payload.get("writeback_policy") or "task_default"),
                "allow_long_term_memory": True,
                "memory_scope_hint": str(payload.get("memory_scope_hint") or "memory_recall_long_term"),
                "authority": str(payload.get("authority") or "task_system.task_memory_request_profile"),
                "metadata": {
                    **dict(payload.get("metadata") or {}),
                    "derived_from": str(dict(payload.get("metadata") or {}).get("derived_from") or "runtime_memory_route"),
                    "memory_route_long_term_enabled": True,
                },
            }
        )
    return payload


def _build_projection_selection_result(
    *,
    task_id: str,
    task_mode: str,
    registered_task: dict[str, Any] | None,
    current_turn_context: dict[str, Any],
    task_workflow: dict[str, Any] | None,
    merged_binding: Any,
) -> ProjectionSelectionResult:
    explicit_projection_id = str(
        current_turn_context.get("projection_id")
        or current_turn_context.get("projection_card_id")
        or current_turn_context.get("selected_projection_id")
        or ""
    ).strip()
    if explicit_projection_id:
        return ProjectionSelectionResult(
            task_id=task_id,
            selected_projection_id=explicit_projection_id,
            role_type=str(merged_binding.projection_selector or "task_default"),
            posture_tags=tuple(_projection_tags(task_mode)),
            selection_reason="selected by current turn context",
            selection_source="current_turn_context",
        )
    explicit_agent_id = str(current_turn_context.get("agent_id") or "").strip()
    if explicit_agent_id:
        return ProjectionSelectionResult(
            task_id=task_id,
            selected_projection_id="",
            role_type=str(merged_binding.projection_selector or "agent_default"),
            posture_tags=tuple(_projection_tags(task_mode)),
            selection_reason="agent selected by current turn; use agent default projection",
            selection_source="agent_default",
        )
    projection_mode = str(getattr(merged_binding, "projection_selector", "") or "").strip()
    if projection_mode == "agent_default_projection":
        return ProjectionSelectionResult(
            task_id=task_id,
            selected_projection_id="",
            role_type="agent_default",
            posture_tags=tuple(_projection_tags(task_mode)),
            selection_reason="task requires projection resolution from the bound agent",
            selection_source="agent_default",
        )
    registered_projection_id = str((registered_task or {}).get("projection_id") or "").strip()
    if registered_projection_id:
        return ProjectionSelectionResult(
            task_id=task_id,
            selected_projection_id=registered_projection_id,
            role_type=str(merged_binding.projection_selector or "task_default"),
            posture_tags=tuple(_projection_tags(task_mode)),
            selection_reason="selected by registered task binding",
            selection_source="registered_task",
        )
    workflow_projection_ids = [
        str(item).strip()
        for item in list((task_workflow or {}).get("compatible_projection_ids") or [])
        if str(item).strip()
    ]
    if len(workflow_projection_ids) == 1:
        return ProjectionSelectionResult(
            task_id=task_id,
            selected_projection_id=workflow_projection_ids[0],
            role_type=str(merged_binding.projection_selector or "task_default"),
            posture_tags=tuple(_projection_tags(task_mode)),
            selection_reason="single compatible workflow projection",
            selection_source="workflow",
        )
    return ProjectionSelectionResult(
        task_id=task_id,
        selected_projection_id="",
        role_type=str(merged_binding.projection_selector or "task_default"),
        posture_tags=tuple(_projection_tags(task_mode)),
        selection_reason="derived from task binding role and task mode",
        selection_source="task_binding",
    )


def _resolve_task_operation_policy(
    *,
    selected_recipe: Any,
    registered_task: dict[str, Any] | None,
    current_turn_context: dict[str, Any],
    specific_task_policy: SpecificTaskAssemblyPolicy | None = None,
) -> dict[str, Any]:
    recipe_policy = dict(dict(getattr(selected_recipe, "metadata", {}) or {}).get("operation_policy") or {})
    registered_policy = dict((registered_task or {}).get("task_policy") or {})
    task_operation_policy = dict(registered_policy.get("operation_policy") or {})
    specific_tool_policy = (
        specific_task_policy.tool_capability_requirements.to_dict()
        if specific_task_policy is not None
        else {}
    )
    context_policy = dict(current_turn_context.get("operation_policy") or {})
    merged = {**recipe_policy, **task_operation_policy, **specific_tool_policy, **context_policy}
    allowed = _dedupe(
        [
            *list(recipe_policy.get("allowed_operations") or []),
            *list(task_operation_policy.get("allowed_operations") or []),
            *list(specific_tool_policy.get("allowed_operations") or []),
            *list(context_policy.get("allowed_operations") or []),
        ]
    )
    denied = _dedupe(
        [
            *list(recipe_policy.get("denied_operations") or []),
            *list(task_operation_policy.get("denied_operations") or []),
            *list(specific_tool_policy.get("denied_operations") or []),
            *list(context_policy.get("denied_operations") or []),
        ]
    )
    required = _dedupe(
        [
            *list(recipe_policy.get("required_operations") or []),
            *list(task_operation_policy.get("required_operations") or []),
            *list(specific_tool_policy.get("required_operations") or []),
            *list(context_policy.get("required_operations") or []),
        ]
    )
    optional = _dedupe(
        [
            *list(recipe_policy.get("optional_operations") or []),
            *list(task_operation_policy.get("optional_operations") or []),
            *list(specific_tool_policy.get("optional_operations") or []),
            *list(context_policy.get("optional_operations") or []),
        ]
    )
    if not allowed and not denied and not required and not optional:
        return {}
    return {
        "authority": str(
            context_policy.get("authority")
            or specific_tool_policy.get("authority")
            or task_operation_policy.get("authority")
            or recipe_policy.get("authority")
            or "task_system.operation_policy"
        ),
        "allowed_operations": allowed,
        "denied_operations": denied,
        "required_operations": required,
        "optional_operations": optional,
        **(
            {"specific_task_assembly_policy_ref": specific_task_policy.policy_id}
            if specific_task_policy is not None
            else {}
        ),
    }


def _task_environment_payload(specific_task_policy: SpecificTaskAssemblyPolicy | None) -> dict[str, Any]:
    if specific_task_policy is None:
        return {}
    return {
        "environment_id": specific_task_policy.environment_id,
        "specific_task_assembly_policy_ref": specific_task_policy.policy_id,
        "authority": "task_system.specific_task_assembly_policy",
    }


def _align_projection_selection_with_binding(
    *,
    projection_selection: ProjectionSelectionResult,
    projection_binding: Any,
) -> ProjectionSelectionResult:
    mode = str(getattr(projection_binding, "projection_selection_mode", "") or "").strip()
    if mode != "agent_default_projection":
        return projection_selection
    return ProjectionSelectionResult(
        task_id=projection_selection.task_id,
        selected_projection_id="",
        role_type="agent_default",
        posture_tags=tuple(projection_selection.posture_tags),
        selection_reason="task projection binding requires the bound agent default projection",
        selection_source="agent_default",
    )


def _skill_views_for_task_binding(
    *,
    skill_registry: SkillRegistry,
    merged_binding: Any,
) -> list[SkillRuntimeView]:
    return skill_runtime_views_from_registry(
        registry=skill_registry,
        skill_refs=tuple(merged_binding.skill_scope or ()),
        task_reason="Candidate capability available under current task binding.",
    )


def _registry_base_dir():
    from pathlib import Path

    return Path(__file__).resolve().parents[1]


def _select_communication_protocol(
    *,
    flow_registry: TaskFlowRegistry,
    registered_task: dict[str, Any] | None,
    current_turn_context: dict[str, Any] | None = None,
):
    current_turn_payload = dict(current_turn_context or {})
    explicit_protocol_id = str(
        current_turn_payload.get("communication_protocol_id")
        or current_turn_payload.get("protocol_id")
        or ""
    ).strip()
    if explicit_protocol_id:
        explicit_protocol = flow_registry.get_task_communication_protocol(explicit_protocol_id)
        if explicit_protocol is not None:
            return explicit_protocol
    metadata = dict((registered_task or {}).get("metadata") or {})
    metadata_protocol_id = str(metadata.get("communication_protocol_id") or "").strip()
    if metadata_protocol_id:
        protocol = flow_registry.get_task_communication_protocol(metadata_protocol_id)
        if protocol is not None:
            return protocol
    task_graph = _select_task_graph(
        flow_registry=flow_registry,
        registered_task=registered_task,
        current_turn_context=current_turn_payload,
    )
    protocol_id = str(
        getattr(task_graph, "default_protocol_id", "")
        or dict(getattr(task_graph, "metadata", {}) or {}).get("protocol_id")
        or ""
    ).strip()
    if protocol_id:
        protocol = flow_registry.get_task_communication_protocol(protocol_id)
        if protocol is not None:
            return protocol
    return None


def _select_task_graph(
    *,
    flow_registry: TaskFlowRegistry,
    registered_task: dict[str, Any] | None,
    current_turn_context: dict[str, Any] | None = None,
):
    current_turn_payload = dict(current_turn_context or {})
    if _is_stage_execution_turn(current_turn_payload):
        return None
    explicit_refs = (
        current_turn_payload.get("graph_id"),
        current_turn_payload.get("selected_graph_id"),
        current_turn_payload.get("task_graph_id"),
        current_turn_payload.get("coordination_task_id"),
    )
    for ref in explicit_refs:
        target = str(ref or "").strip()
        if not target:
            continue
        resolved = flow_registry.get_task_graph(target)
        if resolved is not None:
            return resolved
    task_id = str((registered_task or {}).get("task_id") or "").strip()
    metadata = dict((registered_task or {}).get("metadata") or {})
    metadata_graph_ref = str(
        metadata.get("graph_id")
        or metadata.get("task_graph_id")
        or ""
    ).strip()
    if metadata_graph_ref:
        resolved = flow_registry.get_task_graph(metadata_graph_ref)
        if resolved is not None:
            return resolved
    for item in flow_registry.list_task_graphs():
        if task_id and task_id in list(item.to_dict().get("subtask_refs") or []):
            return item
    return None


def _is_stage_execution_turn(current_turn_payload: dict[str, Any]) -> bool:
    if not current_turn_payload:
        return False
    if str(current_turn_payload.get("continuation_stage_id") or "").strip():
        return True
    if str(current_turn_payload.get("stage_execution_request_ref") or "").strip():
        return True
    if str(current_turn_payload.get("coordination_run_id") or "").strip():
        return True
    if dict(current_turn_payload.get("task_result_ready_event") or {}):
        return True
    return False
