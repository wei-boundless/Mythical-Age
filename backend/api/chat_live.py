from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.deps import require_runtime
from runtime.shared.runtime_run_registry import RuntimeRun
from runtime.shared.stream_replay import AGENT_LIVE_PROTOCOL, parse_stream_event_id
from sessions import InvalidSessionId, validate_session_id


router = APIRouter()
logger = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL_SECONDS = 10.0
_SUBSCRIBE_TIMEOUT_SECONDS = 10.0


@router.websocket("/chat/sessions/{session_id}/live")
async def chat_session_live(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    try:
        validated_session_id = validate_session_id(session_id)
    except InvalidSessionId:
        await _send_error_and_close(websocket, code="invalid_session_id", status_code=1008)
        return

    runtime = require_runtime()
    host = runtime.harness_runtime.single_agent_runtime_host
    registry = host.run_registry
    replay = host.stream_replay
    try:
        await _send_json(
            websocket,
            {
                "type": "hello",
                "protocol": AGENT_LIVE_PROTOCOL,
                "session_id": validated_session_id,
                "server_time": time.time(),
                "heartbeat_interval_ms": int(_HEARTBEAT_INTERVAL_SECONDS * 1000),
                "ack_policy": {
                    "required": True,
                    "max_unacked_events": 200,
                    "lag_warning_ms": 3000,
                },
            },
        )
    except WebSocketDisconnect:
        logger.debug("Chat live client disconnected before subscribe", extra={"session_id": validated_session_id})
        return

    try:
        subscribe = await asyncio.wait_for(websocket.receive_json(), timeout=_SUBSCRIBE_TIMEOUT_SECONDS)
    except WebSocketDisconnect:
        return
    except Exception:
        await _send_error_and_close(websocket, code="subscribe_required", status_code=1008)
        return

    try:
        run, latest_offset, last_event_id = _resolve_subscription(registry, validated_session_id, subscribe)
    except ValueError as exc:
        await _send_error_and_close(websocket, code=str(exc) or "invalid_subscription", status_code=1008)
        return

    subscription = host.event_log.subscribe(run_id=run.event_log_id)
    queue_task: asyncio.Task[Any] | None = None
    receive_task: asyncio.Task[Any] | None = None
    last_ack_offset = latest_offset
    try:
        latest_offset, terminal = await _send_catchup(websocket, replay, registry, run, latest_offset=latest_offset)
        if terminal:
            await _send_terminal(websocket, registry.get_run(run.stream_run_id) or run, latest_offset)
            await websocket.close(code=1000)
            return
        queue_task = asyncio.create_task(subscription.queue.get())
        receive_task = asyncio.create_task(websocket.receive_json())
        while True:
            done, _pending = await asyncio.wait(
                {task for task in (queue_task, receive_task) if task is not None},
                timeout=_HEARTBEAT_INTERVAL_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                await _send_json(
                    websocket,
                    {
                        "type": "heartbeat",
                        "protocol": AGENT_LIVE_PROTOCOL,
                        "stream_run_id": run.stream_run_id,
                        "event_log_id": run.event_log_id,
                        "event_offset": latest_offset,
                        "last_ack_offset": last_ack_offset,
                        "server_time": time.time(),
                    },
                )
                continue
            if receive_task in done:
                try:
                    message = receive_task.result()
                except WebSocketDisconnect:
                    return
                if isinstance(message, dict) and str(message.get("type") or "") == "ack":
                    last_ack_offset = max(last_ack_offset, _safe_int(message.get("last_event_offset"), latest_offset))
                receive_task = asyncio.create_task(websocket.receive_json())
            if queue_task in done:
                with contextlib.suppress(Exception):
                    queue_task.result()
                current = registry.get_run(run.stream_run_id) or run
                latest_offset, terminal = await _send_catchup(websocket, replay, registry, current, latest_offset=latest_offset)
                if terminal:
                    await _send_terminal(websocket, registry.get_run(run.stream_run_id) or current, latest_offset)
                    await websocket.close(code=1000)
                    return
                queue_task = asyncio.create_task(subscription.queue.get())
    except WebSocketDisconnect:
        logger.debug("Chat live client disconnected", extra={"session_id": validated_session_id, "stream_run_id": run.stream_run_id})
        return
    finally:
        host.event_log.unsubscribe(subscription)
        for task in (queue_task, receive_task):
            await _cancel_and_drain_task(task)


def _resolve_subscription(registry: Any, session_id: str, message: Any) -> tuple[RuntimeRun, int, str]:
    payload = dict(message or {}) if isinstance(message, dict) else {}
    if str(payload.get("type") or "") != "subscribe":
        raise ValueError("subscribe_required")
    if str(payload.get("protocol") or AGENT_LIVE_PROTOCOL) != AGENT_LIVE_PROTOCOL:
        raise ValueError("unsupported_protocol")
    subscriptions = list(payload.get("subscriptions") or [])
    subscription = dict(subscriptions[0] if subscriptions and isinstance(subscriptions[0], dict) else payload)
    stream_run_id = str(subscription.get("stream_run_id") or "").strip()
    if not stream_run_id:
        raise ValueError("stream_run_id_required")
    run = registry.get_run(stream_run_id)
    if run is None:
        raise ValueError("chat_run_not_found")
    if str(run.session_id or "") != session_id:
        raise ValueError("chat_run_session_mismatch")
    event_log_id = str(subscription.get("event_log_id") or run.event_log_id)
    if event_log_id and event_log_id != run.event_log_id:
        raise ValueError("event_log_id_mismatch")
    after_offset = _safe_int(subscription.get("after_offset"), -1)
    last_event_id = str(subscription.get("last_event_id") or "")
    cursor = parse_stream_event_id(
        last_event_id,
        expected_stream_run_id=run.stream_run_id,
        expected_event_log_id=run.event_log_id,
    )
    if cursor is not None:
        after_offset = max(after_offset, cursor.last_event_offset)
        last_event_id = cursor.last_event_id
    return run, after_offset, last_event_id


async def _send_catchup(websocket: WebSocket, replay: Any, registry: Any, run: RuntimeRun, *, latest_offset: int) -> tuple[int, bool]:
    terminal = False
    current = registry.get_run(run.stream_run_id) or run
    events = replay.list_public_events_after(current, after_offset=latest_offset)
    for event in events:
        if event.offset <= latest_offset:
            continue
        latest_offset = int(event.offset)
        envelope = replay.to_public_envelope(current, event, sent_at_key="server_ws_sent_at")
        await _send_json(websocket, envelope)
        terminal = terminal or bool(envelope.get("terminal") is True)
        if terminal:
            break
    return latest_offset, terminal


async def _send_terminal(websocket: WebSocket, run: RuntimeRun, latest_offset: int) -> None:
    await _send_json(
        websocket,
        {
            "type": "terminal",
            "protocol": AGENT_LIVE_PROTOCOL,
            "stream_run_id": run.stream_run_id,
            "event_log_id": run.event_log_id,
            "event_offset": int(latest_offset),
            "status": str(run.status or "completed"),
        },
    )


async def _send_error_and_close(websocket: WebSocket, *, code: str, status_code: int) -> None:
    with contextlib.suppress(Exception):
        await _send_json(
            websocket,
            {
                "type": "error",
                "protocol": AGENT_LIVE_PROTOCOL,
                "code": code,
                "server_time": time.time(),
            },
        )
    with contextlib.suppress(Exception):
        await websocket.close(code=status_code)


async def _send_json(websocket: WebSocket, payload: dict[str, Any]) -> None:
    try:
        await websocket.send_json(payload)
    except WebSocketDisconnect:
        raise
    except Exception as exc:
        if _is_client_disconnected_error(exc):
            raise WebSocketDisconnect(code=1006) from exc
        raise


def _is_client_disconnected_error(exc: Exception) -> bool:
    name = exc.__class__.__name__
    message = str(exc).lower()
    return name == "ClientDisconnected" or "disconnect" in message or "websocket is not connected" in message


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


async def _cancel_and_drain_task(task: asyncio.Task[Any] | None) -> None:
    if task is None:
        return
    if not task.done():
        task.cancel()
    with contextlib.suppress(BaseException):
        await task
