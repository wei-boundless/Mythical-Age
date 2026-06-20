from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from api.deps import require_runtime
from file_management.api_models import (
    ManagedFileEditRequest,
    ManagedFileOpenInVSCodeRequest,
    ManagedFileReadRequest,
    ManagedFileWriteRequest,
)
from file_management.service import ManagedFileService, ManagedFileServiceContext
from integrations.vscode_connection import get_vscode_connection_store

router = APIRouter()


@router.get("/file-management/profiles")
async def list_file_management_profiles() -> dict[str, Any]:
    runtime = require_runtime()
    return await asyncio.to_thread(ManagedFileService(runtime).list_profiles)


@router.get("/file-management/repositories")
async def list_file_management_repositories(session_id: str = "") -> dict[str, Any]:
    runtime = require_runtime()
    return await asyncio.to_thread(ManagedFileService(runtime).list_repositories, session_id=session_id)


@router.post("/file-management/files/read")
async def read_managed_file(payload: ManagedFileReadRequest) -> dict[str, Any]:
    runtime = require_runtime()
    return await asyncio.to_thread(
        ManagedFileService(runtime).read,
        payload.target,
        context=_context(payload.session_id or payload.target.scope_id),
    )


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
    command_session_id = str(status.connection_session_id or session_id).strip() or session_id
    command = await asyncio.to_thread(
        connection_store.enqueue_command,
        session_id=command_session_id,
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
