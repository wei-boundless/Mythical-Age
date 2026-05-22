from __future__ import annotations

import time
from typing import Any

from orchestration.runtime_directive import RuntimeDirective
from permissions import ResourceDecision, ResourcePolicy
from runtime.shared.action_request import RuntimeActionRequest


def approval_state_from_permit(permit: Any) -> str:
    return str(getattr(permit, "approval_state", "") or "").strip()


def runtime_directive_from_approval_state(approval_state: dict[str, Any]) -> RuntimeDirective:
    payload = dict(approval_state.get("directive") or {})
    operation_id = str(approval_state.get("operation_id") or "").strip()
    return RuntimeDirective(
        directive_id=str(payload.get("directive_id") or approval_state.get("directive_ref") or ""),
        task_id=str(payload.get("task_id") or approval_state.get("task_run_id") or ""),
        plan_ref=str(payload.get("plan_ref") or "orchplan:approval-resume"),
        stage_ref=str(payload.get("stage_ref") or "orchstage:approval-resume"),
        executor_type=str(payload.get("executor_type") or "tool"),  # type: ignore[arg-type]
        adopted_resource_policy_ref=str(
            payload.get("adopted_resource_policy_ref")
            or dict(approval_state.get("resource_policy") or {}).get("policy_id")
            or "respol:approval-resume"
        ),
        operation_refs=tuple(
            str(item)
            for item in list(payload.get("operation_refs") or [operation_id])
            if str(item)
        ),
        input_contract_ref=str(payload.get("input_contract_ref") or ""),
        output_contract_ref=str(payload.get("output_contract_ref") or ""),
        execution_graph_ref=str(payload.get("execution_graph_ref") or ""),
        runtime_executable=True,
        diagnostics=dict(payload.get("diagnostics") or {}),
    )


def resource_policy_from_approval_state(approval_state: dict[str, Any]) -> ResourcePolicy:
    payload = dict(approval_state.get("resource_policy") or {})
    decisions = tuple(
        ResourceDecision(
            operation_id=str(item.get("operation_id") or ""),
            decision=item.get("decision", "unknown"),
            reason=str(item.get("reason") or ""),
            risk_tags=tuple(str(tag) for tag in list(item.get("risk_tags") or [])),
            requires_user_approval=bool(item.get("requires_user_approval") is True),
            authorization_owner=str(item.get("authorization_owner") or "ResourcePolicy"),
            approval_channel=str(item.get("approval_channel") or ""),
            diagnostics=dict(item.get("diagnostics") or {}),
        )
        for item in list(payload.get("decisions") or [])
        if isinstance(item, dict)
    )
    return ResourcePolicy(
        policy_id=str(payload.get("policy_id") or "respol:approval-resume"),
        task_id=str(payload.get("task_id") or approval_state.get("task_run_id") or ""),
        allowed_operations=tuple(str(item) for item in list(payload.get("allowed_operations") or [])),
        denied_operations=tuple(str(item) for item in list(payload.get("denied_operations") or [])),
        requires_approval_operations=tuple(
            str(item) for item in list(payload.get("requires_approval_operations") or [])
        ),
        not_executable_operations=tuple(str(item) for item in list(payload.get("not_executable_operations") or [])),
        allowed_tools=tuple(str(item) for item in list(payload.get("allowed_tools") or [])),
        denied_tools=tuple(str(item) for item in list(payload.get("denied_tools") or [])),
        allowed_mcps=tuple(str(item) for item in list(payload.get("allowed_mcps") or [])),
        denied_mcps=tuple(str(item) for item in list(payload.get("denied_mcps") or [])),
        allowed_agents=tuple(str(item) for item in list(payload.get("allowed_agents") or [])),
        denied_agents=tuple(str(item) for item in list(payload.get("denied_agents") or [])),
        memory_read_scope=str(payload.get("memory_read_scope") or "none"),
        memory_write_scope=str(payload.get("memory_write_scope") or "none"),
        filesystem_scope=dict(payload.get("filesystem_scope") or {}),
        network_scope=dict(payload.get("network_scope") or {}),
        shell_scope=dict(payload.get("shell_scope") or {}),
        approval_policy=str(payload.get("approval_policy") or "runtime_tool_dispatch"),
        runtime_view_only=bool(payload.get("runtime_view_only") is True),
        adopted=bool(payload.get("adopted") is True),
        runtime_executable=bool(payload.get("runtime_executable") is True),
        decisions=decisions,
        diagnostics=dict(payload.get("diagnostics") or {}),
    )


def action_request_from_approval_state(task_run_id: str, approval_state: dict[str, Any]) -> RuntimeActionRequest:
    tool_name = str(approval_state.get("tool_name") or "").strip()
    tool_call = {
        "id": str(approval_state.get("tool_call_id") or approval_state.get("action_request_ref") or ""),
        "name": tool_name,
        "args": dict(approval_state.get("tool_args") or {}),
        "type": "tool_call",
    }
    return RuntimeActionRequest(
        request_id=str(approval_state.get("action_request_ref") or f"rtact:{task_run_id}:approval"),
        task_run_id=task_run_id,
        request_type="tool_call",
        step_id=str(approval_state.get("step_ref") or ""),
        directive_ref=str(approval_state.get("directive_ref") or ""),
        operation_id=str(approval_state.get("operation_id") or ""),
        payload={
            "tool_name": tool_name,
            "tool_call": tool_call,
            "execution_state": "approved_for_dispatch",
        },
        created_at=float(approval_state.get("created_at") or time.time()),
    )
