from __future__ import annotations

from typing import Any

from operations import OperationDescriptor, ResourceDecision, ResourcePolicy

from ..runtime_directive import RuntimeDirective
from .action_request import RuntimeActionRequest


def build_tool_request_runtime_adoption(
    *,
    action_request: RuntimeActionRequest,
    task_id: str,
    task_operation_preview: dict[str, Any],
    operation_id: str,
    operation_descriptor: OperationDescriptor | None,
) -> tuple[RuntimeDirective, ResourcePolicy]:
    """Adopt a tool request for runtime dispatch."""

    plan_preview = dict(task_operation_preview.get("orchestration_plan_preview") or {})
    stages = list(plan_preview.get("stages") or [])
    stage_preview = dict(stages[0] if stages else {})
    policy_ref = f"respol:{task_id}:tool-preflight:{action_request.request_id}"
    tool_allowed = bool(operation_descriptor is not None)
    decision = ResourceDecision(
        operation_id=operation_id,
        decision="allow" if tool_allowed else "deny",
        reason=(
            "tool request admitted for runtime dispatch"
            if tool_allowed
            else "tool request denied because operation descriptor is missing"
        ),
        risk_tags=tuple(operation_descriptor.risk_tags) if operation_descriptor is not None else ("unknown_operation",),
        requires_user_approval=bool(operation_descriptor.requires_approval_by_default)
        if operation_descriptor is not None
        else False,
    )
    resource_policy = ResourcePolicy(
        policy_id=policy_ref,
        task_id=task_id,
        allowed_operations=(operation_id,) if tool_allowed else (),
        denied_operations=() if tool_allowed else (operation_id,),
        requires_approval_operations=(),
        preview_only_operations=(),
        allowed_tools=(str(action_request.payload.get("tool_name") or ""),) if tool_allowed else (),
        denied_tools=() if tool_allowed else (str(action_request.payload.get("tool_name") or ""),),
        memory_read_scope="context_package_preview",
        memory_write_scope="none",
        approval_policy="runtime_tool_dispatch",
        preview_only=False,
        adopted=True,
        runtime_executable=True,
        decisions=(decision,),
        diagnostics={
            "runtime_executable": True,
            "adopted": True,
            "tool_preflight_only": False,
            "tool_dispatch_enabled": tool_allowed,
            "tool_allowed": tool_allowed,
            "read_only": bool(operation_descriptor.read_only) if operation_descriptor is not None else False,
            "destructive": bool(operation_descriptor.destructive) if operation_descriptor is not None else False,
            "memory_write_allowed": False,
            "filesystem_write_allowed": False,
            "adoption_owner": "TaskRunLoop",
        },
    )
    directive = RuntimeDirective(
        directive_id=f"runtime-directive:{task_id}:tool:{action_request.request_id}",
        task_id=task_id,
        plan_ref=str(plan_preview.get("plan_id") or f"orchplan:{task_id}").replace(":preview", ":runtime"),
        stage_ref=str(stage_preview.get("stage_id") or f"orchstage:{task_id}:tool").replace(":preview", ":runtime"),
        executor_type="tool",
        adopted_resource_policy_ref=policy_ref,
        operation_refs=(operation_id,),
        input_contract_ref=str(operation_descriptor.input_contract_ref) if operation_descriptor is not None else "",
        output_contract_ref=str(operation_descriptor.output_contract_ref) if operation_descriptor is not None else "",
        execution_graph_ref=str(
            task_operation_preview.get("execution_graph_preview", {}).get("graph_preview_id") or ""
        ).replace(":preview", ":runtime"),
        runtime_executable=True,
        diagnostics={
            "source_action_request_ref": action_request.request_id,
            "tool_preflight_only": False,
            "tool_dispatch_enabled": tool_allowed,
            "directive_only_executor": True,
            "adoption_owner": "TaskRunLoop",
        },
    )
    return directive, resource_policy
