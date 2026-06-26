from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
import sys
from typing import Any

from fastapi import APIRouter, HTTPException

from api.deps import require_runtime
from file_management.api_models import (
    ExternalReadScopeRequest,
    ManagedFileEditRequest,
    ManagedFileOpenInVSCodeRequest,
    ManagedFileReadRequest,
    ManagedFileSelectOpenRequest,
    ManagedFileWriteRequest,
)
from file_management.service import ManagedFileService, ManagedFileServiceContext
from integrations.vscode_connection import get_vscode_connection_store

router = APIRouter()
MANAGED_PROJECT_PROFILE_ID = "file_profile.managed_project_workspace"
MANAGED_PROJECT_REPOSITORY_ID = "repo.managed_project.project_workspace"


@router.get("/file-management/profiles")
async def list_file_management_profiles() -> dict[str, Any]:
    runtime = require_runtime()
    return await asyncio.to_thread(ManagedFileService(runtime).list_profiles)


@router.get("/file-management/repositories")
async def list_file_management_repositories(session_id: str = "") -> dict[str, Any]:
    runtime = require_runtime()
    return await asyncio.to_thread(ManagedFileService(runtime).list_repositories, session_id=session_id)


@router.get("/file-management/external-read-scopes")
async def list_external_read_scopes() -> dict[str, Any]:
    runtime = require_runtime()
    return await asyncio.to_thread(ManagedFileService(runtime).list_external_read_scopes)


@router.post("/file-management/external-read-scopes")
async def upsert_external_read_scope(payload: ExternalReadScopeRequest) -> dict[str, Any]:
    runtime = require_runtime()
    return await asyncio.to_thread(
        ManagedFileService(runtime).upsert_external_read_scope,
        source_path=payload.source_path,
        scope_id=payload.scope_id,
        title=payload.title,
        enabled=payload.enabled,
    )


@router.delete("/file-management/external-read-scopes/{scope_id}")
async def delete_external_read_scope(scope_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return await asyncio.to_thread(ManagedFileService(runtime).delete_external_read_scope, scope_id)


@router.post("/file-management/files/read")
async def read_managed_file(payload: ManagedFileReadRequest) -> dict[str, Any]:
    runtime = require_runtime()
    return await asyncio.to_thread(
        ManagedFileService(runtime).read,
        payload.target,
        context=_context(payload.session_id or payload.target.scope_id),
    )


@router.post("/file-management/files/select-open")
async def select_open_managed_file(payload: ManagedFileSelectOpenRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        selected_path = await asyncio.to_thread(_select_file_with_windows_dialog)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not selected_path:
        raise HTTPException(status_code=409, detail="file selection cancelled")

    target, display_path, selected_absolute_path = _managed_target_for_selected_file(
        runtime,
        selected_path,
        session_id=payload.session_id,
    )
    result = await asyncio.to_thread(
        ManagedFileService(runtime).read,
        target,
        context=_context(payload.session_id or target.scope_id),
    )
    result["path"] = display_path
    result["selected_path"] = selected_absolute_path
    result["display_path"] = display_path
    return result


@router.post("/file-management/files/write")
async def write_managed_file(payload: ManagedFileWriteRequest) -> dict[str, Any]:
    runtime = require_runtime()
    return await asyncio.to_thread(
        ManagedFileService(runtime).write,
        payload.target,
        content=payload.content,
        expected_sha256=payload.expected_sha256,
        source=payload.source,
        reason=payload.reason,
        force=payload.force,
        context=_context(payload.session_id or payload.target.scope_id),
    )


@router.post("/file-management/files/edit")
async def edit_managed_file(payload: ManagedFileEditRequest) -> dict[str, Any]:
    runtime = require_runtime()
    return await asyncio.to_thread(
        ManagedFileService(runtime).edit,
        payload.target,
        old_text=payload.old_text,
        new_text=payload.new_text,
        expected_sha256=payload.expected_sha256,
        source=payload.source,
        reason=payload.reason,
        force=payload.force,
        context=_context(payload.session_id or payload.target.scope_id),
    )


@router.post("/file-management/files/open-vscode")
async def open_managed_file_in_vscode(payload: ManagedFileOpenInVSCodeRequest) -> dict[str, Any]:
    runtime = require_runtime()
    session_id = str(payload.session_id or payload.target.scope_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    connection_store = get_vscode_connection_store()
    status = await asyncio.to_thread(connection_store.status, session_id, session_manager=getattr(runtime, "session_manager", None))
    if not status.connected or status.stale:
        raise HTTPException(status_code=409, detail="VS Code connection is not active")
    read_payload = await asyncio.to_thread(
        ManagedFileService(runtime).read,
        payload.target,
        context=_context(session_id),
    )
    root = str(dict(read_payload.get("root_binding") or {}).get("root") or "").strip()
    logical_path = str(read_payload.get("path") or payload.target.logical_path).strip()
    if not root:
        raise HTTPException(status_code=409, detail="managed file root is unavailable")
    from pathlib import Path

    target_path = (Path(root).resolve() / logical_path).resolve()
    command = await asyncio.to_thread(
        connection_store.enqueue_command,
        session_id=session_id,
        command={
            "type": "open_file",
            "uri": target_path.as_uri(),
            "logical_path": logical_path,
            "request_session_id": session_id,
            "target": payload.target.model_dump(),
        },
    )
    return {
        "ok": True,
        "command": command,
        "connection_status": status.to_dict(),
        "authority": "api.file_management.open_vscode",
    }


def _context(session_id: str) -> ManagedFileServiceContext:
    return ManagedFileServiceContext(
        session_id=str(session_id or "").strip(),
        task_run_id="",
        agent_run_id="agent-ui",
        tool_call_id="",
        actor_id="agent_ui",
    )


def _managed_target_for_selected_file(runtime: Any, selected_path: str, *, session_id: str = "") -> tuple[Any, str, str]:
    from file_management.api_models import ManagedFileTarget
    from file_management.external_read_scopes import external_logical_path

    file_path = Path(selected_path).expanduser().resolve()
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Selected file not found")
    if not file_path.is_file():
        raise HTTPException(status_code=400, detail="Selected path is not a file")

    root = _session_project_root(runtime, session_id=session_id)
    if root is not None and _is_inside(file_path, root):
        logical_path = file_path.relative_to(root).as_posix()
        workspace_root = root
        display_path = logical_path
    else:
        service = ManagedFileService(runtime)
        scope = service.register_external_read_scope(source_path=str(file_path))
        target = service.external_read_target(scope)
        return target, external_logical_path(scope.scope_id, scope.default_logical_path()), str(file_path)

    scope_id = str(session_id or workspace_root.name or "selected-file").strip()
    target = ManagedFileTarget(
        repository_id=MANAGED_PROJECT_REPOSITORY_ID,
        repository_kind="project_workspace",
        scope_kind="project_scoped",
        scope_id=scope_id,
        logical_path=logical_path,
        workspace_root=str(workspace_root),
        profile_id=MANAGED_PROJECT_PROFILE_ID,
    )
    return target, display_path, str(file_path)


def _session_project_root(runtime: Any, *, session_id: str = "") -> Path | None:
    target_session_id = str(session_id or "").strip()
    session_manager = getattr(runtime, "session_manager", None)
    if not target_session_id or session_manager is None:
        return None
    binding = session_manager.get_project_binding(target_session_id)
    workspace_root = str(dict(binding or {}).get("workspace_root") or "").strip()
    if not workspace_root:
        return None
    root = Path(workspace_root).expanduser().resolve()
    return root if root.is_dir() else None


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _select_file_with_windows_dialog() -> str:
    if not sys.platform.startswith("win"):
        raise RuntimeError("Native file selection is only available on Windows.")
    try:
        selected = _select_file_with_tkinter()
    except Exception as tk_error:
        try:
            return _select_file_with_powershell()
        except RuntimeError as ps_error:
            raise RuntimeError(f"{ps_error}; tkinter selection failed: {tk_error}") from ps_error
    return selected


def _select_file_with_tkinter() -> str:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
        root.update()
        selected = filedialog.askopenfilename(
            parent=root,
            title="选择要打开的文件",
            filetypes=(
                ("文本和代码文件", "*.txt *.md *.json *.ts *.tsx *.js *.jsx *.py *.css *.html *.yml *.yaml *.toml *.ini *.log"),
                ("所有文件", "*.*"),
            ),
        )
        return str(selected or "").strip()
    finally:
        root.destroy()


def _select_file_with_powershell() -> str:
    command = [
        "powershell",
        "-NoProfile",
        "-STA",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        (
            "$ErrorActionPreference = 'Stop';"
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$dialog = New-Object System.Windows.Forms.OpenFileDialog;"
            "$dialog.Title = '选择要打开的文件';"
            "$dialog.CheckFileExists = $true;"
            "$dialog.Multiselect = $false;"
            "$dialog.Filter = '文本和代码文件|*.txt;*.md;*.json;*.ts;*.tsx;*.js;*.jsx;*.py;*.css;*.html;*.yml;*.yaml;*.toml;*.ini;*.log|所有文件|*.*';"
            "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {"
            "  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8;"
            "  Write-Output $dialog.FileName;"
            "}"
        ),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "File selection failed.").strip()
        raise RuntimeError(detail)
    return (completed.stdout or "").strip()
