from __future__ import annotations

from typing import Any

from capability_system import OperationDescriptor
from permissions.resource_policy import ResourceDecision, ResourcePolicy

from orchestration.runtime_directive import RuntimeDirective
from runtime.shared.action_request import RuntimeActionRequest


def build_tool_request_runtime_admission(
    *,
    action_request: RuntimeActionRequest,
    task_id: str,
    task_operation: dict[str, Any],
    operation_id: str,
    operation_descriptor: OperationDescriptor | None,
    adopted_resource_policy: ResourcePolicy | None,
) -> tuple[RuntimeDirective, ResourcePolicy]:
    """Admit a tool request for supervised runtime dispatch."""

    policy_ref = f"respol:{task_id}:tool-preflight:{action_request.request_id}"
    decision_kind, reason = _tool_request_decision(
        operation_id=operation_id,
        operation_descriptor=operation_descriptor,
        adopted_resource_policy=adopted_resource_policy,
    )
    tool_allowed = decision_kind == "allow"
    requires_approval = decision_kind == "requires_approval"
    decision = ResourceDecision(
        operation_id=operation_id,
        decision=decision_kind,
        reason=reason,
        risk_tags=tuple(operation_descriptor.risk_tags) if operation_descriptor is not None else ("unknown_operation",),
        requires_user_approval=bool(operation_descriptor.requires_approval_by_default)
        if operation_descriptor is not None
        else False,
    )
    resource_policy = ResourcePolicy(
        policy_id=policy_ref,
        task_id=task_id,
        allowed_operations=(operation_id,) if tool_allowed else (),
        denied_operations=() if tool_allowed or requires_approval else (operation_id,),
        requires_approval_operations=(operation_id,) if requires_approval else (),
        not_executable_operations=(),
        allowed_tools=(str(action_request.payload.get("tool_name") or ""),) if tool_allowed else (),
        denied_tools=() if tool_allowed or requires_approval else (str(action_request.payload.get("tool_name") or ""),),
        memory_read_scope="context_package",
        memory_write_scope="none",
        approval_policy="runtime_tool_dispatch",
        runtime_view_only=False,
        adopted=True,
        runtime_executable=True,
        decisions=(decision,),
        diagnostics={
            "runtime_executable": True,
            "adopted": True,
            "tool_preflight_only": False,
            "tool_dispatch_enabled": tool_allowed,
            "tool_allowed": tool_allowed,
            "tool_requires_approval": requires_approval,
            "read_only": bool(operation_descriptor.read_only) if operation_descriptor is not None else False,
            "destructive": bool(operation_descriptor.destructive) if operation_descriptor is not None else False,
            "memory_write_allowed": False,
            "filesystem_write_allowed": bool(operation_id in {"op.write_file", "op.edit_file"} and tool_allowed),
            "admission_owner": "TaskRunLoop",
            "task_safety_envelope": dict(
                dict(task_operation.get("operation_requirement") or {}).get("metadata") or {}
            ).get("safety_envelope", {}),
        },
    )
    directive = RuntimeDirective(
        directive_id=f"runtime-directive:{task_id}:tool:{action_request.request_id}",
        task_id=task_id,
        plan_ref=f"orchplan:{task_id}:runtime",
        stage_ref=f"orchstage:{task_id}:tool",
        executor_type="tool",
        adopted_resource_policy_ref=policy_ref,
        operation_refs=(operation_id,),
        input_contract_ref=str(operation_descriptor.input_contract_ref) if operation_descriptor is not None else "",
        output_contract_ref=str(operation_descriptor.output_contract_ref) if operation_descriptor is not None else "",
        execution_graph_ref=f"execgraph:{task_id}:runtime",
        runtime_executable=True,
        diagnostics={
            "source_action_request_ref": action_request.request_id,
            "tool_preflight_only": False,
            "tool_dispatch_enabled": tool_allowed,
            "tool_requires_approval": requires_approval,
            "directive_only_executor": True,
            "admission_owner": "TaskRunLoop",
        },
    )
    return directive, resource_policy


def _tool_request_decision(
    *,
    operation_id: str,
    operation_descriptor: OperationDescriptor | None,
    adopted_resource_policy: ResourcePolicy | None,
) -> tuple[str, str]:
    if operation_descriptor is None:
        return "deny", "tool request denied because operation descriptor is missing"
    if adopted_resource_policy is None:
        return "deny", "tool request denied because adopted resource policy is missing"
    if (
        adopted_resource_policy.runtime_view_only
        or not adopted_resource_policy.adopted
        or not adopted_resource_policy.runtime_executable
    ):
        return "deny", "tool request denied because resource policy is not executable"
    if operation_id in adopted_resource_policy.denied_operations:
        return "deny", "tool request denied by adopted resource policy"
    if operation_id in adopted_resource_policy.requires_approval_operations:
        return "requires_approval", "tool request requires approval by adopted resource policy"
    if operation_id in adopted_resource_policy.allowed_operations:
        return "allow", "tool request admitted by adopted resource policy"
    return "deny", "tool request is not allowed by adopted resource policy"
