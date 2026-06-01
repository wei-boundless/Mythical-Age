from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from harness.runtime.session_timeline import build_session_runtime_timeline
from task_system.session_scope import assert_optional_session_scope, request_scope_from_query

router = APIRouter()

DEFAULT_SESSION_TITLE = "New Session"


class CreateSessionRequest(BaseModel):
    title: str = DEFAULT_SESSION_TITLE
    scope: dict[str, Any] = Field(default_factory=dict)


class RenameSessionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)


class GenerateTitleRequest(BaseModel):
    message: str | None = None


class TruncateMessagesRequest(BaseModel):
    message_index: int = Field(..., ge=0)


@router.get("/sessions")
async def list_sessions(
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> list[dict[str, Any]]:
    runtime = require_runtime()
    return runtime.session_manager.list_sessions(
        workspace_view=workspace_view,
        task_environment_id=task_environment_id,
        project_id=project_id,
    )


@router.post("/sessions")
async def create_session(payload: CreateSessionRequest) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.session_manager.create_session(title=payload.title, scope=payload.scope)


@router.put("/sessions/{session_id}")
async def rename_session(
    session_id: str,
    payload: RenameSessionRequest,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    return runtime.session_manager.rename_session(session_id, payload.title)


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, bool]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    runtime.session_manager.delete_session(session_id)
    runtime.memory_facade.delete_session_memory(session_id)
    return {"ok": True}


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    return {
        "messages": runtime.session_manager.load_session(session_id),
        "latest_prompt_manifest_summary": _latest_prompt_manifest_summary(runtime, session_id),
    }


@router.get("/sessions/{session_id}/history")
async def get_session_history(
    session_id: str,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    return runtime.session_manager.get_history(session_id)


@router.get("/sessions/{session_id}/timeline")
async def get_session_timeline(
    session_id: str,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    history = runtime.session_manager.get_history(session_id)
    return build_session_runtime_timeline(
        session_id=session_id,
        history=history,
        runtime_host=runtime.harness_runtime.single_agent_runtime_host,
    )


@router.post("/sessions/{session_id}/messages/truncate")
async def truncate_session_messages(
    session_id: str,
    payload: TruncateMessagesRequest,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
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
async def generate_title(
    session_id: str,
    payload: GenerateTitleRequest,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, str]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    if payload.message:
        seed = payload.message
    else:
        messages = runtime.session_manager.load_session(session_id)
        first_user = next((item["content"] for item in messages if item.get("role") == "user"), "")
        seed = first_user
    title = await runtime.harness_runtime.generate_title(seed or DEFAULT_SESSION_TITLE)
    runtime.session_manager.set_title(session_id, title)
    return {"session_id": session_id, "title": title}


def _latest_prompt_manifest_summary(runtime: Any, session_id: str) -> dict[str, Any]:
    ledger = runtime.harness_runtime.single_agent_runtime_host.prompt_accounting_ledger
    maps = ledger.list_segment_maps(session_id=session_id)
    latest = maps[-1] if maps else {}
    return {
        "authority": "api.sessions.latest_prompt_manifest_summary",
        "available": bool(latest),
        "request_id": str(latest.get("request_id") or ""),
        "task_run_id": str(latest.get("task_run_id") or ""),
        "segment_count": len(list(latest.get("segments") or [])),
        "predicted_prompt_tokens": int(latest.get("predicted_prompt_tokens") or 0),
        "metadata": dict(latest.get("metadata") or {}),
    }


