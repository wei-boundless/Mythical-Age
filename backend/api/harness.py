from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from api.deps import require_runtime
from harness.runtime.task_record_lifecycle import (
    TaskRecordLifecycleConflict,
    TaskRecordLifecycleManager,
    TaskRecordLifecycleNotFound,
)

router = APIRouter()


@router.get("/harness/sessions/{session_id}/task-runs")
async def list_harness_task_runs(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.harness_runtime.single_agent_runtime_host.list_session_traces(session_id)


@router.get("/harness/task-runs/{task_run_id}")
async def get_harness_trace(
    task_run_id: str,
    include_payloads: bool = False,
    include_model_messages: bool = False,
    event_limit: int | None = None,
) -> dict[str, Any]:
    runtime = require_runtime()
    trace = runtime.harness_runtime.single_agent_runtime_host.get_trace(
        task_run_id,
        include_payloads=include_payloads,
        include_model_messages=include_model_messages,
        event_limit=event_limit,
    )
    if trace is None:
        raise HTTPException(status_code=404, detail="TaskRun trace not found")
    return trace


@router.get("/harness/turn-runs/{turn_run_id}")
async def get_harness_turn_trace(
    turn_run_id: str,
    include_payloads: bool = False,
    include_model_messages: bool = False,
    event_limit: int | None = None,
) -> dict[str, Any]:
    runtime = require_runtime()
    trace = runtime.harness_runtime.single_agent_runtime_host.get_turn_trace(
        turn_run_id,
        include_payloads=include_payloads,
        include_model_messages=include_model_messages,
        event_limit=event_limit,
    )
    if trace is None:
        raise HTTPException(status_code=404, detail="TurnRun trace not found")
    return trace


@router.delete("/harness/task-runs/{task_run_id}")
async def delete_harness_task_run(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return await TaskRecordLifecycleManager(runtime).delete_task_record(task_run_id)
    except TaskRecordLifecycleNotFound as exc:
        raise HTTPException(status_code=404, detail="TaskRun not found") from exc
    except TaskRecordLifecycleConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": exc.reason,
                "task_run_id": exc.task_run_id,
                "graph_run_id": exc.graph_run_id,
            },
        ) from exc

@router.get("/harness/task-runs/{task_run_id}/artifacts")
async def get_harness_task_run_artifacts(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.harness_runtime.single_agent_runtime_host.get_task_run_artifacts(task_run_id)


@router.get("/harness/task-runs/{task_run_id}/memory-receipts")
async def get_harness_task_run_memory_receipts(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.harness_runtime.single_agent_runtime_host.get_task_run_memory_receipts(task_run_id)


@router.get("/harness/projects/{project_id}/runtime-status")
async def get_project_runtime_status(project_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    status = runtime.harness_runtime.single_agent_runtime_host.get_project_runtime_status(project_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Project runtime status not found")
    return status
