from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from agent_system.profiles.runtime_profile_models import AgentRuntimeProfile
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from agent_system.registry.agent_registry import AgentRegistry

from .models import (
    AgentInvocation,
    AgentAssemblyContract,
    AssemblyPort,
    CapabilityAssemblyBinding,
    MemoryAssemblyBinding,
    OutputBoundaryBinding,
    PromptAssemblyContract,
    RolePromptBinding,
    WorkOrder,
)
from .boundary import (
    build_model_context_payload,
    build_runtime_control_payload,
    build_task_selection_payload,
    runtime_control_ref_summary,
)


def build_model_context(assembly: AgentAssemblyContract) -> dict[str, Any]:
    return {
        "assembly_id": assembly.assembly_id,
        "work_order_id": assembly.work_order_id,
        "task_ref": assembly.task_ref,
        "executor_type": assembly.executor_type,
        "agent_id": assembly.agent_id,
        "agent_profile_id": assembly.agent_profile_id,
        "runtime_lane": assembly.runtime_lane,
        "model_profile_id": assembly.model_profile_id,
        "memory_binding": assembly.memory_binding.to_dict(),
        "capability_binding": assembly.capability_binding.to_dict(),
        "output_boundary": assembly.output_boundary.to_dict(),
        "current_turn_context": dict(assembly.current_turn_context),
        "visible_ports": [port.to_dict() for port in assembly.ports if port.mode == "input" or port.required],
    }


def build_agent_assembly_contract(
    work_order: WorkOrder,
    *,
    base_dir: Path,
    agent_runtime_profile: AgentRuntimeProfile | None = None,
) -> AgentAssemblyContract:
    base_dir = Path(base_dir)
    agent_id, agent_profile_id, runtime_profile, agent_descriptor = _resolve_agent_identity(
        work_order,
        base_dir=base_dir,
        agent_runtime_profile=agent_runtime_profile,
    )
    runtime_lane = _resolve_runtime_lane(work_order, runtime_profile)
    memory_binding = _build_memory_binding(work_order, runtime_profile)
    capability_binding = _build_capability_binding(work_order, runtime_profile, agent_descriptor)
    role_name = _role_name_for_work_order(work_order)
    role_summary = _role_summary_for_work_order(work_order, agent_descriptor)
    instruction_text = _instruction_text_for_work_order(work_order, agent_descriptor, runtime_profile)
    runtime_model_requirement = _runtime_model_requirement(work_order)
    role_prompt_source = _runtime_role_prompt_source(work_order) or "fallback"
    role_prompt_binding = RolePromptBinding(
        role_prompt_id=_runtime_role_prompt_id(work_order),
        role_name=role_name,
        role_summary=role_summary,
        metadata={
            "agent_name": getattr(agent_descriptor, "agent_name", ""),
            "agent_category": getattr(agent_descriptor, "agent_category", ""),
            "runtime_profile_id": getattr(runtime_profile, "agent_profile_id", ""),
            "role_prompt_source": role_prompt_source,
        },
    )
    output_boundary = _build_output_boundary(work_order, agent_descriptor)
    ports = _build_ports(work_order, capability_binding, memory_binding, output_boundary)
    prompt_assembly = PromptAssemblyContract(
        prompt_id=f"prompt:{work_order.work_order_id}",
        role_name=role_name,
        role_summary=role_summary,
        instruction_text=instruction_text,
        visible_sections=ports,
        forbidden_actions=_forbidden_actions_for_work_order(work_order, runtime_profile),
        required_outputs=_required_outputs_for_work_order(work_order, output_boundary),
        metadata={
            "work_kind": work_order.work_kind,
            "executor_type": work_order.executor_type,
            "role_prompt_source": role_prompt_source,
            "model_requirement": runtime_model_requirement,
        },
    )
    assembly = AgentAssemblyContract(
        assembly_id="",
        work_order_id=work_order.work_order_id,
        work_kind=work_order.work_kind,
        task_ref=work_order.task_ref,
        executor_type=work_order.executor_type,
        coordination_run_id=work_order.coordination_run_id,
        thread_id=work_order.thread_id,
        root_task_run_id=work_order.root_task_run_id,
        stage_id=work_order.stage_id,
        node_id=work_order.node_id,
        agent_id=agent_id,
        agent_profile_id=agent_profile_id,
        runtime_lane=runtime_lane,
        model_profile_id=str(getattr(runtime_profile.model_profile, "profile_id", "") or "") if runtime_profile is not None else "",
        prompt_assembly=prompt_assembly,
        memory_binding=memory_binding,
        capability_binding=capability_binding,
        role_prompt_binding=role_prompt_binding,
        output_boundary=output_boundary,
        ports=ports,
        execution_contract_ref=_execution_contract_ref(work_order),
        current_turn_context=dict(work_order.current_turn_context),
        work_order=work_order.to_dict(),
        artifact_policy=dict(work_order.artifact_policy),
        stream_policy=dict(work_order.stream_policy),
        dispatch_context=dict(work_order.dispatch_context),
        memory_snapshot=dict(work_order.memory_snapshot),
        artifact_context_packet=dict(work_order.artifact_context_packet),
        revision_packet=dict(work_order.revision_packet),
        human_work_packet=dict(work_order.human_work_packet),
        a2a_payload=dict(work_order.a2a_payload),
        executor_binding=dict(work_order.executor_binding),
        graph_state=dict(work_order.graph_state),
        runtime_assembly=dict(work_order.runtime_assembly),
        model_context={},
        metadata={
            "work_order_kind": work_order.work_kind,
            "work_order_executor_type": work_order.executor_type,
            "agent_name": getattr(agent_descriptor, "agent_name", ""),
            "agent_category": getattr(agent_descriptor, "agent_category", ""),
            "agent_resolution_source": _agent_resolution_source(work_order, agent_runtime_profile, runtime_profile),
            "runtime_lane_source": _runtime_lane_source(work_order, runtime_profile),
            "model_requirement": runtime_model_requirement,
            "tool_execution_policy": _runtime_tool_execution_policy(work_order),
            "dynamic_memory_read_policy": _runtime_dynamic_memory_read_policy(work_order),
        },
        diagnostics={
            "work_order_id": work_order.work_order_id,
            "executor_type": work_order.executor_type,
            "agent_id": agent_id,
            "agent_profile_id": agent_profile_id,
            "runtime_lane": runtime_lane,
            "runtime_profile_id": getattr(runtime_profile, "agent_profile_id", ""),
            "model_requirement": runtime_model_requirement,
            "prompt_role_source": role_prompt_source,
            "ports": [port.to_dict() for port in ports],
        },
    )
    assembly = replace(assembly, model_context=build_model_context(assembly))
    return assembly


def build_agent_invocation(
    work_order: WorkOrder,
    *,
    base_dir: Path,
    agent_runtime_profile: AgentRuntimeProfile | None = None,
) -> AgentInvocation:
    from harness.runtime.execution_policy import build_execution_permit

    assembly = build_agent_assembly_contract(
        work_order,
        base_dir=base_dir,
        agent_runtime_profile=agent_runtime_profile,
    )
    permit = build_execution_permit(assembly)
    work_order_payload = work_order.to_dict()
    assembly_payload = assembly.to_dict()
    permit_payload = permit.to_dict()
    stage_execution_request = _stage_execution_request_payload(work_order_payload)
    runtime_control = build_runtime_control_payload(
        stage_execution_request=stage_execution_request,
        stage_execution_request_ref=str(
            stage_execution_request.get("request_id")
            or work_order_payload.get("idempotency_key")
            or work_order.work_order_id
            or ""
        ),
        node_work_order=work_order_payload,
        agent_assembly_contract=assembly_payload,
        standard_input_package=dict(work_order.input_package),
    )
    model_context = build_model_context_payload(
        current_turn_context=dict(work_order.current_turn_context),
        stage_execution_request=stage_execution_request,
        node_work_order=work_order_payload,
        agent_assembly_contract=assembly_payload,
        stage_execution_request_ref=str(runtime_control.get("stage_execution_request_ref") or ""),
    )
    task_selection = build_task_selection_payload(
        current_turn_context=model_context,
        agent_assembly_contract=assembly_payload,
        runtime_control=runtime_control,
    )
    return AgentInvocation(
        invocation_id="",
        work_order_id=work_order.work_order_id,
        assembly_id=assembly.assembly_id,
        task_ref=work_order.task_ref,
        executor_type=work_order.executor_type,
        agent_id=assembly.agent_id,
        agent_profile_id=assembly.agent_profile_id,
        runtime_lane=assembly.runtime_lane,
        work_order=work_order_payload,
        assembly_contract=assembly_payload,
        execution_permit=permit_payload,
        runtime_control=runtime_control,
        model_context=model_context,
        task_selection=task_selection,
        diagnostics={
            "runtime_control_summary": runtime_control_ref_summary(runtime_control),
            "work_order_kind": work_order.work_kind,
            "executor_type": work_order.executor_type,
        },
        metadata={
            "assembly_authority": assembly.authority,
            "permit_authority": permit.authority,
        },
    )


def build_execution_permit_for_work_order(
    work_order: WorkOrder,
    *,
    base_dir: Path,
    agent_runtime_profile: AgentRuntimeProfile | None = None,
):
    from harness.runtime.execution_policy import build_execution_permit

    assembly = build_agent_assembly_contract(
        work_order,
        base_dir=base_dir,
        agent_runtime_profile=agent_runtime_profile,
    )
    return build_execution_permit(assembly)


def _stage_execution_request_payload(work_order_payload: dict[str, Any]) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in dict(work_order_payload or {}).items()
        if key not in {"authority", "work_kind"}
    }
    payload.setdefault("request_id", str(work_order_payload.get("work_order_id") or ""))
    payload.setdefault("standard_input_package", dict(work_order_payload.get("input_package") or {}))
    payload.setdefault("authority", "task_graph.node_execution_request")
    return payload


def _resolve_agent_identity(
    work_order: WorkOrder,
    *,
    base_dir: Path,
    agent_runtime_profile: AgentRuntimeProfile | None,
) -> tuple[str, str, AgentRuntimeProfile | None, Any | None]:
    registry = AgentRegistry(base_dir)
    runtime_registry = AgentRuntimeRegistry(base_dir)
    resolved_profile = agent_runtime_profile
    agent_id = str(work_order.agent_id or "").strip()
    agent_profile_id = str(work_order.agent_profile_id or "").strip()
    agent_descriptor = registry.get_agent(agent_id) if agent_id else None
    if resolved_profile is None and agent_id:
        resolved_profile = runtime_registry.get_profile(agent_id)
    if resolved_profile is None and agent_profile_id:
        resolved_profile = _find_runtime_profile_by_profile_id(runtime_registry, agent_profile_id)
    if agent_descriptor is None and resolved_profile is not None:
        agent_descriptor = registry.get_agent(str(getattr(resolved_profile, "agent_id", "") or "").strip())
    if agent_descriptor is None and not agent_id:
        agent_descriptor = registry.get_agent("agent:0")
        agent_id = str(getattr(agent_descriptor, "agent_id", "") or "agent:0")
    if resolved_profile is None and agent_id:
        resolved_profile = runtime_registry.get_profile(agent_id)
    if resolved_profile is None:
        resolved_profile = _find_runtime_profile_by_profile_id(runtime_registry, "main_interactive_agent")
    if agent_descriptor is None and resolved_profile is not None:
        agent_descriptor = registry.get_agent(str(getattr(resolved_profile, "agent_id", "") or "agent:0"))
    if agent_descriptor is None:
        agent_descriptor = registry.get_agent("agent:0")
    if not agent_id:
        agent_id = str(getattr(agent_descriptor, "agent_id", "") or getattr(resolved_profile, "agent_id", "") or "agent:0")
    if not agent_profile_id:
        agent_profile_id = str(
            getattr(resolved_profile, "agent_profile_id", "")
            or getattr(agent_descriptor, "metadata", {}).get("runtime_template_id", "")
            or "main_interactive_agent"
        )
    return agent_id, agent_profile_id, resolved_profile, agent_descriptor


def _find_runtime_profile_by_profile_id(
    runtime_registry: AgentRuntimeRegistry,
    profile_id: str,
) -> AgentRuntimeProfile | None:
    target = str(profile_id or "").strip()
    if not target:
        return None
    return next((item for item in runtime_registry.list_profiles() if item.agent_profile_id == target), None)


def _resolve_runtime_lane(work_order: WorkOrder, runtime_profile: AgentRuntimeProfile | None) -> str:
    candidates = [
        str(work_order.runtime_lane or "").strip(),
        *[str(item).strip() for item in list(getattr(runtime_profile, "allowed_runtime_lanes", ()) or ()) if str(item).strip()],
    ]
    if work_order.executor_type == "human":
        return str(work_order.runtime_lane or "human_review").strip()
    for candidate in candidates:
        if candidate:
            return candidate
    return "role_interaction"


def _build_memory_binding(
    work_order: WorkOrder,
    runtime_profile: AgentRuntimeProfile | None,
) -> MemoryAssemblyBinding:
    allowed_layers = tuple(str(item).strip() for item in list(getattr(runtime_profile, "allowed_memory_scopes", ()) or ()) if str(item).strip())
    if work_order.executor_type == "human":
        allowed_layers = ()
    read_scope = {
        "layers": list(allowed_layers),
        "source": "agent_runtime_profile",
    }
    write_scope = {
        "mode": "disabled" if work_order.executor_type == "human" else "task_bound",
        "source": "work_order",
    }
    snapshot_ref = str(dict(work_order.memory_snapshot or {}).get("memory_snapshot_id") or "").strip()
    durable_ref = str(dict(work_order.dispatch_context or {}).get("durable_memory_ref") or "").strip()
    return MemoryAssemblyBinding(
        read_scope=read_scope,
        write_scope=write_scope,
        snapshot_ref=snapshot_ref,
        durable_ref=durable_ref,
    )


def _build_capability_binding(
    work_order: WorkOrder,
    runtime_profile: AgentRuntimeProfile | None,
    agent_descriptor: Any | None,
) -> CapabilityAssemblyBinding:
    tool_execution_policy = _runtime_tool_execution_policy(work_order)
    explicit_tool_names = _policy_tool_names(tool_execution_policy, "allowed_tool_names")
    denied_tool_names = _policy_tool_names(tool_execution_policy, "denied_tool_names")
    denied_operation_refs = _policy_operation_refs(tool_execution_policy, "denied_operation_refs", "blocked_operation_refs")
    if work_order.executor_type != "agent":
        return CapabilityAssemblyBinding(
            allowed_operations=(),
            visible_tools=(),
            dispatchable_tools=(),
            mcp_routes=(),
            delegated_agent_ids=(),
            metadata={
                "agent_name": getattr(agent_descriptor, "agent_name", ""),
                "agent_category": getattr(agent_descriptor, "agent_category", ""),
                "can_delegate_to_agents": False,
                "approval_policy": str(getattr(runtime_profile, "approval_policy", "") or ""),
                "executor_type": work_order.executor_type,
                "tool_execution_policy": tool_execution_policy,
            },
        )
    allowed_operations = tuple(
        str(item).strip()
        for item in list(getattr(runtime_profile, "allowed_operations", ()) or ())
        if str(item).strip()
    )
    explicit_operations = _work_order_operation_policy_operations(work_order)
    policy_operations = _policy_operation_refs(tool_execution_policy, "allowed_operation_refs", "allowed_operations")
    if explicit_operations:
        allowed_operations = tuple(_dedupe([*allowed_operations, *explicit_operations]))
    if policy_operations:
        allowed_operations = tuple(_dedupe(["op.model_response", *policy_operations]))
    if denied_operation_refs:
        denied = set(denied_operation_refs)
        allowed_operations = tuple(item for item in allowed_operations if item not in denied)
    if not allowed_operations and work_order.executor_type != "human":
        allowed_operations = ("op.model_response",)
    operation_visible_tools = tuple(
        _tool_names_for_operation(item, preferred_tool_names=explicit_tool_names)
        for item in allowed_operations
        if item != "op.model_response"
    )
    visible_tools = tuple(_dedupe([*explicit_tool_names, *operation_visible_tools]))
    if denied_tool_names:
        denied_tools = set(denied_tool_names)
        visible_tools = tuple(item for item in visible_tools if item not in denied_tools)
    dispatchable_tools = visible_tools
    delegated_agent_ids = tuple(
        str(item).strip()
        for item in list(getattr(runtime_profile, "allowed_delegate_agent_ids", ()) or ())
        if str(item).strip()
    )
    mcp_routes = tuple(item for item in allowed_operations if item.startswith("op.mcp_"))
    metadata = {
        "agent_name": getattr(agent_descriptor, "agent_name", ""),
        "agent_category": getattr(agent_descriptor, "agent_category", ""),
        "can_delegate_to_agents": bool(getattr(runtime_profile, "can_delegate_to_agents", False)),
        "approval_policy": str(getattr(runtime_profile, "approval_policy", "") or ""),
        "tool_execution_policy": tool_execution_policy,
        "dynamic_memory_read_policy": _runtime_dynamic_memory_read_policy(work_order),
        "explicit_allowed_tool_names": list(explicit_tool_names),
        "denied_tool_names": list(denied_tool_names),
        "denied_operation_refs": list(denied_operation_refs),
    }
    return CapabilityAssemblyBinding(
        allowed_operations=allowed_operations,
        visible_tools=visible_tools,
        dispatchable_tools=dispatchable_tools,
        mcp_routes=mcp_routes,
        delegated_agent_ids=delegated_agent_ids,
        metadata=metadata,
    )


def _work_order_operation_policy_operations(work_order: WorkOrder) -> tuple[str, ...]:
    policies = [
        dict(work_order.current_turn_context or {}).get("operation_policy") or {},
        dict(work_order.runtime_assembly or {}).get("operation_policy") or {},
    ]
    operations: list[str] = []
    for policy in policies:
        item = dict(policy or {})
        operations.extend(str(value).strip() for value in list(item.get("allowed_operations") or []) if str(value).strip())
        operations.extend(str(value).strip() for value in list(item.get("required_operations") or []) if str(value).strip())
        operations.extend(str(value).strip() for value in list(item.get("optional_operations") or []) if str(value).strip())
    if operations:
        operations.append("op.model_response")
    return tuple(_dedupe(operations))


def _runtime_assembly_metadata(work_order: WorkOrder) -> dict[str, Any]:
    return dict(dict(work_order.runtime_assembly or {}).get("metadata") or {})


def _runtime_contract_bindings(work_order: WorkOrder) -> dict[str, Any]:
    runtime_assembly = dict(work_order.runtime_assembly or {})
    metadata = dict(runtime_assembly.get("metadata") or {})
    contract_bindings = dict(metadata.get("contract_bindings") or runtime_assembly.get("contract_bindings") or {})
    return {str(key).strip(): dict(value) for key, value in contract_bindings.items() if str(key).strip() and isinstance(value, dict)}


def _runtime_bindings(work_order: WorkOrder) -> dict[str, Any]:
    return dict(_runtime_contract_bindings(work_order).get("runtime") or {})


def _runtime_memory_bindings(work_order: WorkOrder) -> dict[str, Any]:
    return dict(_runtime_contract_bindings(work_order).get("memory") or {})


def _runtime_model_requirement(work_order: WorkOrder) -> dict[str, Any]:
    requirement = dict(_runtime_bindings(work_order).get("model_requirement") or {})
    runtime_assembly = dict(work_order.runtime_assembly or {})
    metadata = dict(runtime_assembly.get("metadata") or {})
    if not requirement:
        requirement = dict(metadata.get("model_requirement") or runtime_assembly.get("model_requirement") or {})
    return requirement


def _runtime_tool_execution_policy(work_order: WorkOrder) -> dict[str, Any]:
    policy = dict(_runtime_bindings(work_order).get("tool_execution_policy") or {})
    runtime_assembly = dict(work_order.runtime_assembly or {})
    metadata = dict(runtime_assembly.get("metadata") or {})
    if not policy:
        policy = dict(metadata.get("tool_execution_policy") or runtime_assembly.get("tool_execution_policy") or {})
    return policy


def _runtime_dynamic_memory_read_policy(work_order: WorkOrder) -> dict[str, Any]:
    policy = dict(_runtime_memory_bindings(work_order).get("dynamic_memory_read_policy") or {})
    runtime_assembly = dict(work_order.runtime_assembly or {})
    metadata = dict(runtime_assembly.get("metadata") or {})
    if not policy:
        policy = dict(
            metadata.get("dynamic_memory_read_policy")
            or runtime_assembly.get("dynamic_memory_read_policy")
            or {}
        )
    return policy


def _runtime_role_prompt(work_order: WorkOrder) -> str:
    runtime_assembly = dict(work_order.runtime_assembly or {})
    metadata = dict(runtime_assembly.get("metadata") or {})
    contract_bindings = _runtime_contract_bindings(work_order)
    candidates = [
        metadata.get("role_prompt"),
        runtime_assembly.get("role_prompt"),
        dict(contract_bindings.get("prompt") or {}).get("role_prompt"),
        metadata.get("role_identity"),
        runtime_assembly.get("role_identity"),
    ]
    return next((str(item).strip() for item in candidates if str(item or "").strip()), "")


def _runtime_role_prompt_source(work_order: WorkOrder) -> str:
    runtime_assembly = dict(work_order.runtime_assembly or {})
    metadata = dict(runtime_assembly.get("metadata") or {})
    if str(metadata.get("role_prompt") or "").strip():
        return "runtime_assembly.metadata.role_prompt"
    if str(runtime_assembly.get("role_prompt") or "").strip():
        return "runtime_assembly.role_prompt"
    prompt_bindings = dict(_runtime_contract_bindings(work_order).get("prompt") or {})
    if str(prompt_bindings.get("role_prompt") or "").strip():
        return "runtime_assembly.metadata.contract_bindings.prompt.role_prompt"
    if str(metadata.get("role_identity") or "").strip():
        return "runtime_assembly.metadata.role_identity"
    if str(runtime_assembly.get("role_identity") or "").strip():
        return "runtime_assembly.role_identity"
    return ""


def _runtime_role_prompt_id(work_order: WorkOrder) -> str:
    runtime_assembly = dict(work_order.runtime_assembly or {})
    metadata = dict(runtime_assembly.get("metadata") or {})
    prompt_bindings = dict(_runtime_contract_bindings(work_order).get("prompt") or {})
    return str(
        metadata.get("role_prompt_id")
        or runtime_assembly.get("role_prompt_id")
        or prompt_bindings.get("role_prompt_id")
        or ""
    ).strip()


def _policy_tool_names(policy: dict[str, Any], *keys: str) -> tuple[str, ...]:
    values: list[Any] = []
    for key in keys:
        values.extend(list(dict(policy or {}).get(key) or []))
    return tuple(_dedupe([str(item).strip() for item in values if str(item).strip()]))


def _policy_operation_refs(policy: dict[str, Any], *keys: str) -> tuple[str, ...]:
    values: list[Any] = []
    for key in keys:
        values.extend(list(dict(policy or {}).get(key) or []))
    return tuple(_dedupe([str(item).strip() for item in values if str(item).strip()]))


def _tool_names_for_operation(operation_id: str, *, preferred_tool_names: tuple[str, ...] = ()) -> str:
    item = str(operation_id or "").strip()
    if not item:
        return ""
    if item == "op.memory_read" and "memory_search" in set(preferred_tool_names):
        return "memory_search"
    return _operation_to_visible_tool(item)


def _dedupe(values: list[Any] | tuple[Any, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _build_output_boundary(
    work_order: WorkOrder,
    agent_descriptor: Any | None,
) -> OutputBoundaryBinding:
    if work_order.executor_type == "human":
        channel = "human_review"
        canonical_state = "human_response"
        persist_policy = "manual_commit"
        finalization_policy = "human_commit"
    elif work_order.work_kind == "node":
        channel = "graph_node_result"
        canonical_state = "graph_node"
        persist_policy = "graph_commit"
        finalization_policy = "node_result_commit"
    elif work_order.work_kind == "graph_module":
        channel = "graph_module_result"
        canonical_state = "graph_module"
        persist_policy = "graph_module_commit"
        finalization_policy = "graph_module_result_commit"
    else:
        channel = "assistant_message"
        canonical_state = "assistant_message"
        persist_policy = "assistant_commit"
        finalization_policy = "assistant_message_commit"
    fallback_reason = "missing_output_contract" if not work_order.output_contract_id else ""
    leak_flags = tuple(
        str(item).strip()
        for item in list(dict(work_order.dispatch_context or {}).get("leak_flags") or [])
        if str(item).strip()
    )
    return OutputBoundaryBinding(
        boundary_id=f"boundary:{work_order.work_order_id}",
        selected_channel=channel,
        canonical_state=canonical_state,
        persist_policy=persist_policy,
        finalization_policy=finalization_policy,
        fallback_reason=fallback_reason,
        leak_flags=leak_flags,
        metadata={
            "agent_name": getattr(agent_descriptor, "agent_name", ""),
        },
    )


def _build_ports(
    work_order: WorkOrder,
    capability_binding: CapabilityAssemblyBinding,
    memory_binding: MemoryAssemblyBinding,
    output_boundary: OutputBoundaryBinding,
) -> tuple[AssemblyPort, ...]:
    ports = [
        AssemblyPort(
            port_id=f"input:{work_order.work_order_id}",
            port_kind="task_input",
            mode="input",
            required=True,
            ref=str(work_order.input_package.get("package_id") or work_order.a2a_payload.get("payload_id") or work_order.work_order_id),
            metadata={"work_kind": work_order.work_kind},
        ),
        AssemblyPort(
            port_id=f"output:{work_order.work_order_id}",
            port_kind="task_output",
            mode="output",
            required=True,
            ref=output_boundary.boundary_id,
            metadata={"selected_channel": output_boundary.selected_channel},
        ),
        AssemblyPort(
            port_id=f"memory:{work_order.work_order_id}",
            port_kind="memory_scope",
            mode="input",
            required=False,
            ref=memory_binding.snapshot_ref or memory_binding.durable_ref,
            metadata={"read_layers": list(memory_binding.read_scope.get("layers") or [])},
        ),
    ]
    if capability_binding.allowed_operations:
        ports.append(
            AssemblyPort(
                port_id=f"permission:{work_order.work_order_id}",
                port_kind="execution_permission",
                mode="input",
                required=False,
                ref=",".join(capability_binding.allowed_operations),
                metadata={
                    "visible_tools": list(capability_binding.visible_tools),
                    "dispatchable_tools": list(capability_binding.dispatchable_tools),
                },
            )
        )
    if work_order.executor_type == "human":
        ports.append(
            AssemblyPort(
                port_id=f"human:{work_order.work_order_id}",
                port_kind="human_work_packet",
                mode="output",
                required=False,
                ref=str(work_order.human_work_packet.get("work_packet_id") or ""),
                metadata={"executor_type": "human"},
            )
        )
    return tuple(ports)


def _role_name_for_work_order(work_order: WorkOrder) -> str:
    role_prompt = _runtime_role_prompt(work_order)
    if role_prompt:
        first_line = role_prompt.splitlines()[0].strip()
        if first_line.startswith("你是一名"):
            name = first_line.removeprefix("你是一名").split("。", 1)[0].strip()
            if name:
                return name
        if first_line.startswith("你是"):
            name = first_line.removeprefix("你是").strip(" “”\"'。")
            if name:
                return name
    if work_order.executor_type == "human":
        return "人工审核员"
    if work_order.work_kind == "node":
        return "阶段任务执行者"
    if work_order.work_kind == "graph_module":
        return "图模块执行者"
    return "执行代理"


def _role_summary_for_work_order(work_order: WorkOrder, agent_descriptor: Any | None) -> str:
    agent_name = str(getattr(agent_descriptor, "agent_name", "") or "").strip()
    role_prompt = _runtime_role_prompt(work_order)
    if role_prompt:
        summary_lines = [line.strip() for line in role_prompt.splitlines() if line.strip()]
        return "\n".join(summary_lines[:3])
    if work_order.executor_type == "human":
        return "你负责人工确认和人工结果回填，只处理当前工作单。"
    if work_order.work_kind == "node":
        return f"你负责完成当前阶段任务 {work_order.node_id or work_order.stage_id}，不替代上层流程做取舍。"
    if work_order.work_kind == "graph_module":
        return "你负责启动并接收当前图模块的结果，只返回图模块对父图承诺的输出。"
    return f"{agent_name or '你'}负责完成当前工作单并交付受限结果。"


def _instruction_text_for_work_order(
    work_order: WorkOrder,
    agent_descriptor: Any | None,
    runtime_profile: AgentRuntimeProfile | None,
) -> str:
    _ = runtime_profile
    agent_name = str(getattr(agent_descriptor, "agent_name", "") or "").strip()
    role_prompt = _runtime_role_prompt(work_order)
    if role_prompt:
        return role_prompt
    if work_order.executor_type == "human":
        return (
            "你是一名人工执行者。"
            "你只负责阅读当前工作单并返回明确结果。"
            "你不负责扩写背景，也不负责替系统决策。"
        )
    if work_order.work_kind == "node":
        return (
            "你是一名阶段任务执行者。"
            "你只负责完成当前阶段职责，交付必须符合当前阶段的验收要求。"
            "你不负责替上层流程重写任务安排。"
        )
    if work_order.work_kind == "graph_module":
        return (
            "你是一名图模块执行者。"
            "你只负责完成当前导入图模块并返回对父图承诺的结果。"
            "你不负责暴露导入图内部执行细节，也不替父图改写流程。"
        )
    return (
        f"你是一名{agent_name or '执行代理'}。"
        "你只负责完成当前工作单并返回可验证结果。"
        "你不负责扩写无关内容，也不负责修改运行边界。"
    )


def _forbidden_actions_for_work_order(
    work_order: WorkOrder,
    runtime_profile: AgentRuntimeProfile | None,
) -> tuple[str, ...]:
    profile_blocked = tuple(
        str(item).strip()
        for item in list(getattr(runtime_profile, "blocked_operations", ()) or ())
        if str(item).strip()
    )
    extras = ["越权修改运行边界", "泄露内部装配细节"]
    if work_order.executor_type == "human":
        extras.append("替系统自动执行")
    return tuple(dict.fromkeys([*profile_blocked, *extras]))


def _required_outputs_for_work_order(
    work_order: WorkOrder,
    output_boundary: OutputBoundaryBinding,
) -> tuple[str, ...]:
    _ = output_boundary
    required = ["最终回答"]
    if work_order.work_kind == "node":
        required.append("当前阶段结果")
    if work_order.executor_type == "human":
        required.append("人工反馈")
    if work_order.work_kind == "graph_module":
        required.append("图模块结果")
    return tuple(dict.fromkeys([item for item in required if item]))


def _execution_contract_ref(work_order: WorkOrder) -> str:
    runtime_assembly = dict(work_order.runtime_assembly or {})
    return str(runtime_assembly.get("execution_contract_ref") or runtime_assembly.get("runtime_spec_id") or work_order.output_contract_id or work_order.work_order_id)


def _operation_to_visible_tool(operation_id: str) -> str:
    item = str(operation_id or "").strip()
    if not item:
        return ""
    return item.removeprefix("op.")


def _agent_resolution_source(
    work_order: WorkOrder,
    agent_runtime_profile: AgentRuntimeProfile | None,
    runtime_profile: AgentRuntimeProfile | None,
) -> str:
    if agent_runtime_profile is not None:
        return "explicit_agent_runtime_profile"
    if work_order.agent_id:
        return "work_order_agent_id"
    if runtime_profile is not None:
        return "runtime_registry"
    return "system_default"


def _runtime_lane_source(work_order: WorkOrder, runtime_profile: AgentRuntimeProfile | None) -> str:
    if work_order.runtime_lane:
        return "work_order"
    if runtime_profile is not None and runtime_profile.allowed_runtime_lanes:
        return "runtime_profile"
    return "default"
