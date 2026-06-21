from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from file_management.api_models import VSCodeCommandResultRequest
from integrations.vscode_connection import get_vscode_connection_store
from integrations.vscode_connection.models import VSCodeConnectionConflict, VSCodeConnectionLeaseConflict
from runtime.file_changes import FileChangeMissing, FileChangeTracker

router = APIRouter()

DEFAULT_COMMAND_POLL_WAIT_SECONDS = 10.0
MAX_COMMAND_POLL_WAIT_SECONDS = 15.0
COMMAND_POLL_STEP_SECONDS = 0.25
EMPTY_COMMAND_RETRY_AFTER_MS = 2500


class VSCodeContextRequest(BaseModel):
    connection_id: str = Field(default="", max_length=240)
    source: str = Field(default="vscode", max_length=80)
    captured_at: str = Field(default="", max_length=100)
    workspace_roots: list[str] = Field(default_factory=list)
    active_file: dict[str, Any] = Field(default_factory=dict)
    visible_files: list[dict[str, Any]] = Field(default_factory=list)
    open_tabs: list[dict[str, Any]] = Field(default_factory=list)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    limits: dict[str, Any] = Field(default_factory=dict)


class VSCodeSessionResolveRequest(BaseModel):
    workspace_roots: list[str] = Field(default_factory=list)
    connection_id: str = Field(default="", max_length=240)


class VSCodeConnectionAcquireRequest(BaseModel):
    connection_id: str = Field(default="", max_length=240)
    workspace_roots: list[str] = Field(default_factory=list)
    source: str = Field(default="vscode.extension", max_length=120)
    client_name: str = Field(default="", max_length=240)


class VSCodeConnectionHeartbeatRequest(BaseModel):
    workspace_roots: list[str] = Field(default_factory=list)


class VSCodeOpenFileChangeDiffRequest(BaseModel):
    record_id: str = Field(max_length=240)


@router.post("/vscode/sessions/resolve")
async def resolve_vscode_session(payload: VSCodeSessionResolveRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            get_vscode_connection_store().resolve_launch_intent,
            workspace_roots=list(payload.workspace_roots or []),
            connection_id=payload.connection_id,
        )
    except VSCodeConnectionLeaseConflict as exc:
        _raise_lease_conflict(exc)


@router.post("/vscode/sessions/{session_id}/connections/acquire")
async def acquire_vscode_connection(session_id: str, payload: VSCodeConnectionAcquireRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        lease = await asyncio.to_thread(
            get_vscode_connection_store().acquire_connection,
            session_manager=runtime.session_manager,
            session_id=session_id,
            workspace_roots=list(payload.workspace_roots or []),
            connection_id=payload.connection_id,
            source=payload.source,
            client_name=payload.client_name,
        )
        status = await asyncio.to_thread(
            get_vscode_connection_store().status,
            session_id,
            session_manager=runtime.session_manager,
        )
        return {
            "ok": True,
            "lease": lease.to_dict(),
            "connection_status": status.to_dict(),
            "authority": "api.vscode.connection_acquire",
        }
    except VSCodeConnectionLeaseConflict as exc:
        _raise_lease_conflict(exc)
    except VSCodeConnectionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/vscode/sessions/{session_id}/connections/{connection_id}/heartbeat")
async def heartbeat_vscode_connection(session_id: str, connection_id: str, payload: VSCodeConnectionHeartbeatRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        lease = await asyncio.to_thread(
            get_vscode_connection_store().heartbeat_connection,
            session_manager=runtime.session_manager,
            session_id=session_id,
            connection_id=connection_id,
            workspace_roots=list(payload.workspace_roots or []),
        )
        return {"ok": True, "lease": lease.to_dict(), "authority": "api.vscode.connection_heartbeat"}
    except VSCodeConnectionLeaseConflict as exc:
        _raise_lease_conflict(exc)
    except VSCodeConnectionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/vscode/sessions/{session_id}/connections/{connection_id}")
async def release_vscode_connection(session_id: str, connection_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return await asyncio.to_thread(
            get_vscode_connection_store().release_connection,
            session_manager=runtime.session_manager,
            session_id=session_id,
            connection_id=connection_id,
        )
    except VSCodeConnectionLeaseConflict as exc:
        _raise_lease_conflict(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/vscode/sessions/{session_id}/context")
async def record_vscode_context(session_id: str, payload: VSCodeContextRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        status = await asyncio.to_thread(
            get_vscode_connection_store().record_context,
            session_manager=runtime.session_manager,
            session_id=session_id,
            connection_id=payload.connection_id,
            editor_context=payload.model_dump(),
        )
        return status.to_dict()
    except VSCodeConnectionLeaseConflict as exc:
        _raise_lease_conflict(exc)
    except VSCodeConnectionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/vscode/sessions/{session_id}/connection-status")
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
async def next_vscode_command(
    session_id: str,
    wait_seconds: float = DEFAULT_COMMAND_POLL_WAIT_SECONDS,
    connection_id: str = Query(default="", max_length=240),
) -> dict[str, Any]:
    command, retry_after_ms, poll_reason = await _wait_for_next_command(session_id, connection_id=connection_id, wait_seconds=wait_seconds)
    if command:
        return {
            "session_id": session_id,
            "status": "ok",
            "command": command,
            "commands": [command],
            "retry_after_ms": retry_after_ms,
            "authority": "api.vscode.command_poll",
        }
    return {
        "session_id": session_id,
        "status": "empty",
        "command": None,
        "commands": [],
        "retry_after_ms": retry_after_ms,
        "poll_reason": poll_reason,
        "authority": "api.vscode.command_poll",
    }


@router.post("/vscode/sessions/{session_id}/commands/{command_id}/result")
async def record_vscode_command_result(
    session_id: str,
    command_id: str,
    payload: VSCodeCommandResultRequest,
    connection_id: str = Query(default="", max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        result = await asyncio.to_thread(
            get_vscode_connection_store().record_command_result,
            session_id=session_id,
            command_id=command_id,
            connection_id=connection_id,
            result=payload.model_dump(),
            session_manager=runtime.session_manager,
        )
        return {"ok": True, "result": result, "authority": "api.vscode.command_result"}
    except VSCodeConnectionLeaseConflict as exc:
        _raise_lease_conflict(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
            "request_session_id": session_id,
        },
    )
    return {
        "ok": True,
        "command": command,
        "connection_status": status.to_dict(),
        "authority": "api.vscode.open_file_change_diff",
    }


async def _wait_for_next_command(session_id: str, *, connection_id: str, wait_seconds: float) -> tuple[dict[str, Any], int, str]:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return {}, EMPTY_COMMAND_RETRY_AFTER_MS, "missing_session_id"
    runtime = require_runtime()
    store = get_vscode_connection_store()
    try:
        lease = await asyncio.to_thread(
            store.begin_command_poll,
            session_id=normalized_session_id,
            connection_id=connection_id,
            session_manager=runtime.session_manager,
        )
    except VSCodeConnectionLeaseConflict as exc:
        _raise_lease_conflict(exc)
    try:
        deadline = asyncio.get_running_loop().time() + max(0.0, min(float(wait_seconds or 0.0), MAX_COMMAND_POLL_WAIT_SECONDS))
        while True:
            command = store.pop_next_command(normalized_session_id)
            if command:
                return command, 250, "command_available"
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return {}, EMPTY_COMMAND_RETRY_AFTER_MS, "empty"
            await asyncio.sleep(min(COMMAND_POLL_STEP_SECONDS, remaining))
    finally:
        store.end_command_poll(lease.connection_id)


def _raise_lease_conflict(exc: VSCodeConnectionLeaseConflict) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
