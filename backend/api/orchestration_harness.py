from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.deps import require_runtime

router = APIRouter()


def _sse(event: str, data: dict[str, Any], *, event_id: str = "") -> str:
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


class TaskRunStopRequest(BaseModel):
    reason: str = Field(default="user_aborted", max_length=120)
    message: str = Field(default="", max_length=500)
    coordination_run_id: str = Field(default="", max_length=180)


class TaskRunApprovalRequest(BaseModel):
    decision: str = Field(..., min_length=1, max_length=40)
    message: str = Field(default="", max_length=500)


class TaskGraphMonitorEvaluateRequest(BaseModel):
    monitor_node_id: str = Field(default="", max_length=180)
    monitor_policy: dict[str, Any] = Field(default_factory=dict)


@router.get("/orchestration/harness/sessions/{session_id}/task-runs")
async def list_harness_task_runs(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.single_agent_runtime_host.list_session_traces(session_id)


@router.get("/orchestration/harness/live-monitor")
async def list_harness_global_live_monitor(limit: int = 20) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.single_agent_runtime_host.list_global_live_monitor(limit=limit)


@router.get("/orchestration/harness/monitor-events")
async def stream_harness_monitor_events(request: Request, limit: int = 40):
    runtime = require_runtime()
    runtime_host = runtime.query_runtime.single_agent_runtime_host
    subscription = runtime_host.event_log.subscribe()
    requested_limit = max(1, min(int(limit or 40), 100))

    async def event_generator():
        try:
            yield _sse(
                "runtime_monitor_snapshot",
                {
                    "monitor": runtime_host.list_global_live_monitor(limit=requested_limit),
                    "source": "initial",
                },
            )
            while not await request.is_disconnected():
                try:
                    runtime_event = await asyncio.wait_for(subscription.queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield _sse(
                        "runtime_monitor_heartbeat",
                        {
                            "updated_at": time.time(),
                            "source": "heartbeat",
                        },
                    )
                    continue
                monitor = runtime_host.list_global_live_monitor(limit=requested_limit)
                yield _sse(
                    "runtime_monitor_event",
                    {
                        "runtime_event": runtime_event.to_dict(),
                        "monitor": monitor,
                        "source": "runtime_event_log",
                    },
                    event_id=runtime_event.event_id,
                )
        finally:
            runtime_host.event_log.unsubscribe(subscription)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/orchestration/harness/sessions/{session_id}/live-monitor")
async def get_harness_session_live_monitor(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.single_agent_runtime_host.get_session_live_monitor(session_id)


@router.get("/orchestration/harness/task-runs/{task_run_id}")
async def get_harness_trace(
    task_run_id: str,
    include_payloads: bool = False,
    include_model_messages: bool = False,
) -> dict[str, Any]:
    runtime = require_runtime()
    trace = runtime.query_runtime.single_agent_runtime_host.get_trace(
        task_run_id,
        include_payloads=include_payloads,
        include_model_messages=include_model_messages,
    )
    if trace is None:
        raise HTTPException(status_code=404, detail="TaskRun trace not found")
    return trace


@router.get("/orchestration/harness/task-runs/{task_run_id}/live-monitor")
async def get_harness_task_run_live_monitor(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    monitor = runtime.query_runtime.single_agent_runtime_host.get_task_run_live_monitor(task_run_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="TaskRun live monitor not found")
    return monitor


@router.get("/orchestration/harness/task-runs/{task_run_id}/task-graph-monitor")
async def get_harness_task_graph_run_monitor(task_run_id: str) -> dict[str, Any]:
    raise HTTPException(status_code=410, detail="TaskGraph monitor is not available in the rebuilt single-agent runtime")


@router.post("/orchestration/harness/task-runs/{task_run_id}/task-graph-monitor/evaluate")
async def evaluate_harness_task_graph_monitor(
    task_run_id: str,
    payload: TaskGraphMonitorEvaluateRequest,
) -> dict[str, Any]:
    del task_run_id, payload
    raise HTTPException(status_code=410, detail="TaskGraph monitor evaluation is not available in the rebuilt single-agent runtime")


@router.get("/orchestration/harness/task-runs/{task_run_id}/monitor-decisions")
async def list_harness_task_graph_monitor_decisions(task_run_id: str) -> dict[str, Any]:
    del task_run_id
    raise HTTPException(status_code=410, detail="TaskGraph monitor decisions are not available in the rebuilt single-agent runtime")


@router.get("/orchestration/harness/task-runs/{task_run_id}/artifacts")
async def get_harness_task_run_artifacts(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.single_agent_runtime_host.get_task_run_artifacts(task_run_id)


@router.get("/orchestration/harness/task-runs/{task_run_id}/memory-receipts")
async def get_harness_task_run_memory_receipts(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.single_agent_runtime_host.get_task_run_memory_receipts(task_run_id)


@router.post("/orchestration/harness/task-runs/{task_run_id}/approval")
async def resolve_harness_task_run_approval(
    task_run_id: str,
    payload: TaskRunApprovalRequest,
) -> dict[str, Any]:
    del task_run_id, payload
    raise HTTPException(status_code=410, detail="Legacy pending approval resolution is not available in the rebuilt single-agent runtime")


@router.get("/orchestration/projects/{project_id}/runtime-status")
async def get_project_runtime_status(project_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    status = runtime.query_runtime.single_agent_runtime_host.get_project_runtime_status(project_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Project runtime status not found")
    return status


@router.post("/orchestration/harness/task-runs/{task_run_id}/stop")
async def stop_task_run(
    task_run_id: str,
    payload: TaskRunStopRequest,
) -> dict[str, Any]:
    del task_run_id, payload
    raise HTTPException(status_code=410, detail="Legacy checkpoint stop is not available in the rebuilt single-agent runtime")



