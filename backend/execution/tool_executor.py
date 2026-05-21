from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from execution.tool_result_envelope import build_tool_result_envelope
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
        sandbox_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tool_name = str(action_request.payload.get("tool_name") or "").strip()
        tool_call = dict(action_request.payload.get("tool_call") or {})
        tool_args = dict(tool_call.get("args") or {})
        tool_call_id = str(tool_call.get("id") or action_request.request_id)
        sandbox_context = _sandbox_context_for_tool(tool_name, sandbox_policy)
        if sandbox_context:
            _prepare_sandbox_overlay_for_tool(
                tool_name=tool_name,
                tool_args=tool_args,
                sandbox_context=sandbox_context,
            )
        current_record = execution_record
        if execution_store is not None:
            dispatch_diagnostics = {"tool_name": tool_name, "directive_ref": directive.directive_id}
            if sandbox_context:
                dispatch_diagnostics["sandbox"] = dict(sandbox_context)
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
            definition.build(Path(str(sandbox_context["sandbox_root"])).resolve())
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
            sandbox=sandbox_context,
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
                result_payload["sandbox"] = dict(sandbox_context)
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
            "sandbox": dict(sandbox_context),
        }


DEFAULT_SIDE_EFFECT_TOOL_NAMES = {"write_file", "edit_file", "terminal", "python_repl"}
OVERLAY_COPY_ON_WRITE_TOOL_NAMES = {"edit_file"}


def _sandbox_context_for_tool(tool_name: str, sandbox_policy: dict[str, Any] | None) -> dict[str, Any]:
    policy = dict(sandbox_policy or {})
    if policy.get("enabled") is not True:
        return {}
    side_effect_tools = {
        str(item or "").strip()
        for item in list(policy.get("side_effect_tools") or DEFAULT_SIDE_EFFECT_TOOL_NAMES)
        if str(item or "").strip()
    }
    if str(tool_name or "").strip() not in side_effect_tools:
        return {}
    sandbox_root = Path(str(policy.get("sandbox_root") or "")).resolve() if policy.get("sandbox_root") else None
    if sandbox_root is None:
        return {}
    sandbox_root.mkdir(parents=True, exist_ok=True)
    return {
        "enabled": True,
        "mode": str(policy.get("mode") or "workspace_overlay"),
        "sandbox_root": str(sandbox_root),
        "workspace_root": str(Path(str(policy.get("workspace_root") or "")).resolve()) if policy.get("workspace_root") else "",
        "tool_name": str(tool_name or ""),
        "real_workspace_access": str(policy.get("real_workspace_access") or "read_only"),
        "overlay_copy_on_write": bool(policy.get("overlay_copy_on_write") is not False),
    }


def _prepare_sandbox_overlay_for_tool(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    sandbox_context: dict[str, Any],
) -> None:
    if not bool(sandbox_context.get("overlay_copy_on_write") is True):
        return
    if str(tool_name or "").strip() not in OVERLAY_COPY_ON_WRITE_TOOL_NAMES:
        return
    relative_path = _normalize_relative_path(tool_args.get("path"))
    if not relative_path:
        return
    workspace_root = Path(str(sandbox_context.get("workspace_root") or "")).resolve()
    sandbox_root = Path(str(sandbox_context.get("sandbox_root") or "")).resolve()
    if not str(workspace_root) or not str(sandbox_root):
        return
    source = (workspace_root / relative_path).resolve()
    target = (sandbox_root / relative_path).resolve()
    if workspace_root not in source.parents and source != workspace_root:
        return
    if sandbox_root not in target.parents and target != sandbox_root:
        return
    if target.exists() or not source.exists() or not source.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _normalize_relative_path(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip().strip("/")
    while "//" in text:
        text = text.replace("//", "/")
    if not text or text.startswith("../") or "/../" in f"/{text}/":
        return ""
    return text
