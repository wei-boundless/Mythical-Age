from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from api.deps import require_runtime
from runtime.shared.events import RuntimeEvent
from runtime.shared.stream_replay import format_sse

router = APIRouter()

RUNTIME_LOG_RETRY_MS = 1500
RUNTIME_LOG_HEARTBEAT_SECONDS = 15.0


@router.get("/runtime/logs/task-runs/{task_run_id}/events")
async def stream_task_run_log_events(
    task_run_id: str,
    request: Request,
    after_offset: int | None = Query(default=None),
    limit: int = Query(default=240, ge=1, le=1000),
    include_payloads: bool = False,
    include_model_messages: bool = False,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    runtime = require_runtime()
    host = runtime.harness_runtime.single_agent_runtime_host
    run_id = str(task_run_id or "").strip()
    if not run_id or host.state_index.get_task_run(run_id) is None:
        raise HTTPException(status_code=404, detail="TaskRun log not found")
    effective_after_offset = _resolve_runtime_log_after_offset(
        "task_run",
        run_id,
        after_offset=after_offset,
        last_event_id=last_event_id,
    )
    return _runtime_log_streaming_response(
        host,
        request=request,
        scope="task_run",
        run_id=run_id,
        after_offset=effective_after_offset,
        limit=limit,
        include_payloads=include_payloads,
        include_model_messages=include_model_messages,
    )


@router.get("/runtime/logs/turn-runs/{turn_run_id}/events")
async def stream_turn_run_log_events(
    turn_run_id: str,
    request: Request,
    after_offset: int | None = Query(default=None),
    limit: int = Query(default=240, ge=1, le=1000),
    include_payloads: bool = False,
    include_model_messages: bool = False,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    runtime = require_runtime()
    host = runtime.harness_runtime.single_agent_runtime_host
    run_id = str(turn_run_id or "").strip()
    if not run_id or host.state_index.get_turn_run(run_id) is None:
        raise HTTPException(status_code=404, detail="TurnRun log not found")
    effective_after_offset = _resolve_runtime_log_after_offset(
        "turn_run",
        run_id,
        after_offset=after_offset,
        last_event_id=last_event_id,
    )
    return _runtime_log_streaming_response(
        host,
        request=request,
        scope="turn_run",
        run_id=run_id,
        after_offset=effective_after_offset,
        limit=limit,
        include_payloads=include_payloads,
        include_model_messages=include_model_messages,
    )


def _runtime_log_streaming_response(
    host: Any,
    *,
    request: Request,
    scope: str,
    run_id: str,
    after_offset: int,
    limit: int,
    include_payloads: bool,
    include_model_messages: bool,
) -> StreamingResponse:
    return StreamingResponse(
        _stream_runtime_log_events(
            host,
            request=request,
            scope=scope,
            run_id=run_id,
            after_offset=after_offset,
            limit=limit,
            include_payloads=include_payloads,
            include_model_messages=include_model_messages,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_runtime_log_events(
    host: Any,
    *,
    request: Request,
    scope: str,
    run_id: str,
    after_offset: int,
    limit: int,
    include_payloads: bool,
    include_model_messages: bool,
):
    subscription = host.event_log.subscribe(run_id=run_id, max_queue_size=max(100, int(limit or 240)))
    latest_offset = int(after_offset)
    try:
        yield "retry: 1500\n\n"
        replay_events = _runtime_log_events_after(
            host,
            run_id,
            after_offset=latest_offset,
            limit=limit,
            include_payloads=include_payloads,
        )
        if replay_events:
            latest_offset = max(latest_offset, max(event.offset for event in replay_events))
        yield _runtime_log_snapshot_sse(
            scope=scope,
            run_id=run_id,
            events=replay_events,
            latest_offset=latest_offset,
            include_model_messages=include_model_messages,
        )
        while not await request.is_disconnected():
            try:
                event = await asyncio.wait_for(subscription.queue.get(), timeout=RUNTIME_LOG_HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield format_sse(
                    "runtime_log_heartbeat",
                    {
                        "source": "heartbeat",
                        "scope": scope,
                        "run_id": run_id,
                        "event_offset": latest_offset,
                        "updated_at": time.time(),
                    },
                    retry_ms=RUNTIME_LOG_RETRY_MS,
                )
                continue
            if event.offset <= latest_offset:
                continue
            if event.offset > latest_offset + 1:
                catchup_events = _runtime_log_events_after(
                    host,
                    run_id,
                    after_offset=latest_offset,
                    limit=max(int(limit or 240), event.offset - latest_offset),
                    include_payloads=include_payloads,
                )
                recovered = bool(catchup_events and catchup_events[0].offset == latest_offset + 1)
                if not recovered:
                    yield _runtime_log_gap_sse(
                        scope=scope,
                        run_id=run_id,
                        expected_after_offset=latest_offset,
                        observed_offset=event.offset,
                        recovered=False,
                    )
                    latest_offset = event.offset
                    yield _runtime_log_event_sse(
                        scope=scope,
                        run_id=run_id,
                        event=event,
                        include_model_messages=include_model_messages,
                    )
                    continue
                for catchup in catchup_events:
                    if catchup.offset <= latest_offset:
                        continue
                    latest_offset = catchup.offset
                    yield _runtime_log_event_sse(
                        scope=scope,
                        run_id=run_id,
                        event=catchup,
                        include_model_messages=include_model_messages,
                    )
                continue
            latest_offset = event.offset
            yield _runtime_log_event_sse(
                scope=scope,
                run_id=run_id,
                event=event,
                include_model_messages=include_model_messages,
            )
    finally:
        host.event_log.unsubscribe(subscription)


def _runtime_log_events_after(
    host: Any,
    run_id: str,
    *,
    after_offset: int,
    limit: int,
    include_payloads: bool,
) -> list[RuntimeEvent]:
    requested_limit = max(1, min(int(limit or 240), 1000))
    events = host.event_log.list_event_window(
        run_id,
        limit=requested_limit,
        include_payloads=include_payloads,
    )
    return [event for event in events if event.offset > int(after_offset)]


def _runtime_log_snapshot_sse(
    *,
    scope: str,
    run_id: str,
    events: list[RuntimeEvent],
    latest_offset: int,
    include_model_messages: bool,
) -> str:
    event_id = _runtime_log_event_id(scope, run_id, latest_offset) if latest_offset >= 0 else ""
    return format_sse(
        "runtime_log_snapshot",
        {
            "source": "snapshot",
            "scope": scope,
            "run_id": run_id,
            "events": [
                _public_runtime_log_event(event, include_model_messages=include_model_messages)
                for event in events
            ],
            "event_offset": latest_offset,
            "returned": len(events),
            "updated_at": time.time(),
        },
        event_id=event_id,
        retry_ms=RUNTIME_LOG_RETRY_MS,
    )


def _runtime_log_event_sse(
    *,
    scope: str,
    run_id: str,
    event: RuntimeEvent,
    include_model_messages: bool,
) -> str:
    return format_sse(
        "runtime_log_event",
        {
            "source": "event",
            "scope": scope,
            "run_id": run_id,
            "event": _public_runtime_log_event(event, include_model_messages=include_model_messages),
            "event_offset": event.offset,
            "updated_at": time.time(),
        },
        event_id=_runtime_log_event_id(scope, run_id, event.offset),
        retry_ms=RUNTIME_LOG_RETRY_MS,
    )


def _runtime_log_gap_sse(
    *,
    scope: str,
    run_id: str,
    expected_after_offset: int,
    observed_offset: int,
    recovered: bool,
) -> str:
    return format_sse(
        "runtime_log_gap",
        {
            "source": "gap",
            "scope": scope,
            "run_id": run_id,
            "event_offset": observed_offset,
            "gap": {
                "expected_after_offset": int(expected_after_offset),
                "observed_offset": int(observed_offset),
                "recovered": bool(recovered),
            },
            "updated_at": time.time(),
        },
        event_id=_runtime_log_event_id(scope, run_id, observed_offset),
        retry_ms=RUNTIME_LOG_RETRY_MS,
    )


def _public_runtime_log_event(event: RuntimeEvent, *, include_model_messages: bool = False) -> dict[str, Any]:
    record = event.to_dict()
    if not include_model_messages:
        record["payload"] = _redact_runtime_log_payload(dict(record.get("payload") or {}))
    return record


def _redact_runtime_log_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(payload)
    for key in ("model_messages", "messages", "history"):
        if key in redacted:
            redacted[key] = "[redacted]"
    packet = redacted.get("packet")
    if isinstance(packet, dict) and "model_messages" in packet:
        redacted["packet"] = {**packet, "model_messages": "[redacted]"}
    return redacted


def _runtime_log_event_id(scope: str, run_id: str, offset: int) -> str:
    return f"runtime-log:{scope}:{run_id}:{int(offset)}"


def _resolve_runtime_log_after_offset(
    scope: str,
    run_id: str,
    *,
    after_offset: int | None,
    last_event_id: str | None,
) -> int:
    if after_offset is not None:
        return int(after_offset)
    cursor = _parse_runtime_log_event_id(scope, run_id, str(last_event_id or ""))
    if cursor is not None:
        return cursor
    return -1


def _parse_runtime_log_event_id(scope: str, run_id: str, value: str) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    prefix = f"runtime-log:{scope}:{run_id}:"
    if raw.startswith(prefix):
        tail = raw[len(prefix):]
        if tail.isdigit():
            return int(tail)
    return None
