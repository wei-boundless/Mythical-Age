from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from capability_system.tools.tool_units.sandbox_command_guard import validate_sandbox_command_text
from capability_system.tools.workspace_file_service import (
    DEFAULT_EXCLUDED_DIRS,
    DEFAULT_SEARCH_EXCLUDED_PATHS,
    WorkspaceFileService,
)
from config import get_settings
from file_management import (
    FileGateway,
    FileGatewayApprovalRequired,
    FileGatewayPermissionError,
    FileGatewayRequestContext,
    build_file_access_table,
    resolve_file_environment,
)
from memory_system.runtime_scope import project_id_for_task_run
from memory_system.runtime_services import MemoryRuntimeServices
from runtime.file_changes import FileChangeTracker
from runtime_objects.tool_result_storage import (
    DEFAULT_REHYDRATION_SIZE_BYTES,
    MAX_REHYDRATION_SIZE_BYTES,
    read_persisted_tool_result,
)
from runtime_encoding import build_windows_powershell_command, is_windows, utf8_subprocess_text_kwargs
from runtime.tool_runtime.docker_sandbox_backend import DockerSandboxBackend
from runtime.tool_runtime.tool_definition import ToolPermissionResult, ToolValidationResult
from runtime.tool_runtime.read_file_window import (
    READ_FILE_DEFAULT_LINE_COUNT,
    READ_FILE_MAX_LINE_COUNT,
    build_read_file_error_result,
    build_read_file_window_result,
)
from runtime.tool_runtime.tool_result_envelope import (
    ToolResultEnvelope,
    build_tool_result_envelope_id,
    build_tool_result_idempotency_key,
    infer_file_state_events,
)
from runtime.tool_runtime.tool_use_context import ToolUseContext

if TYPE_CHECKING:
    from capability_system.tools.native_tool_catalog import ToolDefinition as CapabilityToolDefinition


NATIVE_RUNTIME_TOOL_NAMES = {
    "read_file",
    "read_persisted_tool_result",
    "read_structured_file",
    "search_files",
    "search_text",
    "glob_paths",
    "list_dir",
    "stat_path",
    "path_exists",
    "write_file",
    "edit_file",
    "terminal",
    "python_repl",
    "memory_search",
}

def build_native_runtime_tool(
    *,
    capability_definition: CapabilityToolDefinition,
) -> Any | None:
    name = str(capability_definition.name or "").strip()
    if name == "read_file":
        return NativeReadFileTool(capability_definition)
    if name == "read_persisted_tool_result":
        return NativeReadPersistedToolResultTool(capability_definition)
    if name == "write_file":
        return NativeWriteFileTool(capability_definition)
    if name == "edit_file":
        return NativeEditFileTool(capability_definition)
    if name == "terminal":
        return NativeTerminalTool(capability_definition)
    if name == "python_repl":
        return NativePythonReplTool(capability_definition)
    if name == "memory_search":
        return NativeMemorySearchTool(capability_definition)
    if name == "read_structured_file":
        return NativeReadStructuredFileTool(capability_definition)
    if name == "search_files":
        return NativeSearchFilesTool(capability_definition)
    if name == "search_text":
        return NativeSearchTextTool(capability_definition)
    if name == "glob_paths":
        return NativeGlobPathsTool(capability_definition)
    if name == "list_dir":
        return NativeListDirTool(capability_definition)
    if name == "stat_path":
        return NativeStatPathTool(capability_definition)
    if name == "path_exists":
        return NativePathExistsTool(capability_definition)
    return None


@dataclass(slots=True)
class _NativeToolBase:
    capability_definition: CapabilityToolDefinition
    input_schema: Any = None
    output_schema: Any = None

    @property
    def name(self) -> str:
        return self.capability_definition.name

    @property
    def operation_id(self) -> str:
        return self.capability_definition.operation_id

    def validate_input(self, args: dict[str, Any], context: ToolUseContext) -> ToolValidationResult:
        required = [
            str(item).strip()
            for item in list(self.capability_definition.contract.required_inputs or [])
            if str(item).strip()
        ]
        missing = [name for name in required if name not in dict(args or {})]
        if missing:
            return ToolValidationResult(
                allowed=False,
                reason="missing_required_tool_inputs",
                repair_instruction="Retry the tool call with required argument(s): " + ", ".join(missing) + ".",
                normalized_args=dict(args or {}),
                diagnostics={"missing_inputs": missing},
            )
        return ToolValidationResult(allowed=True, normalized_args=dict(args or {}))

    def check_permissions(self, args: dict[str, Any], context: ToolUseContext) -> ToolPermissionResult:
        return ToolPermissionResult(allowed=True, decision="allow")

    def _files(self, context: ToolUseContext) -> WorkspaceFileService:
        return WorkspaceFileService(context.workspace_root)

    def _file_gateway(self, context: ToolUseContext) -> FileGateway | None:
        config = _file_management_config(context)
        if not config:
            return None
        profile_id = str(config.get("profile_id") or "").strip()
        if not profile_id:
            return None
        environment = resolve_file_environment(
            profile_id,
            repository_requirements=dict(config.get("repository_requirements") or {}),
        )
        table = build_file_access_table(
            environment,
            task_file_requirements=dict(config.get("task_file_requirements") or {}),
            agent_allowed_actions=tuple(
                str(item)
                for item in list(config.get("agent_allowed_file_actions") or [])
                if str(item).strip()
            ),
            table_id=str(config.get("file_access_table_id") or ""),
        )
        project_root = _real_workspace_root(context)
        sandbox_root = context.sandbox_root or _sandbox_root_from_policy(context)
        managed_storage_root = _managed_storage_root(context, project_root)
        return FileGateway.for_roots(
            environment=environment,
            access_table=table,
            project_root=project_root,
            sandbox_root=sandbox_root,
            managed_storage_root=managed_storage_root,
            runtime_output_root=_runtime_output_root(context, managed_storage_root),
        )

    def _gateway_context(self, context: ToolUseContext) -> FileGatewayRequestContext:
        return FileGatewayRequestContext(
            task_run_id=context.task_run_id,
            agent_run_id=context.agent_run_id,
            tool_call_id=context.tool_call_id,
            actor_id=context.agent_run_id,
        )

    def _envelope(
        self,
        *,
        tool_args: dict[str, Any],
        status: str,
        text: str,
        structured_payload: dict[str, Any] | None = None,
        observed_paths: tuple[str, ...] = (),
        artifact_refs: tuple[dict[str, Any], ...] = (),
        command_receipt: dict[str, Any] | None = None,
        matched_paths: tuple[str, ...] = (),
        written_paths: tuple[str, ...] = (),
        file_state_events: tuple[dict[str, Any], ...] = (),
        execution_receipt: dict[str, Any] | None = None,
    ) -> ToolResultEnvelope:
        payload = dict(structured_payload or {})
        if observed_paths:
            payload["observed_paths"] = list(observed_paths)
        if matched_paths:
            payload["matched_paths"] = list(matched_paths)
        if written_paths:
            payload["written_paths"] = list(written_paths)
        if artifact_refs:
            payload["artifact_refs"] = [dict(item) for item in artifact_refs]
        inferred_file_state_events = tuple(file_state_events) or infer_file_state_events(
            tool_name=self.name,
            tool_args=dict(tool_args or {}),
            status=status,
            structured_payload=payload,
            observed_paths=tuple(observed_paths),
            matched_paths=tuple(matched_paths),
            written_paths=tuple(written_paths),
        )
        if inferred_file_state_events:
            payload["file_state_events"] = [dict(item) for item in inferred_file_state_events]
        if command_receipt:
            payload["command_receipt"] = dict(command_receipt)
        receipt = dict(execution_receipt or {})
        idempotency_key = str(receipt.get("idempotency_key") or "").strip() or build_tool_result_idempotency_key(
            caller_ref=context_caller_ref(receipt),
            action_request_id=context_action_request_id(receipt),
            tool_call_id=context_tool_call_id(receipt),
            tool_name=self.name,
            tool_args=dict(tool_args or {}),
        )
        return ToolResultEnvelope(
            envelope_id=build_tool_result_envelope_id(idempotency_key),
            tool_name=self.name,
            tool_args=dict(tool_args or {}),
            status=status,
            tool_call_id=str(context_tool_call_id(execution_receipt) or ""),
            action_request_id=str(context_action_request_id(execution_receipt) or ""),
            caller_kind=str(context_caller_kind(execution_receipt) or ""),
            caller_ref=str(context_caller_ref(execution_receipt) or ""),
            text=str(text or ""),
            structured_payload=payload,
            observed_paths=tuple(observed_paths),
            matched_paths=tuple(matched_paths),
            written_paths=tuple(written_paths),
            artifact_refs=tuple(dict(item) for item in artifact_refs),
            file_state_events=tuple(dict(item) for item in inferred_file_state_events),
            command_receipt=dict(command_receipt or {}),
            execution_receipt=receipt,
            idempotency_key=idempotency_key,
            error=str(text or "") if status == "error" else "",
        )


class NativeReadFileTool(_NativeToolBase):
    def validate_input(self, args: dict[str, Any], context: ToolUseContext) -> ToolValidationResult:
        base = super().validate_input(args, context)
        if not base.allowed:
            return base
        payload = dict(args or {})
        allowed = {"path", "start_line", "line_count", "read_intent"}
        unexpected = sorted(str(key) for key in payload if str(key) not in allowed)
        if unexpected:
            return ToolValidationResult(
                allowed=False,
                reason="unexpected_tool_inputs",
                repair_instruction=(
                    "read_file accepts only path, start_line, and line_count. "
                    "start_line is a one-based line number and line_count is the number of lines to return. "
                    "Remove unsupported argument(s): " + ", ".join(unexpected) + "."
                ),
                normalized_args=payload,
                diagnostics={"unexpected_inputs": unexpected, "allowed_inputs": sorted(allowed)},
            )
        start_line, start_line_error = _coerce_read_window_int(
            payload.get("start_line"),
            default=1,
            minimum=1,
            maximum=None,
            field_name="start_line",
        )
        if start_line_error:
            return ToolValidationResult(
                allowed=False,
                reason="invalid_tool_input",
                repair_instruction=start_line_error,
                normalized_args=payload,
                diagnostics={"field": "start_line"},
            )
        line_count, line_count_error = _coerce_read_window_int(
            payload.get("line_count"),
            default=READ_FILE_DEFAULT_LINE_COUNT,
            minimum=1,
            maximum=READ_FILE_MAX_LINE_COUNT,
            field_name="line_count",
        )
        if line_count_error:
            return ToolValidationResult(
                allowed=False,
                reason="invalid_tool_input",
                repair_instruction=line_count_error,
                normalized_args=payload,
                diagnostics={"field": "line_count"},
            )
        return ToolValidationResult(
            allowed=True,
            normalized_args={
                "path": str(payload.get("path") or "").strip(),
                "start_line": start_line,
                "line_count": line_count,
                "read_intent": _normalize_read_intent(payload.get("read_intent")),
            },
        )

    async def call(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        return await asyncio.to_thread(self._call_sync, dict(args or {}), context)

    def _call_sync(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        path = str(args.get("path") or "").strip()
        start_line = int(args.get("start_line") or 1)
        line_count = int(args.get("line_count") or READ_FILE_DEFAULT_LINE_COUNT)
        read_intent = _normalize_read_intent(args.get("read_intent"))
        gateway = self._file_gateway(context)
        if gateway is not None:
            return self._call_gateway_read(args=args, context=context, gateway=gateway, path=path)
        files = self._files(context)
        try:
            file_path = files.resolve(path, require_path=True)
            if not file_path.exists():
                raise FileNotFoundError("file does not exist")
            if file_path.is_dir():
                raise IsADirectoryError("path is a directory")
            content = files.read_text(file_path, limit=None)
            rel = files.relative_path(file_path)
            window = build_read_file_window_result(
                content,
                path=rel,
                start_line=start_line,
                line_count=line_count,
            )
            tool_result = window.to_dict(include_text=False)
            if read_intent:
                tool_result["read_intent"] = read_intent
            unchanged = _unchanged_previous_read_window(
                context=context,
                path=rel,
                start_line=window.start_line,
                end_line=window.end_line,
                content_sha256=window.content_sha256,
            )
            text = window.text
            if unchanged:
                tool_result.update(unchanged)
                text = _file_unchanged_read_stub(
                    path=rel,
                    start_line=window.start_line,
                    end_line=window.end_line,
                    previous_observation_ref=str(unchanged.get("previous_observation_ref") or ""),
                )
        except Exception as exc:
            return self._envelope(
                tool_args=args,
                status="error",
                text=f"Read failed: {exc}",
                structured_payload={"tool_result": build_read_file_error_result(path=path, error=str(exc))},
                execution_receipt=context.execution_receipt,
            )
        return self._envelope(
            tool_args=args,
            status="ok",
            text=text,
            structured_payload={"tool_result": tool_result},
            observed_paths=(rel,),
            execution_receipt=context.execution_receipt,
        )

    def _call_gateway_read(
        self,
        *,
        args: dict[str, Any],
        context: ToolUseContext,
        gateway: FileGateway,
        path: str,
    ) -> ToolResultEnvelope:
        start_line = int(args.get("start_line") or 1)
        line_count = int(args.get("line_count") or READ_FILE_DEFAULT_LINE_COUNT)
        read_intent = _normalize_read_intent(args.get("read_intent"))
        repository_id = _repository_for_action(context, "read")
        try:
            result = gateway.read_text(
                repository_id,
                path,
                self._gateway_context(context),
                operation_id=self.operation_id,
            )
            window = build_read_file_window_result(
                result.content,
                path=result.logical_path,
                repository_id=result.repository_id,
                managed_file_ref=result.managed_file_ref.to_dict(),
                start_line=start_line,
                line_count=line_count,
            )
            tool_result = window.to_dict(include_text=False)
            if read_intent:
                tool_result["read_intent"] = read_intent
            unchanged = _unchanged_previous_read_window(
                context=context,
                path=result.logical_path,
                start_line=window.start_line,
                end_line=window.end_line,
                content_sha256=window.content_sha256,
            )
            text = window.text
            if unchanged:
                tool_result.update(unchanged)
                text = _file_unchanged_read_stub(
                    path=result.logical_path,
                    start_line=window.start_line,
                    end_line=window.end_line,
                    previous_observation_ref=str(unchanged.get("previous_observation_ref") or ""),
                )
        except Exception as exc:
            return self._envelope(
                tool_args=args,
                status="error",
                text=f"Read failed: {exc}",
                structured_payload={
                    "tool_result": build_read_file_error_result(
                        path=path,
                        error=str(exc),
                        repository_id=repository_id,
                    )
                },
                execution_receipt=context.execution_receipt,
            )
        return self._envelope(
            tool_args=args,
            status="ok",
            text=text,
            structured_payload={
                "tool_result": tool_result,
                "file_gateway": {
                    "access_decision": result.access_decision,
                    "root_binding": result.metadata.get("root_binding"),
                },
            },
            observed_paths=(result.logical_path,),
            execution_receipt=context.execution_receipt,
        )


class NativeReadPersistedToolResultTool(_NativeToolBase):
    def validate_input(self, args: dict[str, Any], context: ToolUseContext) -> ToolValidationResult:
        base = super().validate_input(args, context)
        if not base.allowed:
            return base
        payload = dict(args or {})
        replacement_id = str(payload.get("replacement_id") or "").strip()
        path = str(payload.get("path") or "").strip()
        if not replacement_id and not path:
            return ToolValidationResult(
                allowed=False,
                reason="missing_required_tool_inputs",
                repair_instruction="Retry with replacement_id or path from the rehydration_plan.",
                normalized_args=payload,
                diagnostics={"missing_inputs": ["replacement_id_or_path"]},
            )
        return ToolValidationResult(
            allowed=True,
            normalized_args={
                "replacement_id": replacement_id,
                "path": path,
                "task_run_id": str(payload.get("task_run_id") or context.task_run_id or "").strip(),
                "start_byte": payload.get("start_byte", 0),
                "max_bytes": payload.get("max_bytes", DEFAULT_REHYDRATION_SIZE_BYTES),
            },
        )

    async def call(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        return await asyncio.to_thread(self._call_sync, dict(args or {}), context)

    def _call_sync(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        result = read_persisted_tool_result(
            root_dir=_real_workspace_root(context),
            replacement_id=str(args.get("replacement_id") or ""),
            path=str(args.get("path") or ""),
            task_run_id=str(args.get("task_run_id") or context.task_run_id or ""),
            start_byte=args.get("start_byte", 0),
            max_bytes=args.get("max_bytes", DEFAULT_REHYDRATION_SIZE_BYTES),
            trusted_roots=_runtime_context_storage_roots(context),
        )
        if result.get("ok") is not True:
            error = str(result.get("error") or "persisted tool result read failed")
            return self._envelope(
                tool_args=args,
                status="error",
                text=f"Read persisted tool result failed: {error}",
                structured_payload={
                    "tool_result": {
                        "kind": "persisted_tool_result",
                        "status": "error",
                        "replacement_id": str(args.get("replacement_id") or ""),
                        "path": str(args.get("path") or ""),
                        "error": error,
                    },
                    "structured_error": {
                        "code": "persisted_tool_result_read_failed",
                        "message": error,
                        "retryable": False,
                    },
                },
                execution_receipt=context.execution_receipt,
            )
        tool_result = {
            "kind": "persisted_tool_result",
            "status": "ok",
            "replacement_id": str(result.get("replacement_id") or ""),
            "path": str(result.get("path") or ""),
            "start_byte": int(result.get("start_byte") or 0),
            "returned_bytes": int(result.get("returned_bytes") or 0),
            "total_bytes": int(result.get("total_bytes") or 0),
            "truncated": bool(result.get("truncated")),
            "authority": str(result.get("authority") or "runtime.tool_result_rehydration"),
        }
        observed = (tool_result["path"],) if tool_result["path"] else ()
        return self._envelope(
            tool_args=args,
            status="ok",
            text=str(result.get("content") or ""),
            structured_payload={"tool_result": tool_result},
            observed_paths=observed,
            execution_receipt=context.execution_receipt,
        )


def _coerce_read_window_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int | None,
    field_name: str,
) -> tuple[int, str]:
    if value in (None, ""):
        return default, ""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default, f"{field_name} must be an integer."
    if number < minimum:
        return default, f"{field_name} must be >= {minimum}."
    if maximum is not None and number > maximum:
        return default, f"{field_name} must be <= {maximum}."
    return number, ""


_READ_INTENT_VALUES = {
    "edit_target",
    "verify_behavior",
    "understand_api",
    "locate_symbol",
    "inspect_dependency",
    "recover_failure",
}


def _normalize_read_intent(value: Any) -> str:
    intent = str(value or "").strip()
    return intent if intent in _READ_INTENT_VALUES else ""


def _unchanged_previous_read_window(
    *,
    context: ToolUseContext,
    path: str,
    start_line: int,
    end_line: int,
    content_sha256: str,
) -> dict[str, Any]:
    task_run_id = str(getattr(context, "task_run_id", "") or "").strip()
    if not task_run_id or not content_sha256:
        return {}
    try:
        from runtime.memory.file_state_store import FileStateAuthorityStore

        for root in _runtime_context_storage_roots(context):
            state = FileStateAuthorityStore(root).load(task_run_id)
            for file_state in state.files:
                if str(file_state.path or "").replace("\\", "/").strip().strip("/") != str(path or "").replace("\\", "/").strip().strip("/"):
                    continue
                if str(file_state.content_sha256 or "") != str(content_sha256 or ""):
                    continue
                for segment in file_state.read_ranges:
                    if segment.stale:
                        continue
                    if int(segment.start_line) != int(start_line) or int(segment.end_line) != int(end_line):
                        continue
                    if str(segment.content_sha256 or "") != str(content_sha256 or ""):
                        continue
                    return {
                        "file_unchanged": True,
                        "content_omitted": True,
                        "previous_observation_ref": str(segment.observation_ref or ""),
                    }
    except Exception:
        return {}
    return {}


def _file_unchanged_read_stub(
    *,
    path: str,
    start_line: int,
    end_line: int,
    previous_observation_ref: str,
) -> str:
    ref = f" Previous observation: {previous_observation_ref}." if previous_observation_ref else ""
    return f"File unchanged for {path}:{start_line}-{end_line}; content omitted. Use the earlier read result for this exact window.{ref}"


class NativeWriteFileTool(_NativeToolBase):
    def check_permissions(self, args: dict[str, Any], context: ToolUseContext) -> ToolPermissionResult:
        gateway = self._file_gateway(context)
        gateway_permission = _check_gateway_file_permission(
            tool=self,
            args=args,
            context=context,
            action="write",
        )
        if gateway_permission is not None and not gateway_permission.allowed:
            return gateway_permission
        path = str(args.get("path") or "").strip()
        if gateway is not None:
            try:
                existing = gateway.existing_file_path(_repository_for_action(context, "write"), path)
            except (KeyError, ValueError) as exc:
                return ToolPermissionResult(
                    allowed=False,
                    decision="deny",
                    reason="file_gateway_permission_denied",
                    repair_instruction="Retry with a path and operation allowed by the active task environment.",
                    diagnostics={"action": "write", "path": path, "error": str(exc)},
                )
        else:
            files = self._files(context)
            existing = _resolve_existing_file(files, path)
        if existing is not None and not _overwrite_intent_is_explicit(args, existing, context):
            return ToolPermissionResult(
                allowed=False,
                decision="deny",
                reason="existing_file_overwrite_requires_explicit_intent",
                repair_instruction=(
                    "The target file already exists. Read or inspect it first, then retry with allow_overwrite=true "
                    "or expected_previous_sha256 matching the current file."
                ),
                diagnostics={"path": path, "sha256": _file_sha256(existing)},
            )
        return ToolPermissionResult(allowed=True, decision="allow")

    async def call(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        return await asyncio.to_thread(self._call_sync, dict(args or {}), context)

    def _call_sync(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        path = str(args.get("path") or "").strip()
        content = str(args.get("content") or "")
        gateway = self._file_gateway(context)
        if gateway is not None:
            return self._call_gateway_write(args=args, context=context, gateway=gateway, path=path, content=content)
        try:
            files = self._files(context)
            target_path = files.resolve(path, require_path=True)
            before_content = files.read_text(target_path) if target_path.exists() and target_path.is_file() else None
            file_path = files.write_text(
                path,
                content,
                allow_overwrite=bool(args.get("allow_overwrite") is True),
                expected_previous_sha256=str(args.get("expected_previous_sha256") or ""),
            )
            rel = files.relative_path(file_path)
        except Exception as exc:
            return self._envelope(tool_args=args, status="error", text=f"Write failed: {exc}", execution_receipt=context.execution_receipt)
        artifact = _artifact_ref_for_file(context=context, path=file_path, logical_path=rel, kind="file", source=self.name)
        file_change = _record_text_file_change(
            context=context,
            tool_name=self.name,
            operation_id=self.operation_id,
            logical_path=rel,
            absolute_path=file_path,
            workspace_root=_change_root_for_path(context, file_path),
            before_content=before_content,
            after_content=content,
        )
        return self._envelope(
            tool_args=args,
            status="ok",
            text=f"Write succeeded: {rel}",
            structured_payload={
                "tool_result": {
                    "kind": "file_write",
                    "path": rel,
                    "size_bytes": file_path.stat().st_size,
                    "sha256": _file_sha256(file_path),
                },
                "file_change": file_change,
            },
            observed_paths=(rel,),
            artifact_refs=(artifact,),
            execution_receipt=context.execution_receipt,
        )

    def _call_gateway_write(
        self,
        *,
        args: dict[str, Any],
        context: ToolUseContext,
        gateway: FileGateway,
        path: str,
        content: str,
    ) -> ToolResultEnvelope:
        repository_id = _repository_for_action(context, "write")
        try:
            result = gateway.write_text(
                repository_id,
                path,
                content,
                self._gateway_context(context),
                operation_id=self.operation_id,
                approval_fingerprint=_gateway_approval_fingerprint(context),
            )
        except Exception as exc:
            return self._envelope(tool_args=args, status="error", text=f"Write failed: {exc}", execution_receipt=context.execution_receipt)
        artifact = _artifact_ref_for_gateway_file(context=context, result=result, kind="file", source=self.name)
        receipt = result.receipt.to_dict() if result.receipt is not None else {}
        file_change = _record_text_file_change(
            context=context,
            tool_name=self.name,
            operation_id=self.operation_id,
            logical_path=result.logical_path,
            absolute_path=result.physical_path,
            workspace_root=_gateway_result_root(result) or _change_root_for_path(context, Path(result.physical_path)),
            before_content=result.before_content,
            after_content=result.content,
            metadata={
                "repository_id": result.repository_id,
                "repository_kind": result.repository_kind,
                "file_operation_receipt_id": str(receipt.get("receipt_id") or ""),
            },
        )
        return self._envelope(
            tool_args=args,
            status="ok",
            text=f"Write succeeded: {result.logical_path}",
            structured_payload={
                "tool_result": {
                    "kind": "file_write",
                    "path": result.logical_path,
                    "repository_id": result.repository_id,
                    "managed_file_ref": result.managed_file_ref.to_dict(),
                    "size_bytes": len(content.encode("utf-8")),
                    "sha256": result.managed_file_ref.content_hash,
                },
                "file_gateway": {
                    "access_decision": result.access_decision,
                    "receipt": receipt,
                    "root_binding": result.metadata.get("root_binding"),
                },
                "file_change": file_change,
            },
            observed_paths=(result.logical_path,),
            artifact_refs=(artifact,),
            execution_receipt={**dict(context.execution_receipt), "file_operation_receipt": receipt},
        )


class NativeEditFileTool(_NativeToolBase):
    def check_permissions(self, args: dict[str, Any], context: ToolUseContext) -> ToolPermissionResult:
        gateway_permission = _check_gateway_file_permission(
            tool=self,
            args=args,
            context=context,
            action="edit",
        )
        if gateway_permission is not None and not gateway_permission.allowed:
            return gateway_permission
        return ToolPermissionResult(allowed=True, decision="allow")

    async def call(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        return await asyncio.to_thread(self._call_sync, dict(args or {}), context)

    def _call_sync(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        path = str(args.get("path") or "").strip()
        gateway = self._file_gateway(context)
        if gateway is not None:
            return self._call_gateway_edit(args=args, context=context, gateway=gateway, path=path)
        try:
            files = self._files(context)
            target_path = files.resolve(path, require_path=True)
            before_content = files.read_text(target_path)
            file_path = files.edit_text(path, str(args.get("old_text") or ""), str(args.get("new_text") or ""))
            rel = files.relative_path(file_path)
            after_content = files.read_text(file_path)
        except Exception as exc:
            return self._envelope(tool_args=args, status="error", text=f"Edit failed: {exc}", execution_receipt=context.execution_receipt)
        artifact = _artifact_ref_for_file(context=context, path=file_path, logical_path=rel, kind="file", source=self.name)
        file_change = _record_text_file_change(
            context=context,
            tool_name=self.name,
            operation_id=self.operation_id,
            logical_path=rel,
            absolute_path=file_path,
            workspace_root=_change_root_for_path(context, file_path),
            before_content=before_content,
            after_content=after_content,
        )
        return self._envelope(
            tool_args=args,
            status="ok",
            text=f"Edit succeeded: {rel}",
            structured_payload={
                "tool_result": {
                    "kind": "file_edit",
                    "path": rel,
                    "size_bytes": file_path.stat().st_size,
                    "sha256": _file_sha256(file_path),
                },
                "file_change": file_change,
            },
            observed_paths=(rel,),
            artifact_refs=(artifact,),
            execution_receipt=context.execution_receipt,
        )

    def _call_gateway_edit(
        self,
        *,
        args: dict[str, Any],
        context: ToolUseContext,
        gateway: FileGateway,
        path: str,
    ) -> ToolResultEnvelope:
        repository_id = _repository_for_action(context, "edit")
        try:
            result = gateway.edit_text(
                repository_id,
                path,
                str(args.get("old_text") or ""),
                str(args.get("new_text") or ""),
                self._gateway_context(context),
                operation_id=self.operation_id,
                approval_fingerprint=_gateway_approval_fingerprint(context),
            )
        except Exception as exc:
            return self._envelope(tool_args=args, status="error", text=f"Edit failed: {exc}", execution_receipt=context.execution_receipt)
        artifact = _artifact_ref_for_gateway_file(context=context, result=result, kind="file", source=self.name)
        receipt = result.receipt.to_dict() if result.receipt is not None else {}
        file_change = _record_text_file_change(
            context=context,
            tool_name=self.name,
            operation_id=self.operation_id,
            logical_path=result.logical_path,
            absolute_path=result.physical_path,
            workspace_root=_gateway_result_root(result) or _change_root_for_path(context, Path(result.physical_path)),
            before_content=result.before_content,
            after_content=result.content,
            metadata={
                "repository_id": result.repository_id,
                "repository_kind": result.repository_kind,
                "file_operation_receipt_id": str(receipt.get("receipt_id") or ""),
            },
        )
        return self._envelope(
            tool_args=args,
            status="ok",
            text=f"Edit succeeded: {result.logical_path}",
            structured_payload={
                "tool_result": {
                    "kind": "file_edit",
                    "path": result.logical_path,
                    "repository_id": result.repository_id,
                    "managed_file_ref": result.managed_file_ref.to_dict(),
                    "size_bytes": len(result.content.encode("utf-8")),
                    "sha256": result.managed_file_ref.content_hash,
                },
                "file_gateway": {
                    "access_decision": result.access_decision,
                    "receipt": receipt,
                    "root_binding": result.metadata.get("root_binding"),
                },
                "file_change": file_change,
            },
            observed_paths=(result.logical_path,),
            artifact_refs=(artifact,),
            execution_receipt={**dict(context.execution_receipt), "file_operation_receipt": receipt},
        )


class NativeTerminalTool(_NativeToolBase):
    async def call(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        return await asyncio.to_thread(self._call_sync, dict(args or {}), context)

    def _call_sync(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        command = str(args.get("command") or "").strip()
        structured_payload = _tool_call_structured_payload(args)
        blocked_reason = validate_sandbox_command_text(command, kind="command", workspace_root=context.workspace_root)
        if blocked_reason:
            receipt = {"command": command, "exit_code": 1, "passed": False, "output_preview": blocked_reason}
            return self._envelope(
                tool_args=args,
                status="error",
                text=blocked_reason,
                structured_payload=structured_payload,
                command_receipt=receipt,
                execution_receipt=context.execution_receipt,
            )
        settings = get_settings()
        before_files = _capture_command_file_snapshot(context, force=False, command=command)
        docker = DockerSandboxBackend()
        if docker.is_enabled(context.sandbox_policy):
            sandbox_root = context.sandbox_root or context.workspace_root
            execution = docker.run_shell(
                command=command,
                workspace_root=context.environment_snapshot.get("workspace_root") or context.workspace_root,
                sandbox_root=sandbox_root,
                sandbox_policy={
                    **dict(context.sandbox_policy),
                    "sbx": {
                        **dict(dict(context.sandbox_policy).get("sbx") or {}),
                        "timeout_seconds": settings.terminal_timeout_seconds,
                    },
                },
            )
            file_changes = _record_command_file_changes(
                context=context,
                before_snapshot=before_files,
                tool_name=self.name,
                operation_id=self.operation_id,
                command_label=command,
            )
            if file_changes:
                structured_payload = {**structured_payload, "file_changes": file_changes}
            return self._envelope(
                tool_args=args,
                status="ok" if execution.exit_code == 0 else "error",
                text=execution.output,
                structured_payload=structured_payload,
                command_receipt={"command": command, **execution.receipt},
                execution_receipt=context.execution_receipt,
            )
        shell_command = build_windows_powershell_command(command) if is_windows() else ["bash", "-lc", command]
        try:
            completed = subprocess.run(
                shell_command,
                cwd=context.workspace_root,
                capture_output=True,
                timeout=settings.terminal_timeout_seconds,
                check=False,
                **utf8_subprocess_text_kwargs(),
            )
            combined = ((completed.stdout or "") + (completed.stderr or "")).strip() or "[no output]"
            exit_code = int(completed.returncode or 0)
        except subprocess.TimeoutExpired:
            combined = f"Timed out after {settings.terminal_timeout_seconds} seconds."
            exit_code = 124
        text = combined[:5000]
        file_changes = _record_command_file_changes(
            context=context,
            before_snapshot=before_files,
            tool_name=self.name,
            operation_id=self.operation_id,
            command_label=command,
        )
        if file_changes:
            structured_payload = {**structured_payload, "file_changes": file_changes}
        receipt = {"command": command, "exit_code": exit_code, "passed": exit_code == 0, "output_preview": text[:500]}
        return self._envelope(
            tool_args=args,
            status="ok" if exit_code == 0 else "error",
            text=text,
            structured_payload=structured_payload,
            command_receipt=receipt,
            execution_receipt=context.execution_receipt,
        )


class NativePythonReplTool(_NativeToolBase):
    async def call(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        return await asyncio.to_thread(self._call_sync, dict(args or {}), context)

    def _call_sync(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        code = str(args.get("code") or "")
        blocked_reason = validate_sandbox_command_text(code, kind="code", workspace_root=context.workspace_root)
        if blocked_reason:
            receipt = {"command": "python -c <code>", "exit_code": 1, "passed": False, "output_preview": blocked_reason}
            return self._envelope(
                tool_args=args,
                status="error",
                text=blocked_reason,
                command_receipt=receipt,
                execution_receipt=context.execution_receipt,
            )
        before_files = _capture_command_file_snapshot(context, force=True, command="python -c <code>")
        docker = DockerSandboxBackend()
        if docker.is_enabled(context.sandbox_policy):
            sandbox_root = context.sandbox_root or context.workspace_root
            execution = docker.run_python(
                code=code,
                workspace_root=context.environment_snapshot.get("workspace_root") or context.workspace_root,
                sandbox_root=sandbox_root,
                sandbox_policy={
                    **dict(context.sandbox_policy),
                    "sbx": {
                        **dict(dict(context.sandbox_policy).get("sbx") or {}),
                        "timeout_seconds": min(get_settings().terminal_timeout_seconds, 30),
                    },
                },
            )
            file_changes = _record_command_file_changes(
                context=context,
                before_snapshot=before_files,
                tool_name=self.name,
                operation_id=self.operation_id,
                command_label="python -c <code>",
            )
            return self._envelope(
                tool_args=args,
                status="ok" if execution.exit_code == 0 else "error",
                text=execution.output,
                structured_payload={"file_changes": file_changes} if file_changes else {},
                command_receipt={"command": "python -c <code>", **execution.receipt},
                execution_receipt=context.execution_receipt,
            )
        try:
            completed = subprocess.run(
                [sys.executable, "-c", code],
                cwd=context.workspace_root,
                capture_output=True,
                timeout=15,
                check=False,
                **utf8_subprocess_text_kwargs(),
            )
            combined = ((completed.stdout or "") + (completed.stderr or "")).strip() or "[no output]"
            exit_code = int(completed.returncode or 0)
        except subprocess.TimeoutExpired:
            combined = "Timed out after 15 seconds."
            exit_code = 124
        text = combined[:5000]
        file_changes = _record_command_file_changes(
            context=context,
            before_snapshot=before_files,
            tool_name=self.name,
            operation_id=self.operation_id,
            command_label="python -c <code>",
        )
        receipt = {"command": "python -c <code>", "exit_code": exit_code, "passed": exit_code == 0, "output_preview": text[:500]}
        return self._envelope(
            tool_args=args,
            status="ok" if exit_code == 0 else "error",
            text=text,
            structured_payload={"file_changes": file_changes} if file_changes else {},
            command_receipt=receipt,
            execution_receipt=context.execution_receipt,
        )


class NativeMemorySearchTool(_NativeToolBase):
    def validate_input(self, args: dict[str, Any], context: ToolUseContext) -> ToolValidationResult:
        base = super().validate_input(args, context)
        if not base.allowed:
            return base
        payload = dict(args or {})
        query = str(payload.get("query") or "").strip()
        if not query:
            return ToolValidationResult(
                allowed=False,
                reason="memory_search_query_required",
                repair_instruction="memory_search requires a non-empty query.",
                normalized_args=payload,
                diagnostics={"missing_inputs": ["query"]},
            )
        task_scope = str(payload.get("task_run_id") or context.task_run_id or "").strip()
        project_scope = str(payload.get("project_id") or "").strip()
        if not project_scope and task_scope:
            project_scope = project_id_for_task_run(_native_runtime_base_dir(context), task_scope)
        if not task_scope and not project_scope:
            return ToolValidationResult(
                allowed=False,
                reason="memory_search_scope_required",
                repair_instruction="memory_search requires runtime-bound task_run_id or project_id. Reassemble the runtime with memory scope before retrying.",
                normalized_args=payload,
                diagnostics={"missing_inputs": ["task_run_id_or_project_id"]},
            )
        return ToolValidationResult(
            allowed=True,
            normalized_args={
                "query": query,
                "task_run_id": task_scope,
                "project_id": project_scope,
                "repositories": [str(item).strip() for item in list(payload.get("repositories") or []) if str(item).strip()],
                "collections": [str(item).strip() for item in list(payload.get("collections") or []) if str(item).strip()],
                "limit": max(1, min(int(payload.get("limit") or 8), 20)),
            },
        )

    async def call(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        return await asyncio.to_thread(self._call_sync, dict(args or {}), context)

    def _call_sync(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        try:
            payload = _memory_search_payload(args, root_dir=_native_runtime_base_dir(context))
        except Exception as exc:
            return self._envelope(
                tool_args=args,
                status="error",
                text=f"memory_search failed: {exc}",
                structured_payload={"tool_result": {"kind": "memory_search", "status": "error", "error": str(exc)}},
                execution_receipt=context.execution_receipt,
            )
        return self._envelope(
            tool_args=args,
            status="ok",
            text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            structured_payload={"tool_result": {"kind": "memory_search", **payload}},
            execution_receipt=context.execution_receipt,
        )


class NativeReadStructuredFileTool(_NativeToolBase):
    async def call(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        return await asyncio.to_thread(self._call_sync, dict(args or {}), context)

    def _call_sync(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        path = str(args.get("path") or "").strip()
        files = self._files(context)
        try:
            file_path = files.resolve(path, require_path=True)
            if not file_path.exists():
                raise FileNotFoundError("file does not exist")
            if file_path.is_dir():
                raise IsADirectoryError("path is a directory")
            data, data_format = _parse_structured_file(file_path)
        except Exception as exc:
            return self._envelope(
                tool_args=args,
                status="error",
                text=f"Structured read failed: {exc}",
                structured_payload={"tool_result": {"kind": "structured_file", "status": "error", "error": str(exc)}},
                execution_receipt=context.execution_receipt,
            )
        summary = _summarize(data)
        rel = files.relative_path(file_path)
        return self._envelope(
            tool_args=args,
            status="ok",
            text=summary,
            structured_payload={
                "tool_result": {
                    "kind": "structured_file",
                    "path": rel,
                    "format": data_format,
                    "root_type": type(data).__name__,
                    "data": data,
                    "summary": summary,
                }
            },
            observed_paths=(rel,),
            execution_receipt=context.execution_receipt,
        )


class NativeSearchFilesTool(_NativeToolBase):
    async def call(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        return await asyncio.to_thread(self._call_sync, dict(args or {}), context)

    def _call_sync(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        query = str(args.get("query") or "").strip()
        if not query:
            return self._envelope(tool_args=args, status="error", text="Search failed: query is required.", execution_receipt=context.execution_receipt)
        files = self._files(context)
        using_default_roots = not [str(item or "").strip() for item in list(args.get("roots") or [])]
        safe_roots = files.safe_roots(args.get("roots"))
        if not safe_roots:
            return self._envelope(tool_args=args, status="error", text="Search failed: no safe search roots.", execution_receipt=context.execution_receipt)
        limit = max(1, min(int(args.get("max_results") or 20), 100))
        paths = _workspace_files(files, safe_roots=safe_roots, using_default_roots=using_default_roots)
        terms = _query_terms(query)
        matches = [path for path in paths if any(term in path.lower() for term in terms)]
        matched = tuple(sorted(dict.fromkeys(matches))[:limit])
        text = "\n".join(f"[{index}] {path}" for index, path in enumerate(matched, start=1)) or f"没有找到匹配项：{query}"
        return self._envelope(
            tool_args=args,
            status="ok",
            text=text,
            structured_payload={"tool_result": {"kind": "path_search", "query": query, "matches": list(matched)}},
            matched_paths=matched,
            execution_receipt=context.execution_receipt,
        )


class NativeSearchTextTool(_NativeToolBase):
    async def call(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        return await asyncio.to_thread(self._call_sync, dict(args or {}), context)

    def _call_sync(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        query = str(args.get("query") or "").strip()
        if not query:
            return self._envelope(tool_args=args, status="error", text="Search failed: query is required.", execution_receipt=context.execution_receipt)
        files = self._files(context)
        limit = _search_result_limit(args)
        offset = max(0, int(args.get("offset") or 0))
        scan_limit = min(100, limit + offset + 1)
        glob = str(args.get("glob") or "").strip()
        output_mode = _normalize_search_output_mode(args.get("output_mode"))
        context_lines = max(0, min(int(args.get("context") or 0), 20))
        case_sensitive = bool(args.get("case_sensitive") is True)
        requested_paths = _nonempty_path_args(args.get("paths"))
        if requested_paths:
            target_paths, path_error = _resolve_search_paths(files, requested_paths)
            if path_error:
                return self._envelope(
                    tool_args=args,
                    status="error",
                    text=f"Search failed: {path_error}",
                    structured_payload={"tool_result": {"kind": "text_search", "status": "error", "error": path_error}},
                    execution_receipt=context.execution_receipt,
                )
            matches = _search_text_in_paths(files, query=query, paths=target_paths, glob=glob, limit=scan_limit, case_sensitive=case_sensitive)
            total_matches = len(matches)
            matches = _slice_search_matches(matches, offset=offset, limit=limit)
            matched_paths = tuple(dict.fromkeys(str(item.get("path") or "") for item in matches if str(item.get("path") or "").strip()))
            text = _format_text_search_output(matches, query=query, output_mode=output_mode)
            return self._envelope(
                tool_args=args,
                status="ok",
                text=text,
                structured_payload={
                    "tool_result": _text_search_tool_result(
                        query=query,
                        matches=matches,
                        requested_paths=requested_paths,
                        output_mode=output_mode,
                        limit=limit,
                        offset=offset,
                        total_matches=total_matches,
                        context_lines=context_lines,
                    )
                },
                matched_paths=matched_paths,
                execution_receipt=context.execution_receipt,
            )
        roots_error = _roots_file_misuse_error(files, args.get("roots"))
        if roots_error:
            return self._envelope(
                tool_args=args,
                status="error",
                text=f"Search failed: {roots_error}",
                structured_payload={"tool_result": {"kind": "text_search", "status": "error", "error": roots_error}},
                execution_receipt=context.execution_receipt,
            )
        using_default_roots = not [str(item or "").strip() for item in list(args.get("roots") or [])]
        safe_roots = files.safe_roots(args.get("roots"))
        if not safe_roots:
            return self._envelope(tool_args=args, status="error", text="Search failed: no safe search roots.", execution_receipt=context.execution_receipt)
        matches = _search_text(
            files,
            query=query,
            safe_roots=safe_roots,
            glob=glob,
            limit=scan_limit,
            using_default_roots=using_default_roots,
            case_sensitive=case_sensitive,
        )
        total_matches = len(matches)
        matches = _slice_search_matches(matches, offset=offset, limit=limit)
        matched_paths = tuple(dict.fromkeys(str(item.get("path") or "") for item in matches if str(item.get("path") or "").strip()))
        text = _format_text_search_output(matches, query=query, output_mode=output_mode)
        return self._envelope(
            tool_args=args,
            status="ok",
            text=text,
            structured_payload={
                "tool_result": _text_search_tool_result(
                    query=query,
                    matches=matches,
                    requested_paths=(),
                    output_mode=output_mode,
                    limit=limit,
                    offset=offset,
                    total_matches=total_matches,
                    context_lines=context_lines,
                )
            },
            matched_paths=matched_paths,
            execution_receipt=context.execution_receipt,
        )


class NativeGlobPathsTool(_NativeToolBase):
    async def call(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        return await asyncio.to_thread(self._call_sync, dict(args or {}), context)

    def _call_sync(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        pattern = str(args.get("pattern") or "").strip()
        try:
            matches = tuple(self._files(context).glob_paths(pattern, max_results=int(args.get("max_results") or 80)))
        except Exception as exc:
            return self._envelope(tool_args=args, status="error", text=f"Glob failed: {exc}", execution_receipt=context.execution_receipt)
        return self._envelope(
            tool_args=args,
            status="ok",
            text="\n".join(matches) or "No paths matched.",
            structured_payload={"tool_result": {"kind": "glob_paths", "pattern": pattern, "matches": list(matches)}},
            matched_paths=matches,
            execution_receipt=context.execution_receipt,
        )


class NativeListDirTool(_NativeToolBase):
    async def call(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        return await asyncio.to_thread(self._call_sync, dict(args or {}), context)

    def _call_sync(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        path = str(args.get("path") or ".").strip() or "."
        files = self._files(context)
        try:
            entries = files.list_dir(path)
        except Exception as exc:
            return self._envelope(tool_args=args, status="error", text=f"List failed: {exc}", execution_receipt=context.execution_receipt)
        limit = max(1, min(int(args.get("max_entries") or 80), 300))
        rows: list[dict[str, Any]] = []
        for item in entries[:limit]:
            rows.append(
                {
                    "path": files.relative_path(item),
                    "kind": "dir" if item.is_dir() else "file",
                    "size_bytes": 0 if item.is_dir() else item.stat().st_size,
                }
            )
        text = "\n".join(f"{row['kind']}\t{row['path']}\t{row['size_bytes']} bytes" for row in rows) or "Directory is empty."
        observed = tuple(str(row["path"]) for row in rows)
        return self._envelope(
            tool_args=args,
            status="ok",
            text=text,
            structured_payload={"tool_result": {"kind": "directory_listing", "path": path, "entries": rows}},
            observed_paths=observed,
            execution_receipt=context.execution_receipt,
        )


class NativeStatPathTool(_NativeToolBase):
    async def call(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        return await asyncio.to_thread(self._call_sync, dict(args or {}), context)

    def _call_sync(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        path = str(args.get("path") or "").strip()
        files = self._files(context)
        try:
            info = files.path_info(path)
        except Exception as exc:
            return self._envelope(tool_args=args, status="error", text=f"Stat failed: {exc}", execution_receipt=context.execution_receipt)
        payload = {
            "kind": "path_stat",
            "path": info.relative_path,
            "exists": info.exists,
            "is_dir": info.is_dir,
            "is_file": info.is_file,
            "size_bytes": info.size_bytes,
            "suffix": info.suffix,
        }
        text = "\n".join(f"{key}: {value}" for key, value in payload.items())
        return self._envelope(
            tool_args=args,
            status="ok",
            text=text,
            structured_payload={"tool_result": payload},
            observed_paths=(info.relative_path,),
            execution_receipt=context.execution_receipt,
        )


class NativePathExistsTool(_NativeToolBase):
    async def call(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        return await asyncio.to_thread(self._call_sync, dict(args or {}), context)

    def _call_sync(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        path = str(args.get("path") or "").strip()
        files = self._files(context)
        try:
            target = files.resolve(path, require_path=True)
            rel = files.relative_path(target)
            exists = target.exists()
        except Exception as exc:
            return self._envelope(tool_args=args, status="error", text=f"Exists failed: {exc}", execution_receipt=context.execution_receipt)
        return self._envelope(
            tool_args=args,
            status="ok",
            text="true" if exists else "false",
            structured_payload={"tool_result": {"kind": "path_exists", "path": rel, "exists": exists}},
            observed_paths=(rel,),
            execution_receipt=context.execution_receipt,
        )


def _parse_structured_file(file_path: Path) -> tuple[Any, str]:
    suffix = file_path.suffix.lower()
    if suffix == ".json":
        return json.loads(file_path.read_text(encoding="utf-8")), "json"
    if suffix in {".yaml", ".yml"}:
        return yaml.safe_load(file_path.read_text(encoding="utf-8")), "yaml"
    if suffix == ".toml":
        return tomllib.loads(file_path.read_text(encoding="utf-8")), "toml"
    raise ValueError("supported formats are JSON, YAML, and TOML")


def _summarize(value: Any, *, max_items: int = 30) -> str:
    lines: list[str] = [f"root_type: {type(value).__name__}"]
    _walk(value, "$", lines, max_items=max_items)
    return "\n".join(lines[: max_items + 1])


def _walk(value: Any, path: str, lines: list[str], *, max_items: int) -> None:
    if len(lines) > max_items:
        return
    if isinstance(value, dict):
        keys = [str(key) for key in value.keys()]
        lines.append(f"{path}: object keys={keys[:20]}")
        for key, item in list(value.items())[:8]:
            _walk(item, f"{path}.{key}", lines, max_items=max_items)
        return
    if isinstance(value, list):
        lines.append(f"{path}: array len={len(value)}")
        if value:
            _walk(value[0], f"{path}[0]", lines, max_items=max_items)
        return
    if isinstance(value, (str, int, float, bool)) or value is None:
        preview = str(value)
        if len(preview) > 120:
            preview = preview[:117] + "..."
        lines.append(f"{path}: {type(value).__name__} = {preview}")
        return
    lines.append(f"{path}: {type(value).__name__}")


def _memory_search_payload(args: dict[str, Any], *, root_dir: Path) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    task_scope = str(args.get("task_run_id") or "").strip()
    project_scope = str(args.get("project_id") or "").strip()
    if not task_scope and not project_scope:
        raise ValueError("memory_search requires task_run_id or project_id")
    repo_filter = {str(item or "").strip() for item in list(args.get("repositories") or []) if str(item or "").strip()}
    collection_filter = {str(item or "").strip() for item in list(args.get("collections") or []) if str(item or "").strip()}
    result_limit = max(1, min(int(args.get("limit") or 8), 20))
    service = MemoryRuntimeServices.from_runtime_root(root_dir).formal_memory
    versions = tuple(
        version
        for version in service.store.list_versions(limit=2000)
        if _memory_version_visible(version, task_run_id=task_scope, project_id=project_scope)
    )
    terms = _memory_query_terms(query)
    matches: list[dict[str, Any]] = []
    for version in versions:
        if version.status not in {"accepted", "committed"}:
            continue
        if repo_filter and version.logical_repository_id not in repo_filter and version.repository_id not in repo_filter:
            continue
        if collection_filter and version.collection_id not in collection_filter:
            continue
        haystack = "\n".join(
            str(item or "")
            for item in (
                version.logical_repository_id,
                version.collection_id,
                version.record_key,
                version.record_kind,
                version.summary,
                version.canonical_text,
                json.dumps(version.payload, ensure_ascii=False, sort_keys=True),
            )
        ).lower()
        score = _memory_match_score(terms, haystack)
        if score <= 0:
            continue
        matches.append(
            {
                "score": score,
                "memory_ref": version.version_id,
                "record_key": version.record_key,
                "record_kind": version.record_kind,
                "repository": version.logical_repository_id or version.repository_id,
                "effective_repository": version.repository_id,
                "collection": version.collection_id,
                "summary": version.summary,
                "canonical_text_preview": _memory_preview(version.canonical_text),
                "artifact_refs": list(version.artifact_refs),
                "source_node_id": version.source_node_id,
                "source_clock": version.source_clock,
            }
        )
    matches.sort(key=lambda item: (-int(item["score"]), str(item["repository"]), str(item["collection"]), str(item["record_key"])))
    return {
        "authority": "formal_memory.memory_search_tool",
        "query": query,
        "task_run_id": task_scope,
        "project_id": project_scope,
        "repositories": sorted(repo_filter),
        "collections": sorted(collection_filter),
        "result_count": min(len(matches), result_limit),
        "results": matches[:result_limit],
        "diagnostics": {"candidate_version_count": len(versions), "matched_version_count": len(matches), "search_terms": terms},
    }


def _memory_version_visible(version: Any, *, task_run_id: str, project_id: str) -> bool:
    if task_run_id and str(getattr(version, "task_run_id", "") or "") == task_run_id:
        return True
    if project_id and str(getattr(version, "scope_kind", "") or "") == "project_scoped":
        return str(getattr(version, "scope_id", "") or "") == project_id
    return False


def _memory_query_terms(query: str) -> list[str]:
    raw_terms = re.findall(r"[A-Za-z0-9_.\-\u4e00-\u9fff]+", query.lower())
    terms: list[str] = []
    seen: set[str] = set()
    for term in [query.lower(), *raw_terms]:
        normalized = term.strip("._- \t\r\n")
        if len(normalized) < 2 or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(normalized)
    return terms


def _memory_match_score(terms: list[str], haystack: str) -> int:
    score = 0
    for term in terms:
        if term in haystack:
            score += max(1, min(len(term), 20))
    return score


def _memory_preview(text: str, *, limit: int = 1200) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _file_management_config(context: ToolUseContext) -> dict[str, Any]:
    config = dict(context.file_management_policy or {})
    if not config:
        snapshot_config = context.environment_snapshot.get("file_management")
        if isinstance(snapshot_config, dict):
            config = dict(snapshot_config)
    payload = dict(config or {})
    if payload.get("enabled") is False:
        return {}
    if not str(payload.get("profile_id") or "").strip():
        return {}
    return payload


def context_tool_call_id(execution_receipt: dict[str, Any] | None) -> str:
    return str(dict(execution_receipt or {}).get("tool_call_id") or "").strip()


def context_action_request_id(execution_receipt: dict[str, Any] | None) -> str:
    return str(dict(execution_receipt or {}).get("action_request_id") or dict(execution_receipt or {}).get("request_ref") or "").strip()


def context_caller_kind(execution_receipt: dict[str, Any] | None) -> str:
    return str(dict(execution_receipt or {}).get("caller_kind") or "").strip()


def context_caller_ref(execution_receipt: dict[str, Any] | None) -> str:
    return str(dict(execution_receipt or {}).get("caller_ref") or "").strip()




def _repository_for_action(context: ToolUseContext, action: str) -> str:
    config = _file_management_config(context)
    repositories = dict(config.get("repositories") or {})
    action_name = str(action or "").strip()
    profile_id = str(config.get("profile_id") or "").strip()
    explicit = str(repositories.get(action_name) or "").strip()
    if explicit:
        return _full_access_project_repository_override(context, profile_id=profile_id, action=action_name, selected=explicit) or explicit
    selected = _repository_for_profile_action(
        profile_id,
        action_name,
        sandbox_available=context.sandbox_root is not None,
        repository_requirements=dict(config.get("repository_requirements") or {}),
    )
    override = _full_access_project_repository_override(context, profile_id=profile_id, action=action_name, selected=selected)
    if override:
        return override
    return selected or str(config.get("default_repository_id") or "").strip()


def _full_access_project_repository_override(
    context: ToolUseContext,
    *,
    profile_id: str,
    action: str,
    selected: str,
) -> str:
    if profile_id != "file_profile.managed_project_workspace":
        return ""
    if action not in {"write", "edit"}:
        return ""
    if str(context.permission_mode or "").strip().lower() not in {"full_access", "bypass"}:
        return ""
    if selected and selected != "repo.managed_project.sandbox_workspace":
        return ""
    return "repo.managed_project.project_workspace"


def _repository_for_profile_action(
    profile_id: str,
    action: str,
    *,
    sandbox_available: bool,
    repository_requirements: dict[str, dict[str, Any]],
) -> str:
    if not str(profile_id or "").strip():
        return ""
    try:
        environment = resolve_file_environment(
            profile_id,
            repository_requirements=repository_requirements,
        )
    except Exception:
        return ""
    action_name = str(action or "").strip()
    priorities = _repository_kind_priorities(action_name, sandbox_available=sandbox_available)
    repositories = list(environment.repositories)
    for kind in priorities:
        for repository in repositories:
            if repository.repository_kind == kind and _repository_supports_action(repository, action_name):
                return repository.repository_id
    for repository in repositories:
        if _repository_supports_action(repository, action_name):
            return repository.repository_id
    return ""


def _repository_kind_priorities(action: str, *, sandbox_available: bool) -> tuple[str, ...]:
    if action in {"write", "edit"}:
        return (
            *((("sandbox_workspace",) if sandbox_available else ())),
            "draft_workspace",
            "review_workspace",
            "artifact_repository",
            "evidence_archive",
            "download_cache",
            "citation_snapshot_repository",
            "runtime_output",
            "test_artifacts",
            "project_workspace",
        )
    return (
        *((("sandbox_workspace",) if sandbox_available else ())),
        "project_workspace",
        "official_work",
        "artifact_repository",
        "evidence_archive",
        "download_cache",
        "citation_snapshot_repository",
        "material_mount",
        "draft_workspace",
        "review_workspace",
    )


def _repository_supports_action(repository: Any, action: str) -> bool:
    action_name = str(action or "").strip()
    rules = tuple(repository.rules_for_action(action_name))
    if rules:
        return any(str(rule.behavior or "") != "deny" for rule in rules)
    if action_name in {"open", "read"}:
        return bool(getattr(repository, "readable", False))
    if action_name == "search":
        return bool(getattr(repository, "searchable", False))
    if action_name in {"write", "edit"}:
        return bool(getattr(repository, "writable", False))
    return False


def _check_gateway_file_permission(
    *,
    tool: _NativeToolBase,
    args: dict[str, Any],
    context: ToolUseContext,
    action: str,
) -> ToolPermissionResult | None:
    gateway = tool._file_gateway(context)
    if gateway is None:
        return None
    repository_id = _repository_for_action(context, action)
    path = str(args.get("path") or "").strip()
    try:
        gateway.check_access(
            repository_id,
            action,
            approval_fingerprint=_gateway_approval_fingerprint(context),
        )
    except FileGatewayApprovalRequired as exc:
        return ToolPermissionResult(
            allowed=False,
            decision="requires_approval",
            reason="file_gateway_approval_required",
            requires_approval=True,
            repair_instruction="This file operation requires platform approval before execution.",
            diagnostics={
                "repository_id": exc.repository_id,
                "action": exc.action,
                "reason": exc.reason,
                "source": exc.source,
                "path": path,
            },
        )
    except (FileGatewayPermissionError, KeyError, ValueError) as exc:
        return ToolPermissionResult(
            allowed=False,
            decision="deny",
            reason="file_gateway_permission_denied",
            repair_instruction="Retry with a path and operation allowed by the active task environment.",
            diagnostics={
                "repository_id": repository_id,
                "action": action,
                "path": path,
                "error": str(exc),
            },
        )
    return ToolPermissionResult(
        allowed=True,
        decision="allow",
        diagnostics={"repository_id": repository_id, "action": action, "path": path},
    )


def _gateway_approval_fingerprint(context: ToolUseContext) -> str:
    explicit = str(context.approval_fingerprint or "").strip()
    if explicit:
        return explicit
    mode = str(context.permission_mode or "").strip().lower()
    if mode in {"full_access", "bypass"}:
        scope = (
            str(context.task_run_id or "").strip()
            or str(context.turn_id or "").strip()
            or str(context.session_id or "").strip()
            or str(context.tool_call_id or "").strip()
            or "runtime"
        )
        return f"runtime-permission:{mode}:{scope}"
    return ""


def _real_workspace_root(context: ToolUseContext) -> Path:
    snapshot_root = str(context.environment_snapshot.get("workspace_root") or "").strip()
    if snapshot_root:
        return Path(snapshot_root).resolve()
    policy_root = str(dict(context.sandbox_policy or {}).get("workspace_root") or "").strip()
    if policy_root:
        return Path(policy_root).resolve()
    return Path(context.workspace_root).resolve()


def _native_runtime_base_dir(context: ToolUseContext) -> Path:
    value = str(getattr(context, "runtime_base_dir", "") or "").strip()
    if value:
        return Path(value).resolve()
    return _real_workspace_root(context)


_COMMAND_CHANGE_EXCLUDED_DIRS = set(DEFAULT_EXCLUDED_DIRS) | {
    ".git",
    ".hg",
    ".svn",
    ".next",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
}
_COMMAND_CHANGE_WRITE_MARKERS = (
    ">",
    ">>",
    " add-content",
    " copy-item",
    " mkdir",
    " move-item",
    " new-item",
    " out-file",
    " remove-item",
    " rename-item",
    " set-content",
    " tee-object",
    " touch ",
    " rm ",
    " mv ",
    " cp ",
    " sed -i",
)
_COMMAND_CHANGE_MAX_FILES = 1800
_COMMAND_CHANGE_MAX_RECORDS = 24
_COMMAND_CHANGE_MAX_FILE_BYTES = 1_000_000
_COMMAND_CHANGE_MAX_TOTAL_BYTES = 16_000_000


def _capture_command_file_snapshot(
    context: ToolUseContext,
    *,
    force: bool,
    command: str,
) -> dict[str, Any] | None:
    if not force and not _command_likely_writes_files(command):
        return None
    root = Path(context.workspace_root).resolve()
    if not root.exists() or not root.is_dir():
        return None
    files = WorkspaceFileService(root)
    entries: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    scanned_files = 0
    truncated = False
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                if child.name in _COMMAND_CHANGE_EXCLUDED_DIRS:
                    continue
                stack.append(child)
                continue
            if not child.is_file():
                continue
            if files.is_excluded(child, include_default_search_excludes=True):
                continue
            rel = files.relative_path(child)
            if rel.startswith("storage/file_changes/"):
                continue
            scanned_files += 1
            if scanned_files > _COMMAND_CHANGE_MAX_FILES:
                truncated = True
                break
            item = _read_trackable_text_file(child)
            if item is None:
                continue
            size = int(item["size_bytes"])
            if total_bytes + size > _COMMAND_CHANGE_MAX_TOTAL_BYTES:
                truncated = True
                break
            total_bytes += size
            entries[rel] = {
                **item,
                "path": rel,
                "absolute_path": str(child.resolve()),
            }
        if truncated:
            break
    return {
        "root": str(root),
        "entries": entries,
        "scanned_files": scanned_files,
        "truncated": truncated,
        "authority": "runtime.file_changes.command_snapshot",
    }


def _record_command_file_changes(
    *,
    context: ToolUseContext,
    before_snapshot: dict[str, Any] | None,
    tool_name: str,
    operation_id: str,
    command_label: str,
) -> dict[str, Any]:
    if not before_snapshot:
        return {}
    root = Path(str(before_snapshot.get("root") or context.workspace_root)).resolve()
    after_snapshot = _capture_command_file_snapshot(context, force=True, command=command_label)
    if not after_snapshot:
        return {}
    before_entries = dict(before_snapshot.get("entries") or {})
    after_entries = dict(after_snapshot.get("entries") or {})
    changed_paths = [
        path
        for path in sorted(set(before_entries) | set(after_entries))
        if str(dict(before_entries.get(path) or {}).get("sha256") or "") != str(dict(after_entries.get(path) or {}).get("sha256") or "")
    ]
    records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for logical_path in changed_paths[:_COMMAND_CHANGE_MAX_RECORDS]:
        before = dict(before_entries.get(logical_path) or {})
        after = dict(after_entries.get(logical_path) or {})
        absolute_path = str(after.get("absolute_path") or before.get("absolute_path") or (root / logical_path))
        result = _record_text_file_change(
            context=context,
            tool_name=tool_name,
            operation_id=operation_id,
            logical_path=logical_path,
            absolute_path=absolute_path,
            workspace_root=root,
            before_content=str(before["content"]) if "content" in before else None,
            after_content=str(after["content"]) if "content" in after else None,
            metadata={"source": "command_snapshot", "command": command_label},
        )
        if str(result.get("status") or "") == "recorded":
            records.append(dict(result.get("record") or {}))
        elif str(result.get("status") or "") == "error":
            errors.append({"path": logical_path, "error": str(result.get("error") or "")})
    return {
        "status": "recorded" if records else "unchanged",
        "record_count": len(records),
        "changed_path_count": len(changed_paths),
        "skipped_path_count": max(0, len(changed_paths) - len(records)),
        "snapshot_truncated": bool(before_snapshot.get("truncated") or after_snapshot.get("truncated")),
        "records": records,
        "frontend_diffs": [_frontend_diff_for_record(record) for record in records],
        "errors": errors,
        "authority": "runtime.file_changes.command_integration",
    }


def _read_trackable_text_file(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as handle:
            data = handle.read(_COMMAND_CHANGE_MAX_FILE_BYTES + 1)
    except OSError:
        return None
    if len(data) > _COMMAND_CHANGE_MAX_FILE_BYTES or b"\x00" in data:
        return None
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return {
        "content": content,
        "size_bytes": len(data),
        "sha256": _sha256_text(content),
    }


def _command_likely_writes_files(command: str) -> bool:
    normalized = f" {str(command or '').strip().lower()} "
    if not normalized.strip():
        return False
    return any(marker in normalized for marker in _COMMAND_CHANGE_WRITE_MARKERS)


def _record_text_file_change(
    *,
    context: ToolUseContext,
    tool_name: str,
    operation_id: str,
    logical_path: str,
    absolute_path: str | Path,
    workspace_root: str | Path,
    before_content: str | None,
    after_content: str | None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    before_text = "" if before_content is None else str(before_content)
    after_text = "" if after_content is None else str(after_content)
    if before_content is None and after_content is None:
        return {"status": "unchanged", "authority": "runtime.file_changes.noop"}
    if before_content is not None and after_content is not None and _sha256_text(before_text) == _sha256_text(after_text):
        return {"status": "unchanged", "authority": "runtime.file_changes.noop"}
    try:
        record = FileChangeTracker(_file_change_tracker_base_dir(context)).record_text_change(
            session_id=context.session_id,
            task_run_id=context.task_run_id,
            agent_run_id=context.agent_run_id,
            tool_call_id=context.tool_call_id,
            tool_name=tool_name,
            operation_id=operation_id,
            workspace_root=workspace_root,
            logical_path=logical_path,
            absolute_path=absolute_path,
            before_content=before_content,
            after_content=after_content,
            metadata=metadata,
        )
        return {
            "status": "recorded",
            "record": record,
            "frontend_diff": _frontend_diff_for_record(record),
            "authority": "runtime.file_changes.tool_integration",
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "authority": "runtime.file_changes.tool_integration",
        }


def _frontend_diff_for_record(record: dict[str, Any]) -> dict[str, Any]:
    record_id = str(dict(record or {}).get("record_id") or "").strip()
    if not record_id:
        return {}
    return {
        "record_id": record_id,
        "api_path": f"/file-changes/{record_id}/diff",
        "authority": "runtime.file_changes.frontend_diff",
    }


def _change_root_for_path(context: ToolUseContext, path: str | Path) -> Path:
    target = Path(path).resolve()
    candidates = [
        context.workspace_root,
        context.sandbox_root,
        _real_workspace_root(context),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        root = Path(candidate).resolve()
        if target == root or root in target.parents:
            return root
    return target.parent.resolve()


def _file_change_tracker_base_dir(context: ToolUseContext) -> Path:
    value = str(getattr(context, "runtime_base_dir", "") or "").strip()
    if value:
        return Path(value).resolve()
    return _real_workspace_root(context)


def _gateway_result_root(result: Any) -> str:
    root_binding = dict(dict(getattr(result, "metadata", {}) or {}).get("root_binding") or {})
    return str(root_binding.get("root") or "").strip()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _runtime_context_storage_roots(context: ToolUseContext) -> tuple[Path, ...]:
    roots: list[Path] = []
    project_root = _real_workspace_root(context)
    storage = dict(context.file_management_policy.get("storage_space") or {})
    for key in ("runtime_state_root", "cache_root", "environment_storage_root"):
        text = str(storage.get(key) or "").strip()
        if not text:
            continue
        candidate = Path(text)
        root = candidate.resolve() if candidate.is_absolute() else (project_root / candidate).resolve()
        if root not in roots:
            roots.append(root)
    return tuple(roots)


def _sandbox_root_from_policy(context: ToolUseContext) -> Path | None:
    value = str(dict(context.sandbox_policy or {}).get("sandbox_root") or "").strip()
    if not value:
        return None
    return Path(value).resolve()


def _managed_storage_root(context: ToolUseContext, project_root: Path) -> Path:
    config = _file_management_config(context)
    explicit = str(config.get("managed_storage_root") or "").strip()
    if explicit:
        root = Path(explicit)
        return root.resolve() if root.is_absolute() else (project_root / root).resolve()
    return (project_root / ".managed-files").resolve()


def _runtime_output_root(context: ToolUseContext, managed_storage_root: Path) -> Path:
    config = _file_management_config(context)
    explicit = str(config.get("runtime_output_root") or "").strip()
    if explicit:
        root = Path(explicit)
        return root.resolve() if root.is_absolute() else (_real_workspace_root(context) / root).resolve()
    return (managed_storage_root / "runtime").resolve()


def _workspace_files(files: WorkspaceFileService, *, safe_roots: list[Path], using_default_roots: bool) -> list[str]:
    paths: list[str] = []
    for root in safe_roots:
        for path in root.rglob("*"):
            if path.is_file() and not files.is_excluded(path, include_default_search_excludes=using_default_roots):
                paths.append(files.relative_path(path))
    return sorted(dict.fromkeys(paths))


def _nonempty_path_args(paths: Any) -> list[str]:
    values = [paths] if isinstance(paths, str) else list(paths or [])
    return [str(item or "").strip() for item in values if str(item or "").strip()]


def _roots_file_misuse_error(files: WorkspaceFileService, roots: Any) -> str:
    for item in _nonempty_path_args(roots):
        try:
            target = files.resolve(item, require_path=True)
        except ValueError:
            continue
        if target.exists() and target.is_file():
            rel = files.relative_path(target)
            return f"roots accepts directories only. Put file paths in paths instead, for example paths=[\"{rel}\"]."
    return ""


def _resolve_search_paths(files: WorkspaceFileService, paths: list[str]) -> tuple[list[Path], str]:
    resolved: list[Path] = []
    seen: set[Path] = set()
    for item in paths:
        try:
            target = files.resolve(item, require_path=True)
        except ValueError as exc:
            return [], str(exc)
        if not target.exists():
            return [], f"path does not exist: {item}"
        if target.is_dir():
            return [], f"paths accepts files only. Put directory roots in roots instead: {item}"
        if target not in seen:
            seen.add(target)
            resolved.append(target)
    return resolved, ""


def _query_terms(query: str) -> list[str]:
    import re

    normalized = str(query or "").strip()
    terms = [normalized.lower()] if normalized else []
    for item in re.findall(r"[A-Za-z0-9_.\-\u4e00-\u9fff]+", normalized):
        lowered = item.lower().strip("._-")
        if len(lowered) < 2 or lowered in {"文件", "查找", "搜索", "帮我", "找到", "打开", "读取", "一下", "路径"}:
            continue
        terms.append(lowered)
    return list(dict.fromkeys(term for term in terms if term))


def _search_text(
    files: WorkspaceFileService,
    *,
    query: str,
    safe_roots: list[Path],
    glob: str,
    limit: int,
    using_default_roots: bool,
    case_sensitive: bool = False,
) -> list[dict[str, Any]]:
    args = [
        "--line-number",
        "--column",
        "--hidden",
        "--max-count",
        str(limit),
    ]
    if not bool(case_sensitive):
        args.append("--ignore-case")
    for excluded in DEFAULT_EXCLUDED_DIRS:
        args.extend(["--glob", f"!**/{excluded}/**"])
    if using_default_roots:
        for excluded in DEFAULT_SEARCH_EXCLUDED_PATHS:
            args.extend(["--glob", f"!{excluded}/**"])
    if glob:
        args.extend(["--glob", glob])
    args.append(query)
    completed = None
    if files.search_root_args_are_workspace_relative(safe_roots):
        args.extend(files.relative_path(root) for root in safe_roots)
        try:
            completed = subprocess.run(
                ["rg", *args],
                cwd=files.workspace_root,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=8.0,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
            completed = None
    if completed is None:
        return _fallback_search_text(
            files,
            query=query,
            safe_roots=safe_roots,
            glob=glob,
            limit=limit,
            using_default_roots=using_default_roots,
            case_sensitive=case_sensitive,
        )
    if completed.returncode not in {0, 1}:
        return []
    matches: list[dict[str, Any]] = []
    for raw in completed.stdout.splitlines():
        item = _parse_rg_match(raw)
        if item:
            matches.append(item)
            if len(matches) >= limit:
                break
    return matches


def _search_text_in_paths(
    files: WorkspaceFileService,
    *,
    query: str,
    paths: list[Path],
    glob: str,
    limit: int,
    case_sensitive: bool = False,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    pattern = str(glob or "").strip()
    query_cmp = query if case_sensitive else query.lower()
    for path in paths:
        if len(matches) >= limit:
            return matches
        rel = files.relative_path(path)
        if pattern and not fnmatch.fnmatch(rel, pattern):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            line_cmp = line if case_sensitive else line.lower()
            column = line_cmp.find(query_cmp) + 1
            if column <= 0:
                continue
            matches.append({"path": rel, "line": line_number, "column": column, "text": line[:240]})
            if len(matches) >= limit:
                return matches
    return matches


def _parse_rg_match(line: str) -> dict[str, Any]:
    parts = str(line or "").replace("\\", "/").split(":", 3)
    if len(parts) < 4:
        return {}
    path, line_no, column, text = parts
    try:
        parsed_line = int(line_no)
        parsed_column = int(column)
    except ValueError:
        return {}
    return {"path": path, "line": parsed_line, "column": parsed_column, "text": text[:240]}


def _fallback_search_text(
    files: WorkspaceFileService,
    *,
    query: str,
    safe_roots: list[Path],
    glob: str,
    limit: int,
    using_default_roots: bool,
    case_sensitive: bool = False,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    pattern = glob.strip() or "*"
    query_cmp = query if case_sensitive else query.lower()
    for root in safe_roots:
        for path in root.rglob(pattern):
            if len(matches) >= limit:
                return matches
            if not path.is_file() or files.is_excluded(path, include_default_search_excludes=using_default_roots):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                line_cmp = line if case_sensitive else line.lower()
                column = line_cmp.find(query_cmp) + 1
                if column <= 0:
                    continue
                matches.append({"path": files.relative_path(path), "line": line_number, "column": column, "text": line[:240]})
                break
    return matches


def _search_result_limit(args: dict[str, Any]) -> int:
    head_limit = int(args.get("head_limit") or 0)
    selected = head_limit if head_limit > 0 else int(args.get("max_results") or 20)
    return max(1, min(selected, 100))


def _normalize_search_output_mode(value: Any) -> str:
    mode = str(value or "content").strip()
    return mode if mode in {"content", "files_with_matches", "count"} else "content"


def _slice_search_matches(matches: list[dict[str, Any]], *, offset: int, limit: int) -> list[dict[str, Any]]:
    start = max(0, int(offset or 0))
    return list(matches)[start : start + max(1, int(limit or 1))]


def _format_text_search_output(matches: list[dict[str, Any]], *, query: str, output_mode: str) -> str:
    if not matches:
        return f"没有找到匹配项：{query}"
    if output_mode == "files_with_matches":
        paths = [str(item.get("path") or "") for item in matches if str(item.get("path") or "")]
        return "\n".join(dict.fromkeys(paths)) or f"没有找到匹配项：{query}"
    if output_mode == "count":
        counts: dict[str, int] = {}
        for item in matches:
            path = str(item.get("path") or "")
            if path:
                counts[path] = counts.get(path, 0) + 1
        return "\n".join(f"{path}:{count}" for path, count in counts.items()) or f"没有找到匹配项：{query}"
    return "\n".join(f"{item['path']}:{item['line']}:{item['column']}:{item['text']}" for item in matches)


def _text_search_tool_result(
    *,
    query: str,
    matches: list[dict[str, Any]],
    requested_paths: Any,
    output_mode: str,
    limit: int,
    offset: int,
    total_matches: int,
    context_lines: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "text_search",
        "query": query,
        "matches": matches,
        "output_mode": output_mode,
        "recommended_read_windows": _recommended_read_windows(matches, context_lines=context_lines),
    }
    paths = [str(item) for item in list(requested_paths or []) if str(item)]
    if paths:
        payload["paths"] = paths
    if offset > 0:
        payload["applied_offset"] = offset
    if total_matches > len(matches) + offset:
        payload["applied_limit"] = limit
    return payload


def _recommended_read_windows(matches: list[dict[str, Any]], *, context_lines: int) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    padding = int(context_lines) if int(context_lines or 0) > 0 else 2
    for item in matches:
        path = str(item.get("path") or "").strip()
        line = int(item.get("line") or 0)
        if not path or line <= 0:
            continue
        start_line = max(1, line - padding)
        line_count = max(1, padding * 2 + 1)
        key = (path, start_line, line_count)
        if key in seen:
            continue
        seen.add(key)
        windows.append(
            {
                "path": path,
                "start_line": start_line,
                "line_count": line_count,
                "reason": f"match near line {line}",
            }
        )
    return windows


def _resolve_existing_file(files: WorkspaceFileService, path: str) -> Path | None:
    try:
        candidate = files.resolve(path, require_path=True)
    except ValueError:
        return None
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def _overwrite_intent_is_explicit(args: dict[str, Any], existing: Path, context: ToolUseContext) -> bool:
    if bool(args.get("allow_overwrite") is True):
        return True
    expected_hash = str(args.get("expected_previous_sha256") or "").strip().lower()
    if expected_hash and expected_hash == _file_sha256(existing):
        return True
    artifact_root = str(context.artifact_root or "").replace("\\", "/").strip().strip("/")
    if artifact_root:
        try:
            relative = WorkspaceFileService(context.workspace_root).relative_path(existing)
        except Exception:
            relative = ""
        return relative == artifact_root or relative.startswith(f"{artifact_root}/")
    return False


def _tool_call_structured_payload(args: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    verification_intent = args.get("verification_intent")
    if isinstance(verification_intent, dict) and verification_intent:
        payload["verification_intent"] = dict(verification_intent)
    acceptance = args.get("acceptance")
    if isinstance(acceptance, dict) and acceptance:
        payload["acceptance"] = dict(acceptance)
    acceptance_checks = args.get("acceptance_checks")
    if isinstance(acceptance_checks, dict) and acceptance_checks:
        payload["acceptance_checks"] = dict(acceptance_checks)
    return payload


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_ref_for_file(
    *,
    context: ToolUseContext,
    path: Path,
    logical_path: str,
    kind: str,
    source: str,
) -> dict[str, Any]:
    artifact = {
        "path": str(logical_path or ""),
        "kind": kind,
        "source": source,
        "absolute_path": str(Path(path).resolve()),
    }
    if context.sandbox_root is not None:
        try:
            artifact["sandbox_path"] = Path(path).resolve().relative_to(context.sandbox_root.resolve()).as_posix()
        except ValueError:
            artifact["sandbox_path"] = str(logical_path or "")
    return artifact


def _artifact_ref_for_gateway_file(
    *,
    context: ToolUseContext,
    result: Any,
    kind: str,
    source: str,
) -> dict[str, Any]:
    logical_path = str(getattr(result, "logical_path", "") or "")
    physical_path = str(getattr(result, "physical_path", "") or "").strip()
    if physical_path:
        artifact = _artifact_ref_for_file(
            context=context,
            path=Path(physical_path),
            logical_path=logical_path,
            kind=kind,
            source=source,
        )
    else:
        artifact = {
            "path": logical_path,
            "kind": kind,
            "source": source,
        }
    repository_id = str(getattr(result, "repository_id", "") or "").strip()
    if repository_id:
        artifact["repository_id"] = repository_id
    repository_kind = str(getattr(result, "repository_kind", "") or "").strip()
    if repository_kind:
        artifact["repository_kind"] = repository_kind
    if repository_kind and repository_kind != "sandbox_workspace":
        artifact["bypass_sandbox_publish"] = True
    return artifact


