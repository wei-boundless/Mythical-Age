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


def _stream_poll_interval(value: float | int | None) -> float:
    try:
        parsed = float(value if value is not None else 2.0)
    except (TypeError, ValueError):
        parsed = 2.0
    return max(0.5, min(parsed, 15.0))


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
async def stream_runtime_monitor_events(request: Request, limit: int = 40, poll_interval_seconds: float = 2.0):
    service = _service()
    requested_limit = max(1, min(int(limit or 40), 100))
    poll_interval = _stream_poll_interval(poll_interval_seconds)

    async def event_generator():
        yield _sse(
            "runtime_monitor_heartbeat",
            {
                "updated_at": time.time(),
                "source": "connected",
            },
        )
        last_revision = ""
        snapshot_source = "initial"
        while not await request.is_disconnected():
            started_at = time.time()
            try:
                monitor = await _collect_global_runtime_monitor(service, limit=requested_limit)
            except Exception as exc:
                yield _sse(
                    "runtime_monitor_error",
                    {
                        "updated_at": time.time(),
                        "source": "poll",
                        "error": str(exc),
                    },
                )
                await _sleep_until_next_poll(request, poll_interval=poll_interval, started_at=started_at)
                continue
            revision = str(monitor.get("revision") or monitor.get("updated_at") or "")
            if revision and revision == last_revision:
                yield _sse(
                    "runtime_monitor_heartbeat",
                    {
                        "updated_at": time.time(),
                        "source": "unchanged",
                        "revision": revision,
                    },
                )
            else:
                last_revision = revision
                yield _sse(
                    "runtime_monitor_snapshot",
                    {
                        "monitor": monitor,
                        "source": snapshot_source,
                        "updated_at": time.time(),
                    },
                    event_id=revision,
                )
                snapshot_source = "poll"
            await _sleep_until_next_poll(request, poll_interval=poll_interval, started_at=started_at)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _sleep_until_next_poll(request: Request, *, poll_interval: float, started_at: float) -> None:
    remaining = max(0.0, float(poll_interval) - (time.time() - float(started_at)))
    while remaining > 0:
        if await request.is_disconnected():
            return
        delay = min(0.25, remaining)
        await asyncio.sleep(delay)
        remaining -= delay


@router.get("/orchestration/runtime-monitor/sessions/{session_id}")
async def get_runtime_monitor_session(session_id: str, limit: int = 20) -> dict[str, Any]:
    return await asyncio.to_thread(_service().get_session_live_monitor, session_id, limit=limit)


@router.get("/orchestration/runtime-monitor/task-runs/{task_run_id}")
async def get_runtime_monitor_task_run(task_run_id: str) -> dict[str, Any]:
    monitor = await asyncio.to_thread(_service().get_task_run_live_monitor, task_run_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="TaskRun live monitor not found")
    return monitor


@router.get("/orchestration/runtime-monitor/resources/{resource_ref:path}")
async def get_runtime_monitor_resource(resource_ref: str) -> dict[str, Any]:
    return await asyncio.to_thread(_service().get_resource, resource_ref)
