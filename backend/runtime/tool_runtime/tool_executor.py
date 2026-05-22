from __future__ import annotations

from typing import Any

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
        sandbox_context = self.sandbox_backend.context_for_tool(tool_name=tool_name, sandbox_policy=sandbox_policy)
        if sandbox_context:
            self.sandbox_backend.prepare_tool_call(
                tool_name=tool_name,
                tool_args=tool_args,
                context=sandbox_context,
            )
        current_record = execution_record
        if execution_store is not None:
            dispatch_diagnostics = {"tool_name": tool_name, "directive_ref": directive.directive_id}
            if sandbox_context:
                dispatch_diagnostics["sandbox"] = sandbox_context.to_dict()
            current_record = execution_store.mark_dispatched(current_record, diagnostics=dispatch_diagnostics)
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
