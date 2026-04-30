from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from health_system import HealthRegistry

router = APIRouter()


class HealthAgentRunPreviewRequest(BaseModel):
    task_mode: str = Field(default="issue_triage")


@router.get("/health-system/overview")
async def health_system_overview() -> dict[str, Any]:
    runtime = require_runtime()
    return HealthRegistry(runtime.base_dir).build_overview()


@router.get("/health-system/issues")
async def health_system_issues() -> dict[str, Any]:
    runtime = require_runtime()
    registry = HealthRegistry(runtime.base_dir)
    return {"authority": "health_system.issues", "issues": [item.to_dict() for item in registry.list_issues()]}


@router.get("/health-system/agent-runs/{run_id}")
async def health_system_agent_run(run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    run = next((item for item in HealthRegistry(runtime.base_dir).list_agent_runs() if item.run_id == run_id), None)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown health agent run")
    return run.to_dict()


@router.post("/health-system/issues/{issue_id}/agent-runs/preview")
async def health_system_agent_run_preview(issue_id: str, payload: HealthAgentRunPreviewRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return HealthRegistry(runtime.base_dir).preview_agent_run(issue_id=issue_id, task_mode=payload.task_mode)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown health issue or task mode") from exc
