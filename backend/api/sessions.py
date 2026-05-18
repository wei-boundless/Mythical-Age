from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime

router = APIRouter()

DEFAULT_SESSION_TITLE = "New Session"


class CreateSessionRequest(BaseModel):
    title: str = DEFAULT_SESSION_TITLE


class RenameSessionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)


class GenerateTitleRequest(BaseModel):
    message: str | None = None


class TruncateMessagesRequest(BaseModel):
    message_index: int = Field(..., ge=0)


@router.get("/sessions")
async def list_sessions() -> list[dict[str, Any]]:
    runtime = require_runtime()
    return runtime.session_manager.list_sessions()


@router.post("/sessions")
async def create_session(payload: CreateSessionRequest) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.session_manager.create_session(title=payload.title)


@router.put("/sessions/{session_id}")
async def rename_session(session_id: str, payload: RenameSessionRequest) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.session_manager.rename_session(session_id, payload.title)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, bool]:
    runtime = require_runtime()
    runtime.session_manager.delete_session(session_id)
    runtime.memory_facade.delete_session_memory(session_id)
    return {"ok": True}


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return {
        "system_prompt": runtime.query_runtime.build_system_prompt_for_session(session_id),
        "messages": runtime.session_manager.load_session(session_id),
    }


@router.get("/sessions/{session_id}/history")
async def get_session_history(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.session_manager.get_history(session_id)


@router.post("/sessions/{session_id}/messages/truncate")
async def truncate_session_messages(session_id: str, payload: TruncateMessagesRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        record = runtime.session_manager.truncate_messages_from(session_id, payload.message_index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        await runtime.memory_facade.arun_memory_maintenance_after_commit(
            session_id=session_id,
            messages=list(record.get("messages", []) or []),
            durable_lane_enabled=False,
        )
    except Exception:
        pass
    return record


@router.post("/sessions/{session_id}/generate-title")
async def generate_title(session_id: str, payload: GenerateTitleRequest) -> dict[str, str]:
    runtime = require_runtime()
    if payload.message:
        seed = payload.message
    else:
        messages = runtime.session_manager.load_session(session_id)
        first_user = next((item["content"] for item in messages if item.get("role") == "user"), "")
        seed = first_user
    title = await runtime.query_runtime.generate_title(seed or DEFAULT_SESSION_TITLE)
    runtime.session_manager.set_title(session_id, title)
    return {"session_id": session_id, "title": title}
