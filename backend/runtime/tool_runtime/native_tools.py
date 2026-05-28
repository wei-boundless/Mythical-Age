from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from capability_system.units.tools.sandbox_command_guard import validate_sandbox_command_text
from capability_system.workspace_file_service import (
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
from runtime_encoding import build_windows_powershell_command, is_windows, utf8_subprocess_text_kwargs
from runtime.tool_runtime.docker_sandbox_backend import DockerSandboxBackend
from runtime.tool_runtime.tool_definition import ToolPermissionResult, ToolValidationResult
from runtime.tool_runtime.tool_result_envelope import ToolResultEnvelope
from runtime.tool_runtime.tool_use_context import ToolUseContext

if TYPE_CHECKING:
    from capability_system.tool_definitions import ToolDefinition as CapabilityToolDefinition


NATIVE_RUNTIME_TOOL_NAMES = {
    "read_file",
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
}


def build_native_runtime_tool(
    *,
    capability_definition: CapabilityToolDefinition,
) -> Any | None:
    name = str(capability_definition.name or "").strip()
    if name == "read_file":
        return NativeReadFileTool(capability_definition)
    if name == "write_file":
        return NativeWriteFileTool(capability_definition)
    if name == "edit_file":
        return NativeEditFileTool(capability_definition)
    if name == "terminal":
        return NativeTerminalTool(capability_definition)
    if name == "python_repl":
        return NativePythonReplTool(capability_definition)
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
        execution_receipt: dict[str, Any] | None = None,
    ) -> ToolResultEnvelope:
        payload = dict(structured_payload or {})
        if observed_paths:
            payload["observed_paths"] = list(observed_paths)
        if matched_paths:
            payload["matched_paths"] = list(matched_paths)
        if artifact_refs:
            payload["artifact_refs"] = [dict(item) for item in artifact_refs]
        if command_receipt:
            payload["command_receipt"] = dict(command_receipt)
        return ToolResultEnvelope(
            envelope_id=f"tool-result:{uuid.uuid4().hex[:12]}",
            tool_name=self.name,
            tool_args=dict(tool_args or {}),
            status=status,
            text=str(text or ""),
            structured_payload=payload,
            observed_paths=tuple(observed_paths),
            matched_paths=tuple(matched_paths),
            artifact_refs=tuple(dict(item) for item in artifact_refs),
            command_receipt=dict(command_receipt or {}),
            execution_receipt=dict(execution_receipt or {}),
            error=str(text or "") if status == "error" else "",
        )


class NativeReadFileTool(_NativeToolBase):
    async def call(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        return await asyncio.to_thread(self._call_sync, dict(args or {}), context)

    def _call_sync(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        path = str(args.get("path") or "").strip()
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
            text = files.read_text(file_path, limit=int(args.get("limit") or 10000))
            rel = files.relative_path(file_path)
        except Exception as exc:
            return self._envelope(
                tool_args=args,
                status="error",
                text=f"Read failed: {exc}",
                structured_payload={"tool_result": {"kind": "text_file", "status": "error", "error": str(exc)}},
                execution_receipt=context.execution_receipt,
            )
        return self._envelope(
            tool_args=args,
            status="ok",
            text=text,
            structured_payload={
                "tool_result": {
                    "kind": "text_file",
                    "path": rel,
                    "size_chars": len(text),
                    "truncated": len(text) >= int(args.get("limit") or 10000),
                }
            },
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
        limit = int(args.get("limit") or 10000)
        repository_id = _repository_for_action(context, "read")
        try:
            result = gateway.read_text(
                repository_id,
                path,
                self._gateway_context(context),
                operation_id=self.operation_id,
            )
            text = result.content[: max(0, limit)]
        except Exception as exc:
            return self._envelope(
                tool_args=args,
                status="error",
                text=f"Read failed: {exc}",
                structured_payload={"tool_result": {"kind": "text_file", "status": "error", "error": str(exc)}},
                execution_receipt=context.execution_receipt,
            )
        return self._envelope(
            tool_args=args,
            status="ok",
            text=text,
            structured_payload={
                "tool_result": {
                    "kind": "text_file",
                    "path": result.logical_path,
                    "repository_id": result.repository_id,
                    "managed_file_ref": result.managed_file_ref.to_dict(),
                    "size_chars": len(result.content),
                    "truncated": len(result.content) > len(text),
                },
                "file_gateway": {
                    "access_decision": result.access_decision,
                    "root_binding": result.metadata.get("root_binding"),
                },
            },
            observed_paths=(result.logical_path,),
            execution_receipt=context.execution_receipt,
        )


class NativeWriteFileTool(_NativeToolBase):
    def check_permissions(self, args: dict[str, Any], context: ToolUseContext) -> ToolPermissionResult:
        gateway_permission = _check_gateway_file_permission(
            tool=self,
            args=args,
            context=context,
            action="write",
        )
        if gateway_permission is not None and not gateway_permission.allowed:
            return gateway_permission
        files = self._files(context)
        path = str(args.get("path") or "").strip()
        if not _path_within_scopes(files, path, context.write_scopes):
            return ToolPermissionResult(
                allowed=False,
                decision="deny",
                reason="path_outside_write_scopes",
                repair_instruction="Retry with a path inside the allowed write scope.",
                diagnostics={"path": path, "write_scopes": list(context.write_scopes)},
            )
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
            file_path = self._files(context).write_text(path, content)
            rel = self._files(context).relative_path(file_path)
        except Exception as exc:
            return self._envelope(tool_args=args, status="error", text=f"Write failed: {exc}", execution_receipt=context.execution_receipt)
        artifact = _artifact_ref_for_file(context=context, path=file_path, logical_path=rel, kind="file", source=self.name)
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
                }
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
                approval_fingerprint=context.approval_fingerprint,
            )
        except Exception as exc:
            return self._envelope(tool_args=args, status="error", text=f"Write failed: {exc}", execution_receipt=context.execution_receipt)
        artifact = {
            "path": result.logical_path,
            "kind": "file",
            "source": self.name,
            "repository_id": result.repository_id,
        }
        receipt = result.receipt.to_dict() if result.receipt is not None else {}
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
        path = str(args.get("path") or "").strip()
        if not _path_within_scopes(self._files(context), path, context.write_scopes):
            return ToolPermissionResult(
                allowed=False,
                decision="deny",
                reason="path_outside_write_scopes",
                repair_instruction="Retry with a path inside the allowed write scope.",
                diagnostics={"path": path, "write_scopes": list(context.write_scopes)},
            )
        return ToolPermissionResult(allowed=True, decision="allow")

    async def call(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        return await asyncio.to_thread(self._call_sync, dict(args or {}), context)

    def _call_sync(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        path = str(args.get("path") or "").strip()
        gateway = self._file_gateway(context)
        if gateway is not None:
            return self._call_gateway_edit(args=args, context=context, gateway=gateway, path=path)
        try:
            file_path = self._files(context).edit_text(path, str(args.get("old_text") or ""), str(args.get("new_text") or ""))
            rel = self._files(context).relative_path(file_path)
        except Exception as exc:
            return self._envelope(tool_args=args, status="error", text=f"Edit failed: {exc}", execution_receipt=context.execution_receipt)
        artifact = _artifact_ref_for_file(context=context, path=file_path, logical_path=rel, kind="file", source=self.name)
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
                }
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
                approval_fingerprint=context.approval_fingerprint,
            )
        except Exception as exc:
            return self._envelope(tool_args=args, status="error", text=f"Edit failed: {exc}", execution_receipt=context.execution_receipt)
        artifact = {
            "path": result.logical_path,
            "kind": "file",
            "source": self.name,
            "repository_id": result.repository_id,
        }
        receipt = result.receipt.to_dict() if result.receipt is not None else {}
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
        blocked_reason = validate_sandbox_command_text(command, kind="command")
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
        blocked_reason = validate_sandbox_command_text(code, kind="code")
        if blocked_reason:
            receipt = {"command": "python -c <code>", "exit_code": 1, "passed": False, "output_preview": blocked_reason}
            return self._envelope(
                tool_args=args,
                status="error",
                text=blocked_reason,
                command_receipt=receipt,
                execution_receipt=context.execution_receipt,
            )
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
            return self._envelope(
                tool_args=args,
                status="ok" if execution.exit_code == 0 else "error",
                text=execution.output,
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
        receipt = {"command": "python -c <code>", "exit_code": exit_code, "passed": exit_code == 0, "output_preview": text[:500]}
        return self._envelope(
            tool_args=args,
            status="ok" if exit_code == 0 else "error",
            text=text,
            command_receipt=receipt,
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
        using_default_roots = not [str(item or "").strip() for item in list(args.get("roots") or [])]
        safe_roots = files.safe_roots(args.get("roots"))
        if not safe_roots:
            return self._envelope(tool_args=args, status="error", text="Search failed: no safe search roots.", execution_receipt=context.execution_receipt)
        limit = max(1, min(int(args.get("max_results") or 20), 100))
        glob = str(args.get("glob") or "").strip()
        matches = _search_text(files, query=query, safe_roots=safe_roots, glob=glob, limit=limit, using_default_roots=using_default_roots)
        matched_paths = tuple(dict.fromkeys(str(item.get("path") or "") for item in matches if str(item.get("path") or "").strip()))
        text = "\n".join(
            f"{item['path']}:{item['line']}:{item['column']}:{item['text']}"
            for item in matches
        ) or f"没有找到匹配项：{query}"
        return self._envelope(
            tool_args=args,
            status="ok",
            text=text,
            structured_payload={"tool_result": {"kind": "text_search", "query": query, "matches": matches}},
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


def _repository_for_action(context: ToolUseContext, action: str) -> str:
    config = _file_management_config(context)
    repositories = dict(config.get("repositories") or {})
    action_name = str(action or "").strip()
    explicit = str(repositories.get(action_name) or "").strip()
    if explicit:
        return explicit
    profile_id = str(config.get("profile_id") or "").strip()
    if profile_id == "file_profile.vibe_coding_project":
        if action_name in {"write", "edit"}:
            return "repo.coding.sandbox_workspace"
        return "repo.coding.sandbox_workspace" if context.sandbox_root is not None else "repo.coding.project_workspace"
    if profile_id == "file_profile.writing_manuscript":
        if action_name in {"write", "edit"}:
            return "repo.writing.draft_workspace"
        return "repo.writing.official_work"
    if profile_id == "file_profile.web_research_evidence":
        if action_name in {"write", "edit"}:
            return "repo.research.evidence_archive"
        return "repo.research.evidence_archive"
    return str(config.get("default_repository_id") or "").strip()


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
            approval_fingerprint=context.approval_fingerprint,
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


def _real_workspace_root(context: ToolUseContext) -> Path:
    snapshot_root = str(context.environment_snapshot.get("workspace_root") or "").strip()
    if snapshot_root:
        return Path(snapshot_root).resolve()
    policy_root = str(dict(context.sandbox_policy or {}).get("workspace_root") or "").strip()
    if policy_root:
        return Path(policy_root).resolve()
    return Path(context.workspace_root).resolve()


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
) -> list[dict[str, Any]]:
    args = [
        "--line-number",
        "--column",
        "--ignore-case",
        "--hidden",
        "--max-count",
        str(limit),
    ]
    for excluded in DEFAULT_EXCLUDED_DIRS:
        args.extend(["--glob", f"!**/{excluded}/**"])
    if using_default_roots:
        for excluded in DEFAULT_SEARCH_EXCLUDED_PATHS:
            args.extend(["--glob", f"!{excluded}/**"])
    if glob:
        args.extend(["--glob", glob])
    args.append(query)
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
        return _fallback_search_text(
            files,
            query=query,
            safe_roots=safe_roots,
            glob=glob,
            limit=limit,
            using_default_roots=using_default_roots,
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
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    pattern = glob.strip() or "*"
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
                column = line.lower().find(query.lower()) + 1
                if column <= 0:
                    continue
                matches.append({"path": files.relative_path(path), "line": line_number, "column": column, "text": line[:240]})
                break
    return matches


def _path_within_scopes(files: WorkspaceFileService, path: str, scopes: tuple[str, ...]) -> bool:
    cleaned_path = str(path or "").strip()
    if not cleaned_path:
        return False
    try:
        candidate = files.resolve(cleaned_path, require_path=True)
    except ValueError:
        return False
    normalized_candidate = files.relative_path(candidate)
    cleaned_scopes = [str(item or "").replace("\\", "/").strip().strip("/") for item in list(scopes or ())]
    if not cleaned_scopes:
        return True
    return any(
        normalized_candidate == scope or normalized_candidate.startswith(f"{scope}/")
        for scope in cleaned_scopes
        if scope
    )


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


