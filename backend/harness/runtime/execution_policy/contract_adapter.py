from __future__ import annotations

from typing import Any

from runtime.agent_assembly.models import (
    AgentAssemblyContract,
    AssemblyPort,
    CapabilityAssemblyBinding,
    MemoryAssemblyBinding,
    OutputBoundaryBinding,
    PromptAssemblyContract,
    RolePromptBinding,
)

from .permit_builder import build_execution_permit


def build_execution_permit_from_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    assembly = dict(payload or {})
    if not assembly:
        return {}
    return build_execution_permit(agent_assembly_contract_from_payload(assembly)).to_dict()


def agent_assembly_contract_from_payload(payload: dict[str, Any]) -> AgentAssemblyContract:
    capability = dict(payload.get("capability_binding") or {})
    output = dict(payload.get("output_boundary") or {})
    prompt_payload = dict(payload.get("prompt_assembly") or {})
    return AgentAssemblyContract(
        assembly_id=str(payload.get("assembly_id") or ""),
        work_order_id=str(payload.get("work_order_id") or ""),
        work_kind=str(payload.get("work_kind") or ""),
        task_ref=str(payload.get("task_ref") or ""),
        executor_type=str(payload.get("executor_type") or "agent"),
        coordination_run_id=str(payload.get("coordination_run_id") or ""),
        thread_id=str(payload.get("thread_id") or ""),
        root_task_run_id=str(payload.get("root_task_run_id") or ""),
        stage_id=str(payload.get("stage_id") or ""),
        node_id=str(payload.get("node_id") or ""),
        agent_id=str(payload.get("agent_id") or ""),
        agent_profile_id=str(payload.get("agent_profile_id") or ""),
        runtime_lane=str(payload.get("runtime_lane") or ""),
        model_profile_id=str(payload.get("model_profile_id") or ""),
        prompt_assembly=_prompt_from_payload(prompt_payload) if prompt_payload else None,
        memory_binding=MemoryAssemblyBinding(**dict(payload.get("memory_binding") or {})),
        capability_binding=CapabilityAssemblyBinding(
            allowed_operations=_tuple_str(capability.get("allowed_operations")),
            visible_tools=_tuple_str(capability.get("visible_tools")),
            dispatchable_tools=_tuple_str(capability.get("dispatchable_tools")),
            mcp_routes=_tuple_str(capability.get("mcp_routes")),
            delegated_agent_ids=_tuple_str(capability.get("delegated_agent_ids")),
            metadata=dict(capability.get("metadata") or {}),
        ),
        role_prompt_binding=RolePromptBinding(**dict(payload.get("role_prompt_binding") or {})),
        output_boundary=OutputBoundaryBinding(
            boundary_id=str(output.get("boundary_id") or ""),
            selected_channel=str(output.get("selected_channel") or ""),
            canonical_state=str(output.get("canonical_state") or ""),
            persist_policy=str(output.get("persist_policy") or ""),
            finalization_policy=str(output.get("finalization_policy") or ""),
            fallback_reason=str(output.get("fallback_reason") or ""),
            leak_flags=_tuple_str(output.get("leak_flags")),
            metadata=dict(output.get("metadata") or {}),
        ),
        ports=_ports(payload.get("ports")),
        execution_contract_ref=str(payload.get("execution_contract_ref") or ""),
        current_turn_context=dict(payload.get("current_turn_context") or {}),
        work_order=dict(payload.get("work_order") or {}),
        artifact_policy=dict(payload.get("artifact_policy") or {}),
        stream_policy=dict(payload.get("stream_policy") or {}),
        dispatch_context=dict(payload.get("dispatch_context") or {}),
        memory_snapshot=dict(payload.get("memory_snapshot") or {}),
        artifact_context_packet=dict(payload.get("artifact_context_packet") or {}),
        revision_packet=dict(payload.get("revision_packet") or {}),
        human_work_packet=dict(payload.get("human_work_packet") or {}),
        a2a_payload=dict(payload.get("a2a_payload") or {}),
        executor_binding=dict(payload.get("executor_binding") or {}),
        graph_state=dict(payload.get("graph_state") or {}),
        runtime_assembly=dict(payload.get("runtime_assembly") or {}),
        model_context=dict(payload.get("model_context") or {}),
        metadata=dict(payload.get("metadata") or {}),
        diagnostics=dict(payload.get("diagnostics") or {}),
    )


def _prompt_from_payload(payload: dict[str, Any]) -> PromptAssemblyContract:
    return PromptAssemblyContract(
        prompt_id=str(payload.get("prompt_id") or ""),
        role_name=str(payload.get("role_name") or ""),
        role_summary=str(payload.get("role_summary") or ""),
        instruction_text=str(payload.get("instruction_text") or ""),
        visible_sections=_ports(payload.get("visible_sections")),
        forbidden_actions=_tuple_str(payload.get("forbidden_actions")),
        required_outputs=_tuple_str(payload.get("required_outputs")),
        metadata=dict(payload.get("metadata") or {}),
    )


def _ports(values: Any) -> tuple[AssemblyPort, ...]:
    return tuple(AssemblyPort(**dict(item)) for item in list(values or []) if isinstance(item, dict))


def _tuple_str(values: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in list(values or []) if str(item))
