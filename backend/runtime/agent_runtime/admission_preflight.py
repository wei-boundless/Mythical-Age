from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_system.models.model_profile_resolver import ModelProfileResolver
from permissions import build_model_response_runtime_admission, build_runtime_capability_state

from ..capabilities import build_current_turn_capability_plan
from ..execution_permit import tool_instances_for_policy_and_permit
from ..shared.safety import build_task_safety_validators
from .context import chat_model_selection_runtime_defaults, model_requirement_for_model_resolution
from .environment.tool_capability_policy import (
    apply_tool_capability_table_to_turn_plan,
    capability_table_to_runtime_plan_overlay,
    prepare_runtime_tool_capability_table_for_turn,
)


@dataclass(frozen=True, slots=True)
class AgentRuntimeAdmissionPreflightResult:
    directive: Any
    resource_policy: Any
    current_turn_capability_plan: Any
    current_turn_capability_plan_payload: dict[str, Any]
    tool_capability_overlay: dict[str, Any]
    resolved_model_spec: Any | None
    task_safety_validators: dict[str, Any]
    runtime_tool_instances: list[Any]
    runtime_capability_state: dict[str, Any]
    events: tuple[dict[str, Any], ...]


def prepare_agent_runtime_admission(
    *,
    runtime_host: Any,
    task_run_id: str,
    task_id: str,
    task_contract_ref: str,
    task_operation: dict[str, Any],
    task_execution_assembly_payload: dict[str, Any],
    current_turn_context: dict[str, Any],
    assembly_contract: dict[str, Any],
    agent_runtime_spec_payload: dict[str, Any],
    effective_agent_runtime_profile: Any,
    model_response_executor: Any,
    model_selection: dict[str, Any],
    tool_instances: list[Any],
    allowed_search_sources: set[str],
    execution_permit: dict[str, Any],
    sandbox_policy: dict[str, Any],
    file_management_policy: dict[str, Any],
) -> AgentRuntimeAdmissionPreflightResult:
    """Prepare model response admission, tool visibility, and operation validators."""

    directive, resource_policy = build_model_response_runtime_admission(
        task_operation,
        operation_registry=runtime_host.operation_gate.registry,
        agent_runtime_profile=effective_agent_runtime_profile,
        sandbox_policy=sandbox_policy,
    )
    current_turn_capability_plan = build_current_turn_capability_plan(
        tool_instances=tool_instances,
        resource_policy=resource_policy,
        definitions_by_name=runtime_host.tool_authorization_index.definitions_by_name,
        normalize_operation_id=runtime_host.operation_gate.registry.normalize_id,
        task_operation=task_operation,
        allowed_search_sources=allowed_search_sources,
        execution_permit=execution_permit,
    )
    tool_capability_table = prepare_runtime_tool_capability_table_for_turn(
        task_operation={**dict(task_operation), "resource_policy": resource_policy, "task_id": task_id},
        file_management_policy=file_management_policy,
        execution_permit=execution_permit,
        runtime_available_operations=current_turn_capability_plan.allowed_operations,
    )
    if tool_capability_table is not None:
        task_operation["tool_capability_table"] = tool_capability_table
        current_turn_capability_plan = apply_tool_capability_table_to_turn_plan(
            current_turn_capability_plan,
            tool_capability_table,
        )
    current_turn_capability_plan_payload = current_turn_capability_plan.to_dict()
    tool_capability_overlay = capability_table_to_runtime_plan_overlay(tool_capability_table)
    if tool_capability_overlay:
        current_turn_capability_plan_payload["tool_capability_table"] = tool_capability_overlay
    task_operation["current_turn_capability_plan"] = current_turn_capability_plan_payload

    events: list[dict[str, Any]] = []
    resolved_model_spec = None
    settings_service = getattr(getattr(model_response_executor, "model_runtime", None), "settings_service", None)
    if settings_service is not None:
        model_requirement = model_requirement_for_model_resolution(
            task_execution_assembly=task_execution_assembly_payload,
            current_turn_context=current_turn_context,
            agent_assembly_contract=assembly_contract,
        )
        resolved_model_spec = ModelProfileResolver(settings_service).resolve_model_spec(
            agent_runtime_profile=effective_agent_runtime_profile,
            model_requirement=dict(model_requirement) if isinstance(model_requirement, dict) else {},
            runtime_lane=str(agent_runtime_spec_payload.get("runtime_lane") or ""),
            graph_runtime_defaults=chat_model_selection_runtime_defaults(model_selection),
        )
        model_resolution_event = runtime_host.event_log.append(
            task_run_id,
            "model_profile_resolved",
            payload={"model_resolution": resolved_model_spec.to_public_dict()},
            refs={
                "task_contract_ref": task_contract_ref,
                "agent_profile_ref": str(
                    getattr(effective_agent_runtime_profile, "agent_profile_id", "") or ""
                ),
            },
        )
        events.append({"type": "runtime_loop_event", "event": model_resolution_event.to_dict()})

    task_safety_envelope = dict(
        dict(task_operation.get("operation_requirement") or {}).get("metadata") or {}
    ).get("safety_envelope", {})
    task_safety_validators = build_task_safety_validators(
        root_dir=runtime_host.root_dir,
        safety_envelope=task_safety_envelope,
        sandbox_policy=sandbox_policy,
    )
    runtime_tool_instances = tool_instances_for_policy_and_permit(
        tool_instances=tool_instances,
        resource_policy=resource_policy,
        definitions_by_name=runtime_host.tool_authorization_index.definitions_by_name,
        normalize_operation_id=runtime_host.operation_gate.registry.normalize_id,
        allowed_search_sources=allowed_search_sources,
        sandbox_policy=sandbox_policy,
        execution_permit=execution_permit,
        task_operation=task_operation,
        capability_plan=current_turn_capability_plan,
    )
    runtime_capability_state = build_runtime_capability_state(
        task_operation,
        resource_policy=resource_policy,
        agent_runtime_profile=effective_agent_runtime_profile,
        visible_tool_names=list(current_turn_capability_plan.model_visible_tools),
        sandbox_policy=sandbox_policy,
    )
    return AgentRuntimeAdmissionPreflightResult(
        directive=directive,
        resource_policy=resource_policy,
        current_turn_capability_plan=current_turn_capability_plan,
        current_turn_capability_plan_payload=current_turn_capability_plan_payload,
        tool_capability_overlay=tool_capability_overlay,
        resolved_model_spec=resolved_model_spec,
        task_safety_validators=task_safety_validators,
        runtime_tool_instances=list(runtime_tool_instances),
        runtime_capability_state=runtime_capability_state,
        events=tuple(events),
    )
