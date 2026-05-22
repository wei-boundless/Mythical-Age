from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from agent_system.profiles.runtime_profile_models import AgentRuntimeProfile
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from agent_system.registry.agent_registry import AgentRegistry

from .models import (
    AgentAssemblyContract,
    AssemblyPort,
    CapabilityAssemblyBinding,
    MemoryAssemblyBinding,
    OutputBoundaryBinding,
    PromptAssemblyContract,
    SoulAssemblyBinding,
    WorkOrder,
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
        "prompt_manifest_ref": assembly.prompt_manifest_ref,
        "model_profile_id": assembly.model_profile_id,
        "projection_id": assembly.projection_id,
        "soul_id": assembly.soul_id,
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
    projection_id = _resolve_projection_id(work_order, agent_descriptor)
    soul_id = _resolve_soul_id(work_order, agent_descriptor, projection_id=projection_id)
    prompt_manifest_ref = _resolve_prompt_manifest_ref(work_order)
    memory_binding = _build_memory_binding(work_order, runtime_profile)
    capability_binding = _build_capability_binding(work_order, runtime_profile, agent_descriptor)
    soul_binding = SoulAssemblyBinding(
        projection_id=projection_id,
        soul_id=soul_id,
        prompt_manifest_ref=prompt_manifest_ref,
        role_name=_role_name_for_work_order(work_order),
        role_summary=_role_summary_for_work_order(work_order, agent_descriptor),
        metadata={
            "agent_name": getattr(agent_descriptor, "agent_name", ""),
            "agent_category": getattr(agent_descriptor, "agent_category", ""),
            "runtime_profile_id": getattr(runtime_profile, "agent_profile_id", ""),
        },
    )
    output_boundary = _build_output_boundary(work_order, agent_descriptor, prompt_manifest_ref=prompt_manifest_ref)
    ports = _build_ports(work_order, capability_binding, memory_binding, output_boundary)
    prompt_assembly = PromptAssemblyContract(
        prompt_id=f"prompt:{work_order.work_order_id}",
        role_name=_role_name_for_work_order(work_order),
        role_summary=_role_summary_for_work_order(work_order, agent_descriptor),
        instruction_text=_instruction_text_for_work_order(work_order, agent_descriptor, runtime_profile),
        visible_sections=ports,
        forbidden_actions=_forbidden_actions_for_work_order(work_order, runtime_profile),
        required_outputs=_required_outputs_for_work_order(work_order, output_boundary),
        metadata={
            "work_kind": work_order.work_kind,
            "executor_type": work_order.executor_type,
            "prompt_manifest_ref": prompt_manifest_ref,
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
        projection_id=projection_id,
        soul_id=soul_id,
        prompt_manifest_ref=prompt_manifest_ref,
        prompt_assembly=prompt_assembly,
        memory_binding=memory_binding,
        capability_binding=capability_binding,
        soul_binding=soul_binding,
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
            "projection_resolution_source": _projection_resolution_source(work_order, agent_descriptor),
            "runtime_lane_source": _runtime_lane_source(work_order, runtime_profile),
            "prompt_manifest_ref": prompt_manifest_ref,
        },
        diagnostics={
            "work_order_id": work_order.work_order_id,
            "executor_type": work_order.executor_type,
            "agent_id": agent_id,
            "agent_profile_id": agent_profile_id,
            "runtime_lane": runtime_lane,
            "runtime_profile_id": getattr(runtime_profile, "agent_profile_id", ""),
            "ports": [port.to_dict() for port in ports],
        },
    )
    assembly = replace(assembly, model_context=build_model_context(assembly))
    return assembly


def build_execution_permit_for_work_order(
    work_order: WorkOrder,
    *,
    base_dir: Path,
    agent_runtime_profile: AgentRuntimeProfile | None = None,
):
    from runtime.execution_permit import build_execution_permit

    assembly = build_agent_assembly_contract(
        work_order,
        base_dir=base_dir,
        agent_runtime_profile=agent_runtime_profile,
    )
    return build_execution_permit(assembly)


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


def _resolve_projection_id(work_order: WorkOrder, agent_descriptor: Any | None) -> str:
    runtime_assembly = dict(work_order.runtime_assembly or {})
    explicit = str(runtime_assembly.get("projection_id") or runtime_assembly.get("projection_ref") or "").strip()
    if explicit:
        return explicit
    if agent_descriptor is None:
        return ""
    return str(getattr(agent_descriptor, "default_projection_id", "") or "").strip()


def _resolve_soul_id(work_order: WorkOrder, agent_descriptor: Any | None, *, projection_id: str) -> str:
    runtime_assembly = dict(work_order.runtime_assembly or {})
    explicit = str(runtime_assembly.get("soul_id") or "").strip()
    if explicit:
        return explicit
    if projection_id:
        return str(getattr(agent_descriptor, "default_soul_id", "") or "").strip()
    return str(getattr(agent_descriptor, "default_soul_id", "") or "").strip()


def _resolve_prompt_manifest_ref(work_order: WorkOrder) -> str:
    runtime_assembly = dict(work_order.runtime_assembly or {})
    prompt_manifest = dict(runtime_assembly.get("prompt_manifest") or {})
    return str(
        runtime_assembly.get("prompt_manifest_ref")
        or prompt_manifest.get("manifest_id")
        or runtime_assembly.get("manifest_ref")
        or ""
    ).strip()


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
            },
        )
    allowed_operations = tuple(
        str(item).strip()
        for item in list(getattr(runtime_profile, "allowed_operations", ()) or ())
        if str(item).strip()
    )
    if not allowed_operations and work_order.executor_type != "human":
        allowed_operations = ("op.model_response",)
    visible_tools = tuple(
        _operation_to_visible_tool(item)
        for item in allowed_operations
        if item != "op.model_response"
    )
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
    }
    return CapabilityAssemblyBinding(
        allowed_operations=allowed_operations,
        visible_tools=visible_tools,
        dispatchable_tools=dispatchable_tools,
        mcp_routes=mcp_routes,
        delegated_agent_ids=delegated_agent_ids,
        metadata=metadata,
    )


def _build_output_boundary(
    work_order: WorkOrder,
    agent_descriptor: Any | None,
    *,
    prompt_manifest_ref: str,
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
    elif work_order.work_kind == "subruntime":
        channel = "subruntime_result"
        canonical_state = "subruntime"
        persist_policy = "subruntime_commit"
        finalization_policy = "subruntime_result_commit"
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
            "prompt_manifest_ref": prompt_manifest_ref,
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
    if work_order.executor_type == "human":
        return "人工审核员"
    if work_order.work_kind == "node":
        return "阶段任务执行者"
    if work_order.work_kind == "subruntime":
        return "子任务执行者"
    return "执行代理"


def _role_summary_for_work_order(work_order: WorkOrder, agent_descriptor: Any | None) -> str:
    agent_name = str(getattr(agent_descriptor, "agent_name", "") or "").strip()
    if work_order.executor_type == "human":
        return "你负责人工确认和人工结果回填，只处理当前工作单。"
    if work_order.work_kind == "node":
        return f"你负责完成当前阶段任务 {work_order.node_id or work_order.stage_id}，不替代上层流程做取舍。"
    if work_order.work_kind == "subruntime":
        return "你负责完成封装子任务，只返回当前子任务要求的结果。"
    return f"{agent_name or '你'}负责完成当前工作单并交付受限结果。"


def _instruction_text_for_work_order(
    work_order: WorkOrder,
    agent_descriptor: Any | None,
    runtime_profile: AgentRuntimeProfile | None,
) -> str:
    _ = runtime_profile
    agent_name = str(getattr(agent_descriptor, "agent_name", "") or "").strip()
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
    if work_order.work_kind == "subruntime":
        return (
            "你是一名子任务执行者。"
            "你只负责完成封装子任务并返回清晰结果。"
            "你不负责暴露内部执行细节。"
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
    if work_order.work_kind == "subruntime":
        required.append("子任务结果")
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


def _projection_resolution_source(work_order: WorkOrder, agent_descriptor: Any | None) -> str:
    runtime_assembly = dict(work_order.runtime_assembly or {})
    if runtime_assembly.get("projection_id") or runtime_assembly.get("projection_ref"):
        return "runtime_assembly"
    if getattr(agent_descriptor, "default_projection_id", ""):
        return "agent_descriptor_default"
    return "none"


def _runtime_lane_source(work_order: WorkOrder, runtime_profile: AgentRuntimeProfile | None) -> str:
    if work_order.runtime_lane:
        return "work_order"
    if runtime_profile is not None and runtime_profile.allowed_runtime_lanes:
        return "runtime_profile"
    return "default"
