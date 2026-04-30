from __future__ import annotations

from typing import Any

from orchestration import RuntimeActionRequest, RuntimeDirective, build_tool_result_observation


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
        max_result_size_chars: int = 0,
    ):
        tool_name = str(action_request.payload.get("tool_name") or "").strip()
        tool_call = dict(action_request.payload.get("tool_call") or {})
        tool_args = dict(tool_call.get("args") or {})
        tool_call_id = str(tool_call.get("id") or action_request.request_id)
        definition = self.tool_runtime.get_definition(tool_name)
        if definition is None:
            return build_tool_result_observation(
                task_run_id=task_run_id,
                request_ref=action_request.request_id,
                directive_ref=directive.directive_id,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                result=f"Tool execution failed: unknown tool {tool_name}.",
            )
        tool = self.tool_runtime.get_instance(tool_name)
        if tool is None:
            return build_tool_result_observation(
                task_run_id=task_run_id,
                request_ref=action_request.request_id,
                directive_ref=directive.directive_id,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                result=f"Tool execution failed: {tool_name} is unavailable.",
            )
        try:
            if hasattr(tool, "ainvoke"):
                result = await tool.ainvoke(tool_args)
            else:
                result = tool.invoke(tool_args)
        except Exception as exc:
            result = f"Tool execution failed: {exc}"

        text = str(result or "")
        limit = max(0, int(max_result_size_chars or 0))
        truncated = bool(limit and len(text) > limit)
        if truncated:
            text = text[:limit]
        return build_tool_result_observation(
            task_run_id=task_run_id,
            request_ref=action_request.request_id,
            directive_ref=directive.directive_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            result=text,
            truncated=truncated,
        )
