from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from capability_system.tool_contracts import ToolInvocationValidationDecision, ToolInvocationValidator
from runtime.environment import RuntimeEnvironment
from runtime.tool_runtime.tool_result_envelope import build_tool_result_envelope
from runtime.tool_runtime.sandbox_backend import DEFAULT_SIDE_EFFECT_TOOL_NAMES, LocalOverlaySandboxBackend
from runtime.tool_runtime.native_tools import build_native_runtime_tool
from runtime.tool_runtime.tool_adapter import RuntimeToolAdapter
from runtime.tool_runtime.tool_use_context import ToolUseContext
from orchestration.runtime_directive import RuntimeDirective
from runtime.shared.action_request import (
    RuntimeActionRequest,
    build_recoverable_tool_invocation_observation,
    build_tool_result_observation,
    build_tool_unavailable_observation,
)
from runtime.shared.action_request import build_tool_execution_error_observation
from runtime.shared.execution_record import (
    OperationExecutionRecord,
    RuntimeExecutionStore,
    build_execution_receipt,
)
from runtime.shared.policy_rejection_observation import build_policy_rejection_observation


class ToolRuntimeExecutor:
    """Executes tool RuntimeDirectives after OperationGate approval."""

    def __init__(self, *, tool_runtime, sandbox_backend: LocalOverlaySandboxBackend | None = None) -> None:
        self.tool_runtime = tool_runtime
        self.sandbox_backend = sandbox_backend or LocalOverlaySandboxBackend()

    def preflight_validate(
        self,
        *,
        task_run_id: str,
        action_request: RuntimeActionRequest,
        directive: RuntimeDirective,
        sandbox_policy: dict[str, Any] | None = None,
        file_management_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tool_name = str(action_request.payload.get("tool_name") or "").strip()
        tool_call = dict(action_request.payload.get("tool_call") or {})
        tool_args = dict(tool_call.get("args") or {})
        tool_call_id = str(tool_call.get("id") or action_request.request_id)
        definition = self.tool_runtime.get_definition(tool_name)
        if definition is None:
            error = f"tool_not_available: {tool_name}"
            return {
                "allowed": False,
                "observation": build_tool_unavailable_observation(
                    task_run_id=task_run_id,
                    request_ref=action_request.request_id,
                    directive_ref=directive.directive_id,
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    tool_args=tool_args,
                    error=error,
                    repair_kind="tool_not_available",
                ),
                "error": error,
            }
        runtime_tool = build_native_runtime_tool(capability_definition=definition)
        if runtime_tool is None:
            sandbox_context = self.sandbox_backend.context_for_tool(tool_name=tool_name, sandbox_policy=sandbox_policy)
            try:
                tool = _capability_tool_instance(
                    tool_runtime=self.tool_runtime,
                    sandbox_backend=self.sandbox_backend,
                    definition=definition,
                    tool_name=tool_name,
                    sandbox_context=sandbox_context,
                )
            except Exception as exc:
                tool = None
                tool_error = str(exc) or exc.__class__.__name__
            else:
                tool_error = ""
            if tool is None:
                error = f"tool_runtime_unavailable: {tool_name}"
                return {
                    "allowed": False,
                    "observation": build_tool_unavailable_observation(
                        task_run_id=task_run_id,
                        request_ref=action_request.request_id,
                        directive_ref=directive.directive_id,
                        tool_name=tool_name,
                        tool_call_id=tool_call_id,
                        tool_args=tool_args,
                        error=f"{error}{': ' + tool_error if tool_error else ''}",
                        repair_kind="tool_runtime_unavailable",
                    ),
                    "error": error,
                }
            runtime_tool = RuntimeToolAdapter.from_capability_definition(
                capability_definition=definition,
                tool_instance=tool,
            )
        else:
            sandbox_context = self.sandbox_backend.context_for_tool(tool_name=tool_name, sandbox_policy=sandbox_policy)
        sandbox_guard_error = _sandbox_context_guard_error(tool_name=tool_name, sandbox_policy=sandbox_policy, sandbox_context=sandbox_context)
        if sandbox_guard_error:
            return {
                "allowed": False,
                "observation": build_policy_rejection_observation(
                    task_run_id=task_run_id,
                    request_ref=action_request.request_id,
                    directive_ref=directive.directive_id,
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    tool_args=tool_args,
                    policy="sandbox_boundary",
                    reason=sandbox_guard_error,
                    repair_instruction="The active task environment requires sandboxed side effects. Reassemble the runtime with a sandbox context before retrying.",
                    execution_receipt={},
                    diagnostics={"sandbox_policy_enabled": True, "tool_name": tool_name},
                ),
                "error": sandbox_guard_error,
            }
        workspace_root = Path(getattr(self.tool_runtime, "base_dir", ".")).resolve()
        policy_payload = dict(sandbox_policy or {})
        file_policy_payload = dict(file_management_policy or {})
        tool_args = _bind_runtime_scoped_tool_args(tool_name, tool_args, policy_payload=policy_payload, task_run_id=task_run_id)
        tool_context = ToolUseContext(
            workspace_root=self.sandbox_backend.execution_root(sandbox_context) if sandbox_context else workspace_root,
            sandbox_root=self.sandbox_backend.execution_root(sandbox_context) if sandbox_context else None,
            task_run_id=task_run_id,
            session_id=_session_id_from_policy(policy_payload),
            agent_run_id=_agent_run_id_from_policy(policy_payload, task_run_id),
            tool_call_id=tool_call_id,
            read_scopes=tuple(str(item) for item in list(policy_payload.get("read_scopes") or [])),
            write_scopes=tuple(str(item) for item in list(policy_payload.get("write_scopes") or [])),
            material_mounts=tuple(dict(item) for item in list(policy_payload.get("material_mounts") or []) if isinstance(item, dict)),
            artifact_root=str(policy_payload.get("artifact_root") or ""),
            approval_policy=str(policy_payload.get("approval_policy") or ""),
            approval_fingerprint=_approval_fingerprint_from_policy(file_policy_payload, fallback_policy=policy_payload),
            permission_mode=str(policy_payload.get("permission_mode") or ""),
            sandbox_policy=policy_payload,
            file_management_policy=file_policy_payload,
            environment_snapshot=RuntimeEnvironment(
                workspace_root=workspace_root,
                sandbox_root=self.sandbox_backend.execution_root(sandbox_context) if sandbox_context else None,
            ).snapshot(),
            execution_receipt={},
        )
        validation = runtime_tool.validate_input(tool_args, tool_context)
        if validation.allowed:
            return {"allowed": True, "normalized_args": dict(validation.normalized_args or tool_args)}
        error = validation.reason or "tool_input_validation_failed"
        return {
            "allowed": False,
            "observation": build_recoverable_tool_invocation_observation(
                task_run_id=task_run_id,
                request_ref=action_request.request_id,
                directive_ref=directive.directive_id,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                tool_args=tool_args,
                error=validation.repair_instruction or error,
                execution_receipt={},
                invocation_validation={
                    "missing_inputs": list(validation.diagnostics.get("missing_inputs") or []),
                    "contract": {"required_inputs": _required_inputs_from_definition(definition)},
                },
            ),
            "error": error,
        }

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
        file_management_policy: dict[str, Any] | None = None,
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
        runtime_tool = build_native_runtime_tool(capability_definition=definition)
        sandbox_context = self.sandbox_backend.context_for_tool(tool_name=tool_name, sandbox_policy=sandbox_policy)
        sandbox_guard_error = _sandbox_context_guard_error(tool_name=tool_name, sandbox_policy=sandbox_policy, sandbox_context=sandbox_context)
        if sandbox_guard_error:
            if execution_store is not None:
                current_record = execution_store.mark_failed(
                    current_record,
                    error=sandbox_guard_error,
                    diagnostics={"sandbox_boundary": {"sandbox_policy_enabled": True, "tool_name": tool_name}},
                )
            return {
                "observation": build_policy_rejection_observation(
                    task_run_id=task_run_id,
                    request_ref=action_request.request_id,
                    directive_ref=directive.directive_id,
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    tool_args=tool_args,
                    policy="sandbox_boundary",
                    reason=sandbox_guard_error,
                    repair_instruction="The active task environment requires sandboxed side effects. Reassemble the runtime with a sandbox context before retrying.",
                    execution_receipt=build_execution_receipt(current_record, error=sandbox_guard_error).to_dict(),
                    diagnostics={"sandbox_policy_enabled": True, "tool_name": tool_name},
                ),
                "execution_record": current_record,
                "recoverable_error": sandbox_guard_error,
            }
        if sandbox_context:
            self.sandbox_backend.prepare_tool_call(
                tool_name=tool_name,
                tool_args=tool_args,
                context=sandbox_context,
            )
        tool = None
        if runtime_tool is None:
            invocation_validation = ToolInvocationValidator(mode="enforce").evaluate(
                tool_name=tool_name,
                contract=definition.contract,
                tool_input=tool_args,
            )
            if invocation_validation.should_block:
                error = _invocation_validation_error(invocation_validation)
                if execution_store is not None:
                    current_record = execution_store.mark_failed(
                        current_record,
                        error=error,
                        diagnostics={"tool_invocation_validation": invocation_validation.to_dict()},
                    )
                if _is_recoverable_invocation_validation_error(invocation_validation):
                    return {
                        "observation": build_recoverable_tool_invocation_observation(
                            task_run_id=task_run_id,
                            request_ref=action_request.request_id,
                            directive_ref=directive.directive_id,
                            tool_name=tool_name,
                            tool_call_id=tool_call_id,
                            tool_args=tool_args,
                            error=error,
                            execution_receipt=build_execution_receipt(current_record, error=error).to_dict(),
                            invocation_validation=invocation_validation.to_dict(),
                        ),
                        "execution_record": current_record,
                        "recoverable_error": error,
                    }
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
            tool = _capability_tool_instance(
                tool_runtime=self.tool_runtime,
                sandbox_backend=self.sandbox_backend,
                definition=definition,
                tool_name=tool_name,
                sandbox_context=sandbox_context,
            )
            if tool is not None:
                runtime_tool = RuntimeToolAdapter.from_capability_definition(
                    capability_definition=definition,
                    tool_instance=tool,
                )
        if runtime_tool is None:
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
        if execution_store is not None:
            dispatch_diagnostics = {
                "tool_name": tool_name,
                "directive_ref": directive.directive_id,
                "tool_dispatch_guard": dispatch_decision.to_dict(),
                "runtime_tool_protocol": "native" if tool is None else "adapter",
            }
            if sandbox_context:
                dispatch_diagnostics["sandbox"] = sandbox_context.to_dict()
            current_record = execution_store.mark_dispatched(current_record, diagnostics=dispatch_diagnostics)
        workspace_root = Path(getattr(self.tool_runtime, "base_dir", ".")).resolve()
        execution_root = self.sandbox_backend.tool_workspace_root(sandbox_context) if sandbox_context else workspace_root
        policy_payload = dict(sandbox_policy or {})
        file_policy_payload = dict(file_management_policy or {})
        tool_args = _bind_runtime_scoped_tool_args(tool_name, tool_args, policy_payload=policy_payload, task_run_id=task_run_id)
        tool_context = ToolUseContext(
            workspace_root=execution_root,
            sandbox_root=self.sandbox_backend.execution_root(sandbox_context) if sandbox_context else None,
            task_run_id=task_run_id,
            session_id=_session_id_from_policy(policy_payload),
            agent_run_id=_agent_run_id_from_policy(policy_payload, task_run_id),
            tool_call_id=tool_call_id,
            read_scopes=tuple(str(item) for item in list(policy_payload.get("read_scopes") or [])),
            write_scopes=tuple(str(item) for item in list(policy_payload.get("write_scopes") or [])),
            material_mounts=tuple(dict(item) for item in list(policy_payload.get("material_mounts") or []) if isinstance(item, dict)),
            artifact_root=str(policy_payload.get("artifact_root") or ""),
            approval_policy=str(policy_payload.get("approval_policy") or ""),
            approval_fingerprint=_approval_fingerprint_from_policy(file_policy_payload, fallback_policy=policy_payload),
            permission_mode=str(policy_payload.get("permission_mode") or ""),
            sandbox_policy=policy_payload,
            file_management_policy=file_policy_payload,
            environment_snapshot=RuntimeEnvironment(
                workspace_root=workspace_root,
                sandbox_root=self.sandbox_backend.execution_root(sandbox_context) if sandbox_context else None,
            ).snapshot(),
            execution_receipt=build_execution_receipt(current_record).to_dict(),
        )
        validation = runtime_tool.validate_input(tool_args, tool_context)
        if not validation.allowed:
            error = validation.reason or "tool_input_validation_failed"
            if execution_store is not None:
                current_record = execution_store.mark_failed(
                    current_record,
                    error=error,
                    diagnostics={"tool_validation": validation.diagnostics},
                )
            return {
                "observation": build_recoverable_tool_invocation_observation(
                    task_run_id=task_run_id,
                    request_ref=action_request.request_id,
                    directive_ref=directive.directive_id,
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    tool_args=tool_args,
                    error=validation.repair_instruction or error,
                    execution_receipt=build_execution_receipt(current_record, error=error).to_dict(),
                    invocation_validation={
                        "missing_inputs": list(validation.diagnostics.get("missing_inputs") or []),
                        "contract": {"required_inputs": _required_inputs_from_definition(definition)},
                    },
                ),
                "execution_record": current_record,
                "recoverable_error": error,
            }
        tool_args = dict(validation.normalized_args or tool_args)
        permission = runtime_tool.check_permissions(tool_args, tool_context)
        if not permission.allowed:
            error = permission.reason or "tool_permission_denied"
            if execution_store is not None:
                current_record = execution_store.mark_failed(
                    current_record,
                    error=error,
                    diagnostics={"tool_permission": permission.diagnostics},
                )
            return {
                "observation": build_policy_rejection_observation(
                    task_run_id=task_run_id,
                    request_ref=action_request.request_id,
                    directive_ref=directive.directive_id,
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    tool_args=tool_args,
                    policy="tool_permission",
                    reason=error,
                    repair_instruction=permission.repair_instruction or error,
                    execution_receipt=build_execution_receipt(current_record, error=error).to_dict(),
                    diagnostics=permission.diagnostics,
                ),
                "execution_record": current_record,
                "recoverable_error": error,
            }
        try:
            envelope = await runtime_tool.call(tool_args, tool_context)
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

        text = str(envelope.text or "")
        limit = max(0, int(max_result_size_chars or 0))
        truncated = bool(limit and len(text) > limit)
        if truncated:
            text = text[:limit]
        result_ref = f"execution-result:{current_record.execution_id}"
        envelope = _finalize_runtime_tool_envelope(
            envelope=envelope,
            tool_name=tool_name,
            tool_args=tool_args,
            text=text,
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


def _sandbox_context_guard_error(
    *,
    tool_name: str,
    sandbox_policy: dict[str, Any] | None,
    sandbox_context: Any | None,
) -> str:
    policy = dict(sandbox_policy or {})
    if policy.get("enabled") is not True:
        return ""
    effective_tool = str(tool_name or "").strip()
    if effective_tool not in DEFAULT_SIDE_EFFECT_TOOL_NAMES:
        return ""
    if sandbox_context is not None:
        return ""
    return (
        "sandbox_context_required_for_side_effect_tool: "
        f"{effective_tool} cannot run without the active task environment sandbox context."
    )


def _finalize_runtime_tool_envelope(
    *,
    envelope,
    tool_name: str,
    tool_args: dict[str, Any],
    text: str,
    execution_receipt: dict[str, Any],
    result_ref: str,
    truncated: bool,
    sandbox: dict[str, Any] | None,
):
    structured_payload = {
        **dict(envelope.structured_payload or {}),
        "truncated": bool(truncated),
        "sandbox": dict(sandbox or {}),
    }
    if envelope.observed_paths:
        structured_payload["observed_paths"] = list(envelope.observed_paths)
    if envelope.matched_paths:
        structured_payload["matched_paths"] = list(envelope.matched_paths)
    if envelope.artifact_refs:
        structured_payload["artifact_refs"] = [dict(item) for item in envelope.artifact_refs]
    if envelope.command_receipt:
        structured_payload["command_receipt"] = dict(envelope.command_receipt)
    return type(envelope)(
        envelope_id=envelope.envelope_id,
        tool_name=str(tool_name or envelope.tool_name or ""),
        tool_args=dict(tool_args or envelope.tool_args or {}),
        status=str(envelope.status or "ok"),
        text=str(text or ""),
        structured_payload=structured_payload,
        observed_paths=tuple(envelope.observed_paths or ()),
        matched_paths=tuple(envelope.matched_paths or ()),
        artifact_refs=tuple(dict(item) for item in tuple(envelope.artifact_refs or ())),
        command_receipt=dict(envelope.command_receipt or {}),
        execution_receipt=dict(execution_receipt or {}),
        result_ref=str(result_ref or ""),
        error=str(envelope.error or "") if envelope.status == "error" else "",
    )


def _dispatch_decision_error(decision: ToolDispatchGuardDecision) -> str:
    mismatch_text = ", ".join(decision.mismatches) if decision.mismatches else decision.reason
    return (
        "Tool execution blocked by dispatch guard: "
        f"{mismatch_text}. Expected tool {decision.expected_tool_name} "
        f"with operation {decision.expected_operation_id}."
    )


def _invocation_validation_error(decision: ToolInvocationValidationDecision) -> str:
    details = []
    if decision.missing_inputs:
        details.append(f"missing inputs: {', '.join(decision.missing_inputs)}")
    if decision.missing_bindings:
        details.append(f"missing bindings: {', '.join(decision.missing_bindings)}")
    suffix = f" ({'; '.join(details)})" if details else ""
    return f"Tool execution blocked by invocation validation: {decision.reason}{suffix}."


def _is_recoverable_invocation_validation_error(decision: ToolInvocationValidationDecision) -> bool:
    if str(decision.reason or "") != "missing_required_input":
        return False
    return bool(decision.missing_inputs)


def _structured_tool_result_payload(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    payload = dict(result)
    if "structured_payload" not in payload:
        return {}
    return {
        "text": str(payload.get("text") or payload.get("summary") or ""),
        "structured_payload": dict(payload.get("structured_payload") or {}),
    }


def _required_inputs_from_definition(definition: Any) -> list[str]:
    contract = getattr(definition, "contract", None)
    if contract is None:
        return []
    if isinstance(contract, dict):
        values = list(contract.get("required_inputs") or [])
    else:
        values = list(getattr(contract, "required_inputs", ()) or [])
    return [str(item).strip() for item in values if str(item).strip()]


def _capability_tool_instance(
    *,
    tool_runtime: Any,
    sandbox_backend: LocalOverlaySandboxBackend,
    definition: Any,
    tool_name: str,
    sandbox_context: Any | None,
) -> Any | None:
    if not sandbox_context:
        return tool_runtime.get_instance(tool_name)
    if _uses_system_backend_root(tool_name):
        return tool_runtime.get_instance(tool_name) or definition.build(Path(getattr(tool_runtime, "base_dir", ".")).resolve())
    return definition.build(sandbox_backend.execution_root(sandbox_context))


def _uses_system_backend_root(tool_name: str) -> bool:
    return str(tool_name or "").strip() in {"agent_todo", "image_generate"}


def _bind_runtime_scoped_tool_args(
    tool_name: str,
    tool_args: dict[str, Any],
    *,
    policy_payload: dict[str, Any],
    task_run_id: str,
) -> dict[str, Any]:
    effective_tool = str(tool_name or "").strip()
    if effective_tool == "memory_search":
        return _bind_memory_search_scope(
            tool_args,
            policy_payload=policy_payload,
            task_run_id=task_run_id,
        )
    if effective_tool != "agent_todo":
        return dict(tool_args or {})
    session_id = _session_id_from_policy(policy_payload)
    return {
        **dict(tool_args or {}),
        "session_id": session_id,
        "task_id": task_run_id,
    }


def _bind_memory_search_scope(
    tool_args: dict[str, Any],
    *,
    policy_payload: dict[str, Any],
    task_run_id: str,
) -> dict[str, Any]:
    args = dict(tool_args or {})
    runtime_scope = dict(policy_payload.get("runtime_scope") or {})
    if not runtime_scope:
        return args
    project_id = str(runtime_scope.get("project_id") or policy_payload.get("project_id") or "").strip()
    bound_args = {
        **args,
        "task_run_id": str(args.get("task_run_id") or task_run_id or "").strip(),
    }
    if project_id:
        bound_args["project_id"] = project_id
    return bound_args


def _session_id_from_policy(policy: dict[str, Any]) -> str:
    explicit = str(policy.get("session_id") or "").strip()
    if explicit:
        return explicit
    return "runtime"


def _agent_run_id_from_policy(policy: dict[str, Any], task_run_id: str) -> str:
    explicit = str(policy.get("agent_run_id") or "").strip()
    if explicit:
        return explicit
    return f"agrun:{task_run_id}:main"


def _approval_fingerprint_from_policy(policy: dict[str, Any], *, fallback_policy: dict[str, Any] | None = None) -> str:
    explicit = str(policy.get("approval_fingerprint") or "").strip()
    if explicit:
        return explicit
    token = policy.get("approval_token")
    if isinstance(token, dict):
        return str(token.get("risk_fingerprint") or token.get("token_id") or "").strip()
    if fallback_policy:
        return _approval_fingerprint_from_policy(dict(fallback_policy or {}))
    return ""


