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


@router.get("/harness/runtime-anchors/{runtime_anchor_id}")
async def get_harness_runtime_anchor_trace(
    runtime_anchor_id: str,
    include_payloads: bool = False,
    include_model_messages: bool = False,
    event_limit: int | None = None,
) -> dict[str, Any]:
    runtime = require_runtime()
    task_run_id = _legacy_task_run_id_for_runtime_anchor(runtime, runtime_anchor_id)
    trace = runtime.harness_runtime.single_agent_runtime_host.get_trace(
        task_run_id,
        include_payloads=include_payloads,
        include_model_messages=include_model_messages,
        event_limit=event_limit,
    )
    if trace is None:
        raise HTTPException(status_code=404, detail="RuntimeAnchor trace not found")
    return {
        **trace,
        "runtime_anchor_id": runtime_anchor_id,
        "legacy_task_run_id": task_run_id,
    }


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


@router.delete("/harness/runtime-anchors/{runtime_anchor_id}")
async def delete_harness_runtime_anchor(runtime_anchor_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    task_run_id = _legacy_task_run_id_for_runtime_anchor(runtime, runtime_anchor_id)
    try:
        result = await TaskRecordLifecycleManager(runtime).delete_task_record(task_run_id)
    except TaskRecordLifecycleNotFound as exc:
        raise HTTPException(status_code=404, detail="RuntimeAnchor event scope not found") from exc
    except TaskRecordLifecycleConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": exc.reason,
                "runtime_anchor_id": runtime_anchor_id,
                "task_run_id": exc.task_run_id,
                "graph_run_id": exc.graph_run_id,
            },
        ) from exc
    return {
        **result,
        "runtime_anchor_id": runtime_anchor_id,
        "legacy_task_run_id": task_run_id,
    }


@router.get("/harness/task-runs/{task_run_id}/artifacts")
async def get_harness_task_run_artifacts(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.harness_runtime.single_agent_runtime_host.get_task_run_artifacts(task_run_id)


@router.get("/harness/runtime-anchors/{runtime_anchor_id}/artifacts")
async def get_harness_runtime_anchor_artifacts(runtime_anchor_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    task_run_id = _legacy_task_run_id_for_runtime_anchor(runtime, runtime_anchor_id)
    return {
        **runtime.harness_runtime.single_agent_runtime_host.get_task_run_artifacts(task_run_id),
        "runtime_anchor_id": runtime_anchor_id,
        "legacy_task_run_id": task_run_id,
    }


@router.get("/harness/task-runs/{task_run_id}/memory-receipts")
async def get_harness_task_run_memory_receipts(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.harness_runtime.single_agent_runtime_host.get_task_run_memory_receipts(task_run_id)


@router.get("/harness/runtime-anchors/{runtime_anchor_id}/memory-receipts")
async def get_harness_runtime_anchor_memory_receipts(runtime_anchor_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    task_run_id = _legacy_task_run_id_for_runtime_anchor(runtime, runtime_anchor_id)
    return {
        **runtime.harness_runtime.single_agent_runtime_host.get_task_run_memory_receipts(task_run_id),
        "runtime_anchor_id": runtime_anchor_id,
        "legacy_task_run_id": task_run_id,
    }


@router.get("/harness/projects/{project_id}/runtime-status")
async def get_project_runtime_status(project_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    status = runtime.harness_runtime.single_agent_runtime_host.get_project_runtime_status(project_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Project runtime status not found")
    return status


def _legacy_task_run_id_for_runtime_anchor(runtime: Any, runtime_anchor_id: str) -> str:
    normalized = str(runtime_anchor_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="runtime_anchor_id is required")
    host = runtime.harness_runtime.single_agent_runtime_host
    anchor = host.state_index.get_runtime_anchor(normalized)
    if anchor is None:
        raise HTTPException(status_code=404, detail="RuntimeAnchor not found")
    payload = anchor.to_dict() if hasattr(anchor, "to_dict") else dict(anchor)
    legacy_task_run_id = str(payload.get("legacy_task_run_id") or "").strip()
    if not legacy_task_run_id:
        event_scope_ref = str(payload.get("event_scope_ref") or "").strip()
        legacy_task_run_id = event_scope_ref.removeprefix("task_run:").strip() if event_scope_ref.startswith("task_run:") else event_scope_ref
    if not legacy_task_run_id:
        raise HTTPException(status_code=409, detail="RuntimeAnchor has no legacy event scope")
    return legacy_task_run_id
