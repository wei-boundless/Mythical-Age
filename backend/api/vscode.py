from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from integrations.vscode_connection import get_vscode_connection_store
from integrations.vscode_connection.models import VSCodeConnectionConflict

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


@router.post("/vscode/sessions/resolve")
async def resolve_vscode_session(payload: VSCodeSessionResolveRequest) -> dict[str, Any]:
    runtime = require_runtime()
    return get_vscode_connection_store().resolve_launch_intent(
        workspace_roots=list(payload.workspace_roots or []),
        session_manager=runtime.session_manager,
    )


@router.post("/vscode/sessions/{session_id}/context")
async def record_vscode_context(session_id: str, payload: VSCodeContextRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return get_vscode_connection_store().record_context(
            session_manager=runtime.session_manager,
            session_id=session_id,
            editor_context=payload.model_dump(),
        ).to_dict()
    except VSCodeConnectionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/vscode/sessions/{session_id}/context/latest")
async def latest_vscode_context(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    context = get_vscode_connection_store().latest_editor_context(
        session_id,
        session_manager=runtime.session_manager,
    )
    return {"editor_context": context}


@router.get("/vscode/sessions/{session_id}/status")
async def vscode_connection_status(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return get_vscode_connection_store().status(
            session_id,
            session_manager=runtime.session_manager,
        ).to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/vscode/sessions/{session_id}/commands/next")
async def next_vscode_command(session_id: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "status": "empty",
        "command": "",
        "commands": [],
        "authority": "api.vscode.legacy_command_poll",
    }
