from __future__ import annotations

import asyncio
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from api.session_summary import enrich_session_summaries, enrich_session_summary
from api.sessions import _select_project_directory_with_windows_dialog
from code_environment.models import CodeEnvironmentWorkspaceTreeResponse
from code_environment.workspace_tree import build_workspace_tree
from project_workspaces import ProjectWorkspaceMissing, ProjectWorkspaceService


router = APIRouter()


class RegisterProjectWorkspaceRequest(BaseModel):
    workspace_root: str = Field(..., min_length=1, max_length=1000)
    source: str = Field(default="manual", max_length=80)


class CreateProjectWorkspaceSessionRequest(BaseModel):
    title: str = Field(default="New Session", max_length=120)


@router.get("/project-workspaces")
async def list_project_workspaces() -> dict[str, Any]:
    runtime = require_runtime()
    projects = _service(runtime).list_workspaces()
    return {
        "authority": "project_workspaces.list",
        "projects": projects,
        "summary": {"project_count": len(projects)},
    }


@router.post("/project-workspaces")
async def register_project_workspace(payload: RegisterProjectWorkspaceRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        project = _service(runtime).register_workspace(
            payload.workspace_root,
            source=payload.source or "manual",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "authority": "project_workspaces.register",
        "project": project,
    }


@router.post("/project-workspaces/select-directory")
async def select_project_workspace_directory() -> dict[str, Any]:
    runtime = require_runtime()
    try:
        selected_root = await asyncio.to_thread(_select_project_directory_with_windows_dialog)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not selected_root:
        raise HTTPException(status_code=409, detail="project directory selection cancelled")
    try:
        project = _service(runtime).register_workspace(
            selected_root,
            source="frontend.directory_picker",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "authority": "project_workspaces.directory_picker",
        "project": project,
        "selected_path": selected_root,
    }


@router.get("/project-workspaces/{project_key}")
async def get_project_workspace(project_key: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        project = _service(runtime).workspace_for_key(project_key)
    except ProjectWorkspaceMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "authority": "project_workspaces.detail",
        "project": project,
    }


@router.get("/project-workspaces/{project_key}/sessions")
async def list_project_workspace_sessions(
    project_key: str,
    include_active_task: bool = Query(default=True),
) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        sessions = _service(runtime).sessions_for_workspace(project_key)
    except ProjectWorkspaceMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if include_active_task:
        sessions = enrich_session_summaries(sessions, runtime)
    return {
        "authority": "project_workspaces.sessions",
        "project_key": project_key,
        "sessions": sessions,
    }


@router.post("/project-workspaces/{project_key}/sessions")
async def create_project_workspace_session(
    project_key: str,
    payload: CreateProjectWorkspaceSessionRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    service = _service(runtime)
    try:
        project_binding = service.project_binding_for_key(project_key, source="project_workspace")
        session = runtime.session_manager.create_session(
            title=payload.title or "New Session",
            project_binding=project_binding,
        )
    except ProjectWorkspaceMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "authority": "project_workspaces.session_create",
        "project_key": project_key,
        "session": enrich_session_summary(session, runtime),
        "created": True,
    }


@router.get("/project-workspaces/{project_key}/workspace-tree")
async def project_workspace_tree(
    project_key: str,
    max_depth: int = Query(default=10, ge=1, le=12),
    max_entries: int = Query(default=10000, ge=100, le=50000),
) -> CodeEnvironmentWorkspaceTreeResponse:
    runtime = require_runtime()
    try:
        project = _service(runtime).workspace_for_key(project_key)
    except ProjectWorkspaceMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    root = Path(str(project.get("workspace_root") or "")).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="project workspace root not found")
    return build_workspace_tree(root, max_depth=max_depth, max_entries=max_entries)


@router.post("/project-workspaces/{project_key}/open-vscode")
async def open_project_workspace_in_vscode(project_key: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        project = _service(runtime).workspace_for_key(project_key)
    except ProjectWorkspaceMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    workspace_root = str(project.get("workspace_root") or "").strip()
    if not Path(workspace_root).expanduser().is_dir():
        raise HTTPException(status_code=404, detail="project workspace root not found")
    executable = shutil.which("code")
    if not executable:
        raise HTTPException(status_code=503, detail="VS Code CLI `code` was not found on PATH")
    command = [executable, "--new-window", workspace_root]
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
        subprocess.Popen(
            command,
            creationflags=creationflags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to open VS Code: {exc}") from exc
    return {
        "authority": "project_workspaces.open_vscode",
        "ok": True,
        "project": project,
        "command": command,
        "window_mode": "new_window",
    }


def _service(runtime: Any) -> ProjectWorkspaceService:
    return ProjectWorkspaceService(runtime.base_dir, runtime.session_manager)
