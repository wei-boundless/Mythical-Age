from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from capability_system.tools.contracts import ToolInvocationValidationDecision, ToolInvocationValidator
from runtime.environment import RuntimeEnvironment
from runtime.tool_runtime.tool_result_envelope import build_tool_result_envelope
from runtime.tool_runtime.sandbox_backend import DEFAULT_SIDE_EFFECT_TOOL_NAMES, LocalOverlaySandboxBackend
from runtime.tool_runtime.native_tools import build_native_runtime_tool
from runtime.tool_runtime.tool_adapter import RuntimeToolAdapter
from runtime.tool_runtime.tool_invocation_control import (
    ToolInvocationContext,
    build_tool_invocation_id,
    build_tool_invocation_idempotency_key,
    registry_for,
)
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

_SANDBOX_CONTEXT_REQUIRED_SIDE_EFFECT_TOOL_NAMES = DEFAULT_SIDE_EFFECT_TOOL_NAMES | {
    "browser_control",
    "image_generate",
}


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
        tool_invocation_context: ToolInvocationContext | None = None,
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
        invocation_context = _resolve_tool_invocation_context(
            task_run_id=task_run_id,
            action_request=action_request,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_call_id=tool_call_id,
            sandbox_policy=policy_payload,
            explicit_context=tool_invocation_context,
        )
        tool_args = _bind_tool_invocation_args(tool_name, tool_args, invocation_context=invocation_context)
        invocation_context = _resolve_tool_invocation_context(
            task_run_id=task_run_id,
            action_request=action_request,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_call_id=tool_call_id,
            sandbox_policy=policy_payload,
            explicit_context=invocation_context,
        )
        tool_context = ToolUseContext(
            workspace_root=execution_root,
            sandbox_root=self.sandbox_backend.execution_root(sandbox_context) if sandbox_context else None,
            tool_invocation_id=invocation_context.tool_invocation_id,
            caller_kind=invocation_context.caller_kind,
            caller_ref=invocation_context.caller_ref,
            turn_id=invocation_context.turn_id,
            idempotency_key=invocation_context.idempotency_key,
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
            registry = registry_for(getattr(self.tool_runtime, "runtime_host", None))
            if registry is not None:
                registry.start(
                    tool_invocation_id=invocation_context.tool_invocation_id,
                    caller_kind=invocation_context.caller_kind,
                    caller_ref=invocation_context.caller_ref,
                    session_id=invocation_context.session_id,
                    turn_id=invocation_context.turn_id,
                    task_run_id=invocation_context.task_run_id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_call_id=tool_call_id,
                    idempotency_key=invocation_context.idempotency_key,
                    diagnostics={"action_request_ref": action_request.request_id, "directive_ref": directive.directive_id},
                )
            envelope = await _call_runtime_tool_with_control(
                runtime_tool,
                tool_args,
                tool_context,
                runtime_host=getattr(self.tool_runtime, "runtime_host", None),
                tool_invocation_id=invocation_context.tool_invocation_id,
            )
        except asyncio.CancelledError as exc:
            signal = _tool_signal(getattr(self.tool_runtime, "runtime_host", None), invocation_context.tool_invocation_id)
            reason = str(signal.get("reason") or "tool_cancelled_by_runtime_control")
            kind = str(signal.get("kind") or "stop")
            error = f"Tool execution interrupted by runtime control: {kind}: {reason}"
            if execution_store is not None:
                current_record = execution_store.mark_failed(
                    current_record,
                    error=error,
                    diagnostics={"runtime_control": signal, "tool_interrupted": True},
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
                "recoverable_error": error if kind in {"pause", "replan"} else "",
                "error": error if kind == "stop" else "",
            }
        except Exception as exc:
            error = f"Tool execution failed: {exc}"
            registry = registry_for(getattr(self.tool_runtime, "runtime_host", None))
            if registry is not None:
                registry.fail(invocation_context.tool_invocation_id, error=error)
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
        registry = registry_for(getattr(self.tool_runtime, "runtime_host", None))
        if registry is not None:
            structured_error = dict(envelope.structured_payload.get("structured_error") or {})
            if envelope.status == "error":
                registry.fail(
                    invocation_context.tool_invocation_id,
                    error=str(envelope.error or text or "tool_execution_failed"),
                    structured_error=structured_error,
                    diagnostics={"result_ref": result_ref},
                )
            else:
                registry.complete(
                    invocation_context.tool_invocation_id,
                    result_ref=result_ref,
                    artifact_refs=[dict(item) for item in envelope.artifact_refs],
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

    async def run_core(
        self,
        *,
        caller_kind: str,
        caller_ref: str,
        session_id: str,
        turn_id: str,
        tool_invocation_id: str,
        tool_name: str,
        tool_call_id: str,
        tool_args: dict[str, Any],
        operation_id: str = "",
        sandbox_policy: dict[str, Any] | None = None,
        file_management_policy: dict[str, Any] | None = None,
        max_result_size_chars: int = 0,
    ) -> dict[str, Any]:
        tool_args = dict(tool_args or {})
        invocation_context = _core_invocation_context(
            caller_kind=caller_kind,
            caller_ref=caller_ref,
            session_id=session_id,
            turn_id=turn_id,
            tool_invocation_id=tool_invocation_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_args=tool_args,
        )
        definition = self.tool_runtime.get_definition(tool_name)
        if definition is None:
            error = f"Tool execution failed: unknown tool {tool_name}."
            return _core_error_result(
                invocation_context,
                tool_name=tool_name,
                tool_args=tool_args,
                operation_id=operation_id,
                text=error,
                error=error,
            )
        expected_operation_id = str(getattr(definition, "operation_id", "") or "").strip()
        if operation_id and expected_operation_id and str(operation_id or "").strip() != expected_operation_id:
            error = (
                "Tool execution blocked by dispatch guard: action_request_operation_mismatch. "
                f"Expected tool {tool_name} with operation {expected_operation_id}."
            )
            return _core_error_result(
                invocation_context,
                tool_name=tool_name,
                tool_args=tool_args,
                operation_id=operation_id or expected_operation_id,
                text=error,
                error=error,
            )
        runtime_tool = build_native_runtime_tool(capability_definition=definition)
        sandbox_context = self.sandbox_backend.context_for_tool(tool_name=tool_name, sandbox_policy=sandbox_policy)
        sandbox_guard_error = _sandbox_context_guard_error(tool_name=tool_name, sandbox_policy=sandbox_policy, sandbox_context=sandbox_context)
        if sandbox_guard_error:
            return _core_error_result(
                invocation_context,
                tool_name=tool_name,
                tool_args=tool_args,
                operation_id=operation_id or expected_operation_id,
                text=sandbox_guard_error,
                recoverable_error=sandbox_guard_error,
                sandbox=sandbox_context.to_dict() if sandbox_context else {},
            )
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
                tool_input=dict(tool_args or {}),
            )
            if invocation_validation.should_block:
                error = _invocation_validation_error(invocation_validation)
                recoverable = _is_recoverable_invocation_validation_error(invocation_validation)
                return _core_error_result(
                    invocation_context,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    operation_id=operation_id or expected_operation_id,
                    text=error,
                    recoverable_error=error if recoverable else "",
                    error="" if recoverable else error,
                    sandbox=sandbox_context.to_dict() if sandbox_context else {},
                    diagnostics={"tool_invocation_validation": invocation_validation.to_dict()},
                )
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
            return _core_error_result(
                invocation_context,
                tool_name=tool_name,
                tool_args=tool_args,
                operation_id=operation_id or expected_operation_id,
                text=error,
                error=error,
                sandbox=sandbox_context.to_dict() if sandbox_context else {},
            )
        workspace_root = Path(getattr(self.tool_runtime, "base_dir", ".")).resolve()
        execution_root = self.sandbox_backend.tool_workspace_root(sandbox_context) if sandbox_context else workspace_root
        policy_payload = dict(sandbox_policy or {})
        file_policy_payload = dict(file_management_policy or {})
        tool_args = _bind_runtime_scoped_tool_args(tool_name, tool_args, policy_payload=policy_payload, task_run_id="")
        invocation_context = _core_invocation_context(
            caller_kind=caller_kind,
            caller_ref=caller_ref,
            session_id=session_id,
            turn_id=turn_id,
            tool_invocation_id=tool_invocation_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_args=tool_args,
        )
        tool_args = _bind_tool_invocation_args(tool_name, tool_args, invocation_context=invocation_context)
        invocation_context = _core_invocation_context(
            caller_kind=caller_kind,
            caller_ref=caller_ref,
            session_id=session_id,
            turn_id=turn_id,
            tool_invocation_id=tool_invocation_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_args=tool_args,
        )
        execution_receipt = _core_execution_receipt(
            invocation_context,
            tool_name=tool_name,
            operation_id=operation_id or expected_operation_id,
            status="dispatched",
        )
        tool_context = ToolUseContext(
            workspace_root=execution_root,
            sandbox_root=self.sandbox_backend.execution_root(sandbox_context) if sandbox_context else None,
            tool_invocation_id=invocation_context.tool_invocation_id,
            caller_kind=invocation_context.caller_kind,
            caller_ref=invocation_context.caller_ref,
            turn_id=invocation_context.turn_id,
            idempotency_key=invocation_context.idempotency_key,
            task_run_id="",
            session_id=session_id,
            agent_run_id="",
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
            execution_receipt=execution_receipt,
        )
        validation = runtime_tool.validate_input(tool_args, tool_context)
        if not validation.allowed:
            error = validation.reason or "tool_input_validation_failed"
            return _core_error_result(
                invocation_context,
                tool_name=tool_name,
                tool_args=tool_args,
                operation_id=operation_id or expected_operation_id,
                text=validation.repair_instruction or error,
                recoverable_error=error,
                sandbox=sandbox_context.to_dict() if sandbox_context else {},
                diagnostics={"tool_validation": validation.diagnostics},
            )
        tool_args = dict(validation.normalized_args or tool_args)
        permission = runtime_tool.check_permissions(tool_args, tool_context)
        if not permission.allowed:
            error = permission.reason or "tool_permission_denied"
            return _core_error_result(
                invocation_context,
                tool_name=tool_name,
                tool_args=tool_args,
                operation_id=operation_id or expected_operation_id,
                text=permission.repair_instruction or error,
                recoverable_error=error,
                sandbox=sandbox_context.to_dict() if sandbox_context else {},
                diagnostics={"tool_permission": permission.diagnostics},
            )
        try:
            registry = registry_for(getattr(self.tool_runtime, "runtime_host", None))
            if registry is not None:
                registry.start(
                    tool_invocation_id=invocation_context.tool_invocation_id,
                    caller_kind=invocation_context.caller_kind,
                    caller_ref=invocation_context.caller_ref,
                    session_id=invocation_context.session_id,
                    turn_id=invocation_context.turn_id,
                    task_run_id=invocation_context.task_run_id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_call_id=tool_call_id,
                    idempotency_key=invocation_context.idempotency_key,
                    diagnostics={"operation_id": operation_id, "core_dispatch": True},
                )
            envelope = await _call_runtime_tool_with_control(
                runtime_tool,
                tool_args,
                tool_context,
                runtime_host=getattr(self.tool_runtime, "runtime_host", None),
                tool_invocation_id=invocation_context.tool_invocation_id,
            )
        except asyncio.CancelledError:
            signal = _tool_signal(getattr(self.tool_runtime, "runtime_host", None), invocation_context.tool_invocation_id)
            reason = str(signal.get("reason") or "tool_cancelled_by_runtime_control")
            kind = str(signal.get("kind") or "stop")
            error = f"Tool execution interrupted by runtime control: {kind}: {reason}"
            return _core_error_result(
                invocation_context,
                tool_name=tool_name,
                tool_args=tool_args,
                operation_id=operation_id or expected_operation_id,
                text=error,
                recoverable_error=error if kind in {"pause", "replan"} else "",
                error=error if kind == "stop" else "",
                sandbox=sandbox_context.to_dict() if sandbox_context else {},
            )
        except Exception as exc:
            error = f"Tool execution failed: {exc}"
            registry = registry_for(getattr(self.tool_runtime, "runtime_host", None))
            if registry is not None:
                registry.fail(invocation_context.tool_invocation_id, error=error)
            return _core_error_result(
                invocation_context,
                tool_name=tool_name,
                tool_args=tool_args,
                operation_id=operation_id or expected_operation_id,
                text=error,
                error=error,
                sandbox=sandbox_context.to_dict() if sandbox_context else {},
            )
        text = str(envelope.text or "")
        limit = max(0, int(max_result_size_chars or 0))
        truncated = bool(limit and len(text) > limit)
        if truncated:
            text = text[:limit]
        result_ref = f"tool-result:{tool_invocation_id}"
        final_execution_receipt = {
            **dict(envelope.execution_receipt or execution_receipt),
            **_core_execution_receipt(
                invocation_context,
                tool_name=tool_name,
                operation_id=operation_id or expected_operation_id,
                status="failed" if envelope.status == "error" else "completed",
                result_ref=result_ref,
                error=str(envelope.error or "") if envelope.status == "error" else "",
            ),
        }
        envelope = _finalize_runtime_tool_envelope(
            envelope=envelope,
            tool_name=tool_name,
            tool_args=tool_args,
            text=text,
            execution_receipt=final_execution_receipt,
            result_ref=result_ref,
            truncated=truncated,
            sandbox=sandbox_context.to_dict() if sandbox_context else None,
        )
        registry = registry_for(getattr(self.tool_runtime, "runtime_host", None))
        if registry is not None:
            structured_error = dict(envelope.structured_payload.get("structured_error") or {})
            if envelope.status == "error":
                registry.fail(
                    invocation_context.tool_invocation_id,
                    error=str(envelope.error or text or "tool_execution_failed"),
                    structured_error=structured_error,
                    diagnostics={"result_ref": result_ref},
                )
            else:
                registry.complete(
                    invocation_context.tool_invocation_id,
                    result_ref=result_ref,
                    artifact_refs=[dict(item) for item in envelope.artifact_refs],
                )
        return {
            "status": str(envelope.status or "ok"),
            "text": text,
            "result_ref": result_ref,
            "result_envelope": envelope.to_dict(),
            "artifact_refs": [dict(item) for item in envelope.artifact_refs],
            "error": str(envelope.error or "") if envelope.status == "error" else "",
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
    permission_mode = str(policy.get("permission_mode") or "").strip().lower()
    if permission_mode in {"full_access", "bypass"}:
        return ""
    effective_tool = str(tool_name or "").strip()
    if effective_tool not in _SANDBOX_CONTEXT_REQUIRED_SIDE_EFFECT_TOOL_NAMES:
        return ""
    if sandbox_context is not None:
        return ""
    return (
        "sandbox_context_required_for_side_effect_tool: "
        f"{effective_tool} cannot run without the active task environment sandbox context."
    )


def _core_execution_receipt(
    invocation_context: ToolInvocationContext,
    *,
    tool_name: str,
    operation_id: str,
    status: str,
    result_ref: str = "",
    error: str = "",
) -> dict[str, Any]:
    invocation_id = str(invocation_context.tool_invocation_id or "").strip()
    return {
        "execution_id": f"rtcore:{invocation_id or 'unknown'}",
        "request_ref": invocation_id,
        "status": str(status or "").strip(),
        "replay_decision": "deny_auto_replay",
        "result_ref": str(result_ref or ""),
        "error": str(error or ""),
        "tool_name": str(tool_name or ""),
        "operation_id": str(operation_id or ""),
        "caller_kind": str(invocation_context.caller_kind or ""),
        "caller_ref": str(invocation_context.caller_ref or ""),
        "session_id": str(invocation_context.session_id or ""),
        "turn_id": str(invocation_context.turn_id or ""),
        "task_run_id": str(invocation_context.task_run_id or ""),
        "tool_call_id": str(invocation_context.tool_call_id or ""),
        "idempotency_key": str(invocation_context.idempotency_key or ""),
        "authority": "runtime.tool_runtime.core_execution_receipt",
    }


def _core_invocation_context(
    *,
    caller_kind: str,
    caller_ref: str,
    session_id: str,
    turn_id: str,
    tool_invocation_id: str,
    tool_name: str,
    tool_call_id: str,
    tool_args: dict[str, Any],
) -> ToolInvocationContext:
    invocation_id = str(tool_invocation_id or "").strip()
    return ToolInvocationContext(
        tool_invocation_id=invocation_id,
        caller_kind=str(caller_kind or "").strip() or "agent_turn",
        caller_ref=str(caller_ref or "").strip(),
        session_id=str(session_id or "").strip(),
        turn_id=str(turn_id or "").strip(),
        task_run_id="",
        tool_call_id=str(tool_call_id or "").strip(),
        idempotency_key=build_tool_invocation_idempotency_key(
            tool_name=tool_name,
            tool_args=dict(tool_args or {}),
            tool_invocation_id=invocation_id,
        ),
    )


def _core_error_result(
    invocation_context: ToolInvocationContext,
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    operation_id: str,
    text: str,
    recoverable_error: str = "",
    error: str = "",
    sandbox: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result_ref = f"tool-result:{invocation_context.tool_invocation_id}" if invocation_context.tool_invocation_id else ""
    final_error = str(error or recoverable_error or text or "tool_execution_failed")
    execution_receipt = _core_execution_receipt(
        invocation_context,
        tool_name=tool_name,
        operation_id=operation_id,
        status="failed",
        result_ref=result_ref,
        error=final_error,
    )
    envelope = build_tool_result_envelope(
        tool_name=tool_name,
        tool_args=tool_args,
        result={"ok": False, "error": str(text or final_error)},
        execution_receipt=execution_receipt,
        result_ref=result_ref,
        sandbox=dict(sandbox or {}),
    )
    payload = {
        "status": "error",
        "text": str(text or final_error),
        "result_ref": result_ref,
        "result_envelope": envelope.to_dict(),
        "recoverable_error": str(recoverable_error or ""),
        "error": str(error or ""),
        "sandbox": dict(sandbox or {}),
    }
    if diagnostics:
        payload["diagnostics"] = dict(diagnostics)
    return payload


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


async def _call_runtime_tool_with_control(
    runtime_tool: Any,
    tool_args: dict[str, Any],
    tool_context: ToolUseContext,
    *,
    runtime_host: Any | None,
    tool_invocation_id: str,
) -> Any:
    registry = registry_for(runtime_host)
    if registry is None or not str(tool_invocation_id or "").strip():
        return await runtime_tool.call(tool_args, tool_context)
    task = asyncio.create_task(runtime_tool.call(tool_args, tool_context))
    registry.attach_task(tool_invocation_id, task)
    try:
        return await task
    finally:
        registry.clear_task(tool_invocation_id, task)


def _tool_signal(runtime_host: Any | None, tool_invocation_id: str) -> dict[str, Any]:
    registry = registry_for(runtime_host)
    if registry is None or not str(tool_invocation_id or "").strip():
        return {}
    signal = registry.signal(tool_invocation_id)
    if signal is None:
        return {}
    return signal.to_dict() if hasattr(signal, "to_dict") else {}


def _executor_epoch_from_policy(policy: dict[str, Any]) -> int:
    try:
        return int(dict(policy or {}).get("executor_epoch") or 0)
    except (TypeError, ValueError):
        return 0


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


def _resolve_tool_invocation_context(
    *,
    task_run_id: str,
    action_request: RuntimeActionRequest,
    tool_name: str,
    tool_args: dict[str, Any],
    tool_call_id: str,
    sandbox_policy: dict[str, Any],
    explicit_context: ToolInvocationContext | None,
) -> ToolInvocationContext:
    policy = dict(sandbox_policy or {})
    session_id = str(getattr(explicit_context, "session_id", "") or _session_id_from_policy(policy))
    task_ref = str(getattr(explicit_context, "task_run_id", "") or task_run_id or action_request.task_run_id or "").strip()
    caller_kind = str(getattr(explicit_context, "caller_kind", "") or ("task_run" if task_ref else "agent_turn")).strip()
    caller_ref = str(getattr(explicit_context, "caller_ref", "") or task_ref or policy.get("turn_id") or action_request.task_run_id).strip()
    turn_id = str(getattr(explicit_context, "turn_id", "") or policy.get("turn_id") or "").strip()
    invocation_id = str(getattr(explicit_context, "tool_invocation_id", "") or "").strip()
    if not invocation_id:
        invocation_id = build_tool_invocation_id(
            caller_ref=caller_ref,
            action_request_ref=action_request.request_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
        )
    idempotency_key = build_tool_invocation_idempotency_key(
        tool_name=tool_name,
        tool_args=dict(tool_args or {}),
        tool_invocation_id=invocation_id,
    )
    return ToolInvocationContext(
        tool_invocation_id=invocation_id,
        caller_kind=caller_kind,
        caller_ref=caller_ref,
        session_id=session_id,
        turn_id=turn_id,
        task_run_id=task_ref,
        tool_call_id=str(getattr(explicit_context, "tool_call_id", "") or tool_call_id or "").strip(),
        idempotency_key=idempotency_key,
    )


def _bind_tool_invocation_args(
    tool_name: str,
    tool_args: dict[str, Any],
    *,
    invocation_context: ToolInvocationContext,
) -> dict[str, Any]:
    args = dict(tool_args or {})
    if str(tool_name or "").strip() != "image_generate":
        return args
    if str(args.get("target_id") or "").strip():
        return args
    return {
        **args,
        "target_id": _target_id_from_invocation(invocation_context.tool_invocation_id),
        "overwrite": bool(args.get("overwrite") is True),
    }


def _target_id_from_invocation(tool_invocation_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(tool_invocation_id or "").strip())
    return f"tool-{safe}" if safe else "tool-invocation"


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


