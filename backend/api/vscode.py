from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from integrations.vscode_connection import get_vscode_connection_store
from integrations.vscode_connection.models import VSCodeConnectionConflict
from runtime.file_changes import FileChangeMissing, FileChangeTracker

router = APIRouter()


class VSCodeContextRequest(BaseModel):
    source: str = Field(default="vscode", max_length=80)
    captured_at: str = Field(default="", max_length=100)
    workspace_roots: list[str] = Field(default_factory=list)
    active_file: dict[str, Any] = Field(default_factory=dict)
    visible_files: list[dict[str, Any]] = Field(default_factory=list)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    limits: dict[str, Any] = Field(default_factory=dict)


class VSCodeSessionResolveRequest(BaseModel):
    workspace_roots: list[str] = Field(default_factory=list)


class VSCodeOpenFileChangeDiffRequest(BaseModel):
    record_id: str = Field(max_length=240)


@router.post("/vscode/sessions/resolve")
async def resolve_vscode_session(payload: VSCodeSessionResolveRequest) -> dict[str, Any]:
    runtime = require_runtime()
    return await asyncio.to_thread(
        get_vscode_connection_store().resolve_launch_intent,
        workspace_roots=list(payload.workspace_roots or []),
        session_manager=runtime.session_manager,
    )


@router.post("/vscode/sessions/{session_id}/context")
async def record_vscode_context(session_id: str, payload: VSCodeContextRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        status = await asyncio.to_thread(
            get_vscode_connection_store().record_context,
            session_manager=runtime.session_manager,
            session_id=session_id,
            editor_context=payload.model_dump(),
        )
        return status.to_dict()
    except VSCodeConnectionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/vscode/sessions/{session_id}/context/latest")
async def latest_vscode_context(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    context = await asyncio.to_thread(
        get_vscode_connection_store().latest_editor_context,
        session_id,
        session_manager=runtime.session_manager,
    )
    return {"editor_context": context}


@router.get("/vscode/sessions/{session_id}/status")
async def vscode_connection_status(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        status = await asyncio.to_thread(
            get_vscode_connection_store().status,
            session_id,
            session_manager=runtime.session_manager,
        )
        return status.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/vscode/sessions/{session_id}/commands/next")
async def next_vscode_command(session_id: str) -> dict[str, Any]:
    command = await asyncio.to_thread(get_vscode_connection_store().pop_next_command, session_id)
    if command:
        return {
            "session_id": session_id,
            "status": "ok",
            "command": command,
            "commands": [command],
            "authority": "api.vscode.command_poll",
        }
    return {
        "session_id": session_id,
        "status": "empty",
        "command": None,
        "commands": [],
        "authority": "api.vscode.command_poll",
    }


@router.post("/vscode/sessions/{session_id}/file-change-diffs/open")
async def open_file_change_diff_in_vscode(session_id: str, payload: VSCodeOpenFileChangeDiffRequest) -> dict[str, Any]:
    runtime = require_runtime()
    connection_store = get_vscode_connection_store()
    status = await asyncio.to_thread(connection_store.status, session_id, session_manager=runtime.session_manager)
    if not status.connected or status.stale:
        raise HTTPException(status_code=409, detail="VS Code connection is not active")
    try:
        record = await asyncio.to_thread(FileChangeTracker(runtime.base_dir).require_record, payload.record_id)
    except FileChangeMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if str(record.get("session_id") or "") != str(session_id or "").strip():
        raise HTTPException(status_code=409, detail="file change record does not belong to this session")
    before_uri = str(record.get("before_uri") or "").strip()
    after_uri = str(record.get("after_uri") or "").strip()
    if not before_uri or not after_uri:
        raise HTTPException(status_code=409, detail="file change snapshots are not available")
    command = await asyncio.to_thread(
        connection_store.enqueue_command,
        session_id=session_id,
        command={
            "type": "open_diff",
            "left_uri": before_uri,
            "right_uri": after_uri,
            "title": str(record.get("logical_path") or record.get("record_id") or "File change"),
            "record_id": str(record.get("record_id") or ""),
        },
    )
    return {
        "ok": True,
        "command": command,
        "connection_status": status.to_dict(),
        "authority": "api.vscode.open_file_change_diff",
    }
