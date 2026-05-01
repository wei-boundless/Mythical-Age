from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from health_system import HealthRegistry

router = APIRouter()


class HealthAgentRunPreviewRequest(BaseModel):
    task_mode: str = Field(default="issue_triage")


class HealthAgentRunStartRequest(BaseModel):
    task_mode: str = Field(default="issue_triage")
    session_id: str = Field(default="health-system")
    source: str = Field(default="health_system.manual")


class HealthIssueCreateRequest(BaseModel):
    title: str
    owner_system: str = Field(default="unknown")
    severity: str = Field(default="medium")
    status: str = Field(default="triage_ready")
    source: str = Field(default="manual")
    conversation_ref: str = Field(default="")
    runtime_trace_refs: list[str] = Field(default_factory=list)
    prompt_manifest_refs: list[str] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)
    assertion_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.get("/health-system/overview")
async def health_system_overview() -> dict[str, Any]:
    runtime = require_runtime()
    return HealthRegistry(runtime.base_dir).build_overview()


@router.get("/health-system/issues")
async def health_system_issues() -> dict[str, Any]:
    runtime = require_runtime()
    registry = HealthRegistry(runtime.base_dir)
    return {"authority": "health_system.issues", "issues": [item.to_dict() for item in registry.list_issues()]}


@router.post("/health-system/issues")
async def health_system_create_issue(payload: HealthIssueCreateRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        issue = HealthRegistry(runtime.base_dir).create_issue(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return issue.to_dict()


@router.get("/health-system/issues/{issue_id}")
async def health_system_issue(issue_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    issue = HealthRegistry(runtime.base_dir).get_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Unknown health issue")
    return issue.to_dict()


@router.get("/health-system/agent-runs/{run_id}")
async def health_system_agent_run(run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    run = HealthRegistry(runtime.base_dir).get_agent_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown health agent run")
    return run.to_dict()


@router.get("/health-system/agent-runs/{run_id}/result")
async def health_system_agent_run_result(run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    registry = HealthRegistry(runtime.base_dir)
    run = registry.get_agent_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown health agent run")
    if not run.result_ref:
        raise HTTPException(status_code=404, detail="Health agent run has no result yet")
    result = registry.get_agent_result(run.result_ref)
    if result is None:
        raise HTTPException(status_code=404, detail="Health agent result not found")
    return result


@router.get("/health-system/agent-runs/{run_id}/trace-report")
async def health_system_agent_run_trace_report(run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return HealthRegistry(runtime.base_dir).build_agent_run_trace_report(
            run_id=run_id,
            task_run_loop=runtime.query_runtime.task_run_loop,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown health agent run or trace") from exc


@router.post("/health-system/issues/{issue_id}/agent-runs/preview")
async def health_system_agent_run_preview(issue_id: str, payload: HealthAgentRunPreviewRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return HealthRegistry(runtime.base_dir).preview_agent_run(issue_id=issue_id, task_mode=payload.task_mode)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown health issue or task mode") from exc


@router.post("/health-system/issues/{issue_id}/agent-runs")
async def health_system_agent_run_start(issue_id: str, payload: HealthAgentRunStartRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return await HealthRegistry(runtime.base_dir).execute_agent_run(
            issue_id=issue_id,
            task_mode=payload.task_mode,
            session_id=payload.session_id,
            source=payload.source,
            task_run_loop=runtime.query_runtime.task_run_loop,
            model_response_executor=runtime.query_runtime.model_response_executor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown health issue or task mode") from exc
