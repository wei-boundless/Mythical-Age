from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from api.session_summary import enrich_session_summaries
from harness.runtime.session_lifecycle import SessionRuntimeLifecycleManager
from harness.runtime.session_timeline import build_session_runtime_timeline
from task_system.environments import task_environment_registry_from_backend_dir
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


class ActiveTaskEnvironmentRequest(BaseModel):
    task_environment_id: str = Field(..., min_length=3, max_length=200)
    environment_label: str = Field(default="", max_length=200)
    source: str = Field(default="conversation", max_length=80)


class SessionPermissionModeRequest(BaseModel):
    mode: str = Field(..., min_length=1, max_length=80)


@router.get("/sessions")
async def list_sessions(
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
    include_active_task: bool = Query(default=False),
) -> list[dict[str, Any]]:
    runtime = require_runtime()
    sessions = runtime.session_manager.list_sessions(
        workspace_view=workspace_view,
        task_environment_id=task_environment_id,
        project_id=project_id,
    )
    if not include_active_task:
        return sessions
    return enrich_session_summaries(sessions, runtime)


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
) -> dict[str, Any]:
    runtime = require_runtime()
    missing_session = False
    try:
        assert_optional_session_scope(
            runtime.session_manager,
            session_id,
            request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
        )
    except ValueError as exc:
        if str(exc) != "Unknown session_id":
            raise
        missing_session = True
    try:
        cleanup = await SessionRuntimeLifecycleManager(runtime).detach_session_runtime(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not missing_session:
        runtime.session_manager.delete_session(session_id)
    return {"ok": True, "cleanup": cleanup, "session_missing_before_delete": missing_session}


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


@router.get("/sessions/{session_id}/conversation-state")
async def get_session_conversation_state(
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
    return runtime.session_manager.get_conversation_state(session_id)


@router.put("/sessions/{session_id}/active-task-environment")
async def set_session_active_task_environment(
    session_id: str,
    payload: ActiveTaskEnvironmentRequest,
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
        task_environment_registry_from_backend_dir(runtime.base_dir).require(payload.task_environment_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown task environment: {payload.task_environment_id}") from exc
    return runtime.session_manager.set_active_task_environment(
        session_id,
        {
            "task_environment_id": payload.task_environment_id,
            "environment_label": payload.environment_label or payload.task_environment_id,
            "source": payload.source or "conversation",
        },
    )


@router.put("/sessions/{session_id}/permission-mode")
async def set_session_permission_mode(
    session_id: str,
    payload: SessionPermissionModeRequest,
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
    return runtime.session_manager.set_permission_mode(session_id, payload.mode)


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
        ledger = runtime.harness_runtime.single_agent_runtime_host.prompt_accounting_ledger
        reset = getattr(ledger, "reset_prompt_cache_baseline", None)
        if callable(reset):
            reset(
                request_id=f"pcachebaseline-reset:session-truncate:{session_id}:{payload.message_index}",
                session_id=session_id,
                reason="session_history_truncated",
                reset_ref=f"session:{session_id}:message_index:{payload.message_index}",
                diagnostics={"message_index": payload.message_index},
            )
    except Exception:
        pass
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


