from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.deps import require_runtime
from harness.runtime.run_monitor import RuntimeMonitorActionService
from runtime.file_change_signals import subscribe_file_change_signals, unsubscribe_file_change_signals

router = APIRouter()


class _RuntimeMonitorSnapshotCoalescer:
    def __init__(self, *, ttl_seconds: float = 0.75) -> None:
        self._ttl_seconds = max(0.0, float(ttl_seconds))
        self._lock = threading.RLock()
        self._in_flight: dict[tuple[int, int, int], asyncio.Task[dict[str, Any]]] = {}
        self._cache: dict[tuple[int, int, int], tuple[float, dict[str, Any]]] = {}

    async def collect(self, service: Any, *, limit: int) -> dict[str, Any]:
        normalized_limit = max(1, int(limit or 1))
        key = (id(asyncio.get_running_loop()), id(service), normalized_limit)
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached and now - cached[0] <= self._ttl_seconds:
                return cached[1]
            task = self._in_flight.get(key)
            if task is None:
                task = asyncio.create_task(_collect_global_runtime_monitor_raw(service, limit=normalized_limit))
                self._in_flight[key] = task
                task.add_done_callback(lambda completed, cache_key=key: self._complete(cache_key, completed))
        return await asyncio.shield(task)

    def _complete(self, key: tuple[int, int, int], task: asyncio.Task[dict[str, Any]]) -> None:
        monitor: dict[str, Any] | None = None
        if not task.cancelled():
            try:
                monitor = task.result()
            except Exception:
                monitor = None
        with self._lock:
            if self._in_flight.get(key) is task:
                self._in_flight.pop(key, None)
            if monitor is not None:
                self._cache[key] = (time.monotonic(), monitor)


_RUNTIME_MONITOR_SNAPSHOT_COALESCER = _RuntimeMonitorSnapshotCoalescer()


class RuntimeMonitorActionRequest(BaseModel):
    action: str = Field(default="", max_length=80)
    signal_id: str = Field(default="", max_length=300)
    task_run_id: str = Field(default="", max_length=300)
    graph_run_id: str = Field(default="", max_length=300)
    reason: str = Field(default="", max_length=500)
    source_revision: str = Field(default="", max_length=300)
    max_steps: int = Field(default=12, ge=1, le=50)


class RuntimeMonitorMaintenanceRequest(BaseModel):
    limit: int = Field(default=240, ge=1, le=1000)


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
    return await _RUNTIME_MONITOR_SNAPSHOT_COALESCER.collect(service, limit=limit)


async def _collect_global_runtime_monitor_raw(service: Any, *, limit: int) -> dict[str, Any]:
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


@router.post("/orchestration/runtime-monitor/maintenance/task-run-retention")
async def run_runtime_monitor_task_run_retention(
    payload: RuntimeMonitorMaintenanceRequest | None = None,
) -> dict[str, Any]:
    requested_limit = payload.limit if payload is not None else 240
    return await asyncio.to_thread(
        _service().run_lifecycle_retention_maintenance,
        limit=requested_limit,
    )


@router.get("/orchestration/runtime-monitor/events")
async def stream_runtime_monitor_events(request: Request, limit: int = 40, poll_interval_seconds: float = 2.0):
    service = _service()
    requested_limit = max(1, min(int(limit or 40), 100))
    poll_interval = _stream_poll_interval(poll_interval_seconds)
    file_change_subscription = subscribe_file_change_signals(max_queue_size=200)

    async def event_generator():
        try:
            yield _sse(
                "runtime_monitor_heartbeat",
                {
                    "updated_at": time.time(),
                    "source": "connected",
                },
            )
            last_revision = ""
            snapshot_source = "initial"
            next_snapshot_at = 0.0
            while not await request.is_disconnected():
                now = time.time()
                if now >= next_snapshot_at:
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
                        next_snapshot_at = time.time() + poll_interval
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
                    next_snapshot_at = time.time() + poll_interval
                    continue

                payload = await _next_file_change_signal(
                    file_change_subscription,
                    timeout_seconds=max(0.0, min(next_snapshot_at - now, 1.0)),
                )
                if payload is None:
                    continue
                yield _sse(
                    "runtime_monitor_file_change",
                    {
                        **payload,
                        "source": "file_change_signal",
                        "updated_at": time.time(),
                    },
                    event_id=str(payload.get("event_id") or ""),
                )
        finally:
            unsubscribe_file_change_signals(file_change_subscription)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _next_file_change_signal(subscription: Any, *, timeout_seconds: float) -> dict[str, Any] | None:
    if subscription is None:
        await asyncio.sleep(max(0.0, timeout_seconds))
        return None
    try:
        return await asyncio.wait_for(subscription.queue.get(), timeout=max(0.01, float(timeout_seconds or 0.01)))
    except asyncio.TimeoutError:
        return None


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
