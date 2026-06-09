from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.deps import require_runtime
from harness.runtime.run_monitor import RuntimeMonitorActionService
from harness.runtime.runtime_monitor_public_projection import project_runtime_monitor_event_public_delta

router = APIRouter()


class RuntimeMonitorActionRequest(BaseModel):
    action: str = Field(default="", max_length=80)
    signal_id: str = Field(default="", max_length=300)
    task_run_id: str = Field(default="", max_length=300)
    graph_run_id: str = Field(default="", max_length=300)
    reason: str = Field(default="", max_length=500)
    source_revision: str = Field(default="", max_length=300)
    max_steps: int = Field(default=12, ge=1, le=50)


def _sse(event: str, data: dict[str, Any], *, event_id: str = "") -> str:
    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


def _service():
    runtime = require_runtime()
    return runtime.harness_runtime.single_agent_runtime_host.runtime_monitor_service


def _action_service() -> RuntimeMonitorActionService:
    runtime = require_runtime()
    return RuntimeMonitorActionService(
        runtime=runtime,
        monitor_service=runtime.harness_runtime.single_agent_runtime_host.runtime_monitor_service,
    )


async def _collect_global_runtime_monitor(service: Any, *, limit: int) -> dict[str, Any]:
    return await asyncio.to_thread(service.collect_global_runtime_monitor, limit=limit)


@router.get("/orchestration/runtime-monitor")
async def list_runtime_monitor(limit: int = 30) -> dict[str, Any]:
    return await _collect_global_runtime_monitor(_service(), limit=limit)


@router.get("/orchestration/runtime-monitor/management")
async def get_runtime_monitor_management(limit: int = 80) -> dict[str, Any]:
    monitor = await _collect_global_runtime_monitor(_service(), limit=limit)
    return {
        "authority": "runtime_monitor.management_api",
        "monitor": monitor,
        "management": dict(monitor.get("management") or {}),
        "updated_at": time.time(),
    }


@router.post("/orchestration/runtime-monitor/actions/preflight")
async def preflight_runtime_monitor_action(payload: RuntimeMonitorActionRequest) -> dict[str, Any]:
    return await _action_service().preflight(payload.model_dump())


@router.post("/orchestration/runtime-monitor/actions")
async def execute_runtime_monitor_action(payload: RuntimeMonitorActionRequest) -> dict[str, Any]:
    return await _action_service().execute(payload.model_dump())


@router.get("/orchestration/runtime-monitor/events")
async def stream_runtime_monitor_events(request: Request, limit: int = 40):
    runtime = require_runtime()
    runtime_host = runtime.harness_runtime.single_agent_runtime_host
    service = runtime_host.runtime_monitor_service
    subscription = runtime_host.event_log.subscribe()
    requested_limit = max(1, min(int(limit or 40), 100))

    async def event_generator():
        try:
            yield _sse(
                "runtime_monitor_snapshot",
                {
                    "monitor": await _collect_global_runtime_monitor(service, limit=requested_limit),
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
                monitor = await _collect_global_runtime_monitor(service, limit=requested_limit)
                raw_event = runtime_event.to_dict()
                public_projection = project_runtime_monitor_event_public_delta(
                    raw_event,
                    runtime_host=runtime_host,
                    monitor=monitor,
                )
                yield _sse(
                    "runtime_monitor_event",
                    {
                        "runtime_event": {**raw_event, **public_projection},
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


@router.get("/orchestration/runtime-monitor/sessions/{session_id}")
async def get_runtime_monitor_session(session_id: str, limit: int = 20) -> dict[str, Any]:
    return _service().get_session_live_monitor(session_id, limit=limit)


@router.get("/orchestration/runtime-monitor/task-runs/{task_run_id}")
async def get_runtime_monitor_task_run(task_run_id: str) -> dict[str, Any]:
    monitor = _service().get_task_run_live_monitor(task_run_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="TaskRun live monitor not found")
    return monitor


@router.get("/orchestration/runtime-monitor/resources/{resource_ref:path}")
async def get_runtime_monitor_resource(resource_ref: str) -> dict[str, Any]:
    return _service().get_resource(resource_ref)
