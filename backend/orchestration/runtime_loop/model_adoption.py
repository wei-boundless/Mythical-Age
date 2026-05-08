from __future__ import annotations

from typing import Any

from capability_system.operation_registry import OperationDescriptor, OperationRegistry
from orchestration.agent_runtime_models import AgentRuntimeProfile
from orchestration.resource_policy import ResourceDecision, ResourcePolicy
from orchestration.resource_policy_builder import RuntimeApprovalContext
from orchestration.resource_scope_mapping import map_operations_to_resource_scopes
from ..runtime_directive import RuntimeDirective


def build_model_response_runtime_adoption(
    task_operation: dict[str, Any],
    *,
    operation_registry: OperationRegistry | None = None,
    agent_runtime_profile: AgentRuntimeProfile | None = None,
    approval_context: RuntimeApprovalContext | None = None,
) -> tuple[RuntimeDirective, ResourcePolicy]:
    """Adopt the current single-agent model lane into an executable directive.

    Task and skill contracts only produce candidate operation requirements.
    This adoption step is where the RuntimeLoop turns those candidates into the
    executable ResourcePolicy consumed by AuthorizedToolSet and OperationGate.
    """

    registry = operation_registry
    context = approval_context or RuntimeApprovalContext()
    task_contract = dict(task_operation.get("task_contract") or {})
    task_execution_assembly = dict(task_operation.get("task_execution_assembly") or {})
    task_body_orchestration = dict(task_operation.get("task_body_orchestration") or {})
    agent_runtime_spec = dict(task_operation.get("agent_runtime_spec") or {})
    task_id = str(task_contract.get("task_id") or "task-runtime")
    policy_ref = f"respol:{task_id}:model-response:runtime"
    decisions = _build_runtime_decisions(
        task_operation,
        registry=registry,
        agent_runtime_profile=agent_runtime_profile,
        approval_context=context,
    )
    allowed_operations = tuple(decision.operation_id for decision in decisions if decision.decision == "allow")
    denied_operations = tuple(decision.operation_id for decision in decisions if decision.decision == "deny")
    requires_approval_operations = tuple(
        decision.operation_id for decision in decisions if decision.decision == "requires_approval"
    )
    not_executable_operations = tuple(
        decision.operation_id for decision in decisions if decision.decision == "not_executable"
    )
    operation_refs = tuple(_dedupe([*allowed_operations, *requires_approval_operations, *not_executable_operations]))
    allowed_scope = (
        map_operations_to_resource_scopes(allowed_operations, registry)
        if registry is not None
        else None
    )
    denied_scope = (
        map_operations_to_resource_scopes(denied_operations, registry)
        if registry is not None
        else None
    )
    not_executable_scope = (
        map_operations_to_resource_scopes(not_executable_operations, registry)
        if registry is not None
        else None
    )
    resource_policy = ResourcePolicy(
        policy_id=policy_ref,
        task_id=task_id,
        allowed_operations=allowed_operations,
        denied_operations=denied_operations,
        requires_approval_operations=requires_approval_operations,
        not_executable_operations=not_executable_operations,
        allowed_tools=allowed_scope.tool_names if allowed_scope is not None else (),
        denied_tools=denied_scope.tool_names if denied_scope is not None else (),
        allowed_mcps=not_executable_scope.mcp_routes if not_executable_scope is not None else (),
        denied_mcps=denied_scope.mcp_routes if denied_scope is not None else (),
        allowed_agents=not_executable_scope.agent_ids if not_executable_scope is not None else (),
        denied_agents=denied_scope.agent_ids if denied_scope is not None else (),
        memory_read_scope="context_package",
        memory_write_scope="none",
        approval_policy=_approval_policy(task_operation, agent_runtime_profile),
        runtime_view_only=False,
        adopted=True,
        runtime_executable=True,
        decisions=tuple(decisions),
        diagnostics={
            "runtime_executable": True,
            "adopted": True,
            "tools_allowed": bool(allowed_scope.tool_names if allowed_scope is not None else ()),
            "mcps_allowed": bool(not_executable_scope.mcp_routes if not_executable_scope is not None else ()),
            "memory_write_allowed": False,
            "filesystem_write_allowed": any(
                operation in {"op.write_file", "op.edit_file"} for operation in allowed_operations
            ),
            "adoption_owner": "TaskRunLoop",
            "authorization_inputs": {
                "task_operation_requirement": True,
                "agent_runtime_profile": bool(agent_runtime_profile is not None),
                "operation_registry": bool(registry is not None),
            },
            "scope_mapping": {
                "allowed": allowed_scope.to_dict() if allowed_scope is not None else {},
                "denied": denied_scope.to_dict() if denied_scope is not None else {},
                "not_executable": not_executable_scope.to_dict() if not_executable_scope is not None else {},
            },
            "task_safety_envelope": dict(dict(task_operation.get("operation_requirement") or {}).get("metadata") or {}).get(
                "safety_envelope",
                {},
            ),
        },
    )
    directive = RuntimeDirective(
        directive_id=f"runtime-directive:{task_id}:model-response",
        task_id=task_id,
        plan_ref=str(task_body_orchestration.get("orchestration_id") or f"orchplan:{task_id}:runtime"),
        stage_ref=str(agent_runtime_spec.get("projection_snapshot_ref") or f"orchstage:{task_id}:model"),
        executor_type="model",
        adopted_resource_policy_ref=policy_ref,
        operation_refs=operation_refs,
        input_contract_ref=str(agent_runtime_spec.get("input_contract_ref") or task_execution_assembly.get("input_contract_id") or task_contract.get("input_contract_id") or ""),
        output_contract_ref=str(agent_runtime_spec.get("output_contract_ref") or task_execution_assembly.get("output_contract_id") or task_contract.get("output_contract_id") or ""),
        execution_graph_ref=f"execgraph:{task_id}:runtime",
        runtime_executable=True,
        diagnostics={
            "directive_only_executor": True,
            "adoption_owner": "TaskRunLoop",
            "task_execution_assembly_ref": str(task_execution_assembly.get("assembly_id") or ""),
            "task_body_orchestration_ref": str(task_body_orchestration.get("orchestration_id") or ""),
            "agent_runtime_spec_ref": str(agent_runtime_spec.get("runtime_spec_id") or ""),
        },
    )
    return directive, resource_policy


def _build_runtime_decisions(
    task_operation: dict[str, Any],
    *,
    registry: OperationRegistry | None,
    agent_runtime_profile: AgentRuntimeProfile | None,
    approval_context: RuntimeApprovalContext,
) -> list[ResourceDecision]:
    requested = _requested_operations(task_operation)
    agent_allowed = _agent_allowed_operations(agent_runtime_profile)
    agent_blocked = _agent_blocked_operations(agent_runtime_profile)
    approval_policy = _approval_policy(task_operation, agent_runtime_profile)
    decisions: list[ResourceDecision] = []
    for operation_id in requested:
        normalized_id = registry.normalize_id(operation_id) if registry is not None else operation_id
        descriptor = registry.get_operation(normalized_id) if registry is not None else None
        decisions.append(
            _decide_runtime_operation(
                normalized_id,
                descriptor=descriptor,
                agent_allowed=agent_allowed,
                agent_blocked=agent_blocked,
                approval_context=approval_context,
                approval_policy=approval_policy,
            )
        )
    if not any(decision.operation_id == "op.model_response" for decision in decisions):
        decisions.insert(
            0,
            ResourceDecision(
                operation_id="op.model_response",
                decision="allow",
                reason="model response is always required for the primary runtime lane",
                risk_tags=("model_response", "read_only"),
            ),
        )
    return decisions


def _requested_operations(task_operation: dict[str, Any]) -> tuple[str, ...]:
    requirement = dict(task_operation.get("operation_requirement") or {})
    requested = [
        "op.model_response",
        *list(requirement.get("required_operations") or ()),
        *list(requirement.get("optional_operations") or ()),
    ]
    denied = {str(item or "").strip() for item in list(requirement.get("denied_operations") or ()) if str(item or "").strip()}
    return tuple(item for item in _dedupe(requested) if item not in denied or item == "op.model_response")


def _agent_allowed_operations(profile: AgentRuntimeProfile | None) -> set[str]:
    if profile is None:
        return {"op.model_response"}
    allowed = {str(item or "").strip() for item in profile.allowed_operations if str(item or "").strip()}
    allowed.add("op.model_response")
    return allowed


def _agent_blocked_operations(profile: AgentRuntimeProfile | None) -> set[str]:
    if profile is None:
        return set()
    return {str(item or "").strip() for item in profile.blocked_operations if str(item or "").strip()}


def _decide_runtime_operation(
    operation_id: str,
    *,
    descriptor: OperationDescriptor | None,
    agent_allowed: set[str],
    agent_blocked: set[str],
    approval_context: RuntimeApprovalContext,
    approval_policy: str,
) -> ResourceDecision:
    if operation_id in agent_blocked:
        return ResourceDecision(
            operation_id=operation_id,
            decision="deny",
            reason="operation blocked by agent capability profile",
            risk_tags=tuple(descriptor.risk_tags) if descriptor is not None else (),
        )
    if operation_id not in agent_allowed:
        return ResourceDecision(
            operation_id=operation_id,
            decision="deny",
            reason="operation outside agent capability profile",
            risk_tags=tuple(descriptor.risk_tags) if descriptor is not None else (),
        )
    if descriptor is None:
        return ResourceDecision(
            operation_id=operation_id,
            decision="deny",
            reason="unknown operation",
            diagnostics={"fail_closed": True},
        )
    if descriptor.operation_type in {"mcp", "agent"}:
        return ResourceDecision(
            operation_id=descriptor.operation_id,
            decision="not_executable",
            reason="mcp and agent operations are not exposed to the model as direct tools",
            risk_tags=descriptor.risk_tags,
        )
    if approval_policy == "task_bounded_write" and descriptor.operation_id in {"op.write_file", "op.edit_file"}:
        return ResourceDecision(
            operation_id=descriptor.operation_id,
            decision="allow",
            reason="task-bounded workspace write allowed by explicit specific task contract",
            risk_tags=descriptor.risk_tags,
            diagnostics={"approval_policy": approval_policy},
        )
    if descriptor.requires_approval_by_default or descriptor.destructive:
        approval_available = bool(
            approval_context.approval_hook_available
            or approval_context.bubble_to_parent_allowed
            or approval_context.interactive_ui_available
        )
        if approval_context.headless_mode or not approval_available:
            return ResourceDecision(
                operation_id=descriptor.operation_id,
                decision="deny",
                reason="approval unavailable for operation",
                risk_tags=descriptor.risk_tags,
                diagnostics={"headless_mode": approval_context.headless_mode},
            )
        return ResourceDecision(
            operation_id=descriptor.operation_id,
            decision="requires_approval",
            reason="operation requires approval before execution",
            risk_tags=descriptor.risk_tags,
            requires_user_approval=True,
            approval_channel="runtime_approval",
        )
    return ResourceDecision(
        operation_id=descriptor.operation_id,
        decision="allow",
        reason="operation allowed by task requirement and agent capability profile",
        risk_tags=descriptor.risk_tags,
    )


def _approval_policy(task_operation: dict[str, Any], profile: AgentRuntimeProfile | None) -> str:
    requirement = dict(task_operation.get("operation_requirement") or {})
    metadata = dict(requirement.get("metadata") or {})
    explicit_policy = str(metadata.get("approval_policy") or "").strip()
    if explicit_policy and explicit_policy != "default":
        return explicit_policy
    if profile is not None and profile.approval_policy:
        return str(profile.approval_policy)
    return explicit_policy or "default"


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
