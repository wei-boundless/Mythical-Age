from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from harness.loop.task_executor import (
    is_task_run_executable,
    is_task_run_executor_claimed,
    request_task_run_pause,
    resume_paused_task_run,
    stop_task_run,
)

router = APIRouter()


class TaskRunExecuteRequest(BaseModel):
    max_steps: int = Field(default=12, ge=1, le=50)


class TaskRunControlRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


@router.get("/orchestration/harness/sessions/{session_id}/task-runs")
async def list_harness_task_runs(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.single_agent_runtime_host.list_session_traces(session_id)


@router.get("/orchestration/harness/task-runs/{task_run_id}")
async def get_harness_trace(
    task_run_id: str,
    include_payloads: bool = False,
    include_model_messages: bool = False,
    event_limit: int | None = None,
) -> dict[str, Any]:
    runtime = require_runtime()
    trace = runtime.query_runtime.single_agent_runtime_host.get_trace(
        task_run_id,
        include_payloads=include_payloads,
        include_model_messages=include_model_messages,
        event_limit=event_limit,
    )
    if trace is None:
        raise HTTPException(status_code=404, detail="TaskRun trace not found")
    return trace


@router.get("/orchestration/harness/turn-runs/{turn_run_id}")
async def get_harness_turn_trace(
    turn_run_id: str,
    include_payloads: bool = False,
    include_model_messages: bool = False,
    event_limit: int | None = None,
) -> dict[str, Any]:
    runtime = require_runtime()
    trace = runtime.query_runtime.single_agent_runtime_host.get_turn_trace(
        turn_run_id,
        include_payloads=include_payloads,
        include_model_messages=include_model_messages,
        event_limit=event_limit,
    )
    if trace is None:
        raise HTTPException(status_code=404, detail="TurnRun trace not found")
    return trace


@router.post("/orchestration/harness/task-runs/{task_run_id}/execute")
async def execute_harness_task_run(
    task_run_id: str,
    payload: TaskRunExecuteRequest | None = None,
) -> dict[str, Any]:
    runtime = require_runtime()
    runtime_host = runtime.query_runtime.single_agent_runtime_host
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        raise HTTPException(status_code=404, detail="TaskRun not found")
    if str(getattr(task_run, "execution_runtime_kind", "") or "") not in {"single_agent_task", "subagent_task"}:
        raise HTTPException(status_code=409, detail="not_single_agent_task_run")
    max_steps = payload.max_steps if payload is not None else 12
    if is_task_run_executor_claimed(task_run):
        executor_status = str(dict(getattr(task_run, "diagnostics", {}) or {}).get("executor_status") or "")
        if executor_status != "scheduled":
            raise HTTPException(status_code=409, detail="task_run_executor_already_running")

        async def _recover_scheduled_executor() -> None:
            await runtime.query_runtime.execute_task_run(task_run_id, max_steps=max_steps)

        runtime_host.spawn_background_task(
            _recover_scheduled_executor(),
            name=f"task-run-executor-recover:{task_run_id}",
        )
        return {
            "ok": True,
            "accepted": True,
            "background_started": True,
            "task_run_id": task_run_id,
            "status": task_run.status,
            "monitor_url": f"/api/orchestration/runtime-monitor/task-runs/{task_run_id}",
            "trace_url": f"/api/orchestration/harness/task-runs/{task_run_id}",
            "recovered_from": "scheduled_executor_claim",
        }
    if not is_task_run_executable(task_run):
        raise HTTPException(status_code=409, detail=f"task_run_not_executable:{task_run.status}")
    schedule_result = runtime.query_runtime.schedule_task_run_executor(
        task_run_id,
        scheduler="task_run_execute_api",
        max_steps=max_steps,
    )
    if not schedule_result.get("ok") or not schedule_result.get("scheduled"):
        raise HTTPException(status_code=409, detail=str(schedule_result.get("reason") or "task_run_schedule_rejected"))
    updated_task_run = runtime_host.state_index.get_task_run(task_run_id) or task_run
    return {
        "ok": True,
        "accepted": True,
        "background_started": True,
        "task_run_id": task_run_id,
        "status": updated_task_run.status,
        "monitor_url": f"/api/orchestration/runtime-monitor/task-runs/{task_run_id}",
        "trace_url": f"/api/orchestration/harness/task-runs/{task_run_id}",
    }


@router.post("/orchestration/harness/task-runs/{task_run_id}/pause")
async def pause_harness_task_run(
    task_run_id: str,
    payload: TaskRunControlRequest | None = None,
) -> dict[str, Any]:
    runtime = require_runtime()
    result = request_task_run_pause(
        runtime.query_runtime.single_agent_runtime_host,
        task_run_id,
        reason=payload.reason if payload is not None else "",
        requested_by="user",
    )
    if result.get("error") == "task_run_not_found":
        raise HTTPException(status_code=404, detail="TaskRun not found")
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=str(result.get("error") or "task_run_pause_rejected"))
    return result


@router.post("/orchestration/harness/task-runs/{task_run_id}/resume")
async def resume_harness_task_run(
    task_run_id: str,
    payload: TaskRunExecuteRequest | None = None,
) -> dict[str, Any]:
    runtime = require_runtime()
    runtime_host = runtime.query_runtime.single_agent_runtime_host
    result = resume_paused_task_run(runtime_host, task_run_id, requested_by="user")
    if result.get("error") == "task_run_not_found":
        raise HTTPException(status_code=404, detail="TaskRun not found")
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=str(result.get("error") or "task_run_resume_rejected"))
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        raise HTTPException(status_code=404, detail="TaskRun not found")
    if is_task_run_executor_claimed(task_run):
        raise HTTPException(status_code=409, detail="task_run_executor_already_running")
    if not is_task_run_executable(task_run):
        raise HTTPException(status_code=409, detail=f"task_run_not_executable:{task_run.status}")
    max_steps = payload.max_steps if payload is not None else 12
    schedule_result = runtime.query_runtime.schedule_task_run_executor(
        task_run_id,
        scheduler="task_run_resume_api",
        max_steps=max_steps,
    )
    if not schedule_result.get("ok") or not schedule_result.get("scheduled"):
        raise HTTPException(status_code=409, detail=str(schedule_result.get("reason") or "task_run_schedule_rejected"))
    updated_task_run = runtime_host.state_index.get_task_run(task_run_id) or task_run
    return {
        **result,
        "background_started": True,
        "task_run_id": task_run_id,
        "status": updated_task_run.status,
        "monitor_url": f"/api/orchestration/runtime-monitor/task-runs/{task_run_id}",
        "trace_url": f"/api/orchestration/harness/task-runs/{task_run_id}",
    }


@router.post("/orchestration/harness/task-runs/{task_run_id}/stop")
async def stop_harness_task_run(
    task_run_id: str,
    payload: TaskRunControlRequest | None = None,
) -> dict[str, Any]:
    runtime = require_runtime()
    result = stop_task_run(
        runtime.query_runtime.single_agent_runtime_host,
        task_run_id,
        reason=payload.reason if payload is not None else "",
        requested_by="user",
    )
    if result.get("error") == "task_run_not_found":
        raise HTTPException(status_code=404, detail="TaskRun not found")
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=str(result.get("error") or "task_run_stop_rejected"))
    return result


@router.get("/orchestration/harness/task-runs/{task_run_id}/artifacts")
async def get_harness_task_run_artifacts(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.single_agent_runtime_host.get_task_run_artifacts(task_run_id)


@router.get("/orchestration/harness/task-runs/{task_run_id}/memory-receipts")
async def get_harness_task_run_memory_receipts(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.single_agent_runtime_host.get_task_run_memory_receipts(task_run_id)


@router.get("/orchestration/projects/{project_id}/runtime-status")
async def get_project_runtime_status(project_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    status = runtime.query_runtime.single_agent_runtime_host.get_project_runtime_status(project_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Project runtime status not found")
    return status
