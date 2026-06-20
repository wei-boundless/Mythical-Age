from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from dataclasses import dataclass, replace
from typing import Any

from artifact_system.artifact_authority import artifact_refs_from_tool_result_payload
from file_management import build_file_access_table, resolve_file_environment
from permissions.operations import build_default_operation_registry
from orchestration.runtime_directive import RuntimeDirective
from permissions import ApprovalState, ApprovalToken, PermissionContext, ResourceDecision, ResourcePolicy
from harness.loop.action_permit import validate_tool_invocation_permit
from runtime.shared.action_request import RuntimeActionRequest
from runtime.shared.execution_record import (
    build_idempotency_token,
    build_request_fingerprint,
    derive_replay_policy,
)
from runtime.shared.models import AgentRun
from runtime.shared.safety import build_task_safety_validators
from runtime.memory.tool_memory_events import commit_tool_memory_events_from_envelope
from runtime.tool_runtime.tool_invocation_request import ToolInvocationRequest
from runtime.tool_runtime.tool_observation import ToolObservation
from runtime.tool_runtime.tool_result_envelope import build_tool_result_envelope
from runtime.tooling import ToolSupervisor

_AGENT_TURN_SANDBOX_AUTO_ALLOW_OPERATIONS = {
    "op.write_file",
    "op.edit_file",
    "op.shell",
    "op.python_repl",
    "op.browser_control",
    "op.image_generate",
}
_EXPLICIT_HUMAN_APPROVAL_POLICIES = {
    "manual_approval_required",
    "requires_human_approval",
    "human_approval_required",
    "runtime_approval_required",
    "always_ask",
}
_DENY_DESTRUCTIVE_APPROVAL_POLICIES = {"deny_destructive"}
_FILE_WRITE_OPERATION_ACTIONS = {
    "op.write_file": "write",
    "op.edit_file": "edit",
}
_SUBAGENT_OPERATION_BY_TOOL_NAME = {
    "spawn_subagent": "op.subagent_spawn",
    "send_subagent_message": "op.subagent_message",
    "wait_subagent": "op.subagent_wait",
    "list_subagents": "op.subagent_list",
    "close_subagent": "op.subagent_close",
}


@dataclass(frozen=True, slots=True)
class ToolDispatchHandler:
    handler_id: str
    caller_kinds: tuple[str, ...]
    tool_names: tuple[str, ...] = ()
    operation_prefixes: tuple[str, ...] = ()
    operation_ids: tuple[str, ...] = ()
    default_for_caller: bool = False

    def matches(self, request: ToolInvocationRequest) -> bool:
        caller_kind = str(request.caller_kind or "").strip()
        if caller_kind not in set(self.caller_kinds):
            return False
        tool_name = str(request.tool_name or "").strip()
        if self.tool_names and tool_name in set(self.tool_names):
            return True
        operation_id = _request_operation_id(request)
        if self.operation_ids and operation_id in set(self.operation_ids):
            return True
        if self.operation_prefixes and any(operation_id.startswith(prefix) for prefix in self.operation_prefixes):
            return True
        return self.default_for_caller


@dataclass(frozen=True, slots=True)
class ToolDispatchHandlerRegistry:
    handlers: tuple[ToolDispatchHandler, ...]

    def handler_for(self, request: ToolInvocationRequest) -> ToolDispatchHandler | None:
        for handler in self.handlers:
            if handler.matches(request):
                return handler
        return None


_DEFAULT_TOOL_HANDLER_REGISTRY = ToolDispatchHandlerRegistry(
    handlers=(
        ToolDispatchHandler(
            handler_id="subagent_control",
            caller_kinds=("task_run", "agent_turn"),
            tool_names=tuple(sorted(_SUBAGENT_OPERATION_BY_TOOL_NAME)),
            operation_prefixes=("op.subagent_",),
        ),
        ToolDispatchHandler(
            handler_id="task_tool_runtime",
            caller_kinds=("task_run",),
            default_for_caller=True,
        ),
        ToolDispatchHandler(
            handler_id="agent_turn_core",
            caller_kinds=("agent_turn",),
            default_for_caller=True,
        ),
    )
)


def _tool_handler_registry() -> ToolDispatchHandlerRegistry:
    return _DEFAULT_TOOL_HANDLER_REGISTRY


@dataclass(slots=True)
class RuntimeToolControlPlane:
    """Runtime/session-level tool admission and observation boundary."""

    tool_runtime_executor: Any | None = None
    tool_supervisor: Any | None = None
    operation_gate: Any | None = None

    async def invoke(self, request: ToolInvocationRequest, *, tool_plan: Any) -> ToolObservation:
        permit_denial = _action_permit_denial(request)
        if permit_denial:
            _publish_tool_permission_decided(
                request,
                tool_plan=tool_plan,
                decision="denied",
                allowed=False,
                stage="action_permit",
                reason=permit_denial,
            )
            return _observation(
                request,
                status="denied",
                text=permit_denial,
                diagnostics={"stage": "action_permit", "reason": permit_denial},
            )
        denial = _membership_denial(request, tool_plan=tool_plan)
        if denial:
            _publish_tool_permission_decided(
                request,
                tool_plan=tool_plan,
                decision="denied",
                allowed=False,
                stage="capability_membership",
                reason=denial,
            )
            return _observation(
                request,
                status="denied",
                text=denial,
                diagnostics={
                    "stage": "capability_membership",
                    "tool_plan_ref": tool_plan.plan_id,
                    "dispatchable_tool_names": list(tool_plan.dispatchable_tool_names),
                },
            )
        if request.caller_kind != "task_run":
            handler = _tool_handler_registry().handler_for(request)
            if handler is None:
                return _observation(
                    request,
                    status="error",
                    text="caller tool dispatch is not connected for this caller",
                    diagnostics={
                        "stage": "caller_dispatch_not_connected",
                        "caller_kind": request.caller_kind,
                        "tool_plan_ref": tool_plan.plan_id,
                    },
                )
            if handler.handler_id != "agent_turn_core":
                return _observation(
                    request,
                    status="error",
                    text="caller tool dispatch handler is not valid for this caller",
                    diagnostics={
                        "stage": "caller_dispatch_handler_mismatch",
                        "handler_id": handler.handler_id,
                        "caller_kind": request.caller_kind,
                        "tool_plan_ref": tool_plan.plan_id,
                    },
                )
            return await self._invoke_agent_turn_or_fail_closed(request, tool_plan=tool_plan)
        handler = _tool_handler_registry().handler_for(request)
        if handler is None:
            return _observation(
                request,
                status="error",
                text="caller tool dispatch is not connected for this caller",
                diagnostics={
                    "stage": "caller_dispatch_not_connected",
                    "caller_kind": request.caller_kind,
                    "tool_plan_ref": tool_plan.plan_id,
                },
            )
        directive, runtime_action, sandbox_policy, file_policy, resource_policy = _execution_contracts(request, tool_plan=tool_plan)
        execution_record = None
        execution_store = _execution_store(request)
        if execution_store is not None:
            execution_record = _create_execution_record(
                request,
                runtime_action=runtime_action,
                directive=directive,
                execution_store=execution_store,
                diagnostics={
                    "execution_context": _execution_context(request),
                    "runtime_tool_plan": _tool_plan_ref(tool_plan),
                },
            )
        supervisor = self.tool_supervisor or ToolSupervisor()
        operation_gate = self.operation_gate or _operation_gate(request)
        if operation_gate is None:
            _publish_tool_permission_decided(
                request,
                tool_plan=tool_plan,
                decision="denied",
                allowed=False,
                stage="operation_gate_unavailable",
                reason="runtime tool control plane has no OperationGate",
            )
            return _observation(
                request,
                status="denied",
                text="runtime tool control plane has no OperationGate",
                diagnostics={"stage": "operation_gate_unavailable", "tool_plan_ref": tool_plan.plan_id},
            )
        operation_id = _request_operation_id(request)
        supervision = supervisor.supervise(
            task_run_id=request.task_run_id,
            agent_run_id=request.agent_run_id,
            tool_call_id=request.tool_call_id,
            operation_id=operation_id,
            tool_name=request.tool_name,
            tool_args=dict(request.tool_args or {}),
            directive=directive,
            resource_policy=resource_policy,
            capability_table=tool_plan.capability_table,
            permission_context=PermissionContext(
                context_id=f"permctx:{request.invocation_id}",
                task_run_id=request.task_run_id,
                agent_run_id=request.agent_run_id,
                environment_id=str(dict(_runtime_assembly(request).get("task_environment") or {}).get("environment_id") or ""),
                tool_capability_table_id=str(getattr(tool_plan.capability_table, "table_id", "") or ""),
                permission_mode=str(request.permission_mode or "default"),
                sandbox_policy=dict(sandbox_policy),
                file_management_policy=dict(file_policy),
                metadata={
                    "caller_kind": request.caller_kind,
                    "caller_ref": request.caller_ref,
                    "tool_plan_ref": getattr(tool_plan, "plan_id", ""),
                },
            ),
            operation_gate=operation_gate,
            tool_runtime_executor=self.tool_runtime_executor,
            action_request=runtime_action,
            approval_token=_approval_token_for_supervision(request),
            approval_state=_approval_state_for_supervision(request),
            approval_risk_fingerprint=str(request.approval_risk_fingerprint or "") or None,
            sandbox_policy=sandbox_policy,
            file_management_policy=file_policy,
            safety_validators=_safety_validators(request, sandbox_policy=sandbox_policy),
        )
        _publish_tool_permission_decided(
            request,
            tool_plan=tool_plan,
            decision="allow" if supervision.allowed else ("needs_approval" if supervision.requires_approval else "denied"),
            allowed=bool(supervision.allowed),
            stage="tool_supervisor",
            reason=supervision.decision.reason or supervision.decision.behavior,
            operation_gate=supervision.gate_result.to_dict() if hasattr(supervision.gate_result, "to_dict") else {},
            supervision=supervision.to_dict(),
        )
        if not supervision.allowed:
            if execution_record is not None and execution_store is not None:
                execution_record = execution_store.mark_failed(
                    execution_record,
                    error=supervision.decision.reason or supervision.decision.behavior,
                    diagnostics={"tool_supervision": supervision.to_dict()},
                )
            return _observation(
                request,
                status="needs_approval" if supervision.requires_approval else "denied",
                text=supervision.decision.reason or supervision.decision.behavior,
                operation_gate=supervision.gate_result.to_dict() if hasattr(supervision.gate_result, "to_dict") else {},
                execution_receipt=_execution_receipt(execution_record, error=supervision.decision.reason),
                diagnostics={
                    "stage": "tool_supervisor",
                    "tool_plan_ref": tool_plan.plan_id,
                    "supervision": supervision.to_dict(),
                },
            )
        normalized_args = dict(supervision.normalized_args or request.tool_args or {})
        runtime_action = _runtime_action_with_args(runtime_action, tool_name=request.tool_name, tool_call_id=request.tool_call_id, tool_args=normalized_args)
        if handler.handler_id == "subagent_control":
            _publish_tool_execution_started(
                request,
                tool_plan=tool_plan,
                handler_id=handler.handler_id,
                directive_ref=str(getattr(directive, "directive_id", "") or ""),
                operation_gate=supervision.gate_result.to_dict() if hasattr(supervision.gate_result, "to_dict") else {},
                execution_receipt=_execution_receipt(execution_record),
            )
            observation = await _invoke_subagent_control(
                request,
                directive=directive,
                normalized_args=normalized_args,
                operation_gate=supervision.gate_result.to_dict() if hasattr(supervision.gate_result, "to_dict") else {},
                execution_record=execution_record,
            )
            _publish_tool_execution_completed(
                request,
                tool_plan=tool_plan,
                handler_id=handler.handler_id,
                observation=observation,
            )
            return observation
        if self.tool_runtime_executor is None:
            return _observation(
                request,
                status="error",
                text="tool_runtime_executor_unavailable",
                operation_gate=supervision.gate_result.to_dict() if hasattr(supervision.gate_result, "to_dict") else {},
                execution_receipt=_execution_receipt(execution_record, error="tool_runtime_executor_unavailable"),
                diagnostics={"stage": "tool_runtime_executor_unavailable", "tool_plan_ref": tool_plan.plan_id},
            )
        tool_runtime = getattr(self.tool_runtime_executor, "tool_runtime", None)
        runtime_host = _runtime_host(request)
        if tool_runtime is not None and getattr(tool_runtime, "runtime_host", None) is None and runtime_host is not None:
            setattr(tool_runtime, "runtime_host", runtime_host)
        dispatch = getattr(self.tool_runtime_executor, "execute_control_plane_request", None)
        if not callable(dispatch):
            return _observation(
                request,
                status="error",
                text="tool_runtime_executor_dispatch_unavailable",
                operation_gate=supervision.gate_result.to_dict() if hasattr(supervision.gate_result, "to_dict") else {},
                execution_receipt=_execution_receipt(execution_record, error="tool_runtime_executor_dispatch_unavailable"),
                diagnostics={
                    "stage": "tool_runtime_executor_dispatch_unavailable",
                    "handler_id": handler.handler_id,
                    "tool_plan_ref": tool_plan.plan_id,
                },
            )
        _publish_tool_execution_started(
            request,
            tool_plan=tool_plan,
            handler_id=handler.handler_id,
            directive_ref=str(getattr(directive, "directive_id", "") or ""),
            operation_gate=supervision.gate_result.to_dict() if hasattr(supervision.gate_result, "to_dict") else {},
            execution_receipt=_execution_receipt(execution_record),
        )
        result = await dispatch(
            request=request,
            runtime_action=runtime_action,
            directive=directive,
            execution_record=execution_record,
            execution_store=execution_store,
            sandbox_policy=sandbox_policy,
            file_management_policy=file_policy,
            normalized_args=normalized_args,
        )
        observation = _observation_from_executor_result(
            request,
            result=result,
            operation_gate=supervision.gate_result.to_dict() if hasattr(supervision.gate_result, "to_dict") else {},
            diagnostics={
                "stage": "tool_runtime_executor",
                "handler_id": handler.handler_id,
                "tool_plan_ref": tool_plan.plan_id,
                "supervision": supervision.to_dict(),
            },
        )
        _publish_tool_execution_completed(
            request,
            tool_plan=tool_plan,
            handler_id=handler.handler_id,
            observation=observation,
        )
        if _should_consume_approval_grant(observation):
            _consume_approval_grant_if_present(
                request,
                directive_ref=str(getattr(directive, "directive_id", "") or ""),
                approval_risk_fingerprint=str(supervision.decision.approval_fingerprint or request.approval_risk_fingerprint or ""),
            )
        return observation

    async def _invoke_agent_turn_or_fail_closed(self, request: ToolInvocationRequest, *, tool_plan: Any) -> ToolObservation:
        if request.caller_kind != "agent_turn":
            return _observation(
                request,
                status="error",
                text="caller tool dispatch is not connected for this caller",
                diagnostics={
                    "stage": "caller_dispatch_not_connected",
                    "caller_kind": request.caller_kind,
                    "tool_plan_ref": tool_plan.plan_id,
                },
            )
        definition = _definition(request)
        if definition is None:
            _publish_tool_permission_decided(
                request,
                tool_plan=tool_plan,
                decision="denied",
                allowed=False,
                stage="tool_definition_unavailable",
                reason="tool definition is unavailable",
            )
            return _observation(
                request,
                status="denied",
                text="tool definition is unavailable",
                diagnostics={"stage": "tool_definition_unavailable", "tool_plan_ref": tool_plan.plan_id},
            )
        directive, sandbox_policy, file_policy, resource_policy = _agent_turn_execution_contracts(request, tool_plan=tool_plan, definition=definition)
        supervisor = self.tool_supervisor or ToolSupervisor()
        operation_gate = self.operation_gate or _operation_gate(request)
        if operation_gate is None:
            _publish_tool_permission_decided(
                request,
                tool_plan=tool_plan,
                decision="denied",
                allowed=False,
                stage="operation_gate_unavailable",
                reason="runtime tool control plane has no OperationGate",
            )
            return _observation(
                request,
                status="denied",
                text="runtime tool control plane has no OperationGate",
                diagnostics={"stage": "operation_gate_unavailable", "tool_plan_ref": tool_plan.plan_id},
            )
        operation_id = _request_operation_id(request)
        supervision = supervisor.supervise(
            task_run_id="",
            agent_run_id=request.agent_run_id,
            tool_call_id=request.tool_call_id,
            operation_id=operation_id,
            tool_name=request.tool_name,
            tool_args=dict(request.tool_args or {}),
            directive=directive,
            resource_policy=resource_policy,
            capability_table=tool_plan.capability_table,
            permission_context=PermissionContext(
                context_id=f"permctx:{request.invocation_id}",
                task_run_id="",
                agent_run_id=request.agent_run_id,
                environment_id=str(dict(_runtime_assembly(request).get("task_environment") or {}).get("environment_id") or ""),
                tool_capability_table_id=str(getattr(tool_plan.capability_table, "table_id", "") or ""),
                permission_mode=str(request.permission_mode or "default"),
                sandbox_policy=dict(sandbox_policy),
                file_management_policy=dict(file_policy),
                metadata={
                    "caller_kind": request.caller_kind,
                    "caller_ref": request.caller_ref,
                    "tool_plan_ref": getattr(tool_plan, "plan_id", ""),
                },
            ),
            operation_gate=operation_gate,
            tool_runtime_executor=None,
            action_request=None,
            approval_token=_approval_token_for_supervision(request),
            approval_state=_approval_state_for_supervision(request),
            approval_risk_fingerprint=str(request.approval_risk_fingerprint or "") or None,
            sandbox_policy=sandbox_policy,
            file_management_policy=file_policy,
            safety_validators=_safety_validators(request, sandbox_policy=sandbox_policy),
        )
        _publish_tool_permission_decided(
            request,
            tool_plan=tool_plan,
            decision="allow" if supervision.allowed else ("needs_approval" if supervision.requires_approval else "denied"),
            allowed=bool(supervision.allowed),
            stage="tool_supervisor",
            reason=supervision.decision.reason or supervision.decision.behavior,
            operation_gate=supervision.gate_result.to_dict() if hasattr(supervision.gate_result, "to_dict") else {},
            supervision=supervision.to_dict(),
        )
        if not supervision.allowed:
            return _observation(
                request,
                status="needs_approval" if supervision.requires_approval else "denied",
                text=supervision.decision.reason or supervision.decision.behavior,
                operation_gate=supervision.gate_result.to_dict() if hasattr(supervision.gate_result, "to_dict") else {},
                diagnostics={
                    "stage": "tool_supervisor",
                    "tool_plan_ref": tool_plan.plan_id,
                    "supervision": supervision.to_dict(),
                },
            )
        if self.tool_runtime_executor is None or not hasattr(self.tool_runtime_executor, "execute_control_plane_request"):
            return _observation(
                request,
                status="error",
                text="tool_runtime_executor_dispatch_unavailable",
                operation_gate=supervision.gate_result.to_dict() if hasattr(supervision.gate_result, "to_dict") else {},
                diagnostics={
                    "stage": "tool_runtime_executor_dispatch_unavailable",
                    "handler_id": "agent_turn_core",
                    "tool_plan_ref": tool_plan.plan_id,
                },
            )
        runtime_host = _runtime_host(request)
        tool_runtime = getattr(self.tool_runtime_executor, "tool_runtime", None)
        if tool_runtime is not None and getattr(tool_runtime, "runtime_host", None) is None and runtime_host is not None:
            setattr(tool_runtime, "runtime_host", runtime_host)
        _publish_tool_execution_started(
            request,
            tool_plan=tool_plan,
            handler_id="agent_turn_core",
            directive_ref=str(getattr(directive, "directive_id", "") or ""),
            operation_gate=supervision.gate_result.to_dict() if hasattr(supervision.gate_result, "to_dict") else {},
        )
        result = await self.tool_runtime_executor.execute_control_plane_request(
            request=request,
            sandbox_policy=sandbox_policy,
            file_management_policy=file_policy,
            normalized_args=dict(supervision.normalized_args or request.tool_args or {}),
        )
        observation = _observation_from_core_result(
            request,
            result=result,
            operation_gate=supervision.gate_result.to_dict() if hasattr(supervision.gate_result, "to_dict") else {},
            diagnostics={
                "stage": "tool_runtime_executor_dispatch",
                "handler_id": "agent_turn_core",
                "tool_plan_ref": tool_plan.plan_id,
                "supervision": supervision.to_dict(),
            },
        )
        observation = _with_tool_memory_commit_diagnostics(request, observation)
        _publish_tool_execution_completed(
            request,
            tool_plan=tool_plan,
            handler_id="agent_turn_core",
            observation=observation,
        )
        if _should_consume_approval_grant(observation):
            _consume_approval_grant_if_present(
                request,
                directive_ref=str(getattr(directive, "directive_id", "") or ""),
                approval_risk_fingerprint=str(supervision.decision.approval_fingerprint or request.approval_risk_fingerprint or ""),
            )
        return observation


def _membership_denial(request: ToolInvocationRequest, *, tool_plan: Any) -> str:
    table = tool_plan.capability_table
    if table is None:
        return "runtime tool plan has no ToolCapabilityTable"
    operation_id = _request_operation_id(request)
    tool_name = str(request.tool_name or "").strip()
    capability = table.capability_for_tool(operation_id=operation_id, tool_name=tool_name)
    if capability is None:
        if table.capability_for_operation(operation_id) is None:
            return "operation not present in RuntimeToolPlan"
        return "tool not present for operation in RuntimeToolPlan"
    if not capability.dispatchable:
        return "tool is not dispatchable in RuntimeToolPlan"
    return ""


def _action_permit_denial(request: ToolInvocationRequest) -> str:
    return validate_tool_invocation_permit(
        action_permit=dict(request.action_permit or {}),
        action_request_ref=request.action_request_ref,
        invocation_kind="task_execution" if request.caller_kind == "task_run" else str(request.caller_kind or ""),
        tool_name=request.tool_name,
        operation_id=_request_operation_id(request),
        session_id=request.session_id,
        turn_id=request.turn_id,
        task_run_id=request.task_run_id,
        approval_risk_fingerprint=request.approval_risk_fingerprint,
        now=time.time(),
    )


def _request_operation_id(request: ToolInvocationRequest) -> str:
    return _canonical_operation_id(
        tool_name=str(request.tool_name or "").strip(),
        operation_id=str(request.operation_id or "").strip(),
    )


def _publish_tool_permission_decided(
    request: ToolInvocationRequest,
    *,
    tool_plan: Any,
    decision: str,
    allowed: bool,
    stage: str,
    reason: str = "",
    operation_gate: dict[str, Any] | None = None,
    supervision: dict[str, Any] | None = None,
) -> None:
    payload = _tool_lifecycle_base_payload(request, tool_plan=tool_plan)
    payload.update(
        {
            "lifecycle_phase": "permission_decided",
            "decision": str(decision or "").strip(),
            "allowed": bool(allowed),
            "stage": str(stage or "").strip(),
            "reason": str(reason or "").strip(),
            "operation_gate": dict(operation_gate or {}),
            "supervision": dict(supervision or {}),
        }
    )
    _publish_tool_lifecycle_signal(
        request,
        signal_type="tool.permission.decided",
        signal_id=f"toolperm:{request.invocation_id}",
        payload=payload,
    )


def _publish_tool_execution_started(
    request: ToolInvocationRequest,
    *,
    tool_plan: Any,
    handler_id: str,
    directive_ref: str = "",
    operation_gate: dict[str, Any] | None = None,
    execution_receipt: dict[str, Any] | None = None,
) -> None:
    payload = _tool_lifecycle_base_payload(request, tool_plan=tool_plan)
    payload.update(
        {
            "lifecycle_phase": "execution_started",
            "handler_id": str(handler_id or "").strip(),
            "directive_ref": str(directive_ref or "").strip(),
            "operation_gate": dict(operation_gate or {}),
            "execution_receipt": dict(execution_receipt or {}),
        }
    )
    _publish_tool_lifecycle_signal(
        request,
        signal_type="tool.execution.started",
        signal_id=f"toolexec:{request.invocation_id}:started",
        payload=payload,
    )


def _publish_tool_execution_completed(
    request: ToolInvocationRequest,
    *,
    tool_plan: Any,
    handler_id: str,
    observation: ToolObservation,
) -> None:
    payload = _tool_lifecycle_base_payload(request, tool_plan=tool_plan)
    payload.update(
        {
            "lifecycle_phase": "execution_completed",
            "handler_id": str(handler_id or "").strip(),
            "status": str(getattr(observation, "status", "") or ""),
            "observation_ref": str(getattr(observation, "observation_id", "") or ""),
            "result_ref": str(getattr(observation, "result_ref", "") or ""),
            "execution_receipt": dict(getattr(observation, "execution_receipt", {}) or {}),
            "artifact_refs": [dict(item) for item in tuple(getattr(observation, "artifact_refs", ()) or ())],
        }
    )
    _publish_tool_lifecycle_signal(
        request,
        signal_type="tool.execution.completed",
        signal_id=f"toolexec:{request.invocation_id}:completed",
        payload=payload,
        refs={
            "observation_ref": str(getattr(observation, "observation_id", "") or ""),
            "result_ref": str(getattr(observation, "result_ref", "") or ""),
        },
    )


def _tool_lifecycle_base_payload(request: ToolInvocationRequest, *, tool_plan: Any) -> dict[str, Any]:
    return {
        "event_family": "tool_lifecycle",
        "tool_invocation_id": str(request.invocation_id or ""),
        "tool_call_id": str(request.tool_call_id or ""),
        "tool_name": str(request.tool_name or ""),
        "operation_id": _request_operation_id(request),
        "action_request_ref": str(request.action_request_ref or ""),
        "packet_ref": str(request.packet_ref or ""),
        "admission_ref": str(request.admission_ref or ""),
        "tool_plan_ref": str(request.tool_plan_ref or getattr(tool_plan, "plan_id", "") or ""),
        "caller_kind": str(request.caller_kind or ""),
        "caller_ref": str(request.caller_ref or ""),
        "task_run_id": str(request.task_run_id or ""),
        "agent_run_id": str(request.agent_run_id or ""),
        "run_cell_id": str(request.run_cell_id or ""),
        "session_id": str(request.session_id or ""),
        "turn_id": str(request.turn_id or ""),
        "permission_mode": str(request.permission_mode or ""),
        "authority": "runtime.tool_runtime.tool_control_plane",
    }


def _publish_tool_lifecycle_signal(
    request: ToolInvocationRequest,
    *,
    signal_type: str,
    signal_id: str,
    payload: dict[str, Any],
    refs: dict[str, Any] | None = None,
) -> None:
    runtime_host = _runtime_host(request)
    control_bus = getattr(runtime_host, "control_bus", None) if runtime_host is not None else None
    publish = getattr(control_bus, "publish", None)
    if not callable(publish):
        return
    normalized_signal_id = str(signal_id or "").strip()
    run_id = _tool_lifecycle_run_id(request)
    if not run_id or not normalized_signal_id:
        return
    try:
        from harness.runtime.control_events import RuntimeSignalScope
    except Exception:
        return
    scope = RuntimeSignalScope(
        session_id=str(request.session_id or ""),
        agent_run_id=str(request.agent_run_id or ""),
        run_cell_id=str(request.run_cell_id or ""),
        turn_id=str(request.turn_id or ""),
        turn_run_id=str(request.caller_ref or "") if request.caller_kind == "agent_turn" else "",
        task_run_id=str(request.task_run_id or ""),
    )
    publish(
        run_id,
        signal_type=str(signal_type or "").strip(),
        signal_id=normalized_signal_id,
        scope=scope,
        source_authority="runtime.tool_runtime.tool_control_plane",
        payload=dict(payload or {}),
        causation_id=str(request.action_request_ref or request.tool_call_id or ""),
        correlation_id=str(request.invocation_id or ""),
        refs={
            "tool_invocation_ref": str(request.invocation_id or ""),
            "tool_call_ref": str(request.tool_call_id or ""),
            "action_request_ref": str(request.action_request_ref or ""),
            "task_run_ref": str(request.task_run_id or ""),
            "agent_run_ref": str(request.agent_run_id or ""),
            "run_cell_ref": str(request.run_cell_id or ""),
            "tool_plan_ref": str(request.tool_plan_ref or dict(payload or {}).get("tool_plan_ref") or ""),
            **dict(refs or {}),
        },
    )


def _tool_lifecycle_run_id(request: ToolInvocationRequest) -> str:
    if request.task_run_id:
        return str(request.task_run_id)
    if request.caller_ref:
        return str(request.caller_ref)
    if request.turn_id:
        return str(request.turn_id)
    if request.session_id:
        return str(request.session_id)
    return "runtime"


def _canonical_operation_id(*, tool_name: str, operation_id: str) -> str:
    reserved_operation_id = _SUBAGENT_OPERATION_BY_TOOL_NAME.get(str(tool_name or "").strip())
    if reserved_operation_id:
        return reserved_operation_id
    return str(operation_id or "").strip()


def _observation(
    request: ToolInvocationRequest,
    *,
    status: str,
    text: str,
    diagnostics: dict[str, Any] | None = None,
    result_ref: str = "",
    result_envelope: dict[str, Any] | None = None,
    operation_gate: dict[str, Any] | None = None,
    execution_receipt: dict[str, Any] | None = None,
    artifact_refs: tuple[dict[str, Any], ...] = (),
) -> ToolObservation:
    receipt = {
        **dict(execution_receipt or {}),
        "agent_run_id": str(request.agent_run_id or ""),
        "run_cell_id": str(request.run_cell_id or ""),
        "task_run_id": str(request.task_run_id or ""),
        "caller_kind": str(request.caller_kind or ""),
        "caller_ref": str(request.caller_ref or ""),
        "tool_invocation_id": str(request.invocation_id or ""),
    }
    envelope = dict(result_envelope or {})
    if not envelope:
        envelope = build_tool_result_envelope(
            tool_name=request.tool_name,
            tool_args=dict(request.tool_args or {}),
            result={"ok": status == "ok", "error": "" if status == "ok" else str(text or status), "text": str(text or "")},
            status=status,
            execution_receipt=receipt,
            result_ref=str(result_ref or ""),
            tool_call_id=request.tool_call_id,
            action_request_id=request.action_request_ref,
            caller_kind=request.caller_kind,
            caller_ref=request.caller_ref,
            diagnostics=dict(diagnostics or {}),
        ).to_dict()
    elif isinstance(envelope.get("execution_receipt"), dict):
        envelope["execution_receipt"] = {**dict(envelope.get("execution_receipt") or {}), **receipt}
    else:
        envelope["execution_receipt"] = receipt
    return ToolObservation(
        observation_id=f"toolobs:{request.invocation_id}:{uuid.uuid4().hex[:8]}",
        invocation_id=request.invocation_id,
        caller_kind=request.caller_kind,
        caller_ref=request.caller_ref,
        tool_name=request.tool_name,
        operation_id=_request_operation_id(request),
        status=status,  # type: ignore[arg-type]
        text=text,
        result_ref=str(result_ref or envelope.get("result_ref") or ""),
        result_envelope=envelope,
        operation_gate=dict(operation_gate or {}),
        execution_receipt=receipt,
        artifact_refs=tuple(dict(item) for item in tuple(artifact_refs or ())),
        diagnostics=dict(diagnostics or {}),
    )


def _with_tool_memory_commit_diagnostics(request: ToolInvocationRequest, observation: ToolObservation) -> ToolObservation:
    envelope = dict(observation.result_envelope or {})
    commit = commit_tool_memory_events_from_envelope(
        envelope=envelope,
        file_evidence_scope=request.file_evidence_scope,
        observation_ref=observation.observation_id,
        tool_call_id=request.tool_call_id,
        source_tool_name=request.tool_name,
        runtime_host=_runtime_host(request),
        task_run_id=request.task_run_id,
        session_id=request.session_id,
        caller_kind=request.caller_kind,
        authority="runtime.tool_runtime.tool_control_plane.tool_memory_commit",
    )
    if not commit:
        return observation
    return replace(
        observation,
        diagnostics={
            **dict(observation.diagnostics or {}),
            "tool_memory_commit": commit,
            "file_state_commit": dict(commit.get("file_state_commit") or commit or {}),
        },
    )


def _execution_contracts(request: ToolInvocationRequest, *, tool_plan: Any) -> tuple[Any, Any, dict[str, Any], dict[str, Any], Any]:
    definition = _definition(request)
    operation_id = _canonical_operation_id(
        tool_name=request.tool_name,
        operation_id=str(request.operation_id or getattr(definition, "operation_id", "") or request.tool_name),
    )
    directive = RuntimeDirective(
        directive_id=str(_requested_constraints(request).get("directive_ref") or f"runtime-directive:{request.caller_ref}:tool:{request.action_request_ref or request.tool_call_id}"),
        task_id=str(_caller_resource_scope(request).get("task_id") or request.caller_ref or request.turn_id),
        plan_ref=str(_caller_resource_scope(request).get("plan_ref") or f"runtime-plan:{request.caller_ref}"),
        stage_ref=str(_caller_resource_scope(request).get("stage_ref") or f"runtime-stage:{request.caller_ref}:tool"),
        executor_type="tool",
        adopted_resource_policy_ref=str(_caller_resource_scope(request).get("resource_policy_ref") or f"respol:{request.caller_ref}:tool:{request.action_request_ref or request.tool_call_id}"),
        operation_refs=(operation_id,),
        input_contract_ref=str(getattr(definition, "input_contract_ref", "") or ""),
        output_contract_ref=str(getattr(definition, "output_contract_ref", "") or ""),
        execution_graph_ref=str(_caller_resource_scope(request).get("execution_graph_ref") or ""),
        diagnostics={
            "packet_ref": request.packet_ref,
            "tool_plan_ref": request.tool_plan_ref or getattr(tool_plan, "plan_id", ""),
            "caller_kind": request.caller_kind,
            "authority": "runtime.tool_runtime.tool_control_plane",
        },
    )
    runtime_action = RuntimeActionRequest(
        request_id=request.action_request_ref or request.tool_call_id,
        task_run_id=request.task_run_id,
        request_type="tool_call",
        step_id=str(_caller_resource_scope(request).get("step_id") or f"tool-step:{request.action_request_ref or request.tool_call_id}"),
        directive_ref=directive.directive_id,
        operation_id=operation_id,
        payload={"tool_name": request.tool_name, "tool_call": {"id": request.tool_call_id, "name": request.tool_name, "args": dict(request.tool_args or {})}},
        created_at=time.time(),
    )
    sandbox_policy = {
        **dict(request.sandbox_scope or {}),
        "session_id": request.session_id,
        "turn_id": request.turn_id,
        "agent_run_id": request.agent_run_id,
        "permission_mode": request.permission_mode,
    }
    file_policy = dict(request.file_scope or {})
    requires_approval = _operation_requires_approval(
        operation_id,
        request=request,
        tool_plan=tool_plan,
        sandbox_policy=sandbox_policy,
    )
    resource_policy = ResourcePolicy(
        policy_id=directive.adopted_resource_policy_ref,
        task_id=str(_caller_resource_scope(request).get("task_id") or request.caller_ref or request.turn_id),
        allowed_operations=() if requires_approval else (operation_id,),
        requires_approval_operations=(operation_id,) if requires_approval else (),
        allowed_tools=(request.tool_name,),
        approval_policy=str(sandbox_policy.get("approval_policy") or "runtime_tool_control_plane"),
        runtime_view_only=False,
        adopted=True,
        runtime_executable=True,
        decisions=(
            ResourceDecision(
                operation_id=operation_id,
                decision="requires_approval" if requires_approval else "allow",
                reason="operation requires approval by runtime tool capability policy" if requires_approval else "operation allowed by task runtime contract",
                risk_tags=tuple(getattr(_operation_descriptor(operation_id), "risk_tags", ()) or ()),
                requires_user_approval=requires_approval,
                approval_channel="runtime_approval" if requires_approval else "",
                diagnostics={
                    "caller_kind": request.caller_kind,
                    "tool_plan_ref": getattr(tool_plan, "plan_id", ""),
                    "sandbox_policy": _public_policy(sandbox_policy),
                },
            ),
        ),
        diagnostics={
            "authority": "runtime.tool_runtime.tool_control_plane",
            "caller_kind": request.caller_kind,
            "sandbox_policy": _public_policy(sandbox_policy),
            "task_run_resource_decision": "requires_approval" if requires_approval else "allow",
        },
    )
    return directive, runtime_action, sandbox_policy, file_policy, resource_policy


@dataclass(frozen=True, slots=True)
class _ToolPermissionDirective:
    directive_id: str
    operation_refs: tuple[str, ...]


def _agent_turn_execution_contracts(request: ToolInvocationRequest, *, tool_plan: Any, definition: Any) -> tuple[Any, dict[str, Any], dict[str, Any], Any]:
    operation_id = _canonical_operation_id(
        tool_name=request.tool_name,
        operation_id=str(request.operation_id or getattr(definition, "operation_id", "") or request.tool_name),
    )
    directive = _ToolPermissionDirective(
        directive_id=str(_requested_constraints(request).get("directive_ref") or f"tool-permit:{request.caller_ref}:{request.tool_call_id}"),
        operation_refs=(operation_id,),
    )
    sandbox_policy = {
        **dict(request.sandbox_scope or {}),
        "session_id": request.session_id,
        "turn_id": request.turn_id,
        "agent_run_id": request.agent_run_id,
        "permission_mode": request.permission_mode,
        "workspace_root": str(_workspace_root(request)),
    }
    file_policy = dict(request.file_scope or {})
    registry = build_default_operation_registry()
    descriptor = registry.get_operation(operation_id)
    decision_kind, decision_reason = _agent_turn_resource_decision(
        operation_id,
        definition=definition,
        descriptor=descriptor,
        permission_mode=str(request.permission_mode or "default"),
        sandbox_policy=sandbox_policy,
    )
    allowed_operations = (operation_id,) if decision_kind == "allow" else ()
    requires_approval_operations = (operation_id,) if decision_kind == "requires_approval" else ()
    denied_operations = (operation_id,) if decision_kind == "deny" else ()
    resource_policy = ResourcePolicy(
        policy_id=str(_caller_resource_scope(request).get("resource_policy_ref") or f"respol:{request.caller_ref}:tool:{request.tool_call_id}"),
        task_id=request.caller_ref or request.turn_id,
        allowed_operations=allowed_operations,
        denied_operations=denied_operations,
        requires_approval_operations=requires_approval_operations,
        allowed_tools=(request.tool_name,),
        denied_tools=(request.tool_name,) if denied_operations else (),
        approval_policy=str(sandbox_policy.get("approval_policy") or "runtime_tool_control_plane"),
        runtime_view_only=False,
        adopted=True,
        runtime_executable=True,
        decisions=(
            ResourceDecision(
                operation_id=operation_id,
                decision=decision_kind,
                reason=decision_reason,
                risk_tags=tuple(getattr(descriptor, "risk_tags", ()) or ()),
                requires_user_approval=decision_kind == "requires_approval",
                approval_channel="runtime_approval" if decision_kind == "requires_approval" else "",
                diagnostics={
                    "caller_kind": request.caller_kind,
                    "permission_mode": str(request.permission_mode or "default"),
                    "sandbox_policy": _public_policy(sandbox_policy),
                },
            ),
        ),
        diagnostics={
            "authority": "runtime.tool_runtime.tool_control_plane",
            "caller_kind": request.caller_kind,
            "tool_plan_ref": getattr(tool_plan, "plan_id", ""),
            "sandbox_policy": _public_policy(sandbox_policy),
            "agent_turn_resource_decision": decision_kind,
            "agent_turn_resource_reason": decision_reason,
        },
    )
    return directive, sandbox_policy, file_policy, resource_policy


def _agent_turn_resource_decision(
    operation_id: str,
    *,
    definition: Any,
    descriptor: Any | None,
    permission_mode: str,
    sandbox_policy: dict[str, Any],
) -> tuple[str, str]:
    mode = str(permission_mode or "default").strip().lower()
    read_only = bool(getattr(definition, "is_read_only", False)) or bool(getattr(descriptor, "read_only", False))
    if read_only:
        return "allow", "read-only operation allowed in visible RuntimeToolPlan"
    if mode in {"full_access", "bypass"}:
        return "allow", f"operation allowed by permission mode {mode}"
    if _agent_turn_sandbox_allows_side_effect(operation_id, descriptor=descriptor, sandbox_policy=sandbox_policy):
        return "allow", "operation allowed inside task environment sandbox boundary"
    approval_policy = str(sandbox_policy.get("approval_policy") or sandbox_policy.get("runtime_approval_policy") or "").strip().lower()
    if approval_policy in _EXPLICIT_HUMAN_APPROVAL_POLICIES:
        return "deny", "single agent turn side-effect approval requires a resumable task approval flow"
    if descriptor is not None and approval_policy in _DENY_DESTRUCTIVE_APPROVAL_POLICIES and bool(getattr(descriptor, "destructive", False)):
        return "deny", "destructive operation denied by explicit approval policy"
    return "allow", "operation allowed by visible RuntimeToolPlan and action permit"


def _agent_turn_sandbox_allows_side_effect(operation_id: str, *, descriptor: Any | None, sandbox_policy: dict[str, Any]) -> bool:
    policy = dict(sandbox_policy or {})
    if policy.get("enabled") is not True:
        return False
    if not str(policy.get("sandbox_root") or "").strip():
        return False
    side_effect_policy = str(policy.get("side_effect_policy") or policy.get("approval_policy") or "").strip()
    if side_effect_policy not in {"sandbox_boundary", "sandboxed_side_effects"}:
        return False
    operations = {
        str(item or "").strip()
        for item in list(policy.get("side_effect_operations") or [])
        if str(item or "").strip()
    }
    operation = str(operation_id or "").strip()
    if operations and operation not in operations:
        return False
    if operation not in _AGENT_TURN_SANDBOX_AUTO_ALLOW_OPERATIONS:
        return False
    if descriptor is not None and bool(getattr(descriptor, "read_only", False)):
        return True
    return bool(operation)


def _create_execution_record(
    request: ToolInvocationRequest,
    *,
    runtime_action: RuntimeActionRequest,
    directive: RuntimeDirective,
    execution_store: Any,
    diagnostics: dict[str, Any],
) -> Any:
    registry = build_default_operation_registry()
    operation_id = str(runtime_action.operation_id or _request_operation_id(request))
    descriptor = registry.get_operation(operation_id)
    fingerprint = build_request_fingerprint(
        step_id=runtime_action.step_id,
        operation_id=operation_id,
        payload=runtime_action.payload,
    )
    return execution_store.create_record(
        task_run_id=request.task_run_id,
        step_id=runtime_action.step_id,
        action_request=runtime_action,
        directive_ref=directive.directive_id,
        operation_id=operation_id,
        executor_type="tool",
        replay_policy=derive_replay_policy(descriptor),
        request_fingerprint=fingerprint,
        idempotency_token=build_idempotency_token(
            task_run_id=request.task_run_id,
            step_id=runtime_action.step_id,
            operation_id=operation_id,
            request_fingerprint=fingerprint,
        ),
        diagnostics=diagnostics,
    )


def _runtime_action_with_args(
    runtime_action: RuntimeActionRequest,
    *,
    tool_name: str,
    tool_call_id: str,
    tool_args: dict[str, Any],
) -> RuntimeActionRequest:
    from dataclasses import replace

    return replace(
        runtime_action,
        payload={"tool_name": tool_name, "tool_call": {"id": tool_call_id, "name": tool_name, "args": dict(tool_args or {})}},
    )


async def _invoke_subagent_control(
    request: ToolInvocationRequest,
    *,
    directive: RuntimeDirective,
    normalized_args: dict[str, Any],
    operation_gate: dict[str, Any],
    execution_record: Any | None,
) -> ToolObservation:
    from harness.agent_control.controller import SubagentControl

    runtime_host = _runtime_host(request)
    services = _services(request)
    task_run = _task_run(request)
    if runtime_host is None or task_run is None:
        return _observation(request, status="error", text="subagent_control_runtime_unavailable", operation_gate=operation_gate)
    parent = _parent_agent_run(request) or _ensure_parent_agent_run(runtime_host, task_run=task_run)
    payload = await SubagentControl(runtime_host, services=services).execute_tool(
        tool_name=request.tool_name,
        tool_args=dict(normalized_args or {}),
        task_run=task_run,
        parent_agent_run=parent,
        runtime_assembly=_runtime_assembly(request),
    )
    ok = bool(dict(payload or {}).get("ok") is True)
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    artifact_refs = _artifact_refs_from_subagent_payload(payload)
    envelope = build_tool_result_envelope(
        tool_name=request.tool_name,
        tool_args=dict(normalized_args or {}),
        result={
            "text": text,
            "structured_payload": {
                "subagent_control": dict(payload or {}),
                "artifact_refs": list(artifact_refs),
            },
        },
        execution_receipt=_execution_receipt(execution_record),
        tool_call_id=request.tool_call_id,
        action_request_id=request.action_request_ref,
        caller_kind=request.caller_kind,
        caller_ref=request.caller_ref,
    )
    return _observation(
        request,
        status="ok" if ok else "error",
        text=text,
        operation_gate=operation_gate,
        execution_receipt=_execution_receipt(execution_record),
        result_envelope=envelope.to_dict(),
        artifact_refs=tuple(artifact_refs),
        diagnostics={"stage": "subagent_control_handler", "handler_id": "subagent_control", "payload": dict(payload or {})},
    )


def _observation_from_executor_result(
    request: ToolInvocationRequest,
    *,
    result: dict[str, Any],
    operation_gate: dict[str, Any],
    diagnostics: dict[str, Any],
) -> ToolObservation:
    observation = dict(result.get("observation").to_dict() if hasattr(result.get("observation"), "to_dict") else result.get("observation") or {})
    payload = dict(observation.get("payload") or {})
    envelope = dict(payload.get("result_envelope") or {})
    artifact_refs = artifact_refs_from_tool_result_payload(payload)
    text = str(payload.get("result") or payload.get("error") or result.get("error") or result.get("recoverable_error") or "")
    status = "error" if result.get("error") or result.get("recoverable_error") or observation.get("error") else "ok"
    return _observation(
        request,
        status=status,
        text=text,
        result_ref=str(payload.get("result_ref") or envelope.get("result_ref") or ""),
        result_envelope=envelope,
        operation_gate=operation_gate,
        execution_receipt=dict(payload.get("execution_receipt") or envelope.get("execution_receipt") or {}),
        artifact_refs=tuple(artifact_refs),
        diagnostics={
            **dict(diagnostics or {}),
            "executor_observation": observation,
            **({"error": str(result.get("error") or result.get("recoverable_error") or observation.get("error") or "")} if status != "ok" else {}),
        },
    )


def _observation_from_core_result(
    request: ToolInvocationRequest,
    *,
    result: dict[str, Any],
    operation_gate: dict[str, Any],
    diagnostics: dict[str, Any],
) -> ToolObservation:
    envelope = dict(result.get("result_envelope") or {})
    artifact_refs = artifact_refs_from_tool_result_payload(result)
    status = "error" if result.get("error") or result.get("recoverable_error") or str(result.get("status") or "") == "error" else "ok"
    text = str(result.get("text") or envelope.get("text") or result.get("error") or result.get("recoverable_error") or "")
    return _observation(
        request,
        status=status,
        text=text,
        result_ref=str(result.get("result_ref") or envelope.get("result_ref") or ""),
        result_envelope=envelope,
        operation_gate=operation_gate,
        execution_receipt=dict(envelope.get("execution_receipt") or {}),
        artifact_refs=tuple(artifact_refs),
        diagnostics={
            **dict(diagnostics or {}),
            "core_result": {key: value for key, value in dict(result or {}).items() if key not in {"result_envelope"}},
            **({"error": str(result.get("error") or result.get("recoverable_error") or "")} if status != "ok" else {}),
        },
    )


def _execution_receipt(record: Any | None, *, error: str = "") -> dict[str, Any]:
    if record is None:
        return {}
    return {
        "execution_id": str(getattr(record, "execution_id", "") or ""),
        "request_ref": str(getattr(record, "request_ref", "") or ""),
        "status": str(getattr(record, "status", "") or ""),
        "replay_decision": str(getattr(record, "replay_policy", "") or ""),
        "result_ref": str(getattr(record, "result_ref", "") or ""),
        "error": str(error or ""),
        "authority": "orchestration.execution_receipt",
    }


def _approval_state_from_request(request: ToolInvocationRequest) -> ApprovalState | None:
    payload = dict(request.approval_state or {})
    tokens: list[ApprovalToken] = []
    for item in list(payload.get("tokens") or []):
        if not isinstance(item, dict):
            continue
        token = _approval_token_from_payload(item)
        if token is not None:
            tokens.append(token)
    return ApprovalState(tokens=tuple(tokens)) if tokens else None


def _approval_state_for_supervision(request: ToolInvocationRequest) -> ApprovalState | None:
    authoritative = _approval_state_from_current_task_run(request)
    if authoritative is not None:
        return authoritative
    return _approval_state_from_request(request)


def _approval_token_for_supervision(request: ToolInvocationRequest) -> ApprovalToken | None:
    if _approval_state_from_current_task_run(request) is not None:
        return None
    return _approval_token_from_request(request)


def _approval_state_from_current_task_run(request: ToolInvocationRequest) -> ApprovalState | None:
    if str(request.caller_kind or "") != "task_run" or not str(request.task_run_id or "").strip():
        return None
    runtime_host = _runtime_host(request)
    state_index = getattr(runtime_host, "state_index", None) if runtime_host is not None else None
    get_task_run = getattr(state_index, "get_task_run", None)
    if not callable(get_task_run):
        return None
    task_run = get_task_run(request.task_run_id)
    if task_run is None:
        return None
    try:
        from harness.loop.task_tool_approval import approval_state_for_task_run
    except Exception:
        return None
    return approval_state_for_task_run(task_run)


def _approval_token_from_request(request: ToolInvocationRequest) -> ApprovalToken | None:
    return _approval_token_from_payload(dict(request.approval_token or {}))


def _approval_token_from_payload(payload: dict[str, Any]) -> ApprovalToken | None:
    if not payload:
        return None
    token_id = str(payload.get("token_id") or "").strip()
    operation_id = str(payload.get("operation_id") or "").strip()
    directive_ref = str(payload.get("directive_ref") or "").strip()
    if not (token_id and operation_id and directive_ref):
        return None
    return ApprovalToken(
        token_id=token_id,
        operation_id=operation_id,
        directive_ref=directive_ref,
        granted=bool(payload.get("granted") is True),
        source=str(payload.get("source") or ""),
        risk_fingerprint=str(payload.get("risk_fingerprint") or ""),
    )


def _operation_requires_approval(operation_id: str, *, request: ToolInvocationRequest, tool_plan: Any, sandbox_policy: dict[str, Any]) -> bool:
    approval_policy = str(
        sandbox_policy.get("approval_policy")
        or sandbox_policy.get("runtime_approval_policy")
        or ""
    ).strip().lower()
    if approval_policy in _EXPLICIT_HUMAN_APPROVAL_POLICIES:
        return True
    capability_table = getattr(tool_plan, "capability_table", None)
    capability = capability_table.capability_for_operation(operation_id) if capability_table is not None else None
    if capability is not None and bool(getattr(capability, "requires_approval", False)):
        if str(request.permission_mode or "").strip().lower() in {"full_access", "bypass"}:
            return False
        if _task_run_sandbox_authorizes_default_approval_operation(operation_id, descriptor=_operation_descriptor(operation_id), sandbox_policy=sandbox_policy):
            return False
        if _file_write_scope_authorizes_without_approval(operation_id, request=request, sandbox_policy=sandbox_policy):
            return False
        return True
    descriptor = _operation_descriptor(operation_id)
    if descriptor is None or not bool(getattr(descriptor, "requires_approval_by_default", False)):
        return False
    if str(request.permission_mode or "").strip().lower() in {"full_access", "bypass"}:
        return False
    if _task_run_sandbox_authorizes_default_approval_operation(operation_id, descriptor=descriptor, sandbox_policy=sandbox_policy):
        return False
    if _file_write_scope_authorizes_without_approval(operation_id, request=request, sandbox_policy=sandbox_policy):
        return False
    return True


def _file_write_scope_authorizes_without_approval(
    operation_id: str,
    *,
    request: ToolInvocationRequest,
    sandbox_policy: dict[str, Any],
) -> bool:
    action = _FILE_WRITE_OPERATION_ACTIONS.get(str(operation_id or "").strip())
    if not action:
        return False
    file_policy = dict(request.file_scope or {})
    if file_policy.get("enabled") is False:
        return False
    profile_id = str(file_policy.get("profile_id") or "").strip()
    if not profile_id:
        return False
    repository_id = _file_scope_repository_for_action(file_policy, action)
    if not repository_id:
        return False
    try:
        environment = resolve_file_environment(
            profile_id,
            repository_requirements=dict(file_policy.get("repository_requirements") or {}),
        )
    except Exception:
        return False
    repository = environment.repository(repository_id)
    if repository is None:
        return False
    if repository.repository_kind == "sandbox_workspace" and not _sandbox_has_concrete_boundary(sandbox_policy):
        return False
    table = build_file_access_table(
        environment,
        task_file_requirements=dict(file_policy.get("task_file_requirements") or {}),
        agent_allowed_actions=tuple(
            str(item)
            for item in list(file_policy.get("agent_allowed_file_actions") or [])
            if str(item).strip()
        ),
        table_id=str(file_policy.get("file_access_table_id") or ""),
    )
    grants = table.grants_for(repository_id=repository_id, action=action)
    return any(grant.behavior == "allow" and not grant.requires_approval for grant in grants)


def _file_scope_repository_for_action(file_policy: dict[str, Any], action: str) -> str:
    repositories = dict(file_policy.get("repositories") or {})
    explicit = str(repositories.get(action) or "").strip()
    if explicit:
        return explicit
    return str(file_policy.get("default_repository_id") or "").strip()


def _sandbox_has_concrete_boundary(sandbox_policy: dict[str, Any]) -> bool:
    policy = dict(sandbox_policy or {})
    if policy.get("enabled") is not True:
        return False
    return bool(str(policy.get("sandbox_root") or "").strip())


def _task_run_sandbox_authorizes_default_approval_operation(operation_id: str, *, descriptor: Any, sandbox_policy: dict[str, Any]) -> bool:
    if bool(getattr(descriptor, "read_only", False)):
        return True
    policy = dict(sandbox_policy or {})
    if policy.get("enabled") is not True:
        return False
    if not str(policy.get("sandbox_root") or "").strip():
        return False
    side_effect_policy = str(policy.get("side_effect_policy") or policy.get("approval_policy") or "").strip()
    if side_effect_policy not in {"sandbox_boundary", "sandboxed_side_effects"}:
        return False
    operations = {
        str(item or "").strip()
        for item in list(policy.get("side_effect_operations") or [])
        if str(item or "").strip()
    }
    operation = str(operation_id or "").strip()
    return bool(operation and (not operations or operation in operations))


def _operation_descriptor(operation_id: str) -> Any | None:
    return build_default_operation_registry().get_operation(str(operation_id or "").strip())


def _consume_approval_grant_if_present(
    request: ToolInvocationRequest,
    *,
    directive_ref: str,
    approval_risk_fingerprint: str,
) -> None:
    runtime_host = _runtime_host(request)
    if runtime_host is None or not request.task_run_id:
        return
    try:
        from harness.loop.task_tool_approval import (
            consume_matching_task_tool_approval,
            publish_task_tool_approval_consumed,
            task_tool_approval_grants,
        )
    except Exception:
        return
    state_index = getattr(runtime_host, "state_index", None)
    if state_index is None or not hasattr(state_index, "get_task_run"):
        return
    task_run = state_index.get_task_run(request.task_run_id)
    if task_run is None:
        return
    updated_diagnostics = consume_matching_task_tool_approval(
        task_run,
        operation_id=_request_operation_id(request),
        directive_ref=directive_ref,
        approval_risk_fingerprint=approval_risk_fingerprint,
    )
    if updated_diagnostics == dict(getattr(task_run, "diagnostics", {}) or {}):
        return
    from dataclasses import replace

    if not hasattr(state_index, "upsert_task_run"):
        return
    updated_task = replace(
        task_run,
        updated_at=time.time(),
        diagnostics=updated_diagnostics,
    )
    state_index.upsert_task_run(updated_task)
    approval_state = dict(updated_diagnostics.get("approval_state") or {}) if isinstance(updated_diagnostics.get("approval_state"), dict) else {}
    consumed_grant_id = str(approval_state.get("latest_consumed_grant_id") or "")
    consumed_grant = None
    for grant in task_tool_approval_grants(updated_task):
        if consumed_grant_id and grant.grant_id != consumed_grant_id:
            continue
        if grant.consumed and grant.operation_id == _request_operation_id(request) and grant.directive_ref == directive_ref:
            consumed_grant = grant
            break
    if consumed_grant is not None:
        publish_task_tool_approval_consumed(
            runtime_host,
            task_run=updated_task,
            grant=consumed_grant,
            directive_ref=directive_ref,
            approval_risk_fingerprint=approval_risk_fingerprint,
        )


def _should_consume_approval_grant(observation: ToolObservation) -> bool:
    return str(getattr(observation, "status", "") or "") not in {"denied", "needs_approval"}


def _safety_validators(request: ToolInvocationRequest, *, sandbox_policy: dict[str, Any]) -> dict[str, Any]:
    backend_dir = _backend_dir(request)
    if backend_dir is None:
        return {}
    return build_task_safety_validators(
        root_dir=backend_dir,
        safety_envelope={},
        sandbox_policy=sandbox_policy,
    )


def _artifact_refs_from_subagent_payload(payload: Any) -> list[dict[str, Any]]:
    result = dict(dict(payload or {}).get("result") or {})
    return artifact_refs_from_tool_result_payload(result)


def _parent_agent_run(request: ToolInvocationRequest) -> Any | None:
    runtime_host = _runtime_host(request)
    if runtime_host is None or not request.agent_run_id:
        return None
    for item in runtime_host.state_index.list_task_agent_runs(request.task_run_id):
        if str(getattr(item, "agent_run_id", "") or "") == request.agent_run_id:
            return item
    return None


def _ensure_parent_agent_run(runtime_host: Any, *, task_run: Any) -> Any:
    expected_id = f"agrun:{task_run.task_run_id}:main"
    for item in runtime_host.state_index.list_task_agent_runs(task_run.task_run_id):
        if str(getattr(item, "agent_run_id", "") or "") == expected_id:
            return item
    now = time.time()
    agent_run = AgentRun(
        agent_run_id=expected_id,
        task_run_id=task_run.task_run_id,
        agent_id=str(getattr(task_run, "agent_id", "") or "agent:0"),
        agent_profile_id=str(getattr(task_run, "agent_profile_id", "") or "main_interactive_agent"),
        status="running",
        execution_runtime_kind="single_agent_task",
        created_at=now,
        updated_at=now,
    )
    runtime_host.state_index.upsert_agent_run(agent_run)
    return agent_run


def _execution_store(request: ToolInvocationRequest) -> Any | None:
    runtime_host = _runtime_host(request)
    if runtime_host is None or request.caller_kind != "task_run":
        return None
    return getattr(runtime_host, "execution_store", None)


def _operation_gate(request: ToolInvocationRequest) -> Any | None:
    runtime_host = _runtime_host(request)
    return getattr(runtime_host, "operation_gate", None) if runtime_host is not None else None


def _definition(request: ToolInvocationRequest) -> Any | None:
    runtime_host = _runtime_host(request)
    index = getattr(runtime_host, "tool_authorization_index", None) if runtime_host is not None else None
    return dict(getattr(index, "definitions_by_name", {}) or {}).get(request.tool_name)


def _task_run(request: ToolInvocationRequest) -> Any | None:
    runtime_host = _runtime_host(request)
    if runtime_host is None or not request.task_run_id:
        return None
    return runtime_host.state_index.get_task_run(request.task_run_id)


def _runtime_host(request: ToolInvocationRequest) -> Any | None:
    return request.requested_constraints.get("runtime_host")


def _services(request: ToolInvocationRequest) -> Any | None:
    return request.requested_constraints.get("services")


def _runtime_assembly(request: ToolInvocationRequest) -> dict[str, Any]:
    payload = request.requested_constraints.get("runtime_assembly")
    return dict(payload or {}) if isinstance(payload, dict) else {}


def _backend_dir(request: ToolInvocationRequest) -> Path | None:
    explicit = request.requested_constraints.get("backend_dir")
    if explicit:
        return Path(str(explicit))
    runtime_host = _runtime_host(request)
    if runtime_host is not None:
        return Path(getattr(runtime_host, "backend_dir", ""))
    return None


def _workspace_root(request: ToolInvocationRequest) -> Path:
    explicit = request.requested_constraints.get("workspace_root")
    if explicit:
        return Path(str(explicit))
    scoped = str(dict(request.sandbox_scope or {}).get("workspace_root") or "").strip()
    if scoped:
        return Path(scoped).resolve()
    runtime_assembly = _runtime_assembly(request)
    backend_dir = _backend_dir(request)
    assembly_backend = runtime_assembly.get("backend_dir")
    root = str(assembly_backend or backend_dir or ".")
    try:
        from project_layout import ProjectLayout

        return ProjectLayout.from_backend_dir(Path(root)).project_root.resolve()
    except Exception:
        return Path(root).resolve()


def _caller_resource_scope(request: ToolInvocationRequest) -> dict[str, Any]:
    return dict(request.caller_resource_scope or {})


def _requested_constraints(request: ToolInvocationRequest) -> dict[str, Any]:
    return dict(request.requested_constraints or {})


def _tool_plan_ref(tool_plan: Any) -> dict[str, Any]:
    return {
        "plan_id": str(getattr(tool_plan, "plan_id", "") or ""),
        "schema_hash": str(getattr(tool_plan, "schema_hash", "") or ""),
        "registry_hash": str(getattr(tool_plan, "registry_hash", "") or ""),
    }


def _execution_context(request: ToolInvocationRequest) -> dict[str, Any]:
    return {
        "packet_ref": request.packet_ref,
        "action_request_ref": request.action_request_ref,
        "admission_ref": request.admission_ref,
        "tool_name": request.tool_name,
        "operation_id": _request_operation_id(request),
        "caller_kind": request.caller_kind,
        "caller_ref": request.caller_ref,
        "permission_mode": request.permission_mode,
        "authority": "runtime.tool_runtime.tool_control_plane.execution_context",
    }


def _public_policy(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(policy or {}).items()
        if key not in {"material_mounts"}
    }
