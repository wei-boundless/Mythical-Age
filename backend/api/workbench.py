from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from sessions import InvalidSessionId
from task_system.session_scope import normalize_session_scope
from workbench_state import WorkbenchStateStore

router = APIRouter()


class CurrentSessionRefRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=200)
    scope: dict[str, Any] = Field(default_factory=dict)
    pool_key: str = Field(default="main-chat", max_length=240)


@router.get("/workbench/current-session")
async def get_workbench_current_session() -> dict[str, Any]:
    runtime = require_runtime()
    return WorkbenchStateStore(runtime.base_dir).current_session_payload()


@router.put("/workbench/current-session")
async def set_workbench_current_session(payload: CurrentSessionRefRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        summary = runtime.session_manager.get_session_summary(payload.session_id)
    except InvalidSessionId:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if payload.scope:
        actual = normalize_session_scope(dict(summary.get("scope") or {}))
        expected = normalize_session_scope(payload.scope)
        if actual.to_dict() != expected.to_dict():
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Session scope mismatch",
                    "session_id": payload.session_id,
                    "actual_scope": actual.to_dict(),
                    "expected_scope": expected.to_dict(),
                },
            )
    return WorkbenchStateStore(runtime.base_dir).set_current_session(
        session_id=payload.session_id,
        scope=dict(summary.get("scope") or {}),
        pool_key=payload.pool_key,
    )


@router.delete("/workbench/current-session")
async def clear_workbench_current_session(
    session_id: str | None = Query(default=None, max_length=200),
) -> dict[str, Any]:
    runtime = require_runtime()
    return WorkbenchStateStore(runtime.base_dir).clear_current_session(session_id=session_id or "")
