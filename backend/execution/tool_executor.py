from __future__ import annotations

from typing import Any

from orchestration import RuntimeActionRequest, RuntimeDirective, build_tool_result_observation
from orchestration.runtime_loop.action_request import build_tool_execution_error_observation
from orchestration.runtime_loop.execution_record import (
    OperationExecutionRecord,
    RuntimeExecutionStore,
    build_execution_receipt,
)


class ToolRuntimeExecutor:
    """Executes tool RuntimeDirectives after OperationGate approval."""

    def __init__(self, *, tool_runtime) -> None:
        self.tool_runtime = tool_runtime

    async def run(
        self,
        *,
        task_run_id: str,
        action_request: RuntimeActionRequest,
        directive: RuntimeDirective,
        execution_record: OperationExecutionRecord,
        execution_store: RuntimeExecutionStore | None = None,
        max_result_size_chars: int = 0,
    ) -> dict[str, Any]:
        tool_name = str(action_request.payload.get("tool_name") or "").strip()
        tool_call = dict(action_request.payload.get("tool_call") or {})
        tool_args = dict(tool_call.get("args") or {})
        tool_call_id = str(tool_call.get("id") or action_request.request_id)
        current_record = execution_record
        if execution_store is not None:
            current_record = execution_store.mark_dispatched(
                current_record,
                diagnostics={"tool_name": tool_name, "directive_ref": directive.directive_id},
            )
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
        tool = self.tool_runtime.get_instance(tool_name)
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
        if execution_store is not None:
            current_record = execution_store.mark_completed(
                current_record,
                result_ref=result_ref,
                result_payload={
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "tool_args": tool_args,
                    "result": text,
                    "result_chars": len(text),
                    "truncated": truncated,
                },
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
        )
        return {
            "observation": observation,
            "execution_record": current_record,
            "error": "",
        }
