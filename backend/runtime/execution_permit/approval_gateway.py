from __future__ import annotations

import time
from typing import Any

from permissions import OperationGatePipelineContext
from orchestration.runtime_directive import RuntimeDirective
from permissions import ResourceDecision, ResourcePolicy
from runtime.execution_engine.tool_loop import execute_prepared_tool_call
from runtime.execution_engine.event_translation import append_executor_observation_event
from runtime.shared.action_request import RuntimeActionRequest, build_tool_result_observation
from runtime.shared.safety import build_task_safety_validators


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


def summarize_tool_args(tool_args: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key, value in dict(tool_args or {}).items():
        if isinstance(value, str):
            summary[key] = value if len(value) <= 220 else f"{value[:220]}..."
        elif isinstance(value, (int, float, bool)) or value is None:
            summary[key] = value
        elif isinstance(value, (list, tuple, set)):
            summary[key] = {
                "type": "array",
                "count": len(list(value)),
            }
        elif isinstance(value, dict):
            summary[key] = {
                "type": "object",
                "keys": sorted(str(item) for item in value.keys())[:20],
            }
        else:
            summary[key] = type(value).__name__
    return summary


def build_pending_approval_state(
    *,
    task_run_id: str,
    action_request: RuntimeActionRequest,
    directive: RuntimeDirective,
    resource_policy: ResourcePolicy,
    gate_result: Any,
    descriptor: Any,
    sandbox_policy: dict[str, Any] | None,
    file_management_policy: dict[str, Any] | None = None,
    step_ref: str = "",
    approval_risk_fingerprint: str = "",
) -> dict[str, Any]:
    tool_call = dict(action_request.payload.get("tool_call") or {})
    tool_args = dict(tool_call.get("args") or {})
    risk_tags = tuple(getattr(descriptor, "risk_tags", ()) or ())
    return {
        "status": "pending",
        "task_run_id": task_run_id,
        "operation_id": str(gate_result.operation_id or ""),
        "directive_ref": directive.directive_id,
        "action_request_ref": action_request.request_id,
        "tool_name": str(action_request.payload.get("tool_name") or ""),
        "tool_call_id": str(tool_call.get("id") or action_request.request_id),
        "tool_args": tool_args,
        "tool_args_summary": summarize_tool_args(tool_args),
        "risk_tags": list(risk_tags),
        "requires_user_interaction": bool(getattr(descriptor, "requires_user_interaction", False)),
        "gate": gate_result.to_dict(),
        "directive": directive.to_dict(),
        "resource_policy": resource_policy.to_dict(),
        "sandbox_policy": dict(sandbox_policy or {}),
        "file_management_policy": dict(file_management_policy or {}),
        "step_ref": step_ref,
        "created_at": time.time(),
        "approval_risk_fingerprint": str(approval_risk_fingerprint or ""),
        "resume_contract": {
            "operation_id": str(gate_result.operation_id or ""),
            "directive_ref": directive.directive_id,
            "action_request_ref": action_request.request_id,
            "risk_fingerprint": str(approval_risk_fingerprint or ""),
            "token_binding": "operation_id+directive_ref+risk_fingerprint",
        },
    }


def append_approval_rejection_observation(
    *,
    event_log: Any,
    runtime_context_manager: Any,
    task_run_id: str,
    approval_state: dict[str, Any],
    directive_ref: str,
    reason: str,
    resolution: dict[str, Any],
) -> list[Any]:
    observation = build_tool_result_observation(
        task_run_id=task_run_id,
        request_ref=str(approval_state.get("action_request_ref") or ""),
        directive_ref=directive_ref,
        tool_name=str(approval_state.get("tool_name") or ""),
        tool_call_id=str(approval_state.get("tool_call_id") or approval_state.get("action_request_ref") or ""),
        tool_args=dict(approval_state.get("tool_args") or {}),
        result=reason,
    )
    context_record = runtime_context_manager.record_observation(observation)
    refs = {
        "action_request_ref": str(approval_state.get("action_request_ref") or ""),
        "directive_ref": directive_ref,
    }
    tool_event = event_log.append(
        task_run_id,
        "tool_result_received",
        payload={
            "observation": observation.to_dict(),
            "context_record": context_record.to_dict(),
            "approval_resolution": dict(resolution or {}),
        },
        refs={
            **refs,
            "observation_ref": observation.observation_id,
        },
    )
    observation_event = append_executor_observation_event(
        event_log=event_log,
        task_run_id=task_run_id,
        observation=observation,
        context_record=context_record,
        refs=refs,
    )
    return [tool_event, observation_event]


async def execute_approved_tool_from_state(
    *,
    event_log: Any,
    runtime_context_manager: Any,
    task_run_id: str,
    approval_state: dict[str, Any],
    approval_token: Any,
    tool_runtime_executor: Any | None,
    operation_gate: Any,
    permission_mode: str,
    root_dir: Any,
    execution_store: Any,
    record_execution_event: Any,
) -> dict[str, Any]:
    if tool_runtime_executor is None:
        return {
            "executed": False,
            "reason": "tool runtime executor unavailable",
            "result_refs": [],
        }
    operation_id = operation_gate.registry.normalize_id(str(approval_state.get("operation_id") or ""))
    descriptor = operation_gate.registry.get_operation(operation_id)
    action_request = action_request_from_approval_state(task_run_id, approval_state)
    directive = runtime_directive_from_approval_state(approval_state)
    resource_policy = resource_policy_from_approval_state(approval_state)
    gate_result = operation_gate.check(
        operation_id,
        resource_policy=resource_policy,
        directive_ref=directive.directive_id,
        context=OperationGatePipelineContext(
            permission_mode=permission_mode,
            approval_token=approval_token,
            approval_risk_fingerprint=str(
                approval_state.get("approval_risk_fingerprint")
                or dict(approval_state.get("resume_contract") or {}).get("risk_fingerprint")
                or ""
            ),
            operation_input={
                "operation_id": operation_id,
                **dict(action_request.payload.get("tool_call") or {}),
            },
            validators=build_task_safety_validators(
                root_dir=root_dir,
                safety_envelope={},
                sandbox_policy=dict(approval_state.get("sandbox_policy") or {}),
            ),
        ),
    )
    gate_event = event_log.append(
        task_run_id,
        "operation_gate_checked",
        payload={
            "gate": gate_result.to_dict(),
            "approval_resume": True,
            "dispatch_enabled": bool(gate_result.allowed),
        },
        refs={
            "operation_id": gate_result.operation_id,
            "directive_ref": directive.directive_id,
            "action_request_ref": action_request.request_id,
            "approval_token_ref": approval_token.token_id,
        },
    )
    if not gate_result.allowed:
        return {
            "executed": False,
            "reason": gate_result.reason,
            "gate": gate_result.to_dict(),
            "events": [gate_event.to_dict()],
            "result_refs": [],
        }
    approved_file_management_policy = {
        **dict(approval_state.get("file_management_policy") or {}),
        "approval_fingerprint": str(approval_token.risk_fingerprint or approval_token.token_id or ""),
        "approval_token": {
            "token_id": str(approval_token.token_id or ""),
            "operation_id": str(approval_token.operation_id or ""),
            "directive_ref": str(approval_token.directive_ref or ""),
            "granted": bool(approval_token.granted),
            "risk_fingerprint": str(approval_token.risk_fingerprint or ""),
            "source": str(approval_token.source or ""),
        },
    }
    execution_events, execution_decision = await execute_prepared_tool_call(
        event_log=event_log,
        runtime_context_manager=runtime_context_manager,
        task_run_id=task_run_id,
        action_request=action_request,
        directive=directive,
        operation_id=operation_id,
        descriptor=descriptor,
        tool_name=str(approval_state.get("tool_name") or ""),
        step_id=str(approval_state.get("step_ref") or ""),
        execution_store=execution_store,
        tool_runtime_executor=tool_runtime_executor,
        gate_result=gate_result,
        sandbox_policy=dict(approval_state.get("sandbox_policy") or {}),
        file_management_policy=approved_file_management_policy,
        record_execution_event=record_execution_event,
        dispatch_reason="tool_dispatch_started_after_approval",
        result_record_reason="tool_execution_finished_after_approval",
    )
    events = [gate_event, *execution_events]
    if execution_decision in {"reuse_completed_result", "deny_auto_replay"}:
        return {
            "executed": False,
            "reason": execution_decision,
            "events": [event.to_dict() for event in events],
            "result_refs": [],
        }
    result_refs = [
        str(dict(dict(event.to_dict()).get("refs") or {}).get("observation_ref") or "")
        for event in events
        if str(getattr(event, "event_type", "") or "") == "executor_observation_received"
        and str(dict(dict(event.to_dict()).get("refs") or {}).get("observation_ref") or "")
    ]
    return {
        "executed": bool(result_refs and execution_decision != "deny_auto_replay"),
        "reason": execution_decision if execution_decision != "dispatch" else "approved tool executed",
        "gate": gate_result.to_dict(),
        "events": [event.to_dict() for event in events],
        "result_refs": result_refs,
    }
