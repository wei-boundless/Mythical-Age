from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from api.deps import require_runtime
from harness.entrypoint import HarnessRuntimeRequest
from harness.runtime.projection.projector import attach_public_projection_event
from harness.runtime.public_progress import public_runtime_progress_summary
from integrations.vscode_connection import get_vscode_connection_store
from runtime.output_boundary import (
    contains_inline_pseudo_tool_call,
    contains_internal_protocol,
    sanitize_visible_assistant_content,
)
from runtime.output_stream.public_contract import (
    ASSISTANT_STREAM_REPAIR_EVENT,
    ASSISTANT_TEXT_DELTA_EVENT,
    ASSISTANT_TEXT_FINAL_EVENT,
    SESSION_OUTPUT_COMMIT_ACK_EVENT,
    SESSION_OUTPUT_COMMIT_CHECKED_EVENT,
    SESSION_OUTPUT_COMMIT_FAILED_EVENT,
    SESSION_OUTPUT_COMMIT_SKIPPED_EVENT,
    TOOL_CALL_REQUESTED_EVENT,
    TOOL_ITEM_COMPLETED_EVENT,
    TOOL_ITEM_STARTED_EVENT,
    TOOL_PERMISSION_DECIDED_EVENT,
    TURN_COMPLETED_EVENT,
    event_requires_public_projection,
)
from runtime.shared.runtime_run_registry import RuntimeRun
from runtime.shared.stream_replay import parse_stream_event_id
from sessions import SessionProjectBindingConflict, validate_session_id
from task_system.session_scope import assert_optional_session_scope

router = APIRouter()
logger = logging.getLogger(__name__)
TERMINAL_STREAM_EVENTS = {TURN_COMPLETED_EVENT}
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
    "runtime_branch_decided": {"runtime_branch"},
    "single_agent_turn_started": {"runtime_branch", "allowed_action_types"},
    "assistant_message_committed": {
        "answer_channel",
        "answer_source",
        "answer_canonical_state",
    },
    "active_task_steer_accepted": {
        "summary",
        "status",
    },
    "runtime_status": {
        "title",
        "detail",
        "state",
        "phase",
        "runtime_task_run_id",
        "task_run_id",
        "runtime_event_id",
        "runtime_run_id",
        "created_at",
        "active_turn_id",
        "active_turn",
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
    "bounded_observation": {"event"},
    "registered_engagement": {"event"},
    "task_run_lifecycle_started": {"event"},
    "task_run_lifecycle_event": {"event"},
    "retrieval": {"results"},
    "output_boundary": {"boundary", "summary", "artifacts"},
    "token": {"content"},
    ASSISTANT_TEXT_DELTA_EVENT: {
        "frame_schema_version",
        "event_type",
        "frame_id",
        "stream_ref",
        "message_ref",
        "turn_run_id",
        "task_run_id",
        "sequence",
        "content",
        "content_utf8_start",
        "content_utf8_end",
        "content_utf8_bytes",
        "accumulated_utf8_bytes",
        "accumulated_sha256",
        "answer_channel",
        "answer_source",
        "visibility",
        "markdown_state",
        "display_hint",
        "body_segment_id",
        "body_sequence",
        "segment_sequence",
        "segment_role",
    },
    ASSISTANT_TEXT_FINAL_EVENT: {
        "frame_schema_version",
        "event_type",
        "stream_ref",
        "message_ref",
        "turn_run_id",
        "task_run_id",
        "sequence",
        "content",
        "content_utf8_bytes",
        "content_sha256",
        "answer_channel",
        "answer_source",
        "answer_canonical_state",
        "answer_persist_policy",
        "answer_finalization_policy",
        "answer_fallback_reason",
        "answer_selected_channel",
        "answer_selected_source",
        "answer_leak_flags",
        "terminal_reason",
        "body_segment_id",
        "body_sequence",
        "segment_sequence",
        "segment_role",
    },
    ASSISTANT_STREAM_REPAIR_EVENT: {
        "frame_schema_version",
        "event_type",
        "stream_ref",
        "message_ref",
        "turn_run_id",
        "task_run_id",
        "repair_sequence",
        "applies_after_sequence",
        "reason",
        "expected_content_sha256",
        "replacement_content",
        "replacement_content_sha256",
        "body_segment_id",
        "body_sequence",
        "segment_sequence",
        "segment_role",
    },
    TOOL_CALL_REQUESTED_EVENT: {
        "item_id",
        "request_id",
        "tool_lifecycle_id",
        "tool_call_id",
        "turn_run_id",
        "task_run_id",
        "tool_name",
        "target",
        "arguments_preview",
        "public_progress_note",
        "public_action_state",
        "runtime_event_id",
    },
    TOOL_PERMISSION_DECIDED_EVENT: {
        "item_id",
        "request_id",
        "tool_call_id",
        "turn_run_id",
        "task_run_id",
        "tool_name",
        "permission_decision_id",
        "permission_decision",
        "permission_reason",
        "system_reason",
        "runtime_event_id",
    },
    TOOL_ITEM_STARTED_EVENT: {
        "item_id",
        "tool_lifecycle_id",
        "tool_call_id",
        "permission_decision_id",
        "turn_run_id",
        "task_run_id",
        "tool_name",
        "title",
        "target",
        "arguments_preview",
        "state",
        "runtime_event_id",
    },
    TOOL_ITEM_COMPLETED_EVENT: {
        "item_id",
        "tool_lifecycle_id",
        "tool_call_id",
        "permission_decision_id",
        "turn_run_id",
        "task_run_id",
        "tool_name",
        "state",
        "observation",
        "error",
        "duration_ms",
        "runtime_event_id",
    },
    TURN_COMPLETED_EVENT: {
        "turn_run_id",
        "task_run_id",
        "status",
        "final_message_ref",
        "terminal_reason",
        "completion_state",
        "error_summary",
        "stopped_reason",
    },
    SESSION_OUTPUT_COMMIT_CHECKED_EVENT: {
        "state",
        "status",
        "turn_id",
        "turn_run_id",
        "task_run_id",
        "message_id",
        "message_ref",
        "content_sha256",
        "commit_event_offset",
        "runtime_event_id",
    },
    SESSION_OUTPUT_COMMIT_ACK_EVENT: {
        "state",
        "status",
        "turn_id",
        "turn_run_id",
        "task_run_id",
        "message_id",
        "message_ref",
        "content_sha256",
        "commit_event_offset",
        "runtime_event_id",
    },
    SESSION_OUTPUT_COMMIT_FAILED_EVENT: {
        "state",
        "status",
        "turn_id",
        "turn_run_id",
        "task_run_id",
        "message_id",
        "message_ref",
        "content_sha256",
        "commit_event_offset",
        "reason",
        "error",
        "summary",
        "runtime_event_id",
    },
    SESSION_OUTPUT_COMMIT_SKIPPED_EVENT: {
        "state",
        "status",
        "turn_id",
        "turn_run_id",
        "task_run_id",
        "message_id",
        "message_ref",
        "content_sha256",
        "commit_event_offset",
        "reason",
        "runtime_event_id",
    },
}


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1)
    session_id: str
    stream: bool = True
    explicit_subtasks: list[dict[str, Any]] = Field(default_factory=list)
    runtime_profile: dict[str, Any] = Field(default_factory=dict)
    environment_binding: dict[str, Any] = Field(default_factory=dict)
    runtime_contract: dict[str, Any] = Field(default_factory=dict)
    model_selection: dict[str, Any] = Field(default_factory=dict)
    image_generation: dict[str, Any] = Field(default_factory=dict)
    permission_mode: str = ""
    session_scope: dict[str, Any] | None = None
    expected_active_turn_id: str = ""
    active_turn_input_policy: str = "auto"
    editor_context: dict[str, Any] = Field(default_factory=dict)


@router.post("/chat/runs")
async def create_chat_run(payload: ChatRequest):
    runtime = require_runtime()
    session_id = validate_session_id(payload.session_id)
    assert_optional_session_scope(runtime.session_manager, session_id, payload.session_scope)
    allow_vscode_context_fallback = bool(runtime.session_manager.get_project_binding(session_id))
    editor_context = _effective_editor_context(
        session_id,
        dict(payload.editor_context or {}),
        session_manager=runtime.session_manager,
        allow_vscode_fallback=allow_vscode_context_fallback,
    )
    _bind_or_validate_editor_project(runtime, session_id, editor_context)
    request = _query_request_from_payload(payload, session_id=session_id, editor_context=editor_context)
    run = _create_and_schedule_run(runtime, request)
    return _run_response(runtime, run)


@router.get("/chat/runs/{stream_run_id}")
async def get_chat_run(stream_run_id: str):
    runtime = require_runtime()
    run = _get_run_or_404(runtime, stream_run_id)
    return _run_response(runtime, run)


@router.get("/chat/sessions/{session_id}/latest-run")
async def get_latest_chat_run_for_session(
    session_id: str,
    active_only: bool = Query(default=True),
):
    runtime = require_runtime()
    validated_session_id = validate_session_id(session_id)
    registry = runtime.harness_runtime.single_agent_runtime_host.run_registry
    now = time.time()
    candidates = [
        run
        for run in registry.list_session_runs(validated_session_id)
        if run.reconnectable_until >= now
        and (not active_only or run.status not in TERMINAL_RUN_STATUSES)
    ]
    if not candidates:
        if active_only:
            return Response(status_code=204)
        raise HTTPException(status_code=404, detail="chat run not found")
    if active_only:
        primary_candidates = [run for run in candidates if not _is_active_turn_steer_run(run)]
        if primary_candidates:
            return _run_response(runtime, primary_candidates[0])
    return _run_response(runtime, candidates[0])


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
        **_run_response(runtime, run),
        "resume_mode": "attach_existing_run",
    }


def _query_request_from_payload(
    payload: ChatRequest,
    *,
    session_id: str,
    editor_context: dict[str, Any] | None = None,
) -> HarnessRuntimeRequest:
    return HarnessRuntimeRequest(
        session_id=session_id,
        message=payload.message,
        explicit_subtasks=list(payload.explicit_subtasks or []),
        runtime_profile=dict(payload.runtime_profile or {}),
        environment_binding=dict(payload.environment_binding or {}),
        runtime_contract=dict(payload.runtime_contract or {}),
        model_selection=dict(payload.model_selection or {}),
        image_generation=dict(payload.image_generation or {}),
        permission_mode=str(payload.permission_mode or ""),
        expected_active_turn_id=str(payload.expected_active_turn_id or ""),
        active_turn_input_policy=str(payload.active_turn_input_policy or "auto"),
        editor_context=dict(editor_context if editor_context is not None else payload.editor_context or {}),
    )


def _effective_editor_context(
    session_id: str,
    payload_editor_context: dict[str, Any],
    *,
    session_manager: Any | None = None,
    allow_vscode_fallback: bool = False,
) -> dict[str, Any]:
    if payload_editor_context:
        return dict(payload_editor_context)
    if not allow_vscode_fallback:
        return {}
    return get_vscode_connection_store().latest_editor_context(
        session_id,
        session_manager=session_manager,
    )


def _bind_or_validate_editor_project(runtime: Any, session_id: str, editor_context: dict[str, Any]) -> None:
    workspace_roots = [
        str(item or "").strip()
        for item in list(editor_context.get("workspace_roots") or [])
        if str(item or "").strip()
    ]
    if not workspace_roots:
        return
    binding = runtime.session_manager.get_project_binding(session_id)
    if binding:
        bound_root = str(binding.get("workspace_root") or "").strip()
        conflict_seen = False
        invalid_seen = ""
        for root in workspace_roots:
            try:
                runtime.session_manager.bind_project(session_id, workspace_root=root, source="vscode")
                return
            except SessionProjectBindingConflict:
                conflict_seen = True
                continue
            except ValueError as exc:
                invalid_seen = str(exc)
                continue
        if conflict_seen:
            raise HTTPException(
                status_code=409,
                detail=f"editor workspace root does not match bound session project: {bound_root}",
            )
        if invalid_seen:
            raise HTTPException(status_code=400, detail=invalid_seen)
        return
    if len(workspace_roots) != 1:
        raise HTTPException(status_code=409, detail="multiple editor workspace roots require explicit project binding")
    try:
        runtime.session_manager.bind_project(session_id, workspace_root=workspace_roots[0], source="vscode")
    except SessionProjectBindingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _create_and_schedule_run(runtime: Any, request: HarnessRuntimeRequest) -> RuntimeRun:
    host = runtime.harness_runtime.single_agent_runtime_host
    run = host.run_registry.create_run(
        session_id=request.session_id,
        owner_process_id=getattr(host, "owner_process_id", None),
        owner_instance_id=getattr(host, "instance_id", ""),
        diagnostics={
            "source": "api.chat",
            "message_chars": len(str(request.message or "")),
            "expected_active_turn_id": str(request.expected_active_turn_id or ""),
            "active_turn_input_policy": str(request.active_turn_input_policy or "auto"),
        },
    )
    request = replace(
        request,
        runtime_profile={
            **dict(request.runtime_profile or {}),
            "stream_run_id": run.stream_run_id,
        },
    )
    host.spawn_background_task(
        _run_chat_to_event_log(runtime, run, request),
        name=f"chat-run-{run.stream_run_id}",
    )
    return run


async def _run_chat_to_event_log(runtime: Any, run: RuntimeRun, request: HarnessRuntimeRequest) -> None:
    host = runtime.harness_runtime.single_agent_runtime_host
    registry = host.run_registry
    replay = host.stream_replay
    terminal_event = ""
    current = _safe_mark_run_running(registry, run)
    try:
        start_data = {"status": "running"}
        _attach_public_projection_frame(
            "chat_run_started",
            start_data,
            session_id=request.session_id,
            sequence=0,
        )
        start_event = replay.append_public_event(
            current,
            public_event_type="chat_run_started",
            data=start_data,
        )
        current = _safe_mark_run_event(registry, current, latest_event_offset=start_event.offset, status="running")
        async for event in runtime.harness_runtime.astream(request):
            event_type = str(event.get("type", "message") or "message")
            runtime_refs = _runtime_run_refs_for_public_event(runtime, request.session_id, event)
            runtime_task_run_id = runtime_refs.get("task_run_id", "")
            runtime_turn_run_id = runtime_refs.get("turn_run_id", "")
            runtime_active_turn_id = runtime_refs.get("active_turn_id", "")
            projections = _project_public_stream_event(event_type, event)
            if not projections:
                continue
            for public_event_type, data in projections:
                if runtime_task_run_id:
                    data.setdefault("runtime_task_run_id", runtime_task_run_id)
                if runtime_turn_run_id:
                    data.setdefault("turn_run_id", runtime_turn_run_id)
                if runtime_active_turn_id:
                    data.setdefault("active_turn_id", runtime_active_turn_id)
                next_sequence = int(getattr(current, "latest_event_offset", -1) or -1) + 1
                if event_requires_public_projection(public_event_type):
                    _attach_public_projection_frame(
                        public_event_type,
                        data,
                        session_id=request.session_id,
                        sequence=next_sequence,
                    )
                logged = replay.append_public_event(current, public_event_type=public_event_type, data=data)
                terminal_event = public_event_type if public_event_type in TERMINAL_STREAM_EVENTS else terminal_event
                diagnostics = {
                    key: value
                    for key, value in {
                        "runtime_task_run_id": runtime_task_run_id,
                        "runtime_turn_run_id": runtime_turn_run_id,
                        "active_turn_id": runtime_active_turn_id,
                    }.items()
                    if value
                }
                if public_event_type != "error":
                    diagnostics.update({"orphaned_by": None, "reason": None, "cancelled": None})
                current = _safe_mark_run_event(
                    registry,
                    current,
                    latest_event_offset=logged.offset,
                    status=_status_for_public_event(public_event_type, data),
                    terminal_event=public_event_type if public_event_type in TERMINAL_STREAM_EVENTS else "",
                    diagnostics=diagnostics or None,
                )
                if public_event_type in TERMINAL_STREAM_EVENTS:
                    break
            if terminal_event:
                break
    except asyncio.CancelledError:
        logger.info("Chat run background task was cancelled.", extra={"stream_run_id": run.stream_run_id})
        current = _safe_update_run(
            registry,
            run.stream_run_id,
            fallback=current,
            status="orphaned",
            diagnostics={"cancelled": True, "reason": "stream_cancelled"},
        )
        host.close_chat_turn_run_for_stream_failure_best_effort(
            current,
            code="stream_cancelled",
            reason="Chat run background task was cancelled.",
        )
        raise
    except Exception as exc:
        logger.exception("Chat run failed before terminal event.", extra={"stream_run_id": run.stream_run_id})
        current = registry.get_run(run.stream_run_id) or current
        logged = replay.append_public_event(
            current,
            public_event_type=TURN_COMPLETED_EVENT,
            data=_turn_completed_data(
                "error",
                {
                    "error": str(exc) or "Chat stream failed.",
                    "code": "stream_exception",
                },
            ),
        )
        current = _safe_mark_run_event(current=current, registry=registry, latest_event_offset=logged.offset, status="failed", terminal_event=TURN_COMPLETED_EVENT)
        host.close_chat_turn_run_for_stream_failure_best_effort(
            current,
            code="stream_exception",
            reason=str(exc) or "Chat stream failed.",
        )
        return
    if not terminal_event:
        current = registry.get_run(run.stream_run_id) or current
        logged = replay.append_public_event(
            current,
            public_event_type=TURN_COMPLETED_EVENT,
            data=_turn_completed_data(
                "error",
                {
                    "error": "Chat stream ended without a terminal event.",
                    "code": "missing_terminal_event",
                },
            ),
        )
        current = _safe_mark_run_event(current=current, registry=registry, latest_event_offset=logged.offset, status="failed", terminal_event=TURN_COMPLETED_EVENT)
        host.close_chat_turn_run_for_stream_failure_best_effort(
            current,
            code="missing_terminal_event",
            reason="Chat stream ended without a terminal event.",
        )


def _safe_mark_run_running(registry: Any, run: RuntimeRun) -> RuntimeRun:
    try:
        return registry.mark_running(run)
    except Exception:
        logger.warning("Failed to update chat run status to running.", extra={"stream_run_id": run.stream_run_id}, exc_info=True)
        return run


def _safe_mark_run_event(
    registry: Any,
    current: RuntimeRun,
    *,
    latest_event_offset: int,
    status: str | None = None,
    terminal_event: str = "",
    diagnostics: dict[str, Any] | None = None,
) -> RuntimeRun:
    try:
        return registry.mark_event(
            current,
            latest_event_offset=latest_event_offset,
            status=status,  # type: ignore[arg-type]
            terminal_event=terminal_event,
            diagnostics=diagnostics,
        )
    except Exception:
        logger.warning(
            "Failed to update chat run event cursor.",
            extra={"stream_run_id": current.stream_run_id, "latest_event_offset": latest_event_offset},
            exc_info=True,
        )
        return current


def _safe_update_run(registry: Any, stream_run_id: str, *, fallback: RuntimeRun, **updates: Any) -> RuntimeRun:
    try:
        return registry.update_run(stream_run_id, **updates)
    except Exception:
        logger.warning("Failed to update chat run registry.", extra={"stream_run_id": stream_run_id}, exc_info=True)
        return fallback


async def _stream_run_events(runtime: Any, run: RuntimeRun, *, after_offset: int):
    host = runtime.harness_runtime.single_agent_runtime_host
    registry = host.run_registry
    replay = host.stream_replay
    subscription = host.event_log.subscribe(run_id=run.event_log_id)
    latest_offset = int(after_offset)
    try:
        yield "retry: 1500\n\n"
        replay_events = replay.list_public_events_after(run, after_offset=latest_offset)
        latest_terminal_offset = max(
            (event.offset for event in replay_events if replay.is_terminal_event(event)),
            default=-1,
        )
        for event in replay_events:
            latest_offset = max(latest_offset, event.offset)
            current = registry.get_run(run.stream_run_id) or run
            is_terminal = replay.is_terminal_event(event)
            if is_terminal and event.offset < latest_terminal_offset:
                continue
            yield replay.to_public_sse(current, event)
            if is_terminal:
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
            if event.offset > latest_offset + 1:
                catchup_events = [
                    candidate
                    for candidate in replay.list_public_events_after(run, after_offset=latest_offset)
                    if candidate.offset <= event.offset
                ]
                for catchup in catchup_events:
                    if catchup.offset <= latest_offset or str(catchup.event_type) != "chat_stream_event":
                        continue
                    current = registry.get_run(run.stream_run_id) or run
                    latest_offset = max(latest_offset, catchup.offset)
                    yield replay.to_public_sse(current, catchup)
                    if replay.is_terminal_event(catchup):
                        return
                continue
            latest_offset = max(latest_offset, event.offset)
            yield replay.to_public_sse(current, event)
            if replay.is_terminal_event(event):
                return
    finally:
        host.event_log.unsubscribe(subscription)


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
    run = runtime.harness_runtime.single_agent_runtime_host.run_registry.get_run(stream_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="chat run not found")
    return run


def _is_active_turn_steer_run(run: RuntimeRun) -> bool:
    diagnostics = dict(run.diagnostics or {})
    expected_active_turn_id = str(diagnostics.get("expected_active_turn_id") or "").strip()
    policy = str(diagnostics.get("active_turn_input_policy") or "").strip().lower()
    return bool(expected_active_turn_id and policy == "steer")


def _run_response(runtime: Any, run: RuntimeRun) -> dict[str, Any]:
    payload = run.to_dict()
    payload.pop("owner_process_id", None)
    payload.pop("owner_instance_id", None)
    active_turn_snapshot = None
    try:
        active_turn = runtime.harness_runtime.single_agent_runtime_host.active_turn_registry.snapshot(run.session_id)
        if active_turn is not None:
            active_turn_snapshot = active_turn.to_dict()
    except Exception:
        active_turn_snapshot = None
    return {
        **payload,
        "active_turn_snapshot": active_turn_snapshot,
        "is_reconnectable": run.reconnectable_until >= time.time()
        and run.status not in TERMINAL_RUN_STATUSES,
        "stream_url": f"/api/chat/runs/{run.stream_run_id}/events",
    }


def _status_for_public_event(event_type: str, data: dict[str, Any] | None = None) -> str:
    if event_type == TURN_COMPLETED_EVENT:
        status = str(dict(data or {}).get("status") or "").strip().lower()
        if status == "failed":
            return "failed"
        if status == "stopped":
            return "stopped"
        return "completed"
    return "running"


def _project_public_stream_event(event_type: str, event: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    normalized = str(event_type or "message").strip() or "message"
    if normalized in INTERNAL_STREAM_EVENTS:
        return []
    if normalized in {"model_action_request", "model_action_admission_checked", "agent_turn_terminal"}:
        return []
    if normalized == "harness_run_started" and _is_turn_trace_only_harness_start(event):
        return []
    raw_data = {key: value for key, value in dict(event).items() if key != "type"}
    if normalized in {"done", "error", "stopped"}:
        return [(TURN_COMPLETED_EVENT, _turn_completed_data(normalized, raw_data))]
    if normalized in {"answer_candidate", "assistant_text"}:
        return []
    if normalized == "token":
        content = str(raw_data.get("content") or "")
        if not content:
            return []
        return [
            (
                ASSISTANT_TEXT_DELTA_EVENT,
                {
                    "content": content,
                    "answer_source": "legacy_token_stream",
                    "visibility": "assistant_body",
                },
            )
        ]
    if normalized == "model_action_admission":
        return _tool_action_public_events(raw_data)
    if normalized in {"turn_tool_observation_recorded", "task_tool_observation_recorded", "tool_observation"}:
        data = _tool_item_completed_data(raw_data)
        return [(TOOL_ITEM_COMPLETED_EVENT, data)] if data else []
    if normalized in {
        SESSION_OUTPUT_COMMIT_CHECKED_EVENT,
        SESSION_OUTPUT_COMMIT_ACK_EVENT,
        SESSION_OUTPUT_COMMIT_FAILED_EVENT,
        SESSION_OUTPUT_COMMIT_SKIPPED_EVENT,
    }:
        data = _session_output_commit_data(normalized, raw_data)
        return [(normalized, data)] if data else []
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
    if "terminal_reason" in data:
        data["terminal_reason"] = _public_terminal_reason(data.get("terminal_reason"))
    if normalized == "runtime_branch_decided":
        branch = dict(data.get("runtime_branch") or {})
        data["runtime_branch"] = _public_runtime_branch(branch)
    elif normalized == "single_agent_turn_started":
        branch = dict(data.get("runtime_branch") or {})
        data = {
            "runtime_branch": _public_runtime_branch(branch),
            "allowed_action_types": list(data.get("allowed_action_types") or []),
        }
    return [(normalized, data)]


def _turn_completed_data(source_event_type: str, raw_data: dict[str, Any]) -> dict[str, Any]:
    source = str(source_event_type or "").strip().lower()
    status = "completed"
    if source == "error":
        status = "failed"
    elif source == "stopped":
        status = "stopped"
    terminal_reason = _public_terminal_reason(
        raw_data.get("terminal_reason")
        or raw_data.get("completion_state")
        or raw_data.get("code")
        or raw_data.get("reason")
        or source
    )
    payload = {
        "status": status,
        "turn_run_id": str(raw_data.get("turn_run_id") or ""),
        "task_run_id": str(raw_data.get("task_run_id") or raw_data.get("runtime_task_run_id") or ""),
        "final_message_ref": str(raw_data.get("message_ref") or raw_data.get("stream_ref") or ""),
        "terminal_reason": terminal_reason,
        "completion_state": str(raw_data.get("completion_state") or ""),
        "error_summary": _safe_public_action_text(raw_data.get("error") or raw_data.get("content") or raw_data.get("message")) if status == "failed" else "",
        "stopped_reason": _safe_public_action_text(raw_data.get("reason") or raw_data.get("content")) if status == "stopped" else "",
    }
    return {key: value for key, value in payload.items() if value not in ("", None)}


def _tool_action_public_events(raw_data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    request_data = _tool_call_requested_data(raw_data)
    if not request_data:
        return []
    permission_data = _tool_permission_decided_data(raw_data, request_data=request_data)
    events: list[tuple[str, dict[str, Any]]] = [(TOOL_CALL_REQUESTED_EVENT, request_data)]
    if permission_data:
        events.append((TOOL_PERMISSION_DECIDED_EVENT, permission_data))
    return events


def _tool_call_requested_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    raw_event = _record(raw_data.get("event"))
    payload = _record(raw_event.get("payload") or raw_data)
    refs = _record(raw_event.get("refs"))
    request = _record(payload.get("model_action_request") or raw_data.get("model_action_request"))
    if not request:
        return {}
    if str(request.get("action_type") or "").strip().lower() != "tool_call":
        return {}
    if _admission_is_blocked(payload):
        return {}
    tool = _record(request.get("tool_call"))
    tool_name = str(tool.get("tool_name") or tool.get("name") or request.get("tool_name") or "").strip()
    tool_call_id = str(tool.get("id") or request.get("tool_call_id") or request.get("request_id") or "").strip()
    if not tool_name or not tool_call_id:
        return {}
    tool_lifecycle_id = _tool_lifecycle_id(tool_call_id=tool_call_id, tool_name=tool_name)
    args = _record(tool.get("args") or tool.get("arguments") or request.get("tool_args"))
    target = _safe_public_tool_target(args)
    data: dict[str, Any] = {
        "item_id": tool_lifecycle_id,
        "request_id": str(request.get("request_id") or tool_call_id),
        "tool_lifecycle_id": tool_lifecycle_id,
        "tool_call_id": tool_call_id,
        "turn_run_id": str(payload.get("turn_run_id") or refs.get("turn_run_ref") or raw_data.get("turn_run_id") or ""),
        "task_run_id": str(payload.get("task_run_id") or refs.get("task_run_ref") or raw_data.get("task_run_id") or raw_data.get("runtime_task_run_id") or ""),
        "tool_name": tool_name,
        "target": target,
        "arguments_preview": _tool_arguments_preview(args),
        "public_progress_note": _safe_public_action_text(request.get("public_progress_note")),
        "public_action_state": _public_action_state(request.get("public_action_state")),
    }
    event_id = str(raw_event.get("event_id") or "").strip()
    if event_id:
        data["runtime_event_id"] = event_id
    return _redact_public_stream_data({key: value for key, value in data.items() if value not in ("", None)})


def _tool_permission_decided_data(raw_data: dict[str, Any], *, request_data: dict[str, Any]) -> dict[str, Any]:
    raw_event = _record(raw_data.get("event"))
    payload = _record(raw_event.get("payload") or raw_data)
    refs = _record(raw_event.get("refs"))
    admission = _record(payload.get("admission") or payload.get("admission_decision") or raw_data.get("admission"))
    if not admission:
        return {}
    decision = str(admission.get("decision") or "").strip()
    permission_decision_id = str(admission.get("admission_id") or "").strip()
    tool_call_id = str(request_data.get("tool_call_id") or admission.get("action_request_ref") or "").strip()
    if not permission_decision_id and tool_call_id:
        permission_decision_id = f"admission:{tool_call_id}"
    data: dict[str, Any] = {
        "item_id": permission_decision_id,
        "request_id": str(request_data.get("request_id") or admission.get("action_request_ref") or ""),
        "tool_call_id": tool_call_id,
        "turn_run_id": str(payload.get("turn_run_id") or refs.get("turn_run_ref") or request_data.get("turn_run_id") or ""),
        "task_run_id": str(payload.get("task_run_id") or refs.get("task_run_ref") or request_data.get("task_run_id") or ""),
        "tool_name": str(request_data.get("tool_name") or ""),
        "permission_decision_id": permission_decision_id,
        "permission_decision": decision,
        "permission_reason": _safe_public_action_text(admission.get("user_visible_reason")),
        "system_reason": _safe_public_action_text(admission.get("system_reason")),
    }
    event_id = str(raw_event.get("event_id") or "").strip()
    if event_id:
        data["runtime_event_id"] = event_id
    return _redact_public_stream_data({key: value for key, value in data.items() if value not in ("", None)})


def _tool_item_completed_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    observation, raw_event = _tool_observation_payload(raw_data)
    if not observation:
        return {}
    tool_name = str(
        observation.get("tool_name")
        or observation.get("tool")
        or _record(observation.get("result_envelope")).get("tool_name")
        or ""
    ).strip()
    tool_call_id = _tool_call_id_from_observation(observation)
    if not tool_name or not tool_call_id:
        return {}
    tool_lifecycle_id = _tool_lifecycle_id(tool_call_id=tool_call_id, tool_name=tool_name)
    status = str(observation.get("status") or "").strip().lower()
    state = "error" if status and status not in {"ok", "done", "completed", "success"} else "done"
    result_envelope = _record(observation.get("result_envelope"))
    execution_receipt = _record(observation.get("execution_receipt") or result_envelope.get("execution_receipt"))
    operation_gate = _record(observation.get("operation_gate"))
    admission = _record(operation_gate.get("admission"))
    refs = _record(raw_event.get("refs"))
    error = _safe_public_action_text(
        observation.get("error")
        or result_envelope.get("error")
        or execution_receipt.get("error")
    )
    observation_text = _safe_tool_observation_text(observation, result_envelope=result_envelope)
    data: dict[str, Any] = {
        "item_id": tool_lifecycle_id,
        "tool_lifecycle_id": tool_lifecycle_id,
        "tool_call_id": tool_call_id,
        "permission_decision_id": _permission_decision_id_from_observation(observation, admission=admission, tool_call_id=tool_call_id),
        "turn_run_id": str(observation.get("caller_ref") or execution_receipt.get("caller_ref") or refs.get("turn_run_ref") or raw_data.get("turn_run_id") or ""),
        "task_run_id": str(observation.get("task_run_id") or execution_receipt.get("task_run_id") or refs.get("task_run_ref") or raw_data.get("task_run_id") or raw_data.get("runtime_task_run_id") or ""),
        "tool_name": tool_name,
        "state": state,
        "observation": observation_text,
        "error": error if state == "error" else "",
        "duration_ms": execution_receipt.get("duration_ms"),
    }
    event_id = str(raw_event.get("event_id") or "").strip()
    if event_id:
        data["runtime_event_id"] = event_id
    return _redact_public_stream_data({key: value for key, value in data.items() if value not in ("", None)})


def _permission_decision_id_from_observation(observation: dict[str, Any], *, admission: dict[str, Any], tool_call_id: str) -> str:
    result_envelope = _record(observation.get("result_envelope"))
    execution_receipt = _record(observation.get("execution_receipt") or result_envelope.get("execution_receipt"))
    diagnostics = _record(observation.get("diagnostics"))
    action_request = _record(diagnostics.get("action_request"))
    request_id = str(action_request.get("request_id") or tool_call_id or "").strip()
    return str(
        admission.get("admission_id")
        or execution_receipt.get("admission_ref")
        or result_envelope.get("admission_ref")
        or (f"admission:{request_id}" if request_id else "")
    ).strip()


def _session_output_commit_data(event_type: str, raw_data: dict[str, Any]) -> dict[str, Any]:
    raw_event = _record(raw_data.get("event"))
    payload = _record(raw_event.get("payload") or raw_data.get("payload") or raw_data)
    refs = _record(raw_event.get("refs"))
    state = str(payload.get("state") or payload.get("status") or "").strip()
    if not state:
        if event_type == SESSION_OUTPUT_COMMIT_ACK_EVENT:
            state = "committed"
        elif event_type == SESSION_OUTPUT_COMMIT_FAILED_EVENT:
            state = "failed"
        elif event_type == SESSION_OUTPUT_COMMIT_SKIPPED_EVENT:
            state = "skipped"
        else:
            state = "checked"
    data: dict[str, Any] = {
        "state": state,
        "status": state,
        "turn_id": str(payload.get("turn_id") or refs.get("turn_ref") or raw_data.get("turn_id") or ""),
        "turn_run_id": str(payload.get("turn_run_id") or refs.get("turn_run_ref") or raw_data.get("turn_run_id") or ""),
        "task_run_id": str(payload.get("task_run_id") or refs.get("task_run_ref") or raw_data.get("task_run_id") or raw_data.get("runtime_task_run_id") or ""),
        "message_id": str(payload.get("message_id") or payload.get("message_ref") or refs.get("message_ref") or ""),
        "message_ref": str(payload.get("message_ref") or refs.get("message_ref") or ""),
        "content_sha256": str(payload.get("content_sha256") or payload.get("sha256") or ""),
        "commit_event_offset": payload.get("commit_event_offset") or raw_event.get("offset") or raw_data.get("event_offset"),
        "reason": _safe_public_action_text(payload.get("reason")),
        "error": _safe_public_action_text(payload.get("error")),
        "summary": _safe_public_action_text(payload.get("summary")),
    }
    event_id = str(raw_event.get("event_id") or "").strip()
    if event_id:
        data["runtime_event_id"] = event_id
    return _redact_public_stream_data({key: value for key, value in data.items() if value not in ("", None)})


def _admission_is_blocked(payload: dict[str, Any]) -> bool:
    admission = _record(payload.get("admission") or payload.get("admission_decision"))
    decision = str(admission.get("decision") or "").strip().lower()
    return decision in {"deny", "denied", "invalid", "needs_contract", "needs_task_run", "blocked"}


def _tool_observation_payload(raw_data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_event = _record(raw_data.get("event"))
    payload = _record(raw_event.get("payload") or raw_data.get("payload"))
    observation = _record(
        raw_data.get("tool_observation")
        or payload.get("tool_observation")
        or payload.get("observation")
        or raw_data.get("observation")
    )
    return observation, raw_event


def _tool_call_id_from_observation(observation: dict[str, Any]) -> str:
    result_envelope = _record(observation.get("result_envelope"))
    execution_receipt = _record(observation.get("execution_receipt") or result_envelope.get("execution_receipt"))
    diagnostics = _record(observation.get("diagnostics"))
    action_request = _record(diagnostics.get("action_request"))
    tool_call = _record(action_request.get("tool_call"))
    return str(
        observation.get("tool_call_id")
        or result_envelope.get("tool_call_id")
        or execution_receipt.get("tool_call_id")
        or tool_call.get("id")
        or ""
    ).strip()


def _tool_lifecycle_id(*, tool_call_id: str, tool_name: str) -> str:
    normalized_call_id = str(tool_call_id or "").strip()
    if normalized_call_id:
        return normalized_call_id
    normalized_tool = str(tool_name or "tool").strip() or "tool"
    return f"tool:{normalized_tool}"


def _safe_tool_observation_text(observation: dict[str, Any], *, result_envelope: dict[str, Any]) -> str:
    for value in (
        result_envelope.get("text"),
        observation.get("text"),
        result_envelope.get("summary"),
        result_envelope.get("result"),
    ):
        text = _safe_public_action_text(value)
        if text:
            return text[:500]
    structured = _record(result_envelope.get("structured_payload"))
    for key in ("summary", "message", "error"):
        text = _safe_public_action_text(structured.get(key))
        if text:
            return text[:500]
    return ""


def _tool_arguments_preview(args: dict[str, Any]) -> str:
    if not args:
        return ""
    parts: list[str] = []
    for key in sorted(args.keys()):
        value = args.get(key)
        if isinstance(value, (dict, list, tuple)):
            continue
        text = _safe_public_action_text(f"{key}={value}")
        if text:
            parts.append(text[:80])
        if len(parts) >= 3:
            break
    return ", ".join(parts)[:240]


def _safe_public_tool_target(args: dict[str, Any]) -> str:
    for key in ("path", "file", "file_path", "target", "url", "query"):
        value = _safe_public_action_text(args.get(key))
        if value:
            return value[:180]
    return ""


def _public_action_state(value: Any) -> dict[str, str]:
    payload = _record(value)
    result: dict[str, str] = {}
    for key in ("current_judgment", "next_action"):
        visible = _safe_public_action_text(payload.get(key))
        if visible:
            result[key] = visible[:220]
    return result


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _safe_public_action_text(value: Any) -> str:
    text = sanitize_visible_assistant_content(str(value or "")).strip()
    if not text:
        return ""
    text = public_runtime_progress_summary(text).strip()
    if not text:
        return ""
    if contains_internal_protocol(text) or contains_inline_pseudo_tool_call(text):
        return ""
    return text[:360]


def _public_terminal_reason(value: Any) -> str:
    reason = str(value or "").strip()
    if reason in {
        "continue_active_work",
        "pause_active_work",
        "stop_active_work",
        "append_instruction_to_active_work",
        "answer_about_active_work",
        "answer_then_continue_active_work",
        "active_work_control",
        "active_work_control_denied",
        "active_work_control_action_not_allowed",
    }:
        return "work_control"
    return reason


def _is_turn_trace_only_harness_start(event: dict[str, Any]) -> bool:
    refs = _runtime_run_refs_from_event(event)
    return bool(refs["turn_run_id"]) and not bool(refs["task_run_id"])


def _public_runtime_branch(branch: dict[str, Any]) -> dict[str, Any]:
    return {
        key: branch.get(key)
        for key in ("branch_kind", "reason")
        if key in branch
    }


def _attach_public_projection_frame(
    public_event_type: str,
    data: dict[str, Any],
    *,
    session_id: str,
    sequence: int = 0,
) -> None:
    attach_public_projection_event(
        public_event_type,
        data,
        session_id=session_id,
        sequence=sequence,
    )


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


def _runtime_run_refs_for_public_event(runtime: Any, session_id: str, event: dict[str, Any]) -> dict[str, str]:
    refs = _runtime_run_refs_from_event(event)
    active_refs = _bound_active_task_refs_for_session(runtime, session_id)
    if not active_refs:
        return refs
    event_task_run_id = refs.get("task_run_id", "")
    active_task_run_id = active_refs.get("task_run_id", "")
    if event_task_run_id and event_task_run_id != active_task_run_id:
        return refs
    if not event_task_run_id:
        refs["task_run_id"] = active_task_run_id
        refs["active_turn_id"] = active_refs.get("active_turn_id", "")
        if active_refs.get("turn_run_id"):
            refs["turn_run_id"] = active_refs.get("turn_run_id", "")
        return refs
    if not refs.get("active_turn_id"):
        refs["active_turn_id"] = active_refs.get("active_turn_id", "")
    if not refs.get("turn_run_id") and active_refs.get("turn_run_id"):
        refs["turn_run_id"] = active_refs.get("turn_run_id", "")
    return refs


def _bound_active_task_refs_for_session(runtime: Any, session_id: str) -> dict[str, str]:
    try:
        active_turn = runtime.harness_runtime.single_agent_runtime_host.active_turn_registry.snapshot(session_id)
    except Exception:
        return {}
    if active_turn is None:
        return {}
    task_run_id = str(getattr(active_turn, "bound_task_run_id", "") or "").strip()
    active_turn_id = str(getattr(active_turn, "turn_id", "") or "").strip()
    if not task_run_id or not active_turn_id:
        return {}
    return {
        "task_run_id": task_run_id,
        "active_turn_id": active_turn_id,
        "turn_run_id": str(getattr(active_turn, "turn_run_id", "") or "").strip(),
    }


def _runtime_run_refs_from_event(event: dict[str, Any]) -> dict[str, str]:
    task_run_id = ""
    turn_run_id = ""
    active_turn_id = str(event.get("active_turn_id") or "").strip()
    runtime_event = dict(event.get("event") or {}) if isinstance(event.get("event"), dict) else {}
    runtime_payload = dict(runtime_event.get("payload") or {}) if isinstance(runtime_event.get("payload"), dict) else {}
    runtime_refs = dict(runtime_event.get("refs") or {}) if isinstance(runtime_event.get("refs"), dict) else {}
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
    if not active_turn_id:
        active_turn = event.get("active_turn")
        if isinstance(active_turn, dict):
            active_turn_id = str(active_turn.get("turn_id") or "").strip()
    if not active_turn_id and task_run_id:
        active_turn_id = str(runtime_refs.get("turn_ref") or "").strip()
    refs = {"task_run_id": task_run_id, "turn_run_id": turn_run_id}
    if active_turn_id:
        refs["active_turn_id"] = active_turn_id
    return refs
