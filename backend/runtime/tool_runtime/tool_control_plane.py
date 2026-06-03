from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from permissions.operations import build_default_operation_registry
from harness.agent_control.controller import SubagentControl
from orchestration.runtime_directive import RuntimeDirective
from permissions import PermissionContext, ResourceDecision, ResourcePolicy
from runtime.shared.action_request import RuntimeActionRequest
from runtime.shared.execution_record import (
    build_idempotency_token,
    build_request_fingerprint,
    derive_replay_policy,
)
from runtime.shared.models import AgentRun
from runtime.shared.safety import build_task_safety_validators
from runtime.tool_runtime.tool_invocation_control import (
    ToolInvocationContext,
    build_tool_invocation_idempotency_key,
)
from runtime.tool_runtime.tool_invocation_request import ToolInvocationRequest
from runtime.tool_runtime.tool_observation import ToolObservation
from runtime.tool_runtime.tool_result_envelope import build_tool_result_envelope
from runtime.tooling import ToolSupervisor

_AGENT_TURN_SANDBOX_AUTO_ALLOW_OPERATIONS = {
    "op.write_file",
    "op.edit_file",
    "op.shell",
    "op.python_repl",
}


@dataclass(slots=True)
class RuntimeToolControlPlane:
    """Runtime/session-level tool admission and observation boundary."""

    tool_runtime_executor: Any | None = None
    tool_supervisor: Any | None = None
    operation_gate: Any | None = None

    async def invoke(self, request: ToolInvocationRequest, *, tool_plan: Any) -> ToolObservation:
        denial = _membership_denial(request, tool_plan=tool_plan)
        if denial:
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
            return await self._invoke_agent_turn_or_fail_closed(request, tool_plan=tool_plan)
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
            return _observation(
                request,
                status="denied",
                text="runtime tool control plane has no OperationGate",
                diagnostics={"stage": "operation_gate_unavailable", "tool_plan_ref": tool_plan.plan_id},
            )
        supervision = supervisor.supervise(
            task_run_id=request.task_run_id,
            agent_run_id=request.agent_run_id,
            tool_call_id=request.tool_call_id,
            operation_id=request.operation_id,
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
            sandbox_policy=sandbox_policy,
            file_management_policy=file_policy,
            safety_validators=_safety_validators(request, sandbox_policy=sandbox_policy),
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
        if _is_subagent_operation(request):
            observation = await _invoke_subagent_control(
                request,
                directive=directive,
                normalized_args=normalized_args,
                operation_gate=supervision.gate_result.to_dict() if hasattr(supervision.gate_result, "to_dict") else {},
                execution_record=execution_record,
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
        result = await self.tool_runtime_executor.run(
            task_run_id=request.task_run_id,
            action_request=runtime_action,
            directive=directive,
            execution_record=execution_record,
            execution_store=execution_store,
            sandbox_policy=sandbox_policy,
            file_management_policy=file_policy,
            tool_invocation_context=ToolInvocationContext(
                tool_invocation_id=request.invocation_id,
                caller_kind=request.caller_kind,
                caller_ref=request.caller_ref,
                session_id=request.session_id,
                turn_id=request.turn_id,
                task_run_id=request.task_run_id,
                tool_call_id=request.tool_call_id,
                idempotency_key=build_tool_invocation_idempotency_key(
                    tool_name=request.tool_name,
                    tool_args=normalized_args,
                    tool_invocation_id=request.invocation_id,
                ),
            ),
        )
        return _observation_from_executor_result(
            request,
            result=result,
            operation_gate=supervision.gate_result.to_dict() if hasattr(supervision.gate_result, "to_dict") else {},
            diagnostics={"stage": "tool_runtime_executor", "tool_plan_ref": tool_plan.plan_id, "supervision": supervision.to_dict()},
        )

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
            return _observation(
                request,
                status="denied",
                text="runtime tool control plane has no OperationGate",
                diagnostics={"stage": "operation_gate_unavailable", "tool_plan_ref": tool_plan.plan_id},
            )
        supervision = supervisor.supervise(
            task_run_id="",
            agent_run_id=request.agent_run_id,
            tool_call_id=request.tool_call_id,
            operation_id=request.operation_id,
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
            sandbox_policy=sandbox_policy,
            file_management_policy=file_policy,
            safety_validators=_safety_validators(request, sandbox_policy=sandbox_policy),
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
        if self.tool_runtime_executor is None or not hasattr(self.tool_runtime_executor, "run_core"):
            return _observation(
                request,
                status="error",
                text="tool_runtime_executor_core_unavailable",
                operation_gate=supervision.gate_result.to_dict() if hasattr(supervision.gate_result, "to_dict") else {},
                diagnostics={"stage": "tool_runtime_executor_core_unavailable", "tool_plan_ref": tool_plan.plan_id},
            )
        runtime_host = _runtime_host(request)
        tool_runtime = getattr(self.tool_runtime_executor, "tool_runtime", None)
        if tool_runtime is not None and getattr(tool_runtime, "runtime_host", None) is None and runtime_host is not None:
            setattr(tool_runtime, "runtime_host", runtime_host)
        result = await self.tool_runtime_executor.run_core(
            caller_kind=request.caller_kind,
            caller_ref=request.caller_ref,
            session_id=request.session_id,
            turn_id=request.turn_id,
            tool_invocation_id=request.invocation_id,
            tool_name=request.tool_name,
            tool_call_id=request.tool_call_id,
            tool_args=dict(supervision.normalized_args or request.tool_args or {}),
            operation_id=request.operation_id,
            sandbox_policy=sandbox_policy,
            file_management_policy=file_policy,
        )
        return _observation_from_core_result(
            request,
            result=result,
            operation_gate=supervision.gate_result.to_dict() if hasattr(supervision.gate_result, "to_dict") else {},
            diagnostics={"stage": "tool_runtime_executor_core", "tool_plan_ref": tool_plan.plan_id, "supervision": supervision.to_dict()},
        )


def _membership_denial(request: ToolInvocationRequest, *, tool_plan: Any) -> str:
    table = tool_plan.capability_table
    if table is None:
        return "runtime tool plan has no ToolCapabilityTable"
    operation_id = str(request.operation_id or "").strip()
    tool_name = str(request.tool_name or "").strip()
    capability = table.capability_for_operation(operation_id)
    if capability is None:
        return "operation not present in RuntimeToolPlan"
    if not capability.dispatchable:
        return "tool is not dispatchable in RuntimeToolPlan"
    if capability.tool_name != tool_name:
        return "tool name does not match RuntimeToolPlan capability"
    return ""


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
    envelope = dict(result_envelope or {})
    if not envelope:
        envelope = build_tool_result_envelope(
            tool_name=request.tool_name,
            tool_args=dict(request.tool_args or {}),
            result={"ok": status == "ok", "error": "" if status == "ok" else str(text or status), "text": str(text or "")},
            status=status,
            execution_receipt=dict(execution_receipt or {}),
            result_ref=str(result_ref or ""),
            tool_call_id=request.tool_call_id,
            action_request_id=request.action_request_ref,
            caller_kind=request.caller_kind,
            caller_ref=request.caller_ref,
            diagnostics=dict(diagnostics or {}),
        ).to_dict()
    return ToolObservation(
        observation_id=f"toolobs:{request.invocation_id}:{uuid.uuid4().hex[:8]}",
        invocation_id=request.invocation_id,
        caller_kind=request.caller_kind,
        caller_ref=request.caller_ref,
        tool_name=request.tool_name,
        operation_id=request.operation_id,
        status=status,  # type: ignore[arg-type]
        text=text,
        result_ref=str(result_ref or envelope.get("result_ref") or ""),
        result_envelope=envelope,
        operation_gate=dict(operation_gate or {}),
        execution_receipt=dict(execution_receipt or {}),
        artifact_refs=tuple(dict(item) for item in tuple(artifact_refs or ())),
        diagnostics=dict(diagnostics or {}),
    )


def _execution_contracts(request: ToolInvocationRequest, *, tool_plan: Any) -> tuple[Any, Any, dict[str, Any], dict[str, Any], Any]:
    definition = _definition(request)
    operation_id = str(request.operation_id or getattr(definition, "operation_id", "") or request.tool_name)
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
    resource_policy = ResourcePolicy(
        policy_id=directive.adopted_resource_policy_ref,
        task_id=str(_caller_resource_scope(request).get("task_id") or request.caller_ref or request.turn_id),
        allowed_operations=(operation_id,),
        allowed_tools=(request.tool_name,),
        approval_policy=str(sandbox_policy.get("approval_policy") or "runtime_tool_control_plane"),
        runtime_view_only=False,
        adopted=True,
        runtime_executable=True,
        diagnostics={
            "authority": "runtime.tool_runtime.tool_control_plane",
            "caller_kind": request.caller_kind,
            "sandbox_policy": _public_policy(sandbox_policy),
        },
    )
    return directive, runtime_action, sandbox_policy, file_policy, resource_policy


@dataclass(frozen=True, slots=True)
class _ToolPermissionDirective:
    directive_id: str
    operation_refs: tuple[str, ...]


def _agent_turn_execution_contracts(request: ToolInvocationRequest, *, tool_plan: Any, definition: Any) -> tuple[Any, dict[str, Any], dict[str, Any], Any]:
    operation_id = str(request.operation_id or getattr(definition, "operation_id", "") or request.tool_name)
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
    if descriptor is not None and (bool(getattr(descriptor, "requires_approval_by_default", False)) or bool(getattr(descriptor, "destructive", False))):
        return "requires_approval", "operation requires approval by default"
    return "requires_approval", "non-read-only operation outside sandbox requires approval"


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
    descriptor = registry.get_operation(request.operation_id)
    fingerprint = build_request_fingerprint(
        step_id=runtime_action.step_id,
        operation_id=request.operation_id,
        payload=runtime_action.payload,
    )
    return execution_store.create_record(
        task_run_id=request.task_run_id,
        step_id=runtime_action.step_id,
        action_request=runtime_action,
        directive_ref=directive.directive_id,
        operation_id=request.operation_id,
        executor_type="tool",
        replay_policy=derive_replay_policy(descriptor),
        request_fingerprint=fingerprint,
        idempotency_token=build_idempotency_token(
            task_run_id=request.task_run_id,
            step_id=runtime_action.step_id,
            operation_id=request.operation_id,
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
    envelope = build_tool_result_envelope(
        tool_name=request.tool_name,
        tool_args=dict(normalized_args or {}),
        result={
            "text": text,
            "structured_payload": {
                "subagent_control": dict(payload or {}),
                "artifact_refs": list(_artifact_refs_from_subagent_payload(payload)),
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
        artifact_refs=tuple(_artifact_refs_from_subagent_payload(payload)),
        diagnostics={"stage": "subagent_control_handler", "payload": dict(payload or {})},
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
        artifact_refs=tuple(dict(item) for item in list(payload.get("artifact_refs") or envelope.get("artifact_refs") or []) if isinstance(item, dict)),
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
        artifact_refs=tuple(dict(item) for item in list(result.get("artifact_refs") or envelope.get("artifact_refs") or []) if isinstance(item, dict)),
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


def _safety_validators(request: ToolInvocationRequest, *, sandbox_policy: dict[str, Any]) -> dict[str, Any]:
    backend_dir = _backend_dir(request)
    if backend_dir is None:
        return {}
    return build_task_safety_validators(
        root_dir=backend_dir,
        safety_envelope={
            "write_mode": "bounded_create",
            "write_roots": _sandbox_relative_write_roots(sandbox_policy),
            "canonical_output_paths": _sandbox_relative_paths(sandbox_policy.get("canonical_output_paths"), sandbox_policy=sandbox_policy),
        },
        sandbox_policy=sandbox_policy,
    )


def _sandbox_relative_write_roots(sandbox_policy: dict[str, Any]) -> list[str]:
    return _sandbox_relative_paths(sandbox_policy.get("write_scopes"), sandbox_policy=sandbox_policy)


def _sandbox_relative_paths(values: Any, *, sandbox_policy: dict[str, Any]) -> list[str]:
    sandbox_root = Path(str(sandbox_policy.get("sandbox_root") or ".")).resolve()
    roots: list[str] = []
    for raw in list(values or []):
        text = str(raw or "").replace("\\", "/").strip().strip("/")
        if not text:
            continue
        try:
            roots.append((sandbox_root / text).resolve().relative_to(sandbox_root).as_posix())
        except Exception:
            roots.append(text)
    return roots


def _is_subagent_operation(request: ToolInvocationRequest) -> bool:
    return str(request.operation_id or "").startswith("op.subagent_")


def _artifact_refs_from_subagent_payload(payload: Any) -> list[dict[str, Any]]:
    result = dict(dict(payload or {}).get("result") or {})
    return [dict(item) for item in list(result.get("artifact_refs") or []) if isinstance(item, dict)]


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
        "operation_id": request.operation_id,
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
