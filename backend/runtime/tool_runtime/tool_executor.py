from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from capability_system.tool_contracts import ToolContractDecision, ToolContractGate
from runtime.tool_runtime.tool_result_envelope import build_tool_result_envelope
from runtime.tool_runtime.sandbox_backend import LocalOverlaySandboxBackend
from orchestration.runtime_directive import RuntimeDirective
from runtime.shared.action_request import RuntimeActionRequest, build_tool_result_observation
from runtime.shared.action_request import build_tool_execution_error_observation
from runtime.shared.execution_record import (
    OperationExecutionRecord,
    RuntimeExecutionStore,
    build_execution_receipt,
)


class ToolRuntimeExecutor:
    """Executes tool RuntimeDirectives after OperationGate approval."""

    def __init__(self, *, tool_runtime, sandbox_backend: LocalOverlaySandboxBackend | None = None) -> None:
        self.tool_runtime = tool_runtime
        self.sandbox_backend = sandbox_backend or LocalOverlaySandboxBackend()

    async def run(
        self,
        *,
        task_run_id: str,
        action_request: RuntimeActionRequest,
        directive: RuntimeDirective,
        execution_record: OperationExecutionRecord,
        execution_store: RuntimeExecutionStore | None = None,
        max_result_size_chars: int = 0,
        sandbox_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tool_name = str(action_request.payload.get("tool_name") or "").strip()
        tool_call = dict(action_request.payload.get("tool_call") or {})
        tool_args = dict(tool_call.get("args") or {})
        tool_call_id = str(tool_call.get("id") or action_request.request_id)
        current_record = execution_record
        definition = self.tool_runtime.get_definition(tool_name)
        if definition is None:
            error = f"Tool execution failed: unknown tool {tool_name}."
            if execution_store is not None:
                current_record = execution_store.mark_failed(current_record, error=error)
            return {
                "observation": build_tool_execution_error_observation(
                    task_run_id=task_run_id,
                    request_ref=action_request.request_id,
                    directive_ref=directive.directive_id,
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    tool_args=tool_args,
                    error=error,
                    execution_receipt=build_execution_receipt(current_record, error=error).to_dict(),
                ),
                "execution_record": current_record,
                "error": error,
            }
        dispatch_decision = _evaluate_dispatch_guard(
            tool_name=tool_name,
            tool_call=tool_call,
            action_request=action_request,
            directive=directive,
            execution_record=execution_record,
            definition=definition,
        )
        if not dispatch_decision.allowed:
            error = _dispatch_decision_error(dispatch_decision)
            if execution_store is not None:
                current_record = execution_store.mark_failed(
                    current_record,
                    error=error,
                    diagnostics={"tool_dispatch_guard": dispatch_decision.to_dict()},
                )
            return {
                "observation": build_tool_execution_error_observation(
                    task_run_id=task_run_id,
                    request_ref=action_request.request_id,
                    directive_ref=directive.directive_id,
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    tool_args=tool_args,
                    error=error,
                    execution_receipt=build_execution_receipt(current_record, error=error).to_dict(),
                ),
                "execution_record": current_record,
                "error": error,
            }
        contract_decision = ToolContractGate(mode="enforce").evaluate(
            tool_name=tool_name,
            contract=definition.contract,
            tool_input=tool_args,
        )
        if contract_decision.should_block:
            error = _contract_decision_error(contract_decision)
            if execution_store is not None:
                current_record = execution_store.mark_failed(
                    current_record,
                    error=error,
                    diagnostics={"tool_contract_decision": contract_decision.to_dict()},
                )
            return {
                "observation": build_tool_execution_error_observation(
                    task_run_id=task_run_id,
                    request_ref=action_request.request_id,
                    directive_ref=directive.directive_id,
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    tool_args=tool_args,
                    error=error,
                    execution_receipt=build_execution_receipt(current_record, error=error).to_dict(),
                ),
                "execution_record": current_record,
                "error": error,
            }
        sandbox_context = self.sandbox_backend.context_for_tool(tool_name=tool_name, sandbox_policy=sandbox_policy)
        if sandbox_context:
            self.sandbox_backend.prepare_tool_call(
                tool_name=tool_name,
                tool_args=tool_args,
                context=sandbox_context,
            )
        if execution_store is not None:
            dispatch_diagnostics = {
                "tool_name": tool_name,
                "directive_ref": directive.directive_id,
                "tool_dispatch_guard": dispatch_decision.to_dict(),
                "tool_contract_decision": contract_decision.to_dict(),
            }
            if sandbox_context:
                dispatch_diagnostics["sandbox"] = sandbox_context.to_dict()
            current_record = execution_store.mark_dispatched(current_record, diagnostics=dispatch_diagnostics)
        tool = (
            definition.build(self.sandbox_backend.execution_root(sandbox_context))
            if sandbox_context
            else self.tool_runtime.get_instance(tool_name)
        )
        if tool is None:
            error = f"Tool execution failed: {tool_name} is unavailable."
            if execution_store is not None:
                current_record = execution_store.mark_failed(current_record, error=error)
            return {
                "observation": build_tool_execution_error_observation(
                    task_run_id=task_run_id,
                    request_ref=action_request.request_id,
                    directive_ref=directive.directive_id,
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    tool_args=tool_args,
                    error=error,
                    execution_receipt=build_execution_receipt(current_record, error=error).to_dict(),
                ),
                "execution_record": current_record,
                "error": error,
            }
        try:
            if hasattr(tool, "ainvoke"):
                result = await tool.ainvoke(tool_args)
            else:
                result = tool.invoke(tool_args)
        except Exception as exc:
            error = f"Tool execution failed: {exc}"
            if execution_store is not None:
                current_record = execution_store.mark_failed(current_record, error=error)
            return {
                "observation": build_tool_execution_error_observation(
                    task_run_id=task_run_id,
                    request_ref=action_request.request_id,
                    directive_ref=directive.directive_id,
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    tool_args=tool_args,
                    error=error,
                    execution_receipt=build_execution_receipt(current_record, error=error).to_dict(),
                ),
                "execution_record": current_record,
                "error": error,
            }

        text = str(result or "")
        limit = max(0, int(max_result_size_chars or 0))
        truncated = bool(limit and len(text) > limit)
        if truncated:
            text = text[:limit]
        result_ref = f"execution-result:{current_record.execution_id}"
        envelope = build_tool_result_envelope(
            tool_name=tool_name,
            tool_args=tool_args,
            result=text,
            execution_receipt=build_execution_receipt(current_record).to_dict(),
            result_ref=result_ref,
            truncated=truncated,
            sandbox=sandbox_context.to_dict() if sandbox_context else None,
        )
        if execution_store is not None:
            result_payload = {
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "tool_args": tool_args,
                "result": text,
                "result_chars": len(text),
                "truncated": truncated,
                "result_envelope": envelope.to_dict(),
                "structured_payload": dict(envelope.structured_payload),
                "observed_paths": list(envelope.observed_paths),
                "matched_paths": list(envelope.matched_paths),
                "artifact_refs": [dict(item) for item in envelope.artifact_refs],
                "command_receipt": dict(envelope.command_receipt),
            }
            if sandbox_context:
                result_payload["sandbox"] = sandbox_context.to_dict()
            current_record = execution_store.mark_completed(
                current_record,
                result_ref=result_ref,
                result_payload=result_payload,
            )
        observation = build_tool_result_observation(
            task_run_id=task_run_id,
            request_ref=action_request.request_id,
            directive_ref=directive.directive_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_args=tool_args,
            result=text,
            truncated=truncated,
            execution_receipt=build_execution_receipt(current_record).to_dict(),
            result_ref=result_ref,
            result_envelope=envelope.to_dict(),
        )
        return {
            "observation": observation,
            "execution_record": current_record,
            "error": "",
            "sandbox": sandbox_context.to_dict() if sandbox_context else {},
        }


@dataclass(frozen=True, slots=True)
class ToolDispatchGuardDecision:
    allowed: bool
    reason: str
    tool_name: str
    expected_tool_name: str
    expected_operation_id: str
    tool_call_name: str = ""
    action_request_operation_id: str = ""
    directive_operation_refs: list[str] = field(default_factory=list)
    execution_record_operation_id: str = ""
    mismatches: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _evaluate_dispatch_guard(
    *,
    tool_name: str,
    tool_call: dict[str, Any],
    action_request: RuntimeActionRequest,
    directive: RuntimeDirective,
    execution_record: OperationExecutionRecord,
    definition: Any,
) -> ToolDispatchGuardDecision:
    expected_tool_name = str(getattr(definition, "name", "") or "").strip()
    expected_operation_id = str(getattr(definition, "operation_id", "") or "").strip()
    tool_call_name = str(tool_call.get("name") or "").strip()
    action_request_operation_id = str(action_request.operation_id or "").strip()
    directive_operation_refs = [
        str(item or "").strip()
        for item in list(directive.operation_refs or ())
        if str(item or "").strip()
    ]
    execution_record_operation_id = str(execution_record.operation_id or "").strip()
    mismatches: list[str] = []
    if not expected_operation_id:
        mismatches.append("definition_missing_operation_id")
    if tool_name != expected_tool_name:
        mismatches.append("tool_name_definition_mismatch")
    if tool_call_name and tool_call_name != tool_name:
        mismatches.append("tool_call_name_mismatch")
    if action_request_operation_id and action_request_operation_id != expected_operation_id:
        mismatches.append("action_request_operation_mismatch")
    if directive_operation_refs != [expected_operation_id]:
        mismatches.append("directive_operation_refs_mismatch")
    if execution_record_operation_id != expected_operation_id:
        mismatches.append("execution_record_operation_mismatch")
    return ToolDispatchGuardDecision(
        allowed=not mismatches,
        reason="dispatch_contract_satisfied" if not mismatches else "dispatch_contract_mismatch",
        tool_name=tool_name,
        expected_tool_name=expected_tool_name,
        expected_operation_id=expected_operation_id,
        tool_call_name=tool_call_name,
        action_request_operation_id=action_request_operation_id,
        directive_operation_refs=directive_operation_refs,
        execution_record_operation_id=execution_record_operation_id,
        mismatches=mismatches,
    )


def _dispatch_decision_error(decision: ToolDispatchGuardDecision) -> str:
    mismatch_text = ", ".join(decision.mismatches) if decision.mismatches else decision.reason
    return (
        "Tool execution blocked by dispatch guard: "
        f"{mismatch_text}. Expected tool {decision.expected_tool_name} "
        f"with operation {decision.expected_operation_id}."
    )


def _contract_decision_error(decision: ToolContractDecision) -> str:
    details = []
    if decision.missing_inputs:
        details.append(f"missing inputs: {', '.join(decision.missing_inputs)}")
    if decision.missing_bindings:
        details.append(f"missing bindings: {', '.join(decision.missing_bindings)}")
    suffix = f" ({'; '.join(details)})" if details else ""
    return f"Tool execution blocked by contract: {decision.reason}{suffix}."
