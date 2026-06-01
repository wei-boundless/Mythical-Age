from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from api.deps import require_runtime
from query import QueryRequest
from runtime.shared.events import RuntimeEvent
from runtime.shared.runtime_run_registry import RuntimeRun
from runtime.shared.stream_replay import (
    TERMINAL_PUBLIC_EVENTS,
    parse_stream_event_id,
)
from sessions import validate_session_id

router = APIRouter()
logger = logging.getLogger(__name__)
TERMINAL_STREAM_EVENTS = {"done", "error", "stopped"}
TERMINAL_RUN_STATUSES = {"completed", "failed", "stopped", "orphaned"}
INTERNAL_STREAM_EVENTS = {
    "debug",
    "runtime_assembly_compiled",
    "runtime_assembly_bound",
    "runtime_invocation_packet",
}
INTERNAL_PUBLIC_DATA_KEYS = {
    "runtime_assembly",
    "compilation",
    "model_messages",
    "messages",
    "prompt_manifest",
    "segment_plan",
    "operation_authorization",
}
PUBLIC_EVENT_DATA_ALLOWLIST = {
    "chat_run_started": {"status"},
    "input_commit_gate": {"status", "message_ref"},
    "turn_route_decided": {"turn_route"},
    "single_agent_turn_started": {"turn_route", "allowed_action_types"},
    "assistant_message_committed": {
        "answer_channel",
        "answer_source",
        "answer_canonical_state",
    },
    "harness_run_started": {"task_run", "turn_run", "event"},
    "runtime_step_summary": {
        "step",
        "status",
        "summary",
        "public_progress_note",
        "agent_brief_output",
        "current_judgment",
        "next_action",
        "completion_status",
        "presentation_source",
        "event",
    },
    "model_action_request": {"event"},
    "model_action_admission": {"event"},
    "bounded_observation": {"event"},
    "registered_engagement": {"event"},
    "task_run_lifecycle_started": {"event"},
    "task_run_lifecycle_event": {"event"},
    "agent_turn_terminal": {"event"},
    "retrieval": {"results"},
    "output_boundary": {"boundary", "summary", "artifacts"},
    "answer_candidate": {"content"},
    "token": {"content"},
    "content_delta": {"content"},
    "done": {
        "content",
        "image",
        "artifacts",
        "files",
        "paths",
        "completion_state",
        "receipt_summary",
        "summary",
        "message",
        "answer_source",
        "terminal_reason",
    },
    "error": {"content", "error", "code", "reason"},
    "stopped": {"reason", "content"},
}


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str
    stream: bool = True
    explicit_subtasks: list[dict[str, Any]] = Field(default_factory=list)
    search_policy: list[str] | None = None
    soul_id: str = ""
    runtime_profile: dict[str, Any] = Field(default_factory=dict)
    task_selection: dict[str, Any] = Field(default_factory=dict)
    model_selection: dict[str, Any] = Field(default_factory=dict)
    image_generation: dict[str, Any] = Field(default_factory=dict)


def _error_status(code: str) -> int:
    if code == "timeout":
        return 504
    if code == "rate_limit":
        return 429
    if code == "provider_unavailable":
        return 503
    return 500


@router.post("/chat/runs")
async def create_chat_run(payload: ChatRequest):
    runtime = require_runtime()
    session_id = validate_session_id(payload.session_id)
    request = _query_request_from_payload(payload, session_id=session_id)
    run = _create_and_schedule_run(runtime, request)
    return _run_response(run)


@router.get("/chat/runs/{stream_run_id}")
async def get_chat_run(stream_run_id: str):
    runtime = require_runtime()
    run = _get_run_or_404(runtime, stream_run_id)
    return _run_response(run)


@router.get("/chat/sessions/{session_id}/latest-run")
async def get_latest_chat_run_for_session(
    session_id: str,
    active_only: bool = Query(default=True),
):
    runtime = require_runtime()
    validated_session_id = validate_session_id(session_id)
    registry = runtime.query_runtime.single_agent_runtime_host.run_registry
    now = time.time()
    candidates = [
        run
        for run in registry.list_session_runs(validated_session_id)
        if run.reconnectable_until >= now
        and (not active_only or run.status not in TERMINAL_RUN_STATUSES)
    ]
    if not candidates:
        raise HTTPException(status_code=404, detail="chat run not found")
    return _run_response(candidates[0])


@router.get("/chat/runs/{stream_run_id}/events")
async def get_chat_run_events(
    stream_run_id: str,
    after_offset: int | None = Query(default=None),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    runtime = require_runtime()
    run = _get_run_or_404(runtime, stream_run_id)
    effective_after_offset = _resolve_after_offset(
        run,
        after_offset=after_offset,
        last_event_id=last_event_id,
    )
    return StreamingResponse(
        _stream_run_events(runtime, run, after_offset=effective_after_offset),
        media_type="text/event-stream",
    )


@router.post("/chat/runs/{stream_run_id}/resume")
async def resume_chat_run(stream_run_id: str):
    runtime = require_runtime()
    run = _get_run_or_404(runtime, stream_run_id)
    # Resume is intentionally attach-only here. Re-executing the original user
    # message would duplicate model/tool side effects; actual task continuation
    # remains owned by the runtime resume and execution-record paths.
    return {
        **_run_response(run),
        "resume_mode": "attach_existing_run",
    }


@router.post("/chat")
async def chat(payload: ChatRequest):
    runtime = require_runtime()
    session_id = validate_session_id(payload.session_id)
    request = _query_request_from_payload(payload, session_id=session_id)
    run = _create_and_schedule_run(runtime, request)

    if payload.stream:
        return StreamingResponse(_stream_run_events(runtime, run, after_offset=-1), media_type="text/event-stream")

    terminal_event, terminal_data = await _wait_for_terminal_public_event(runtime, run)
    if terminal_event == "done":
        response: dict[str, Any] = {"content": str(terminal_data.get("content", "") or "")}
        image = terminal_data.get("image")
        if image is not None:
            response["image"] = image
        return JSONResponse(response)
    if terminal_event == "error":
        code = str(terminal_data.get("code", "") or "").strip()
        return JSONResponse(
            {
                "error": str(terminal_data.get("error", "") or "Request failed"),
                "code": code or None,
            },
            status_code=_error_status(code),
        )
    return JSONResponse(
        {
            "error": "Request finished without a final response.",
            "code": "missing_done",
        },
        status_code=500,
    )


def _query_request_from_payload(payload: ChatRequest, *, session_id: str) -> QueryRequest:
    return QueryRequest(
        session_id=session_id,
        message=payload.message,
        explicit_subtasks=list(payload.explicit_subtasks or []),
        search_policy=list(payload.search_policy) if payload.search_policy is not None else None,
        soul_id=str(payload.soul_id or ""),
        runtime_profile=dict(payload.runtime_profile or {}),
        task_selection=dict(payload.task_selection or {}),
        model_selection=dict(payload.model_selection or {}),
        image_generation=dict(payload.image_generation or {}),
    )


def _create_and_schedule_run(runtime: Any, request: QueryRequest) -> RuntimeRun:
    host = runtime.query_runtime.single_agent_runtime_host
    run = host.run_registry.create_run(
        session_id=request.session_id,
        diagnostics={"source": "api.chat", "message_chars": len(str(request.message or ""))},
    )
    host.spawn_background_task(
        _run_chat_to_event_log(runtime, run, request),
        name=f"chat-run-{run.stream_run_id}",
    )
    return run


async def _run_chat_to_event_log(runtime: Any, run: RuntimeRun, request: QueryRequest) -> None:
    host = runtime.query_runtime.single_agent_runtime_host
    registry = host.run_registry
    replay = host.stream_replay
    terminal_event = ""
    current = registry.mark_running(run)
    try:
        start_event = replay.append_public_event(
            current,
            public_event_type="chat_run_started",
            data={"status": "running"},
        )
        current = registry.mark_event(current, latest_event_offset=start_event.offset, status="running")
        async for event in runtime.query_runtime.astream(request):
            event_type = str(event.get("type", "message") or "message")
            runtime_refs = _runtime_run_refs_from_event(event)
            runtime_task_run_id = runtime_refs["task_run_id"]
            runtime_turn_run_id = runtime_refs["turn_run_id"]
            projection = _project_public_stream_event(event_type, event)
            if projection is None:
                continue
            public_event_type, data = projection
            if runtime_task_run_id:
                data.setdefault("runtime_task_run_id", runtime_task_run_id)
            logged = replay.append_public_event(current, public_event_type=public_event_type, data=data)
            terminal_event = public_event_type if public_event_type in TERMINAL_STREAM_EVENTS else terminal_event
            diagnostics = {
                key: value
                for key, value in {
                    "runtime_task_run_id": runtime_task_run_id,
                    "runtime_turn_run_id": runtime_turn_run_id,
                }.items()
                if value
            }
            current = registry.mark_event(
                current,
                latest_event_offset=logged.offset,
                status=_status_for_public_event(public_event_type),
                terminal_event=public_event_type if public_event_type in TERMINAL_STREAM_EVENTS else "",
                diagnostics=diagnostics or None,
            )
            if public_event_type in TERMINAL_STREAM_EVENTS:
                break
    except asyncio.CancelledError:
        logger.info("Chat run background task was cancelled.", extra={"stream_run_id": run.stream_run_id})
        registry.update_run(run.stream_run_id, status="orphaned", diagnostics={"cancelled": True})
        raise
    except Exception as exc:
        logger.exception("Chat run failed before terminal event.", extra={"stream_run_id": run.stream_run_id})
        current = registry.get_run(run.stream_run_id) or current
        logged = replay.append_public_event(
            current,
            public_event_type="error",
            data={
                "error": str(exc) or "Chat stream failed.",
                "code": "stream_exception",
            },
        )
        registry.mark_event(current, latest_event_offset=logged.offset, status="failed", terminal_event="error")
        return
    if not terminal_event:
        current = registry.get_run(run.stream_run_id) or current
        logged = replay.append_public_event(
            current,
            public_event_type="error",
            data={
                "error": "Chat stream ended without a terminal event.",
                "code": "missing_terminal_event",
            },
        )
        registry.mark_event(current, latest_event_offset=logged.offset, status="failed", terminal_event="error")


async def _stream_run_events(runtime: Any, run: RuntimeRun, *, after_offset: int):
    host = runtime.query_runtime.single_agent_runtime_host
    registry = host.run_registry
    replay = host.stream_replay
    subscription = host.event_log.subscribe(run_id=run.event_log_id)
    latest_offset = int(after_offset)
    try:
        yield "retry: 1500\n\n"
        for event in replay.list_public_events_after(run, after_offset=latest_offset):
            latest_offset = max(latest_offset, event.offset)
            yield replay.to_public_sse(run, event)
            if replay.is_terminal_event(event):
                return
        while True:
            current = registry.get_run(run.stream_run_id) or run
            if current.status in {"completed", "failed", "stopped", "orphaned"} and current.latest_event_offset <= latest_offset:
                return
            try:
                event = await asyncio.wait_for(subscription.queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            if event.offset <= latest_offset or str(event.event_type) != "chat_stream_event":
                continue
            latest_offset = max(latest_offset, event.offset)
            yield replay.to_public_sse(current, event)
            if replay.is_terminal_event(event):
                return
    finally:
        host.event_log.unsubscribe(subscription)


async def _wait_for_terminal_public_event(runtime: Any, run: RuntimeRun) -> tuple[str, dict[str, Any]]:
    host = runtime.query_runtime.single_agent_runtime_host
    replay = host.stream_replay
    subscription = host.event_log.subscribe(run_id=run.event_log_id)
    latest_offset = -1
    try:
        while True:
            for event in replay.list_public_events_after(run, after_offset=latest_offset):
                latest_offset = max(latest_offset, event.offset)
                public_event, data = _public_event_payload(event)
                if public_event in TERMINAL_PUBLIC_EVENTS:
                    return public_event, data
            event = await subscription.queue.get()
            if event.offset <= latest_offset or str(event.event_type) != "chat_stream_event":
                continue
            latest_offset = max(latest_offset, event.offset)
            public_event, data = _public_event_payload(event)
            if public_event in TERMINAL_PUBLIC_EVENTS:
                return public_event, data
    finally:
        host.event_log.unsubscribe(subscription)


def _public_event_payload(event: RuntimeEvent) -> tuple[str, dict[str, Any]]:
    payload = dict(event.payload or {})
    data = dict(payload.get("data") or {})
    data.update({"event_offset": event.offset, "runtime_event_id": event.event_id})
    return str(payload.get("public_event_type") or "message"), data


def _resolve_after_offset(run: RuntimeRun, *, after_offset: int | None, last_event_id: str | None) -> int:
    if after_offset is not None:
        return int(after_offset)
    cursor = parse_stream_event_id(
        str(last_event_id or ""),
        expected_stream_run_id=run.stream_run_id,
        expected_event_log_id=run.event_log_id,
    )
    if cursor is not None:
        return cursor.last_event_offset
    return -1


def _get_run_or_404(runtime: Any, stream_run_id: str) -> RuntimeRun:
    run = runtime.query_runtime.single_agent_runtime_host.run_registry.get_run(stream_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="chat run not found")
    return run


def _run_response(run: RuntimeRun) -> dict[str, Any]:
    return {
        **run.to_dict(),
        "is_reconnectable": run.reconnectable_until >= time.time(),
        "stream_url": f"/api/chat/runs/{run.stream_run_id}/events",
    }


def _status_for_public_event(event_type: str) -> str:
    if event_type == "done":
        return "completed"
    if event_type == "error":
        return "failed"
    if event_type == "stopped":
        return "stopped"
    return "running"


def _project_public_stream_event(event_type: str, event: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    normalized = str(event_type or "message").strip() or "message"
    if normalized in INTERNAL_STREAM_EVENTS:
        return None
    if normalized == "harness_run_started" and _is_turn_trace_only_harness_start(event):
        return None
    raw_data = {key: value for key, value in dict(event).items() if key != "type"}
    allowed = PUBLIC_EVENT_DATA_ALLOWLIST.get(normalized)
    if allowed is None:
        data = {
            key: value
            for key, value in raw_data.items()
            if key not in INTERNAL_PUBLIC_DATA_KEYS
        }
    else:
        data = {key: raw_data[key] for key in allowed if key in raw_data}
    data = _redact_public_stream_data(data)
    if normalized == "turn_route_decided":
        route = dict(data.get("turn_route") or {})
        data["turn_route"] = _public_turn_route(route)
    elif normalized == "single_agent_turn_started":
        route = dict(data.get("turn_route") or {})
        data = {
            "turn_route": _public_turn_route(route),
            "allowed_action_types": list(data.get("allowed_action_types") or []),
        }
    return normalized, data


def _is_turn_trace_only_harness_start(event: dict[str, Any]) -> bool:
    refs = _runtime_run_refs_from_event(event)
    return bool(refs["turn_run_id"]) and not bool(refs["task_run_id"])


def _public_turn_route(route: dict[str, Any]) -> dict[str, Any]:
    return {
        key: route.get(key)
        for key in ("route_kind", "reason")
        if key in route
    }


def _redact_public_stream_data(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if str(key) in INTERNAL_PUBLIC_DATA_KEYS:
                continue
            redacted[str(key)] = _redact_public_stream_data(item)
        return redacted
    if isinstance(value, list):
        return [_redact_public_stream_data(item) for item in value]
    return value


def _runtime_run_refs_from_event(event: dict[str, Any]) -> dict[str, str]:
    task_run_id = ""
    turn_run_id = ""
    runtime_event = dict(event.get("event") or {}) if isinstance(event.get("event"), dict) else {}
    runtime_payload = dict(runtime_event.get("payload") or {}) if isinstance(runtime_event.get("payload"), dict) else {}
    for value in (
        dict(event.get("task_run") or {}).get("task_run_id") if isinstance(event.get("task_run"), dict) else "",
        dict(runtime_payload.get("task_run") or {}).get("task_run_id") if isinstance(runtime_payload.get("task_run"), dict) else "",
        event.get("task_run_id"),
        runtime_event.get("run_id"),
        runtime_event.get("task_run_id"),
    ):
        normalized = str(value or "").strip()
        if normalized.startswith("taskrun:"):
            task_run_id = normalized
            break
    for value in (
        dict(event.get("turn_run") or {}).get("turn_run_id") if isinstance(event.get("turn_run"), dict) else "",
        dict(runtime_payload.get("turn_run") or {}).get("turn_run_id") if isinstance(runtime_payload.get("turn_run"), dict) else "",
        event.get("turn_run_id"),
        runtime_event.get("run_id"),
        runtime_event.get("task_run_id"),
    ):
        normalized = str(value or "").strip()
        if normalized.startswith("turnrun:"):
            turn_run_id = normalized
            break
    return {"task_run_id": task_run_id, "turn_run_id": turn_run_id}
