from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from api.deps import require_runtime
from harness.continuation import select_session_continuation
from harness.entrypoint import HarnessRuntimeRequest
from harness.runtime.control_events import RuntimeSignalScope
from harness.task_run_status import is_stopped_or_terminal_task_run
from runtime.model_gateway.assistant_stream_frame import (
    assistant_message_ref,
)
from runtime.output_stream.public_stream_compiler import (
    ProjectionLifecycleState,
    attach_public_projection_frame,
    project_public_stream_event,
    public_replay_stream_data,
    public_terminal_reason,
    turn_completed_data,
)
from runtime.output_stream.public_contract import (
    ASSISTANT_PUBLIC_FEEDBACK_EVENT,
    ASSISTANT_STREAM_REPAIR_EVENT,
    ASSISTANT_TEXT_DELTA_EVENT,
    ASSISTANT_TEXT_FINAL_EVENT,
    CHAT_TURN_BOUND_EVENT,
    SESSION_OUTPUT_COMMIT_ACK_EVENT,
    SESSION_OUTPUT_COMMIT_CHECKED_EVENT,
    SESSION_OUTPUT_COMMIT_FAILED_EVENT,
    SESSION_OUTPUT_COMMIT_SKIPPED_EVENT,
    TASK_ORIGIN_BOUND_EVENT,
    TASK_BRIDGE_STARTED_EVENT,
    TASK_BRIDGE_TERMINAL_EVENT,
    TOOL_CALL_REQUESTED_EVENT,
    TOOL_ITEM_COMPLETED_EVENT,
    TOOL_ITEM_STARTED_EVENT,
    TOOL_PERMISSION_DECIDED_EVENT,
    TURN_COMPLETED_EVENT,
    event_requires_public_projection,
)
from runtime.shared.queued_user_input_dispatcher import (
    chat_run_execution_attached,
    has_active_primary_chat_run,
    queued_input_admission_target as runtime_queued_input_admission_target,
    validate_queued_steer,
)
from runtime.shared.queued_user_input_store import QueuedUserInput
from runtime.shared.runtime_run_registry import RuntimeRun, TERMINAL_RUNTIME_RUN_STATUSES, is_recoverable_runtime_run_interruption
from sessions import SessionProjectBindingConflict, validate_session_id
from task_system.session_scope import assert_optional_session_scope, request_scope_from_query
from task_system.work_environments.repository import TaskEnvironmentRepository
from capability_system.capabilities.attachments import SUPPORTED_ATTACHMENT_IMAGE_SUFFIXES
from core.config import runtime_config
from core.project_layout import ProjectLayout

router = APIRouter()
logger = logging.getLogger(__name__)
TERMINAL_STREAM_EVENTS = {TURN_COMPLETED_EVENT}
TERMINAL_RUN_STATUSES = TERMINAL_RUNTIME_RUN_STATUSES
TASK_BRIDGE_PUBLIC_EVENT_TYPES = {
    ASSISTANT_PUBLIC_FEEDBACK_EVENT,
    ASSISTANT_STREAM_REPAIR_EVENT,
    ASSISTANT_TEXT_DELTA_EVENT,
    ASSISTANT_TEXT_FINAL_EVENT,
    "step_summary_recorded",
    "model_action_admission_checked",
    "tool_item_started",
    "tool_observation",
    "task_tool_observation_recorded",
    "turn_tool_observation_recorded",
    "session_output_commit_checked",
    "session_output_commit_ack",
    "session_output_commit_failed",
    "session_output_commit_skipped",
}
TASK_BRIDGE_TERMINAL_EVENT_TYPES = {"task_run_lifecycle_finished", "task_run_terminal_observed"}
TURN_CONTEXT_REQUIRED_PUBLIC_EVENTS = {
    ASSISTANT_PUBLIC_FEEDBACK_EVENT,
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
}
@dataclass(frozen=True, slots=True)
class PublicTurnOutputContext:
    context_id: str
    stream_run_id: str
    session_id: str
    turn_id: str
    turn_run_id: str
    assistant_message_ref: str
    source_turn_event_id: str
    source_turn_event_offset: int
    public_sequence_started_at: int
    created_at: float

    def anchor(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "turn_run_id": self.turn_run_id,
            "message_id": self.assistant_message_ref,
            "message_ref": self.assistant_message_ref,
            "stream_run_id": self.stream_run_id,
            "run_id": self.stream_run_id,
        }


@dataclass(frozen=True, slots=True)
class ChatTaskBridgeContext:
    bridge_id: str
    stream_run_id: str
    event_log_id: str
    session_id: str
    turn_id: str
    turn_run_id: str
    task_run_id: str
    assistant_message_ref: str
    source_handoff_event_id: str
    source_handoff_event_offset: int
    task_event_start_offset: int
    public_sequence_base: int
    created_at: float

    def anchor(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "turn_run_id": self.turn_run_id,
            "task_run_id": self.task_run_id,
            "message_id": self.assistant_message_ref,
            "message_ref": self.assistant_message_ref,
            "stream_run_id": self.stream_run_id,
            "run_id": self.stream_run_id,
        }


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1)
    client_message_id: str = Field(default="", max_length=240)
    session_id: str
    stream: bool = True
    explicit_subtasks: list[dict[str, Any]] = Field(default_factory=list)
    runtime_profile: dict[str, Any] = Field(default_factory=dict)
    environment_binding: dict[str, Any] = Field(default_factory=dict)
    runtime_contract: dict[str, Any] = Field(default_factory=dict)
    model_selection: dict[str, Any] = Field(default_factory=dict)
    image_generation: dict[str, Any] = Field(default_factory=dict)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    permission_mode: str = ""
    session_scope: dict[str, Any] | None = None
    expected_active_turn_id: str = ""
    active_turn_input_policy: str = "auto"
    editor_context: dict[str, Any] = Field(default_factory=dict)


class QueuedChatInputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1)
    client_message_id: str = Field(default="", max_length=240)
    explicit_subtasks: list[dict[str, Any]] = Field(default_factory=list)
    runtime_contract: dict[str, Any] = Field(default_factory=dict)
    environment_binding: dict[str, Any] = Field(default_factory=dict)
    model_selection: dict[str, Any] = Field(default_factory=dict)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    permission_mode: str = ""
    session_scope: dict[str, Any] | None = None
    editor_context: dict[str, Any] = Field(default_factory=dict)


class ChatRunInterruptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = Field(default="interrupt_for_resume", max_length=80)
    reason: str = Field(default="user_stop_from_chat", max_length=240)
    expected_active_turn_id: str = Field(default="", max_length=240)


@router.post("/chat/runs")
async def create_chat_run(payload: ChatRequest):
    runtime = require_runtime()
    session_id = validate_session_id(payload.session_id)
    assert_optional_session_scope(runtime.session_manager, session_id, payload.session_scope)
    editor_context = _explicit_editor_context(payload.editor_context)
    _bind_or_validate_editor_project(runtime, session_id, editor_context)
    request = _query_request_from_payload(payload, session_id=session_id, editor_context=editor_context, base_dir=runtime.base_dir)
    queued_active_response = await _enqueue_request_for_attached_active_session(runtime, request)
    if queued_active_response is not None:
        return queued_active_response
    run = _create_and_schedule_run(runtime, request)
    return _run_response(runtime, run)


@router.post("/chat/sessions/{session_id}/queued-inputs")
async def enqueue_queued_chat_input(session_id: str, payload: QueuedChatInputRequest):
    runtime = require_runtime()
    validated_session_id = validate_session_id(session_id)
    assert_optional_session_scope(runtime.session_manager, validated_session_id, payload.session_scope)
    editor_context = _explicit_editor_context(payload.editor_context)
    _bind_or_validate_editor_project(runtime, validated_session_id, editor_context)
    attachments = _normalize_chat_attachments(payload.attachments, session_id=validated_session_id, base_dir=runtime.base_dir)
    host = runtime.harness_runtime.single_agent_runtime_host
    admission = _queued_input_admission_target(runtime, session_id=validated_session_id)
    item = await asyncio.to_thread(
        host.queued_user_inputs.enqueue,
        session_id=validated_session_id,
        content=payload.message,
        client_message_id=payload.client_message_id,
        input_policy=str(admission.get("input_policy") or "auto"),
        expected_active_turn_id=str(admission.get("expected_active_turn_id") or ""),
        task_environment_id=str(admission.get("task_environment_id") or ""),
        attachments=attachments,
        session_scope=dict(payload.session_scope or {}),
        environment_binding=dict(payload.environment_binding or {}),
        runtime_contract=dict(payload.runtime_contract or {}),
        explicit_subtasks=list(payload.explicit_subtasks or []),
        model_selection=dict(payload.model_selection or {}),
        permission_mode=str(payload.permission_mode or ""),
        editor_context=editor_context,
    )
    await _dispatch_next_queued_input(runtime, validated_session_id, reason="queued_input_enqueued")
    return _queued_input_response(runtime, validated_session_id, item)


@router.get("/chat/sessions/{session_id}/queued-inputs")
async def list_queued_chat_inputs(
    session_id: str,
    include_terminal: bool = Query(default=True),
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
):
    runtime = require_runtime()
    validated_session_id = validate_session_id(session_id)
    await asyncio.to_thread(
        assert_optional_session_scope,
        runtime.session_manager,
        validated_session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    items = await asyncio.to_thread(
        runtime.harness_runtime.single_agent_runtime_host.queued_user_inputs.list_session,
        validated_session_id,
        include_terminal=bool(include_terminal),
    )
    return {
        "session_id": validated_session_id,
        "items": [item.to_dict() for item in items],
        "authority": "api.chat.queued_user_inputs",
    }


@router.delete("/chat/sessions/{session_id}/queued-inputs/{queue_item_id}")
async def cancel_queued_chat_input(
    session_id: str,
    queue_item_id: str,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
):
    runtime = require_runtime()
    validated_session_id = validate_session_id(session_id)
    await asyncio.to_thread(
        assert_optional_session_scope,
        runtime.session_manager,
        validated_session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    item = await asyncio.to_thread(
        runtime.harness_runtime.single_agent_runtime_host.queued_user_inputs.cancel,
        validated_session_id,
        queue_item_id,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="queued input not found")
    return {
        "session_id": validated_session_id,
        "item": item.to_dict(),
        "authority": "api.chat.queued_user_inputs",
    }


@router.get("/chat/runs/{stream_run_id}")
async def get_chat_run(stream_run_id: str):
    runtime = require_runtime()
    run = _get_run_or_404(runtime, stream_run_id)
    return _run_response(runtime, run)


@router.post("/chat/runs/{stream_run_id}/interrupt")
async def interrupt_chat_run(stream_run_id: str, payload: ChatRunInterruptRequest | None = None):
    runtime = require_runtime()
    request = payload or ChatRunInterruptRequest()
    run = _get_run_or_404(runtime, stream_run_id)
    mode = _validated_interrupt_mode(request.mode)
    reason = str(request.reason or "user_stop_from_chat").strip() or "user_stop_from_chat"
    host = runtime.harness_runtime.single_agent_runtime_host
    registry = host.run_registry
    active_turn = host.active_turn_registry.snapshot(run.session_id)
    expected_turn_id = str(request.expected_active_turn_id or "").strip()
    active_turn_control: dict[str, Any] = {}
    if active_turn is not None:
        active_turn_control = host.active_turn_registry.mark_interrupting(
            session_id=run.session_id,
            expected_turn_id=expected_turn_id,
            reason=reason,
        )
        if not active_turn_control.get("accepted"):
            raise HTTPException(status_code=409, detail=active_turn_control)
        active_turn = host.active_turn_registry.snapshot(run.session_id)
    elif expected_turn_id:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "active_turn_unavailable",
                "expected_active_turn_id": expected_turn_id,
                "authority": "api.chat.runtime_interruption",
            },
        )

    stream_control = await asyncio.to_thread(
        host.cancel_runtime_run_cells,
        runtime_run_sessions={run.stream_run_id: run.session_id},
        reason=reason,
    )
    interruption_record: dict[str, Any] = {}
    if mode == "interrupt_for_resume":
        interruption_record = await asyncio.to_thread(
            host.record_chat_turn_run_runtime_interruption_best_effort,
            run,
            code="runtime_stream_interrupted",
            reason=reason,
            orphaned_by="api.chat.runtime_interruption",
        )
    else:
        _safe_update_run(
            registry,
            run.stream_run_id,
            fallback=run,
            status="stopped",
            terminal_event="",
            owner_process_id=0,
            owner_instance_id="",
            diagnostics={
                "runtime_interruption_mode": mode,
                "runtime_interruption_reason": reason,
            },
        )
    context_status = _session_context_recovery_status(runtime, run.session_id)
    selection = select_session_continuation(
        host,
        session_id=run.session_id,
        active_work_present=False,
        context_recovery_status=context_status,
    )
    current_run = registry.get_run(run.stream_run_id) or run
    checkpoint = {
        "latest_event_offset": int(getattr(current_run, "latest_event_offset", -1) or -1),
        "stream_run_status": str(getattr(current_run, "status", "") or ""),
        "context_resume_available": bool(context_status.get("available") is True and context_status.get("fresh") is True),
        "authority": "api.chat.runtime_interruption.checkpoint",
    }
    runtime_signal = _publish_chat_interruption_fact_signal(
        host,
        run=current_run,
        mode=mode,
        reason=reason,
        stream_control=stream_control,
        context_recovery_status=context_status,
        checkpoint=checkpoint,
    )
    accepted = bool(
        not stream_control or not stream_control.get("rejected")
    )
    return {
        "ok": accepted,
        "accepted": accepted,
        "stream_run_id": run.stream_run_id,
        "session_id": run.session_id,
        "mode": mode,
        "reason": reason,
        "active_turn": active_turn.to_dict() if active_turn is not None else {},
        "active_turn_control": active_turn_control,
        "stream_control": stream_control,
        "interruption_record": interruption_record,
        "continuation": selection.to_dict(),
        "runtime_signal": runtime_signal,
        "context_recovery_status": context_status,
        "checkpoint": checkpoint,
        "authority": "api.chat.runtime_interruption",
    }


@router.get("/chat/sessions/{session_id}/latest-run")
async def get_latest_chat_run_for_session(
    session_id: str,
    active_only: bool = Query(default=True),
    restore_only: bool = Query(default=False),
):
    runtime = require_runtime()
    validated_session_id = validate_session_id(session_id)
    host = runtime.harness_runtime.single_agent_runtime_host
    registry = host.run_registry
    now = time.time()
    candidates = [
        run
        for run in registry.list_session_runs(validated_session_id)
        if run.reconnectable_until >= now
        and (not active_only or run.status not in TERMINAL_RUN_STATUSES)
    ]
    if active_only:
        candidates = [
            run
            for run in candidates
            if chat_run_execution_attached(host, run, terminal_statuses=TERMINAL_RUN_STATUSES)
        ]
    if restore_only:
        candidates = [
            run
            for run in candidates
            if is_recoverable_runtime_run_interruption(run)
            and str(run.event_log_id or "").strip()
            and int(getattr(run, "latest_event_offset", -1) or -1) >= 0
        ]
    if not candidates:
        if active_only:
            return Response(status_code=204)
        raise HTTPException(status_code=404, detail="chat run not found")
    return _run_response(runtime, candidates[0])


@router.get("/chat/sessions/{session_id}/continuations/latest")
async def get_latest_session_continuation(session_id: str):
    runtime = require_runtime()
    validated_session_id = validate_session_id(session_id)
    host = runtime.harness_runtime.single_agent_runtime_host
    active_work_present = _active_work_blocks_continuation(runtime, validated_session_id)
    context_status = _session_context_recovery_status(runtime, validated_session_id)
    selection = select_session_continuation(
        host,
        session_id=validated_session_id,
        active_work_present=active_work_present,
        context_recovery_status=context_status,
    )
    return {
        "session_id": validated_session_id,
        "available": False,
        "context_recovery_status": context_status,
        "reason": selection.reason,
        "task_continuation_authority": "task_system.task_work_environment",
        "legacy_task_run_selector": "removed",
        "authority": "api.chat.session_continuation_projection",
    }


@router.get("/chat/runs/{stream_run_id}/events/replay")
async def replay_chat_run_events(
    stream_run_id: str,
    after_offset: int = Query(default=-1),
    limit: int = Query(default=500, ge=1, le=2000),
):
    runtime = require_runtime()
    run = _get_run_or_404(runtime, stream_run_id)
    replay = runtime.harness_runtime.single_agent_runtime_host.stream_replay
    return replay.public_replay_response(run, after_offset=int(after_offset), limit=int(limit))


def _query_request_from_payload(
    payload: ChatRequest,
    *,
    session_id: str,
    editor_context: dict[str, Any] | None = None,
    base_dir: str | Path | None = None,
) -> HarnessRuntimeRequest:
    return HarnessRuntimeRequest(
        session_id=session_id,
        message=payload.message,
        client_message_id=str(payload.client_message_id or ""),
        explicit_subtasks=list(payload.explicit_subtasks or []),
        runtime_profile=dict(payload.runtime_profile or {}),
        environment_binding=dict(payload.environment_binding or {}),
        runtime_contract=dict(payload.runtime_contract or {}),
        model_selection=dict(payload.model_selection or {}),
        image_generation=dict(payload.image_generation or {}),
        attachments=_normalize_chat_attachments(payload.attachments, session_id=session_id, base_dir=base_dir),
        permission_mode=str(payload.permission_mode or ""),
        expected_active_turn_id=str(payload.expected_active_turn_id or ""),
        active_turn_input_policy=str(payload.active_turn_input_policy or "auto"),
        editor_context=dict(editor_context if editor_context is not None else payload.editor_context or {}),
    )


def _normalize_chat_attachments(
    attachments: list[dict[str, Any]] | None,
    *,
    session_id: str,
    base_dir: str | Path | None,
) -> list[dict[str, Any]]:
    raw_items = list(attachments or [])
    attachment_config = runtime_config.get_attachments_config()
    if raw_items and not bool(attachment_config.get("enabled", True)):
        raise HTTPException(status_code=403, detail="Chat attachments are disabled")
    max_files = int(attachment_config.get("max_files_per_message") or 8)
    if len(raw_items) > max_files:
        raise HTTPException(status_code=400, detail=f"At most {max_files} attachments are supported per message")
    if not raw_items:
        return []
    project_root = ProjectLayout.from_backend_dir(base_dir or Path(__file__).resolve().parents[1]).project_root
    normalized: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="Invalid attachment payload")
        attachment_session_id = _clean_attachment_text(raw.get("session_id"), limit=120)
        if attachment_session_id and attachment_session_id != session_id:
            raise HTTPException(status_code=400, detail="Attachment session_id does not match chat session")
        attachment_id = _clean_attachment_text(raw.get("attachment_id"), limit=80)
        path = _clean_attachment_text(raw.get("path"), limit=500).replace("\\", "/")
        if not attachment_id or not path:
            raise HTTPException(status_code=400, detail="Attachment payload requires attachment_id and path")
        storage_relative_dir = str(attachment_config.get("storage_relative_dir") or "storage/chat_attachments").replace("\\", "/").strip("/")
        expected_prefix = f"{storage_relative_dir}/{session_id}/"
        if not path.startswith(expected_prefix):
            raise HTTPException(status_code=400, detail="Attachment path is outside this chat session")
        suffix = Path(path).suffix.lower()
        if suffix not in SUPPORTED_ATTACHMENT_IMAGE_SUFFIXES:
            raise HTTPException(status_code=400, detail="Unsupported attachment image suffix")
        resolved = (project_root / path).resolve()
        try:
            resolved.relative_to(project_root.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Attachment path traversal detected") from exc
        if not resolved.is_file():
            raise HTTPException(status_code=400, detail="Attachment file does not exist")
        normalized.append(
            {
                "attachment_id": attachment_id,
                "session_id": session_id,
                "filename": _clean_attachment_text(raw.get("filename"), limit=180),
                "mime_type": _clean_attachment_text(raw.get("mime_type"), limit=120),
                "size_bytes": _safe_int(raw.get("size_bytes")),
                "content_sha256": _clean_attachment_text(raw.get("content_sha256"), limit=120),
                "path": path,
                "created_at": _safe_float(raw.get("created_at")),
                "width": _safe_int(raw.get("width")),
                "height": _safe_int(raw.get("height")),
                "authority": _clean_attachment_text(raw.get("authority"), limit=120) or "api.chat_attachments",
                "storage_authority": _clean_attachment_text(raw.get("storage_authority"), limit=120) or "chat_attachment_store",
            }
        )
    return normalized


def _clean_attachment_text(value: Any, *, limit: int) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()
    return text[: max(0, int(limit))]


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _explicit_editor_context(payload_editor_context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload_editor_context, dict):
        return {}
    return dict(payload_editor_context)


def _editor_context_binding_source(editor_context: dict[str, Any]) -> str:
    source = str(editor_context.get("source") or "").strip()
    return source[:120] if source else "editor_context"


def _bind_or_validate_editor_project(runtime: Any, session_id: str, editor_context: dict[str, Any]) -> None:
    workspace_roots = [
        str(item or "").strip()
        for item in list(editor_context.get("workspace_roots") or [])
        if str(item or "").strip()
    ]
    if not workspace_roots:
        return
    binding_source = _editor_context_binding_source(editor_context)
    binding = runtime.session_manager.get_project_binding(session_id)
    if binding:
        bound_root = str(binding.get("workspace_root") or "").strip()
        conflict_seen = False
        invalid_seen = ""
        for root in workspace_roots:
            try:
                runtime.session_manager.bind_project(session_id, workspace_root=root, source=binding_source)
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
        runtime.session_manager.bind_project(session_id, workspace_root=workspace_roots[0], source=binding_source)
    except SessionProjectBindingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _create_and_schedule_run(runtime: Any, request: HarnessRuntimeRequest) -> RuntimeRun:
    host = runtime.harness_runtime.single_agent_runtime_host
    host.bind_control_loop()
    request_runtime_profile = dict(request.runtime_profile or {})
    run = host.run_registry.create_run(
        session_id=request.session_id,
        owner_process_id=getattr(host, "owner_process_id", None),
        owner_instance_id=getattr(host, "instance_id", ""),
        diagnostics={
            "source": "api.chat",
            "message_chars": len(str(request.message or "")),
            "expected_active_turn_id": str(request.expected_active_turn_id or ""),
            "active_turn_input_policy": str(request.active_turn_input_policy or "auto"),
            "queued_input_id": str(request_runtime_profile.get("queued_input_id") or ""),
            "queued_client_message_id": str(request_runtime_profile.get("queued_client_message_id") or ""),
            "queue_dispatch_reason": str(request_runtime_profile.get("queue_dispatch_reason") or ""),
        },
    )
    request = runtime.harness_runtime.prepare_chat_run_request_for_schedule(
        request,
        stream_run_id=run.stream_run_id,
    )
    request_runtime_profile = dict(request.runtime_profile or {})
    request = replace(
        request,
        runtime_profile={
            **request_runtime_profile,
            "stream_run_id": run.stream_run_id,
        },
    )
    schedule_result = host.agent_run_supervisor.schedule_single_turn(
        session_id=request.session_id,
        stream_run_id=run.stream_run_id,
        work_factory=lambda: _run_chat_to_event_log(runtime, run, request),
        scheduler="api.chat",
        invocation_kind="single_turn",
        primary=True,
        turn_id=str(request_runtime_profile.get("precommitted_user_message_turn_id") or ""),
        on_done=lambda _scope, _handle: _schedule_queued_input_dispatch(
            runtime,
            request.session_id,
            reason="chat_run_cell_done",
        ),
    )
    if not bool(schedule_result.get("scheduled")) and str(schedule_result.get("reason") or "") != "already_running":
        return _fail_chat_run_schedule(
            runtime,
            run,
            schedule_result=schedule_result,
        )
    return host.run_registry.get_run(run.stream_run_id) or run


async def _enqueue_request_for_attached_active_session(
    runtime: Any,
    request: HarnessRuntimeRequest,
) -> dict[str, Any] | None:
    host = runtime.harness_runtime.single_agent_runtime_host
    session_id = str(request.session_id or "").strip()
    if not session_id:
        return None
    if not has_active_primary_chat_run(host, session_id=session_id, terminal_statuses=TERMINAL_RUN_STATUSES):
        return None
    store = getattr(host, "queued_user_inputs", None)
    enqueue = getattr(store, "enqueue", None)
    if not callable(enqueue):
        return None
    admission = _queued_input_admission_target(runtime, session_id=session_id)
    item = await asyncio.to_thread(
        enqueue,
        session_id=session_id,
        content=request.message,
        client_message_id=str(request.client_message_id or ""),
        input_policy=str(admission.get("input_policy") or "auto"),
        expected_active_turn_id=str(admission.get("expected_active_turn_id") or ""),
        task_environment_id=str(admission.get("task_environment_id") or ""),
        attachments=[dict(entry) for entry in list(request.attachments or []) if isinstance(entry, dict)],
        session_scope=dict(getattr(request, "session_scope", {}) or {}),
        environment_binding=dict(request.environment_binding or {}),
        runtime_contract=dict(request.runtime_contract or {}),
        explicit_subtasks=[dict(entry) for entry in list(request.explicit_subtasks or []) if isinstance(entry, dict)],
        model_selection=dict(request.model_selection or {}),
        permission_mode=str(request.permission_mode or ""),
        editor_context=dict(getattr(request, "editor_context", {}) or {}),
    )
    active_run = _latest_attached_chat_run_for_session(runtime, session_id)
    if active_run is None:
        active_run = await _dispatch_next_queued_input(runtime, session_id, reason="active_session_queue_race")
    if active_run is None:
        return {
            "session_id": session_id,
            "accepted_as_queued_input": True,
            "queued_input": item.to_dict(),
            "authority": "api.chat.active_session_queue",
        }
    response = _run_response(runtime, active_run)
    response["accepted_as_queued_input"] = True
    response["queued_input"] = item.to_dict()
    response["queue_authority"] = "api.chat.active_session_queue"
    return response


def _latest_attached_chat_run_for_session(runtime: Any, session_id: str) -> RuntimeRun | None:
    host = runtime.harness_runtime.single_agent_runtime_host
    registry = getattr(host, "run_registry", None)
    list_session_runs = getattr(registry, "list_session_runs", None)
    if not callable(list_session_runs):
        return None
    for run in list(list_session_runs(str(session_id or "").strip()) or []):
        if chat_run_execution_attached(host, run, terminal_statuses=TERMINAL_RUN_STATUSES):
            return run
    return None


def _fail_chat_run_schedule(runtime: Any, run: RuntimeRun, *, schedule_result: dict[str, Any]) -> RuntimeRun:
    host = runtime.harness_runtime.single_agent_runtime_host
    registry = host.run_registry
    replay = host.stream_replay
    reason = str(schedule_result.get("reason") or "runtime_cell_schedule_failed")
    start_data = {"status": "running"}
    attach_public_projection_frame(
        "chat_run_started",
        start_data,
        session_id=run.session_id,
        sequence=0,
    )
    start_event = replay.append_public_event(run, public_event_type="chat_run_started", data=start_data)
    current = registry.mark_event(run, latest_event_offset=start_event.offset, status="running")
    data = turn_completed_data(
        "error",
        {
            "error": "运行未能启动",
            "code": "runtime_cell_schedule_failed",
            "reason": reason,
        },
    )
    terminal_event = replay.append_public_event(current, public_event_type=TURN_COMPLETED_EVENT, data=data)
    return registry.mark_event(
        current,
        latest_event_offset=terminal_event.offset,
        status="failed",
        terminal_event=TURN_COMPLETED_EVENT,
        diagnostics={
            "reason": "runtime_cell_schedule_failed",
            "failure_reason": reason,
            "runtime_cell_schedule": dict(schedule_result or {}),
        },
    )


def _queued_input_response(runtime: Any, session_id: str, item: QueuedUserInput) -> dict[str, Any]:
    host = runtime.harness_runtime.single_agent_runtime_host
    current = host.queued_user_inputs.get_item(session_id, item.queue_item_id) or item
    items = host.queued_user_inputs.list_session(session_id)
    return {
        "session_id": session_id,
        "item": current.to_dict(),
        "items": [entry.to_dict() for entry in items],
        "authority": "api.chat.queued_user_inputs",
    }


def _queued_input_admission_target(runtime: Any, *, session_id: str) -> dict[str, str]:
    host = runtime.harness_runtime.single_agent_runtime_host
    admission = dict(runtime_queued_input_admission_target(host, session_id=session_id))
    if str(admission.get("input_policy") or "").strip().lower() == "steer":
        admission["task_environment_id"] = _foreground_task_environment_id(runtime, session_id)
    else:
        admission["task_environment_id"] = ""
    admission.pop("task_run_id", None)
    admission["authority"] = "api.chat.queued_input_admission_target"
    return admission


def _foreground_task_environment_id(runtime: Any, session_id: str) -> str:
    try:
        repository = TaskEnvironmentRepository(runtime.base_dir)
        binding = repository.get_foreground_session_binding(session_id)
    except Exception:
        logger.debug("Failed to read foreground task environment binding for queued input.", exc_info=True)
        return ""
    if binding is None:
        return ""
    return str(getattr(binding, "task_environment_id", "") or "").strip()


def _schedule_queued_input_dispatch(runtime: Any, session_id: str, *, reason: str) -> None:
    normalized = str(session_id or "").strip()
    if not normalized:
        return
    host = runtime.harness_runtime.single_agent_runtime_host
    if not hasattr(host, "queued_user_inputs"):
        return
    host.spawn_control_background_task(
        lambda: _dispatch_next_queued_input(runtime, normalized, reason=reason),
        name=f"queued-input-dispatch:{normalized}",
    )


async def _dispatch_next_queued_input(runtime: Any, session_id: str, *, reason: str) -> RuntimeRun | None:
    host = runtime.harness_runtime.single_agent_runtime_host
    store = getattr(host, "queued_user_inputs", None)
    if store is None:
        return None
    normalized = str(session_id or "").strip()
    if not normalized:
        return None
    await asyncio.to_thread(store.reset_stale_dispatching, normalized)
    for _attempt in range(8):
        queued_items = [
            item
            for item in await asyncio.to_thread(store.list_session, normalized, include_terminal=False)
            if item.status == "queued"
        ]
        if not queued_items:
            return None
        next_item = queued_items[0]
        if has_active_primary_chat_run(host, session_id=normalized, terminal_statuses=TERMINAL_RUN_STATUSES):
            return None
        if next_item.input_policy == "auto":
            admission = _queued_input_admission_target(runtime, session_id=normalized)
            if str(admission.get("input_policy") or "").strip().lower() == "steer":
                retargeted = await asyncio.to_thread(
                    store.retarget_for_dispatch,
                    normalized,
                    next_item.queue_item_id,
                    input_policy="steer",
                    expected_active_turn_id=str(admission.get("expected_active_turn_id") or ""),
                    task_environment_id=str(admission.get("task_environment_id") or ""),
                )
                if retargeted is None:
                    continue
                return None
            claimed = await asyncio.to_thread(store.claim_next, normalized, policy="auto")
            if claimed is None:
                continue
            return await _dispatch_claimed_queued_input(runtime, claimed, reason=reason)
        steer_allowed, denied_reason = validate_queued_steer(host, next_item)
        if steer_allowed:
            return None
        claimed = await asyncio.to_thread(store.claim_next, normalized, policy="steer")
        if claimed is not None:
            await asyncio.to_thread(store.mark_failed, normalized, claimed.queue_item_id, reason=denied_reason or "queued_steer_not_dispatchable")
        continue
    return None


async def _dispatch_claimed_queued_input(runtime: Any, item: QueuedUserInput, *, reason: str) -> RuntimeRun | None:
    host = runtime.harness_runtime.single_agent_runtime_host
    try:
        await asyncio.to_thread(
            assert_optional_session_scope,
            runtime.session_manager,
            item.session_id,
            dict(item.session_scope or {}),
        )
        request = _request_from_queued_input(item, reason=reason)
        run = _create_and_schedule_run(runtime, request)
        await asyncio.to_thread(host.queued_user_inputs.mark_dispatched, item.session_id, item.queue_item_id, stream_run_id=run.stream_run_id)
        return run
    except Exception as exc:
        logger.exception("Failed to dispatch queued chat input.", extra={"queue_item_id": item.queue_item_id, "session_id": item.session_id})
        await asyncio.to_thread(
            host.queued_user_inputs.mark_failed,
            item.session_id,
            item.queue_item_id,
            reason=str(exc) or "queued_input_dispatch_failed",
        )
        return None


def _request_from_queued_input(item: QueuedUserInput, *, reason: str) -> HarnessRuntimeRequest:
    return HarnessRuntimeRequest(
        session_id=item.session_id,
        message=item.content,
        client_message_id=str(item.client_message_id or ""),
        explicit_subtasks=[dict(entry) for entry in list(item.explicit_subtasks or []) if isinstance(entry, dict)],
        runtime_profile={
            "queued_input_id": item.queue_item_id,
            "queued_client_message_id": item.client_message_id,
            "queue_dispatch_reason": str(reason or ""),
        },
        environment_binding=dict(item.environment_binding or {}),
        runtime_contract=dict(item.runtime_contract or {}),
        model_selection=dict(item.model_selection or {}),
        attachments=[dict(entry) for entry in list(item.attachments or []) if isinstance(entry, dict)],
        permission_mode=str(item.permission_mode or ""),
        expected_active_turn_id=str(item.expected_active_turn_id or "") if item.input_policy == "steer" else "",
        active_turn_input_policy=str(item.input_policy or "auto"),
        editor_context=dict(item.editor_context or {}),
    )


async def _run_chat_to_event_log(runtime: Any, run: RuntimeRun, request: HarnessRuntimeRequest) -> None:
    host = runtime.harness_runtime.single_agent_runtime_host
    registry = host.run_registry
    replay = host.stream_replay
    terminal_event = ""
    bridge_context: ChatTaskBridgeContext | None = None
    turn_context: PublicTurnOutputContext | None = None
    projection_lifecycle = ProjectionLifecycleState()
    current = _safe_mark_run_running(registry, run)
    try:
        start_data = {"status": "running"}
        attach_public_projection_frame(
            "chat_run_started",
            start_data,
            session_id=request.session_id,
            sequence=0,
        )
        previous_offset = _latest_public_event_offset(current)
        start_event = replay.append_public_event(
            current,
            public_event_type="chat_run_started",
            data=start_data,
        )
        current = _safe_mark_run_event(registry, current, latest_event_offset=start_event.offset, status="running")
        await _allow_public_stream_flush(previous_offset, current)
        async for event in runtime.harness_runtime.astream(request):
            event_type = str(event.get("type", "message") or "message")
            raw_refs = _runtime_run_refs_from_event(event)
            event_task_run_id = raw_refs.get("task_run_id", "")
            runtime_turn_run_id = raw_refs.get("turn_run_id", "")
            runtime_active_turn_id = raw_refs.get("active_turn_id", "")
            if turn_context is None:
                created_turn_context = _public_turn_context_from_event(
                    run=run,
                    request=request,
                    event=event,
                    public_sequence_started_at=int(getattr(current, "latest_event_offset", -1) or -1) + 1,
                )
                if created_turn_context is not None:
                    turn_context = created_turn_context
                    previous_offset = _latest_public_event_offset(current)
                    current = _append_chat_public_event(
                        registry=registry,
                        replay=replay,
                        current=current,
                        public_event_type=CHAT_TURN_BOUND_EVENT,
                        data=_public_turn_context_event_data(turn_context),
                        session_id=request.session_id,
                        projection_lifecycle=projection_lifecycle,
                        runtime_turn_run_id=turn_context.turn_run_id,
                        runtime_active_turn_id=turn_context.turn_id,
                        public_anchor=turn_context.anchor(),
                    )
                    await _allow_public_stream_flush(previous_offset, current)
            projections = project_public_stream_event(event_type, event)
            if not projections:
                continue
            for public_event_type, data in projections:
                if turn_context is not None:
                    _apply_turn_context_to_public_data(data, turn_context)
                if event_task_run_id:
                    data.setdefault("runtime_task_run_id", event_task_run_id)
                    data.setdefault("task_run_id", event_task_run_id)
                if runtime_turn_run_id:
                    data.setdefault("turn_run_id", runtime_turn_run_id)
                if runtime_active_turn_id:
                    data.setdefault("active_turn_id", runtime_active_turn_id)
                if turn_context is None and public_event_type in TURN_CONTEXT_REQUIRED_PUBLIC_EVENTS:
                    previous_offset = _latest_public_event_offset(current)
                    current = _append_chat_public_event(
                        registry=registry,
                        replay=replay,
                        current=current,
                        public_event_type="runtime_status",
                        data={
                            "title": "公开投影缺少本轮锚点",
                            "detail": "正文、工具或提交事件在 PublicTurnOutputContext 建立前到达，已拒绝进入主视图。",
                            "state": "failed",
                            "runtime_event_id": _stream_event_id(event),
                            "source_event_type": event_type,
                        },
                        session_id=request.session_id,
                        projection_lifecycle=projection_lifecycle,
                        runtime_task_run_id=event_task_run_id,
                        runtime_turn_run_id=runtime_turn_run_id,
                        runtime_active_turn_id=runtime_active_turn_id,
                    )
                    await _allow_public_stream_flush(previous_offset, current)
                    continue
                if _is_task_origin_bound_public_event(public_event_type, data):
                    bridged_task_run_id = _task_run_id_from_public_data(data) or event_task_run_id
                    if turn_context is None:
                        host.record_chat_turn_run_runtime_interruption_best_effort(
                            current,
                            code="task_origin_binding_context_missing",
                            reason="Task origin binding arrived before a public turn context was available.",
                            orphaned_by="api.chat.run_chat_to_event_log.task_origin_binding_context_missing",
                        )
                        return
                    origin_public_anchor = {**turn_context.anchor(), "task_run_id": bridged_task_run_id}
                    previous_offset = _latest_public_event_offset(current)
                    current = _append_chat_public_event(
                        registry=registry,
                        replay=replay,
                        current=current,
                        public_event_type=public_event_type,
                        data=data,
                        session_id=request.session_id,
                        projection_lifecycle=projection_lifecycle,
                        runtime_task_run_id=bridged_task_run_id,
                        runtime_turn_run_id=runtime_turn_run_id or turn_context.turn_run_id,
                        runtime_active_turn_id=runtime_active_turn_id or turn_context.turn_id,
                        public_anchor=origin_public_anchor,
                    )
                    await _allow_public_stream_flush(previous_offset, current)
                    if bridge_context is None:
                        bridge_context = _chat_task_bridge_context_from_handoff(
                            run=run,
                            request=request,
                            turn_context=turn_context,
                            public_data=data,
                            source_event=event,
                            task_run_id=bridged_task_run_id,
                            public_sequence_base=int(getattr(current, "latest_event_offset", -1) or -1) + 1,
                        )
                        previous_offset = _latest_public_event_offset(current)
                        current = _append_chat_public_event(
                            registry=registry,
                            replay=replay,
                            current=current,
                            public_event_type=TASK_BRIDGE_STARTED_EVENT,
                            data=_task_bridge_started_event_data(bridge_context),
                            session_id=request.session_id,
                            projection_lifecycle=projection_lifecycle,
                            runtime_task_run_id=bridge_context.task_run_id,
                            runtime_turn_run_id=bridge_context.turn_run_id,
                            runtime_active_turn_id=bridge_context.turn_id,
                            public_anchor=bridge_context.anchor(),
                        )
                        await _allow_public_stream_flush(previous_offset, current)
                        current = _safe_update_run(
                            registry,
                            run.stream_run_id,
                            fallback=current,
                            status="running",
                            terminal_event="",
                            diagnostics={
                                "runtime_task_run_id": bridge_context.task_run_id,
                                "runtime_turn_run_id": bridge_context.turn_run_id,
                                "active_turn_id": bridge_context.turn_id,
                                "task_bridge_id": bridge_context.bridge_id,
                                "chat_stream_bridge": "task_run",
                                "task_origin_binding": dict(data.get("task_origin_binding") or {}),
                            },
                        )
                    continue
                previous_offset = _latest_public_event_offset(current)
                public_anchor = (
                    bridge_context.anchor()
                    if bridge_context is not None and event_task_run_id == bridge_context.task_run_id
                    else (turn_context.anchor() if turn_context is not None else None)
                )
                current = _append_chat_public_event(
                    registry=registry,
                    replay=replay,
                    current=current,
                    public_event_type=public_event_type,
                    data=data,
                    session_id=request.session_id,
                    projection_lifecycle=projection_lifecycle,
                    runtime_task_run_id=event_task_run_id,
                    runtime_turn_run_id=runtime_turn_run_id or (turn_context.turn_run_id if turn_context else ""),
                    runtime_active_turn_id=runtime_active_turn_id or (turn_context.turn_id if turn_context else ""),
                    public_anchor=public_anchor,
                )
                await _allow_public_stream_flush(previous_offset, current)
                terminal_event = public_event_type if public_event_type in TERMINAL_STREAM_EVENTS else terminal_event
                if public_event_type in TERMINAL_STREAM_EVENTS:
                    break
            if terminal_event:
                break
        if bridge_context is not None and not terminal_event:
            current = await _bridge_task_run_to_chat_stream(
                runtime,
                run,
                current,
                request=request,
                bridge_context=bridge_context,
                projection_lifecycle=projection_lifecycle,
            )
            terminal_event = str(getattr(current, "terminal_event", "") or "")
    except asyncio.CancelledError:
        logger.info("Chat run background task was cancelled.", extra={"stream_run_id": run.stream_run_id})
        current = registry.get_run(run.stream_run_id) or current
        host.record_chat_turn_run_runtime_interruption_best_effort(
            current,
            code="stream_cancelled",
            reason="Chat run background task was cancelled.",
            orphaned_by="api.chat.run_chat_to_event_log.cancelled",
        )
        raise
    except Exception as exc:
        logger.exception("Chat run failed before terminal event.", extra={"stream_run_id": run.stream_run_id})
        current = registry.get_run(run.stream_run_id) or current
        if _bridge_context_requires_task_bridge_terminal(runtime, bridge_context):
            host.record_chat_turn_run_runtime_interruption_best_effort(
                current,
                code="projection_stream_exception",
                reason=str(exc) or "Chat stream failed.",
                orphaned_by="api.chat.run_chat_to_event_log.bridge_exception",
            )
            return
        host.record_chat_turn_run_runtime_interruption_best_effort(
            current,
            code="stream_exception",
            reason=str(exc) or "Chat stream failed.",
            orphaned_by="api.chat.run_chat_to_event_log.exception",
        )
        return
    if not terminal_event:
        current = registry.get_run(run.stream_run_id) or current
        if _bridge_context_requires_task_bridge_terminal(runtime, bridge_context):
            host.record_chat_turn_run_runtime_interruption_best_effort(
                current,
                code="projection_stream_missing_task_bridge_terminal",
                reason="Chat stream ended before the explicit task bridge emitted a terminal event.",
                orphaned_by="api.chat.run_chat_to_event_log.task_bridge_missing_terminal",
            )
            return
        host.record_chat_turn_run_runtime_interruption_best_effort(
            current,
            code="missing_terminal_event",
            reason="Chat stream ended without a terminal event.",
            orphaned_by="api.chat.run_chat_to_event_log.missing_terminal",
        )


def _append_chat_public_event(
    *,
    registry: Any,
    replay: Any,
    current: RuntimeRun,
    public_event_type: str,
    data: dict[str, Any],
    session_id: str,
    projection_lifecycle: ProjectionLifecycleState,
    runtime_task_run_id: str = "",
    runtime_turn_run_id: str = "",
    runtime_active_turn_id: str = "",
    public_anchor: dict[str, Any] | None = None,
) -> RuntimeRun:
    payload = dict(data or {})
    payload.setdefault("stream_run_id", current.stream_run_id)
    payload.setdefault("runtime_run_id", current.stream_run_id)
    anchor = dict(public_anchor or {})
    if anchor:
        payload["session_id"] = str(anchor.get("session_id") or session_id)
        payload["turn_id"] = str(anchor.get("turn_id") or "")
        payload["active_turn_id"] = str(anchor.get("turn_id") or "")
        payload["turn_run_id"] = str(anchor.get("turn_run_id") or "")
        payload["message_id"] = str(anchor.get("message_id") or anchor.get("message_ref") or "")
        payload["message_ref"] = str(anchor.get("message_ref") or anchor.get("message_id") or "")
        if str(anchor.get("task_run_id") or "").strip():
            runtime_task_run_id = runtime_task_run_id or str(anchor.get("task_run_id") or "").strip()
    if runtime_task_run_id:
        payload.setdefault("runtime_task_run_id", runtime_task_run_id)
        payload.setdefault("task_run_id", runtime_task_run_id)
    if runtime_turn_run_id:
        payload.setdefault("turn_run_id", runtime_turn_run_id)
    if runtime_active_turn_id:
        payload.setdefault("active_turn_id", runtime_active_turn_id)
        payload.setdefault("turn_id", runtime_active_turn_id)
    if _is_model_wait_placeholder_public_data(public_event_type, payload):
        return current
    if not projection_lifecycle.should_emit_public_event(public_event_type, payload):
        return current
    next_sequence = int(getattr(current, "latest_event_offset", -1) or -1) + 1
    if event_requires_public_projection(public_event_type):
        attach_public_projection_frame(
            public_event_type,
            payload,
            session_id=session_id,
            sequence=next_sequence,
            lifecycle_state=projection_lifecycle,
            public_anchor=public_anchor,
        )
    replay_payload = public_replay_stream_data(public_event_type, payload)
    logged = replay.append_public_event(current, public_event_type=public_event_type, data=replay_payload)
    diagnostics = {
        key: value
        for key, value in {
            "runtime_task_run_id": runtime_task_run_id,
            "runtime_turn_run_id": runtime_turn_run_id,
            "active_turn_id": runtime_active_turn_id,
            "public_anchor_turn_id": str(anchor.get("turn_id") or ""),
            "public_anchor_task_run_id": str(anchor.get("task_run_id") or ""),
        }.items()
        if value
    }
    if public_event_type != "error":
        diagnostics.update({"orphaned_by": None, "reason": None, "cancelled": None})
    return _safe_mark_run_event(
        registry,
        current,
        latest_event_offset=logged.offset,
        status=_status_for_public_event(public_event_type, payload),
        terminal_event=public_event_type if public_event_type in TERMINAL_STREAM_EVENTS else "",
        diagnostics=diagnostics or None,
    )


def _is_model_wait_placeholder_public_data(public_event_type: str, data: dict[str, Any]) -> bool:
    if str(public_event_type or "").strip() != "runtime_status":
        return False
    item_id = str(data.get("item_id") or "").strip()
    return (
        str(data.get("presentation_source") or "").strip() == "runtime.model_wait"
        or str(data.get("source_task_event_type") or "").strip() == "task_model_action_wait_heartbeat"
        or str(data.get("status_kind") or "").strip() == "model_wait_placeholder"
        or item_id.startswith("model-wait:")
    )


def _public_turn_context_from_event(
    *,
    run: RuntimeRun,
    request: HarnessRuntimeRequest,
    event: dict[str, Any],
    public_sequence_started_at: int = 0,
) -> PublicTurnOutputContext | None:
    event_type = str(event.get("type") or "").strip()
    turn_anchor_event_types = {
        ASSISTANT_PUBLIC_FEEDBACK_EVENT,
        "input_commit_gate",
        "current_work_boundary_decided",
        "runtime_branch_decided",
        "harness_run_started",
        "single_agent_turn_started",
        "model_action_request",
        "model_action_admission",
        "model_action_admission_checked",
        "task_origin_bound",
        "task_run_lifecycle_event",
    }
    if event_type not in turn_anchor_event_types:
        return None
    refs = _runtime_run_refs_from_event(event)
    diagnostics = dict(getattr(run, "diagnostics", {}) or {})
    agent_scope = dict(diagnostics.get("agent_run_scope") or {}) if isinstance(diagnostics.get("agent_run_scope"), dict) else {}
    turn_run_id = str(
        refs.get("turn_run_id")
        or diagnostics.get("runtime_turn_run_id")
        or diagnostics.get("turn_run_id")
        or agent_scope.get("turn_run_id")
        or ""
    ).strip()
    turn_id = str(
        refs.get("active_turn_id")
        or event.get("turn_id")
        or event.get("active_turn_id")
        or diagnostics.get("active_turn_id")
        or agent_scope.get("turn_id")
        or _turn_id_from_turn_run_id(turn_run_id)
    ).strip()
    if not turn_run_id or not turn_id:
        return None
    stream_ref = f"chat-turn:{run.stream_run_id}:{turn_run_id}"
    message_ref = assistant_message_ref(turn_id=turn_id, stream_ref=stream_ref)
    source_offset = _stream_event_offset(event)
    return PublicTurnOutputContext(
        context_id=f"public-turn:{run.stream_run_id}:{turn_run_id}",
        stream_run_id=run.stream_run_id,
        session_id=request.session_id,
        turn_id=turn_id,
        turn_run_id=turn_run_id,
        assistant_message_ref=message_ref,
        source_turn_event_id=_stream_event_id(event),
        source_turn_event_offset=source_offset,
        public_sequence_started_at=public_sequence_started_at,
        created_at=_stream_event_created_at(event),
    )


def _public_turn_context_event_data(context: PublicTurnOutputContext) -> dict[str, Any]:
    return {
        "context_id": context.context_id,
        "status": "bound",
        "stream_run_id": context.stream_run_id,
        "session_id": context.session_id,
        "turn_id": context.turn_id,
        "active_turn_id": context.turn_id,
        "turn_run_id": context.turn_run_id,
        "message_id": context.assistant_message_ref,
        "message_ref": context.assistant_message_ref,
        "source_turn_event_id": context.source_turn_event_id,
        "source_turn_event_offset": context.source_turn_event_offset,
        "runtime_event_id": context.source_turn_event_id,
        "public_sequence_started_at": context.public_sequence_started_at,
        "created_at": context.created_at,
    }


def _apply_turn_context_to_public_data(data: dict[str, Any], context: PublicTurnOutputContext) -> None:
    data.setdefault("stream_run_id", context.stream_run_id)
    data.setdefault("session_id", context.session_id)
    data.setdefault("turn_id", context.turn_id)
    data.setdefault("active_turn_id", context.turn_id)
    data.setdefault("turn_run_id", context.turn_run_id)
    data.setdefault("message_id", context.assistant_message_ref)
    data.setdefault("message_ref", context.assistant_message_ref)


def _chat_task_bridge_context_from_handoff(
    *,
    run: RuntimeRun,
    request: HarnessRuntimeRequest,
    turn_context: PublicTurnOutputContext,
    public_data: dict[str, Any],
    source_event: dict[str, Any],
    task_run_id: str,
    public_sequence_base: int,
) -> ChatTaskBridgeContext:
    normalized_task_run_id = str(task_run_id or "").strip()
    source_offset = _stream_event_offset(source_event)
    return ChatTaskBridgeContext(
        bridge_id=f"task-bridge:{run.stream_run_id}:{normalized_task_run_id}",
        stream_run_id=run.stream_run_id,
        event_log_id=normalized_task_run_id,
        session_id=request.session_id,
        turn_id=turn_context.turn_id,
        turn_run_id=turn_context.turn_run_id,
        task_run_id=normalized_task_run_id,
        assistant_message_ref=turn_context.assistant_message_ref,
        source_handoff_event_id=_stream_event_id(source_event) or str(public_data.get("runtime_event_id") or ""),
        source_handoff_event_offset=source_offset,
        task_event_start_offset=0,
        public_sequence_base=public_sequence_base,
        created_at=_stream_event_created_at(source_event),
    )


def _task_bridge_started_event_data(context: ChatTaskBridgeContext) -> dict[str, Any]:
    return {
        "bridge_id": context.bridge_id,
        "status": "bound",
        "stream_run_id": context.stream_run_id,
        "event_log_id": context.event_log_id,
        "session_id": context.session_id,
        "turn_id": context.turn_id,
        "active_turn_id": context.turn_id,
        "turn_run_id": context.turn_run_id,
        "task_run_id": context.task_run_id,
        "runtime_task_run_id": context.task_run_id,
        "message_id": context.assistant_message_ref,
        "message_ref": context.assistant_message_ref,
        "source_handoff_event_id": context.source_handoff_event_id,
        "source_handoff_event_offset": context.source_handoff_event_offset,
        "runtime_event_id": context.source_handoff_event_id,
        "task_event_start_offset": context.task_event_start_offset,
        "public_sequence_base": context.public_sequence_base,
        "created_at": context.created_at,
    }


async def _bridge_task_run_to_chat_stream(
    runtime: Any,
    run: RuntimeRun,
    current: RuntimeRun,
    *,
    request: HarnessRuntimeRequest,
    bridge_context: ChatTaskBridgeContext,
    projection_lifecycle: ProjectionLifecycleState,
) -> RuntimeRun:
    host = runtime.harness_runtime.single_agent_runtime_host
    registry = host.run_registry
    replay = host.stream_replay
    normalized_task_run_id = str(bridge_context.task_run_id or "").strip()
    if not normalized_task_run_id:
        return current
    subscription = host.event_log.subscribe(run_id=normalized_task_run_id)
    latest_task_offset = int(bridge_context.task_event_start_offset or 0) - 1
    output_observed = False
    commit_observed = False
    try:
        current = _safe_update_run(
            registry,
            run.stream_run_id,
            fallback=current,
            status="running",
            terminal_event="",
            diagnostics={
                "runtime_task_run_id": normalized_task_run_id,
                "runtime_turn_run_id": bridge_context.turn_run_id,
                "active_turn_id": bridge_context.turn_id,
                "task_bridge_id": bridge_context.bridge_id,
                "chat_stream_bridge": "task_run",
            },
        )
        while True:
            progressed = False
            for task_event in host.event_log.list_events(normalized_task_run_id):
                if int(getattr(task_event, "offset", -1) or -1) <= latest_task_offset:
                    continue
                latest_task_offset = int(getattr(task_event, "offset", -1) or -1)
                progressed = True
                previous_offset = _latest_public_event_offset(current)
                current, terminal, terminal_output_state = _project_task_runtime_event_to_chat(
                    runtime,
                    run,
                    current,
                    request=request,
                    task_event=task_event,
                    bridge_context=bridge_context,
                    projection_lifecycle=projection_lifecycle,
                    output_observed=output_observed,
                    commit_observed=commit_observed,
                )
                await _allow_public_stream_flush(previous_offset, current)
                output_observed = output_observed or terminal_output_state.get("output_observed", False)
                commit_observed = commit_observed or terminal_output_state.get("commit_observed", False)
                if terminal:
                    return current
            if progressed:
                continue
            try:
                event = await asyncio.wait_for(subscription.queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                current = _safe_update_run(
                    registry,
                    run.stream_run_id,
                    fallback=current,
                    status="running",
                    terminal_event="",
                    diagnostics={
                        "runtime_task_run_id": normalized_task_run_id,
                        "runtime_turn_run_id": bridge_context.turn_run_id,
                        "active_turn_id": bridge_context.turn_id,
                        "task_bridge_id": bridge_context.bridge_id,
                        "chat_stream_bridge": "task_run",
                        "bridged_task_event_offset": latest_task_offset,
                    },
                )
                continue
            if str(getattr(event, "run_id", "") or "") != normalized_task_run_id:
                continue
    finally:
        host.event_log.unsubscribe(subscription)


def _project_task_runtime_event_to_chat(
    runtime: Any,
    run: RuntimeRun,
    current: RuntimeRun,
    *,
    request: HarnessRuntimeRequest,
    task_event: Any,
    bridge_context: ChatTaskBridgeContext,
    projection_lifecycle: ProjectionLifecycleState,
    output_observed: bool = False,
    commit_observed: bool = False,
) -> tuple[RuntimeRun, bool, dict[str, bool]]:
    host = runtime.harness_runtime.single_agent_runtime_host
    registry = host.run_registry
    replay = host.stream_replay
    stream_event = _runtime_event_to_stream_event(host, task_event)
    event_type = str(stream_event.get("type") or "").strip()
    event_run_id = str(getattr(task_event, "run_id", "") or "").strip()
    terminal_output_state = {"output_observed": bool(output_observed), "commit_observed": bool(commit_observed)}
    if event_run_id and event_run_id != bridge_context.task_run_id:
        current = _append_chat_public_event(
            registry=registry,
            replay=replay,
            current=current,
            public_event_type="runtime_status",
            data={
                "title": "任务桥接事件被拒绝",
                "detail": "task event run_id 与当前桥接上下文不一致，已作为协议诊断记录。",
                "state": "failed",
                "runtime_event_id": str(getattr(task_event, "event_id", "") or ""),
                "source_task_event_id": str(getattr(task_event, "event_id", "") or ""),
                "source_task_event_offset": int(getattr(task_event, "offset", -1) or -1),
                "source_task_event_type": event_type,
            },
            session_id=request.session_id,
            projection_lifecycle=projection_lifecycle,
            runtime_task_run_id=bridge_context.task_run_id,
            runtime_turn_run_id=bridge_context.turn_run_id,
            runtime_active_turn_id=bridge_context.turn_id,
            public_anchor=bridge_context.anchor(),
        )
        return current, False, terminal_output_state
    if event_type in TASK_BRIDGE_PUBLIC_EVENT_TYPES:
        for public_event_type, data in project_public_stream_event(event_type, stream_event):
            _apply_bridge_context_to_public_data(data, bridge_context, task_event=task_event, source_event_type=event_type)
            if public_event_type in {ASSISTANT_TEXT_FINAL_EVENT, ASSISTANT_STREAM_REPAIR_EVENT}:
                terminal_output_state["output_observed"] = True
            if public_event_type in {
                SESSION_OUTPUT_COMMIT_ACK_EVENT,
                SESSION_OUTPUT_COMMIT_FAILED_EVENT,
                SESSION_OUTPUT_COMMIT_SKIPPED_EVENT,
            }:
                terminal_output_state["commit_observed"] = True
            current = _append_chat_public_event(
                registry=registry,
                replay=replay,
                current=current,
                public_event_type=public_event_type,
                data=data,
                session_id=request.session_id,
                projection_lifecycle=projection_lifecycle,
                runtime_task_run_id=bridge_context.task_run_id,
                runtime_turn_run_id=bridge_context.turn_run_id,
                runtime_active_turn_id=bridge_context.turn_id,
                public_anchor=bridge_context.anchor(),
            )
    if event_type in TASK_BRIDGE_TERMINAL_EVENT_TYPES:
        current = _append_task_bridge_terminal_from_event(
            runtime,
            run,
            current,
            request=request,
            stream_event=stream_event,
            projection_lifecycle=projection_lifecycle,
            bridge_context=bridge_context,
            task_event=task_event,
            output_observed=terminal_output_state["output_observed"],
            commit_observed=terminal_output_state["commit_observed"],
        )
        return current, True, terminal_output_state
    return current, False, terminal_output_state


def _append_task_bridge_terminal_from_event(
    runtime: Any,
    run: RuntimeRun,
    current: RuntimeRun,
    *,
    request: HarnessRuntimeRequest,
    stream_event: dict[str, Any],
    projection_lifecycle: ProjectionLifecycleState,
    bridge_context: ChatTaskBridgeContext,
    task_event: Any,
    output_observed: bool,
    commit_observed: bool,
) -> RuntimeRun:
    context = _task_terminal_context_from_stream_event(stream_event, fallback_task_run_id=bridge_context.task_run_id)
    return _append_task_bridge_terminal(
        runtime,
        run,
        current,
        request=request,
        context=context,
        projection_lifecycle=projection_lifecycle,
        bridge_context=bridge_context,
        task_event=task_event,
        output_observed=output_observed,
        commit_observed=commit_observed,
    )


def _append_task_bridge_terminal(
    runtime: Any,
    run: RuntimeRun,
    current: RuntimeRun,
    *,
    request: HarnessRuntimeRequest,
    context: dict[str, Any],
    projection_lifecycle: ProjectionLifecycleState,
    bridge_context: ChatTaskBridgeContext,
    task_event: Any | None,
    output_observed: bool,
    commit_observed: bool,
) -> RuntimeRun:
    host = runtime.harness_runtime.single_agent_runtime_host
    registry = host.run_registry
    replay = host.stream_replay
    task_run_id = bridge_context.task_run_id
    turn_run_id = bridge_context.turn_run_id
    active_turn_id = bridge_context.turn_id
    source_task_event_id = str(getattr(task_event, "event_id", "") or "").strip()
    source_task_event_offset = int(getattr(task_event, "offset", -1) or -1) if task_event is not None else -1
    if output_observed and not commit_observed:
        current = _append_chat_public_event(
            registry=registry,
            replay=replay,
            current=current,
            public_event_type=SESSION_OUTPUT_COMMIT_FAILED_EVENT,
            data={
                "state": "failed",
                "status": "failed",
                "turn_id": active_turn_id,
                "turn_run_id": turn_run_id,
                "task_run_id": task_run_id,
                "message_id": bridge_context.assistant_message_ref,
                "message_ref": bridge_context.assistant_message_ref,
                "reason": "task_terminal_final_without_commit_event",
                "error": "处理失败",
                "summary": "task_terminal_final_without_commit_event",
                "runtime_event_id": source_task_event_id,
                "source_task_event_id": source_task_event_id,
                "source_task_event_offset": source_task_event_offset,
            },
            session_id=request.session_id,
            projection_lifecycle=projection_lifecycle,
            runtime_task_run_id=task_run_id,
            runtime_turn_run_id=turn_run_id,
            runtime_active_turn_id=active_turn_id,
            public_anchor=bridge_context.anchor(),
        )
    raw_task_status = str(context.get("status") or "completed").strip() or "completed"
    raw_terminal_reason = str(context.get("terminal_reason") or raw_task_status or "completed").strip()
    public_terminal_reason_value = public_terminal_reason(raw_terminal_reason)
    terminal_bridge_data = {
        "bridge_id": bridge_context.bridge_id,
        "status": raw_task_status,
        "stream_run_id": bridge_context.stream_run_id,
        "session_id": bridge_context.session_id,
        "turn_id": active_turn_id,
        "active_turn_id": active_turn_id,
        "turn_run_id": turn_run_id,
        "task_run_id": task_run_id,
        "runtime_task_run_id": task_run_id,
        "message_id": bridge_context.assistant_message_ref,
        "message_ref": bridge_context.assistant_message_ref,
        "terminal_reason": public_terminal_reason_value,
        "completion_state": raw_task_status,
        "source_task_event_id": source_task_event_id,
        "source_task_event_offset": source_task_event_offset,
        "runtime_event_id": source_task_event_id,
        "commit_observed": bool(commit_observed),
        "created_at": time.time(),
    }
    current = _append_chat_public_event(
        registry=registry,
        replay=replay,
        current=current,
        public_event_type=TASK_BRIDGE_TERMINAL_EVENT,
        data=terminal_bridge_data,
        session_id=request.session_id,
        projection_lifecycle=projection_lifecycle,
        runtime_task_run_id=task_run_id,
        runtime_turn_run_id=turn_run_id,
        runtime_active_turn_id=active_turn_id,
        public_anchor=bridge_context.anchor(),
    )
    status = _public_turn_status_for_task_status(raw_task_status)
    terminal_data = turn_completed_data(
        "task_run_lifecycle_finished",
        {
            "status": status,
            "turn_run_id": turn_run_id,
            "task_run_id": task_run_id,
            "terminal_reason": public_terminal_reason_value,
            "completion_state": raw_task_status,
            "error": "处理失败" if status == "failed" else "",
            "runtime_event_id": source_task_event_id,
            "source_task_event_id": source_task_event_id,
            "source_task_event_offset": source_task_event_offset,
        },
    )
    if active_turn_id:
        terminal_data["active_turn_id"] = active_turn_id
        terminal_data["turn_id"] = active_turn_id
    return _append_chat_public_event(
        registry=registry,
        replay=replay,
        current=current,
        public_event_type=TURN_COMPLETED_EVENT,
        data=terminal_data,
        session_id=request.session_id,
        projection_lifecycle=projection_lifecycle,
        runtime_task_run_id=task_run_id,
        runtime_turn_run_id=turn_run_id,
        runtime_active_turn_id=active_turn_id,
        public_anchor=bridge_context.anchor(),
    )


def _runtime_event_to_stream_event(host: Any, event: Any) -> dict[str, Any]:
    raw = event.to_dict() if hasattr(event, "to_dict") else dict(event or {})
    try:
        hydrated = host.event_log.payload_store.hydrate_event_payload(raw)
    except Exception:
        hydrated = raw
    event_type = str(hydrated.get("event_type") or getattr(event, "event_type", "") or "").strip()
    return {"type": event_type, "event": hydrated}


def _apply_bridge_context_to_public_data(
    data: dict[str, Any],
    context: ChatTaskBridgeContext,
    *,
    task_event: Any,
    source_event_type: str,
) -> None:
    source_task_event_id = str(getattr(task_event, "event_id", "") or "").strip()
    source_task_event_offset = int(getattr(task_event, "offset", -1) or -1)
    data["session_id"] = context.session_id
    data["stream_run_id"] = context.stream_run_id
    data["turn_id"] = context.turn_id
    data["active_turn_id"] = context.turn_id
    data["turn_run_id"] = context.turn_run_id
    data["task_run_id"] = context.task_run_id
    data["runtime_task_run_id"] = context.task_run_id
    data["message_id"] = context.assistant_message_ref
    data["message_ref"] = context.assistant_message_ref
    data.setdefault("runtime_event_id", source_task_event_id)
    data["source_task_event_id"] = source_task_event_id
    data["source_task_event_offset"] = source_task_event_offset
    data["source_task_event_type"] = str(source_event_type or "").strip()
    data["bridge_id"] = context.bridge_id


def _bridge_context_requires_task_bridge_terminal(runtime: Any, bridge_context: ChatTaskBridgeContext | None) -> bool:
    if bridge_context is None:
        return False
    task_run_id = str(bridge_context.task_run_id or "").strip()
    if not task_run_id:
        return False
    try:
        host = runtime.harness_runtime.single_agent_runtime_host
        task_run = host.state_index.get_task_run(task_run_id)
    except Exception:
        return False
    return _task_run_requires_task_bridge_terminal(task_run, runtime_host=host)


def _task_run_requires_task_bridge_terminal(task_run: Any, *, runtime_host: Any) -> bool:
    if task_run is None or is_stopped_or_terminal_task_run(task_run, runtime_host=runtime_host):
        return False
    status = str(getattr(task_run, "status", "") or (task_run.get("status") if isinstance(task_run, dict) else "") or "").strip().lower()
    diagnostics = _record(getattr(task_run, "diagnostics", {}) if not isinstance(task_run, dict) else task_run.get("diagnostics"))
    allocation = _record(diagnostics.get("resource_allocation"))
    if status == "admitted":
        return False
    if (
        str(allocation.get("allocated_by") or "").strip() == "request_task_run"
        and allocation.get("executor_scheduled") is False
    ):
        return False
    return True


def _task_terminal_context_from_stream_event(stream_event: dict[str, Any], *, fallback_task_run_id: str = "") -> dict[str, Any]:
    raw_event = _record(stream_event.get("event"))
    payload = _record(raw_event.get("payload"))
    task_run = _record(payload.get("task_run"))
    lifecycle = _record(payload.get("lifecycle"))
    return _task_terminal_context_from_task_run(
        task_run,
        lifecycle=lifecycle,
        fallback_task_run_id=fallback_task_run_id or str(raw_event.get("run_id") or ""),
    )


def _task_terminal_context_from_task_run(
    task_run: dict[str, Any],
    *,
    lifecycle: dict[str, Any] | None = None,
    fallback_task_run_id: str = "",
) -> dict[str, Any]:
    task = _record(task_run)
    lifecycle_payload = _record(lifecycle)
    task_run_id = str(task.get("task_run_id") or lifecycle_payload.get("task_run_id") or fallback_task_run_id or "").strip()
    status = str(task.get("status") or lifecycle_payload.get("status") or "").strip().lower()
    terminal_reason = str(task.get("terminal_reason") or lifecycle_payload.get("terminal_reason") or status or "completed").strip()
    return {
        "task_run_id": task_run_id,
        "status": status,
        "terminal_reason": terminal_reason,
        "error_summary": "处理失败" if status in {"failed", "blocked"} else "",
    }


def _public_turn_status_for_task_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status == "completed":
        return "completed"
    if status in {"aborted", "cancelled", "canceled", "stopped", "blocked"}:
        return "stopped"
    return "failed" if status else "failed"


def _is_task_origin_bound_public_event(public_event_type: str, data: dict[str, Any]) -> bool:
    if public_event_type != TASK_ORIGIN_BOUND_EVENT:
        return False
    binding = data.get("task_origin_binding")
    if not isinstance(binding, dict):
        return False
    return bool(_task_run_id_from_public_data(data) or str(binding.get("task_run_id") or "").strip().startswith("taskrun:"))


def _task_run_id_from_public_data(data: dict[str, Any]) -> str:
    for value in (data.get("task_run_id"), data.get("runtime_task_run_id")):
        normalized = str(value or "").strip()
        if normalized.startswith("taskrun:"):
            return normalized
    return ""


def _turn_id_from_turn_run_id(turn_run_id: str) -> str:
    normalized = str(turn_run_id or "").strip()
    if not normalized.startswith("turnrun:"):
        return ""
    candidate = normalized[len("turnrun:"):]
    return candidate if candidate.startswith("turn:") else ""


def _latest_public_event_offset(run: RuntimeRun) -> int:
    value = getattr(run, "latest_event_offset", -1)
    return -1 if value is None else int(value)


async def _allow_public_stream_flush(previous_offset: int, current: RuntimeRun) -> None:
    if _latest_public_event_offset(current) > int(previous_offset):
        await asyncio.sleep(0)


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


def _get_run_or_404(runtime: Any, stream_run_id: str) -> RuntimeRun:
    run = runtime.harness_runtime.single_agent_runtime_host.run_registry.get_run(stream_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="chat run not found")
    return run


def _validated_active_work_context(runtime: Any, session_id: str) -> Any | None:
    harness_runtime = getattr(runtime, "harness_runtime", None)
    resolver = getattr(harness_runtime, "_active_work_context_from_active_turn", None)
    if not callable(resolver):
        return None
    try:
        return resolver(session_id)
    except Exception:
        logger.debug("Failed to resolve validated active work context.", exc_info=True)
        return None


def _active_work_blocks_continuation(runtime: Any, session_id: str) -> bool:
    host = getattr(getattr(runtime, "harness_runtime", None), "single_agent_runtime_host", None)
    active_registry = getattr(host, "active_turn_registry", None)
    active_turn = None
    if active_registry is not None:
        try:
            active_turn = active_registry.snapshot(session_id)
        except Exception:
            active_turn = None
    if active_turn is not None and str(getattr(active_turn, "state", "") or "") == "interrupting":
        return False
    return _validated_active_work_context(runtime, session_id) is not None


def _validated_interrupt_mode(value: str) -> str:
    mode = str(value or "interrupt_for_resume").strip() or "interrupt_for_resume"
    if mode not in {"interrupt_for_resume", "hard_stop"}:
        raise HTTPException(status_code=400, detail="unsupported_interrupt_mode")
    return mode


def _session_context_recovery_status(runtime: Any, session_id: str) -> dict[str, Any]:
    normalized_session_id = str(session_id or "").strip()
    session_manager = getattr(runtime, "session_manager", None)
    loader = getattr(session_manager, "load_session_record", None)
    if not callable(loader):
        return {
            "available": False,
            "present": False,
            "fresh": False,
            "source": "",
            "reason": "session_manager_unavailable",
            "authority": "api.chat.context_recovery_status",
        }
    try:
        record = dict(loader(normalized_session_id) or {})
    except Exception:
        return {
            "available": False,
            "present": False,
            "fresh": False,
            "source": "",
            "reason": "session_record_unavailable",
            "authority": "api.chat.context_recovery_status",
        }
    raw_messages = [dict(item) for item in list(record.get("messages") or []) if isinstance(item, dict)]
    compacted = bool(str(record.get("compressed_context") or "").strip()) or _safe_float(record.get("provider_protocol_compaction_created_at")) > 0
    if raw_messages and not compacted:
        return {
            "available": True,
            "present": True,
            "fresh": True,
            "source": "full_session_history",
            "raw_message_count": len(raw_messages),
            "requires_context_recovery_package": False,
            "reason": "",
            "authority": "api.chat.context_recovery_status",
        }
    package = {}
    package_loader = getattr(getattr(runtime, "harness_runtime", None), "_context_recovery_package_for_session", None)
    if callable(package_loader):
        try:
            package = dict(package_loader(normalized_session_id, raw_messages=raw_messages) or {})
        except Exception:
            package = {}
    coverage = dict(package.get("coverage") or {}) if package else {}
    if package:
        return {
            "available": True,
            "present": True,
            "fresh": True,
            "source": str(package.get("source") or "context_recovery_package"),
            "package_schema_id": str(package.get("package_schema_id") or ""),
            "covered_message_count": int(coverage.get("covered_message_count") or 0),
            "covered_event_run_id": str(coverage.get("covered_event_run_id") or ""),
            "covered_event_offset_end": coverage.get("covered_event_offset_end"),
            "raw_message_count": len(raw_messages),
            "requires_context_recovery_package": compacted,
            "reason": "",
            "authority": "api.chat.context_recovery_status",
        }
    return {
        "available": False,
        "present": False,
        "fresh": False,
        "source": "",
        "raw_message_count": len(raw_messages),
        "requires_context_recovery_package": compacted,
        "reason": "context_recovery_package_missing_or_stale" if compacted else "session_history_missing",
        "authority": "api.chat.context_recovery_status",
    }


def _publish_chat_interruption_fact_signal(
    host: Any,
    *,
    run: RuntimeRun,
    mode: str,
    reason: str,
    stream_control: dict[str, Any],
    context_recovery_status: dict[str, Any],
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    gateway = getattr(host, "runtime_gateway", None)
    publish = getattr(gateway, "publish", None)
    if not callable(publish):
        return {
            "published": False,
            "reason": "runtime_gateway_unavailable",
            "authority": "api.chat.runtime_interruption.signal",
        }
    diagnostics = dict(run.diagnostics or {})
    active_turn = getattr(getattr(host, "active_turn_registry", None), "snapshot", lambda _session_id: None)(run.session_id)
    turn_id = str(getattr(active_turn, "turn_id", "") or diagnostics.get("turn_id") or diagnostics.get("active_turn_id") or "")
    turn_run_id = str(getattr(active_turn, "turn_run_id", "") or diagnostics.get("turn_run_id") or "")
    payload = {
        "signal_kind": "runtime_interruption_fact",
        "mode": mode,
        "reason": reason,
        "stream_run_id": run.stream_run_id,
        "session_id": run.session_id,
        "turn_id": turn_id,
        "turn_run_id": turn_run_id,
        "stream_control": dict(stream_control or {}),
        "context_recovery_status": dict(context_recovery_status or {}),
        "checkpoint": dict(checkpoint or {}),
        "contract": {
            "system_role": "carry_runtime_facts_and_feedback_only",
            "agent_role": "decide_next_action_from_facts",
            "decision_owner": "agent",
        },
        "authority": "api.chat.runtime_interruption.signal",
    }
    try:
        event = publish(
            run.event_log_id,
            signal_type="runtime.interruption.fact",
            scope=RuntimeSignalScope(
                session_id=run.session_id,
                turn_id=turn_id,
                turn_run_id=turn_run_id,
            ),
            source_authority="api.chat.runtime_interruption",
            payload=payload,
            visibility="model_visible",
            refs={
                "stream_run_ref": run.stream_run_id,
                **({"turn_ref": turn_id} if turn_id else {}),
                **({"turn_run_ref": turn_run_id} if turn_run_id else {}),
            },
        )
    except Exception:
        logger.debug("Failed to publish chat interruption fact signal.", exc_info=True)
        return {
            "published": False,
            "reason": "runtime_signal_publish_failed",
            "authority": "api.chat.runtime_interruption.signal",
        }
    return {
        "published": True,
        "event_id": str(getattr(event, "event_id", "") or ""),
        "offset": int(getattr(event, "offset", -1) or -1),
        "signal_type": "runtime.interruption.fact",
        "authority": "api.chat.runtime_interruption.signal",
    }


def _run_response(runtime: Any, run: RuntimeRun) -> dict[str, Any]:
    payload = run.to_dict()
    payload.pop("owner_process_id", None)
    payload.pop("owner_instance_id", None)
    now = time.time()
    execution_attached = chat_run_execution_attached(
        runtime.harness_runtime.single_agent_runtime_host,
        run,
        terminal_statuses=TERMINAL_RUN_STATUSES,
    )
    restore_contract = _run_restore_contract(
        runtime,
        run,
        execution_attached=execution_attached,
        now=now,
    )
    return {
        **payload,
        "chat_run_execution_attached": execution_attached,
        **restore_contract,
        "replay_url": f"/api/chat/runs/{run.stream_run_id}/events/replay",
        "live_ws_url": f"/api/chat/sessions/{run.session_id}/live",
    }


def _run_restore_contract(
    runtime: Any,
    run: RuntimeRun,
    *,
    execution_attached: bool,
    now: float,
) -> dict[str, Any]:
    diagnostics = dict(run.diagnostics or {})
    terminal = str(run.status or "").strip() in TERMINAL_RUN_STATUSES
    latest_event_offset = int(getattr(run, "latest_event_offset", -1) or -1)
    live_reconnectable = bool(
        run.reconnectable_until >= now
        and not terminal
        and execution_attached
    )
    replay_available = bool(str(run.event_log_id or "").strip() and latest_event_offset >= 0)
    recoverable_interruption = bool(
        diagnostics.get("recoverable") is True
        and diagnostics.get("agent_decision_terminal") is False
    )
    continuation_ref: dict[str, Any] = {}
    continuation_available = False
    if recoverable_interruption:
        try:
            host = runtime.harness_runtime.single_agent_runtime_host
            context_status = _session_context_recovery_status(runtime, run.session_id)
            selection = select_session_continuation(
                host,
                session_id=run.session_id,
                active_work_present=_active_work_blocks_continuation(runtime, run.session_id),
                context_recovery_status=context_status,
            )
            continuation_ref = selection.to_dict()
            continuation_available = False
        except Exception:
            logger.debug(
                "Failed to project chat run continuation contract.",
                exc_info=True,
                extra={"stream_run_id": run.stream_run_id},
            )
            continuation_ref = {
                "reason": "continuation_projection_failed",
                "authority": "api.chat.run_restore_contract",
            }
    return {
        "live_reconnectable": live_reconnectable,
        "replay_available": replay_available,
        "recoverable_interruption": recoverable_interruption,
        "continuation_available": continuation_available,
        "continuation_ref": continuation_ref,
        "restore_contract_authority": "api.chat.run_restore_contract",
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


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _stream_event_id(event: dict[str, Any]) -> str:
    raw_event = _record(event.get("event"))
    return str(
        event.get("runtime_event_id")
        or event.get("event_id")
        or raw_event.get("event_id")
        or ""
    ).strip()


def _stream_event_offset(event: dict[str, Any]) -> int:
    raw_event = _record(event.get("event"))
    for value in (
        event.get("event_offset"),
        event.get("offset"),
        raw_event.get("offset"),
    ):
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return -1


def _stream_event_created_at(event: dict[str, Any]) -> float:
    raw_event = _record(event.get("event"))
    for value in (
        event.get("created_at"),
        raw_event.get("created_at"),
        event.get("updated_at"),
        raw_event.get("updated_at"),
    ):
        try:
            numeric = float(value)
            if numeric > 0:
                return numeric
        except (TypeError, ValueError):
            continue
    return time.time()


def _runtime_run_refs_from_event(event: dict[str, Any]) -> dict[str, str]:
    task_run_id = ""
    turn_run_id = ""
    active_turn_id = str(event.get("active_turn_id") or "").strip()
    turn_run_payload = dict(event.get("turn_run") or {}) if isinstance(event.get("turn_run"), dict) else {}
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
        active_turn_id = str(event.get("turn_id") or turn_run_payload.get("turn_id") or "").strip()
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
