from __future__ import annotations

from dataclasses import dataclass

from .policies import ResourceDecision, ResourcePolicy
from .registry import OperationDescriptor, OperationRegistry
from .requirements import OperationRequirement


APPROVAL_RISK_TAGS = {
    "local_write",
    "destructive",
    "shell_execution",
    "python_execution",
    "requires_human_approval",
}
DENY_BY_DEFAULT_RISK_TAGS = {
    "memory_write_candidate",
    "session_write_candidate",
    "artifact_write_candidate",
}
PREVIEW_ONLY_TYPES = {"worker", "agent"}


@dataclass(frozen=True, slots=True)
class RuntimeApprovalContext:
    interactive_ui_available: bool = True
    approval_hook_available: bool = False
    bubble_to_parent_allowed: bool = False
    headless_mode: bool = False


def build_resource_policy_preview(
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
    preview_only = []

    for requested_id in requested:
        normalized_id = registry.normalize_id(requested_id)
        descriptor = registry.get_operation(requested_id)
        decision = _decide_operation(
            requested_id=requested_id,
            normalized_id=normalized_id,
            descriptor=descriptor,
            explicitly_denied=requested_id in denied_input or normalized_id in normalized_denied_input,
            context=context,
        )
        decisions.append(decision)
        if decision.decision == "allow":
            allowed.append(decision.operation_id)
        elif decision.decision == "requires_approval":
            requires_approval.append(decision.operation_id)
        elif decision.decision == "preview_only":
            preview_only.append(decision.operation_id)
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
    preview_tuple = tuple(_dedupe(preview_only))
    return ResourcePolicy(
        policy_id=f"respol:{requirement.task_id}:preview",
        task_id=requirement.task_id,
        allowed_operations=allowed_tuple,
        denied_operations=denied_tuple,
        requires_approval_operations=requires_tuple,
        preview_only_operations=preview_tuple,
        allowed_tools=allowed_tuple,
        denied_tools=denied_tuple,
        allowed_workers=(),
        denied_workers=tuple(op for op in denied_tuple if _operation_type(registry, op) == "worker"),
        allowed_agents=(),
        denied_agents=tuple(op for op in denied_tuple if _operation_type(registry, op) == "agent"),
        approval_policy=str(requirement.metadata.get("approval_policy") or "default"),
        preview_only=True,
        adopted=False,
        runtime_executable=False,
        decisions=tuple(decisions),
        diagnostics={
            "preview_only": True,
            "fail_closed": True,
            "resource_policy_state": "preview",
            "resource_policy_adopted": False,
            "runtime_executable": False,
            "operation_gate_required_before_execution": True,
        },
    )


def _decide_operation(
    *,
    requested_id: str,
    normalized_id: str,
    descriptor: OperationDescriptor | None,
    explicitly_denied: bool,
    context: RuntimeApprovalContext,
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
        return ResourceDecision(
            operation_id=descriptor.operation_id,
            decision="deny",
            reason="operation is denied by default in preview phase",
            risk_tags=descriptor.risk_tags,
        )
    if descriptor.operation_type in PREVIEW_ONLY_TYPES:
        return ResourceDecision(
            operation_id=descriptor.operation_id,
            decision="preview_only",
            reason="worker and agent operations are preview-only in phase 1",
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
        reason="allowed in preview policy",
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


def _operation_type(registry: OperationRegistry, operation_id: str) -> str:
    descriptor = registry.get_operation(operation_id)
    return descriptor.operation_type if descriptor else ""


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
