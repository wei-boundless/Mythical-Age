from __future__ import annotations

from dataclasses import dataclass

from permissions.operations import OperationDescriptor, OperationRegistry
from task_system.contracts.capability_requirements import OperationRequirement

from permissions.resource_policy import ResourceDecision, ResourcePolicy
from permissions.model_visible_operations import (
    is_model_visible_agent_operation,
    is_model_visible_state_operation,
)
from permissions.resource_scope_mapping import map_operations_to_resource_scopes


APPROVAL_RISK_TAGS = {
    "local_write",
    "destructive",
    "shell_execution",
    "python_execution",
    "requires_human_approval",
}
DANGEROUS_AUTO_RISK_TAGS = {
    "local_write",
    "destructive",
    "shell_execution",
    "python_execution",
}
DENY_BY_DEFAULT_RISK_TAGS = {
    "memory_write_candidate",
    "session_write_candidate",
    "artifact_write_candidate",
}
NOT_EXECUTABLE_TYPES = {"mcp", "agent"}


@dataclass(frozen=True, slots=True)
class RuntimeApprovalContext:
    interactive_ui_available: bool = True
    approval_hook_available: bool = False
    bubble_to_parent_allowed: bool = False
    headless_mode: bool = False


def build_resource_policy_candidate(
    requirement: OperationRequirement,
    registry: OperationRegistry,
    *,
    approval_context: RuntimeApprovalContext | None = None,
) -> ResourcePolicy:
    context = approval_context or RuntimeApprovalContext()
    requested = _dedupe([*requirement.required_operations, *requirement.optional_operations])
    denied_input = set(requirement.denied_operations)
    normalized_denied_input = {registry.normalize_id(operation_id) for operation_id in denied_input}
    decisions = []
    allowed = []
    denied = []
    requires_approval = []
    not_executable = []

    for requested_id in requested:
        normalized_id = registry.normalize_id(requested_id)
        descriptor = registry.get_operation(requested_id)
        decision = _decide_operation(
            requested_id=requested_id,
            normalized_id=normalized_id,
            descriptor=descriptor,
            explicitly_denied=requested_id in denied_input or normalized_id in normalized_denied_input,
            context=context,
            approval_policy=str(requirement.metadata.get("approval_policy") or "default"),
        )
        decisions.append(decision)
        if decision.decision == "allow":
            allowed.append(decision.operation_id)
        elif decision.decision == "requires_approval":
            requires_approval.append(decision.operation_id)
        elif decision.decision == "not_executable":
            not_executable.append(decision.operation_id)
        else:
            denied.append(decision.operation_id)

    for denied_id in requirement.denied_operations:
        normalized_id = registry.normalize_id(denied_id)
        if normalized_id in {decision.operation_id for decision in decisions}:
            continue
        descriptor = registry.get_operation(denied_id)
        risk_tags = descriptor.risk_tags if descriptor else ()
        decisions.append(
            ResourceDecision(
                operation_id=normalized_id,
                decision="deny",
                reason="explicitly denied by task binding",
                risk_tags=risk_tags,
            )
        )
        denied.append(normalized_id)

    allowed_tuple = tuple(_dedupe(allowed))
    denied_tuple = tuple(_dedupe(denied))
    requires_tuple = tuple(_dedupe(requires_approval))
    not_executable_tuple = tuple(_dedupe(not_executable))
    allowed_scope = map_operations_to_resource_scopes(allowed_tuple, registry)
    denied_scope = map_operations_to_resource_scopes(denied_tuple, registry)
    not_executable_scope = map_operations_to_resource_scopes(not_executable_tuple, registry)
    return ResourcePolicy(
        policy_id=f"respol:{requirement.task_id}:candidate",
        task_id=requirement.task_id,
        allowed_operations=allowed_tuple,
        denied_operations=denied_tuple,
        requires_approval_operations=requires_tuple,
        not_executable_operations=not_executable_tuple,
        allowed_tools=allowed_scope.tool_names,
        denied_tools=denied_scope.tool_names,
        allowed_mcps=not_executable_scope.mcp_routes,
        denied_mcps=denied_scope.mcp_routes,
        allowed_agents=(),
        denied_agents=denied_scope.agent_ids,
        approval_policy=str(requirement.metadata.get("approval_policy") or "default"),
        runtime_view_only=True,
        adopted=False,
        runtime_executable=False,
        decisions=tuple(decisions),
        diagnostics={
            "fail_closed": True,
            "resource_policy_state": "candidate",
            "resource_policy_adopted": False,
            "runtime_executable": False,
            "operation_gate_required_before_execution": True,
            "scope_mapping": {
                "allowed": allowed_scope.to_dict(),
                "denied": denied_scope.to_dict(),
                "not_executable": not_executable_scope.to_dict(),
            },
        },
    )


def _decide_operation(
    *,
    requested_id: str,
    normalized_id: str,
    descriptor: OperationDescriptor | None,
    explicitly_denied: bool,
    context: RuntimeApprovalContext,
    approval_policy: str,
) -> ResourceDecision:
    if descriptor is None:
        return ResourceDecision(
            operation_id=normalized_id,
            decision="deny",
            reason="unknown operation",
            diagnostics={"requested_operation_id": requested_id},
        )
    if explicitly_denied:
        return ResourceDecision(
            operation_id=descriptor.operation_id,
            decision="deny",
            reason="explicitly denied by task binding",
            risk_tags=descriptor.risk_tags,
        )
    if set(descriptor.risk_tags) & DENY_BY_DEFAULT_RISK_TAGS:
        if is_model_visible_state_operation(descriptor.operation_id):
            return ResourceDecision(
                operation_id=descriptor.operation_id,
                decision="allow",
                reason="non-destructive task state operation is exposed as a bounded model-visible tool",
                risk_tags=descriptor.risk_tags,
            )
        return ResourceDecision(
            operation_id=descriptor.operation_id,
            decision="deny",
            reason="operation is denied by default before runtime admission",
            risk_tags=descriptor.risk_tags,
        )
    if approval_policy == "auto" and (descriptor.destructive or set(descriptor.risk_tags) & DANGEROUS_AUTO_RISK_TAGS):
        return ResourceDecision(
            operation_id=descriptor.operation_id,
            decision="deny",
            reason="dangerous allow rule stripped in auto approval policy",
            risk_tags=descriptor.risk_tags,
            diagnostics={"approval_policy": approval_policy},
        )
    if is_model_visible_agent_operation(descriptor.operation_id):
        return ResourceDecision(
            operation_id=descriptor.operation_id,
            decision="allow",
            reason="subagent operation is exposed as a bounded model-visible tool",
            risk_tags=descriptor.risk_tags,
        )
    if descriptor.operation_type in NOT_EXECUTABLE_TYPES:
        return ResourceDecision(
            operation_id=descriptor.operation_id,
            decision="not_executable",
            reason="mcp and agent operations are not exposed to the model as direct tools",
            risk_tags=descriptor.risk_tags,
        )
    if descriptor.requires_approval_by_default or descriptor.destructive or set(descriptor.risk_tags) & APPROVAL_RISK_TAGS:
        approval_channel = _approval_channel(context)
        if approval_channel == "deny":
            return ResourceDecision(
                operation_id=descriptor.operation_id,
                decision="deny",
                reason="approval unavailable in headless context",
                risk_tags=descriptor.risk_tags,
                diagnostics={"headless_mode": context.headless_mode},
            )
        return ResourceDecision(
            operation_id=descriptor.operation_id,
            decision="requires_approval",
            reason="operation requires approval before real execution",
            risk_tags=descriptor.risk_tags,
            requires_user_approval=True,
            approval_channel=approval_channel,
        )
    return ResourceDecision(
        operation_id=descriptor.operation_id,
        decision="allow",
        reason="allowed by candidate policy",
        risk_tags=descriptor.risk_tags,
    )


def _approval_channel(context: RuntimeApprovalContext) -> str:
    if context.interactive_ui_available and not context.headless_mode:
        return "interactive"
    if context.approval_hook_available:
        return "hook"
    if context.bubble_to_parent_allowed:
        return "parent"
    return "deny"


def _dedupe(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


