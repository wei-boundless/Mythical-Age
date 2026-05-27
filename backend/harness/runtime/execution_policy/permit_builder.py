from __future__ import annotations

from typing import Any

from .models import AgentAssemblyContract, ExecutionPermit
from .validation import validate_execution_permit


def build_execution_permit(assembly: AgentAssemblyContract) -> ExecutionPermit:
    capability = assembly.capability_binding
    policy = dict(capability.metadata.get("tool_execution_policy") or {})
    explicit_visible_tools = _dedupe(
        [
            *list(policy.get("allowed_tool_names") or []),
            *list(capability.visible_tools),
        ]
    )
    denied_tools = set(_dedupe([*list(policy.get("denied_tool_names") or [])]))
    denied_operations = set(_dedupe([*list(policy.get("denied_operation_refs") or []), *list(policy.get("blocked_operation_refs") or [])]))
    allowed_operations = _dedupe(
        [
            *list(capability.allowed_operations),
            *list(_default_agent_operations(assembly)),
        ]
    )
    if denied_operations:
        allowed_operations = [item for item in allowed_operations if item not in denied_operations]
    visible_tools = _dedupe(
        [
            *explicit_visible_tools,
            *[
                _operation_to_tool_ref(item, preferred_tool_names=explicit_visible_tools)
                for item in allowed_operations
                if item != "op.model_response"
            ],
        ]
    )
    if denied_tools:
        visible_tools = [item for item in visible_tools if item not in denied_tools]
    dispatchable_tools = _dedupe(
        [
            *list(capability.dispatchable_tools),
            *visible_tools,
        ]
    )
    if denied_tools:
        dispatchable_tools = [item for item in dispatchable_tools if item not in denied_tools]
    permit = ExecutionPermit(
        permit_id="",
        assembly_id=assembly.assembly_id,
        work_order_id=assembly.work_order_id,
        executor_type=assembly.executor_type,
        agent_id=assembly.agent_id,
        agent_profile_id=assembly.agent_profile_id,
        allowed_operations=tuple(allowed_operations),
        visible_tools=tuple(visible_tools),
        dispatchable_tools=tuple(dispatchable_tools),
        mcp_routes=tuple(_dedupe(list(capability.mcp_routes))),
        delegated_agent_ids=tuple(_dedupe(list(capability.delegated_agent_ids))),
        sandbox_mode=_sandbox_mode_from_assembly(assembly),
        approval_state=_approval_state_from_assembly(assembly),
        operation_gate_ref=assembly.execution_contract_ref or assembly.assembly_id,
        tool_gate_ref=f"toolgate:{assembly.assembly_id}",
        model_visible_tool_refs=tuple(visible_tools),
        diagnostics={
            "assembly_role_name": assembly.prompt_assembly.role_name if assembly.prompt_assembly is not None else "",
            "assembly_role_summary": assembly.prompt_assembly.role_summary if assembly.prompt_assembly is not None else "",
            "visible_tools_source": "capability_binding",
            "dispatchable_tools_source": "capability_binding",
            "tool_execution_policy": policy,
            "sandbox_policy": _sandbox_policy_snapshot(assembly),
            "approval_state_source": _approval_state_source(assembly),
        },
        metadata={
            "output_boundary_id": assembly.output_boundary.boundary_id,
            "model_requirement": dict(assembly.metadata.get("model_requirement") or {}),
            "dynamic_memory_read_policy": dict(capability.metadata.get("dynamic_memory_read_policy") or {}),
        },
    )
    report = validate_execution_permit(permit)
    if not report.passed:
        messages = "; ".join(issue.message for issue in report.issues)
        raise ValueError(f"invalid execution permit: {messages}")
    return permit


def _default_agent_operations(assembly: AgentAssemblyContract) -> tuple[str, ...]:
    if assembly.executor_type == "human":
        return ()
    if assembly.capability_binding.allowed_operations:
        return ()
    return ("op.model_response",)


def _sandbox_mode_from_assembly(assembly: AgentAssemblyContract) -> str:
    work_order = dict(assembly.work_order or {})
    runtime_assembly = dict(work_order.get("runtime_assembly") or assembly.runtime_assembly or {})
    sandbox_policy = dict(runtime_assembly.get("sandbox_policy") or work_order.get("sandbox_policy") or {})
    return str(sandbox_policy.get("mode") or runtime_assembly.get("sandbox_mode") or work_order.get("sandbox_mode") or "").strip()


def _approval_state_from_assembly(assembly: AgentAssemblyContract) -> str:
    work_order = dict(assembly.work_order or {})
    dispatch_context = dict(assembly.dispatch_context or {})
    runtime_assembly = dict(work_order.get("runtime_assembly") or assembly.runtime_assembly or {})
    candidate = (
        dispatch_context.get("approval_state")
        or runtime_assembly.get("approval_state")
        or work_order.get("approval_state")
        or assembly.capability_binding.metadata.get("approval_state")
        or assembly.output_boundary.finalization_policy
    )
    return str(candidate or "").strip()


def _approval_state_source(assembly: AgentAssemblyContract) -> str:
    work_order = dict(assembly.work_order or {})
    dispatch_context = dict(assembly.dispatch_context or {})
    runtime_assembly = dict(work_order.get("runtime_assembly") or assembly.runtime_assembly or {})
    if dispatch_context.get("approval_state"):
        return "dispatch_context"
    if runtime_assembly.get("approval_state"):
        return "runtime_assembly"
    if work_order.get("approval_state"):
        return "work_order"
    if assembly.capability_binding.metadata.get("approval_state"):
        return "capability_binding"
    if assembly.output_boundary.finalization_policy:
        return "output_boundary"
    return "none"


def _sandbox_policy_snapshot(assembly: AgentAssemblyContract) -> dict[str, Any]:
    work_order = dict(assembly.work_order or {})
    runtime_assembly = dict(work_order.get("runtime_assembly") or assembly.runtime_assembly or {})
    sandbox_policy = dict(runtime_assembly.get("sandbox_policy") or work_order.get("sandbox_policy") or {})
    return dict(sandbox_policy)


def _operation_to_tool_ref(operation_id: Any, *, preferred_tool_names: list[str] | tuple[str, ...] = ()) -> str:
    item = str(operation_id or "").strip()
    if not item:
        return ""
    if item == "op.memory_read" and "memory_search" in set(preferred_tool_names):
        return "memory_search"
    return item.removeprefix("op.")


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
