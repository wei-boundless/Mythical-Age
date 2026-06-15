from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

from permissions import OperationGatePipelineContext
from permissions.context_models import PermissionContext
from permissions.decision_models import PermissionDecision
from permissions.receipt_models import PermissionReceipt
from runtime.shared.approval_fingerprint import build_approval_risk_fingerprint
from runtime.tooling.capability_table import ToolCapabilityTable


VALIDATOR_INPUT_KEYS = (
    "path",
    "file_path",
    "target_path",
    "root",
    "cwd",
    "paths",
    "file_paths",
    "target_paths",
    "command",
)


@dataclass(frozen=True, slots=True)
class ToolSupervisionResult:
    decision: PermissionDecision
    receipt: PermissionReceipt
    normalized_args: dict[str, Any] = field(default_factory=dict)
    preflight: dict[str, Any] = field(default_factory=dict)
    gate_result: Any | None = None

    @property
    def allowed(self) -> bool:
        return self.decision.allowed

    @property
    def requires_approval(self) -> bool:
        return self.decision.requires_approval

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.to_dict(),
            "receipt": self.receipt.to_dict(),
            "normalized_args": dict(self.normalized_args),
            "preflight": _jsonable_payload(self.preflight),
            "gate": self.gate_result.to_dict() if hasattr(self.gate_result, "to_dict") else None,
            "authority": "runtime.tooling.tool_supervisor",
        }


class ToolSupervisor:
    """Single per-call supervision entry for model tool calls."""

    def supervise(
        self,
        *,
        task_run_id: str,
        agent_run_id: str,
        tool_call_id: str,
        operation_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        directive: Any,
        resource_policy: Any,
        capability_table: ToolCapabilityTable | None,
        permission_context: PermissionContext,
        operation_gate: Any,
        tool_runtime_executor: Any | None = None,
        action_request: Any | None = None,
        approval_token: Any | None = None,
        approval_state: Any | None = None,
        approval_risk_fingerprint: str | None = None,
        sandbox_policy: dict[str, Any] | None = None,
        file_management_policy: dict[str, Any] | None = None,
        safety_validators: dict[str, Any] | None = None,
    ) -> ToolSupervisionResult:
        if approval_risk_fingerprint is None:
            fingerprint = build_approval_risk_fingerprint(
                operation_id=operation_id,
                tool_name=tool_name,
                tool_args=dict(tool_args or {}),
                sandbox_policy=dict(sandbox_policy or {}),
                file_management_policy=dict(file_management_policy or {}),
            )
        else:
            fingerprint = str(approval_risk_fingerprint or "")
        membership = _capability_membership(capability_table, operation_id=operation_id, tool_name=tool_name)
        if membership is not None:
            return self._result(
                task_run_id=task_run_id,
                agent_run_id=agent_run_id,
                tool_call_id=tool_call_id,
                decision=PermissionDecision.deny(
                    operation_id,
                    tool_name=tool_name,
                    reason=membership,
                    diagnostics={"tool_capability_table_id": getattr(capability_table, "table_id", "")},
                ),
            )
        preflight = {}
        normalized_args = dict(tool_args or {})
        if tool_runtime_executor is not None and action_request is not None and hasattr(tool_runtime_executor, "preflight_validate"):
            preflight = dict(
                tool_runtime_executor.preflight_validate(
                    task_run_id=task_run_id,
                    action_request=action_request,
                    directive=directive,
                    sandbox_policy=dict(sandbox_policy or {}),
                    file_management_policy=dict(file_management_policy or {}),
                )
                or {}
            )
            if preflight.get("allowed") is False:
                return self._result(
                    task_run_id=task_run_id,
                    agent_run_id=agent_run_id,
                    tool_call_id=tool_call_id,
                    decision=PermissionDecision.repair(
                        operation_id,
                        tool_name=tool_name,
                        reason=str(preflight.get("error") or "tool preflight validation failed"),
                        normalized_args=normalized_args,
                        diagnostics={"preflight": preflight},
                    ),
                    preflight=preflight,
                )
            normalized_args = dict(preflight.get("normalized_args") or normalized_args)

        gate_result = operation_gate.check(
            operation_id,
            resource_policy=resource_policy,
            directive_ref=str(getattr(directive, "directive_id", "") or ""),
            context=OperationGatePipelineContext(
                permission_mode=permission_context.permission_mode,
                approval_token=approval_token,
                approval_state=approval_state,
                approval_risk_fingerprint=fingerprint,
                operation_input=_operation_input(
                    operation_id=operation_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    normalized_args=normalized_args,
                    sandbox_policy=sandbox_policy,
                ),
                validators=dict(safety_validators or {}),
            ),
        )
        if getattr(gate_result, "requires_approval", False):
            decision = PermissionDecision.ask(
                operation_id,
                tool_name=tool_name,
                reason=str(getattr(gate_result, "reason", "") or "operation requires approval"),
                approval_fingerprint=fingerprint,
                normalized_args=normalized_args,
                diagnostics={"gate": gate_result.to_dict()},
            )
        elif not getattr(gate_result, "allowed", False):
            decision = PermissionDecision.deny(
                operation_id,
                tool_name=tool_name,
                reason=str(getattr(gate_result, "reason", "") or "operation denied"),
                diagnostics={"gate": gate_result.to_dict()},
            )
        else:
            decision = PermissionDecision.allow(
                operation_id,
                tool_name=tool_name,
                reason=str(getattr(gate_result, "reason", "") or "operation allowed"),
                normalized_args=normalized_args,
                diagnostics={"gate": gate_result.to_dict()},
            )
        return self._result(
            task_run_id=task_run_id,
            agent_run_id=agent_run_id,
            tool_call_id=tool_call_id,
            decision=decision,
            normalized_args=normalized_args,
            preflight=preflight,
            gate_result=gate_result,
        )

    def _result(
        self,
        *,
        task_run_id: str,
        agent_run_id: str,
        tool_call_id: str,
        decision: PermissionDecision,
        normalized_args: dict[str, Any] | None = None,
        preflight: dict[str, Any] | None = None,
        gate_result: Any | None = None,
    ) -> ToolSupervisionResult:
        return ToolSupervisionResult(
            decision=decision,
            receipt=PermissionReceipt.from_decision(
                task_run_id=task_run_id,
                agent_run_id=agent_run_id,
                tool_call_id=tool_call_id,
                decision=decision,
                metadata={"supervisor": "runtime.tooling.tool_supervisor"},
            ),
            normalized_args=dict(normalized_args or decision.normalized_args),
            preflight=dict(preflight or {}),
            gate_result=gate_result,
        )


def _capability_membership(
    capability_table: ToolCapabilityTable | None,
    *,
    operation_id: str,
    tool_name: str,
) -> str | None:
    if capability_table is None:
        return None
    capability = capability_table.capability_for_tool(operation_id=operation_id, tool_name=tool_name)
    if capability is None:
        if capability_table.capability_for_operation(operation_id) is None:
            return "operation not present in ToolCapabilityTable"
        return "tool not present for operation in ToolCapabilityTable"
    if not capability.dispatchable:
        return "tool is not dispatchable in ToolCapabilityTable"
    return None


def _operation_input(
    *,
    operation_id: str,
    tool_call_id: str,
    tool_name: str,
    normalized_args: dict[str, Any],
    sandbox_policy: dict[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "operation_id": operation_id,
        "id": tool_call_id,
        "name": tool_name,
        "args": dict(normalized_args or {}),
    }
    workspace_root = str(dict(sandbox_policy or {}).get("workspace_root") or "").strip()
    if workspace_root:
        payload["workspace_root"] = workspace_root
    for key in VALIDATOR_INPUT_KEYS:
        if key in dict(normalized_args or {}):
            payload[key] = normalized_args[key]
    return payload


def _jsonable_payload(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _jsonable_payload(value.to_dict())
    if is_dataclass(value):
        return _jsonable_payload(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable_payload(item) for item in value]
    return value


