from __future__ import annotations

import asyncio
import json
import logging
import re
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
from harness.runtime.projection.projector import ProjectionLifecycleState, attach_public_projection_event
from harness.runtime.public_progress import public_runtime_progress_summary
from harness.runtime.runtime_private_text import looks_like_runtime_private_artifact_text
from harness.runtime.task_run_control_gateway import TaskRunControlGateway
from harness.task_run_status import is_stopped_or_terminal_task_run
from harness.runtime.output_boundary import (
    contains_inline_pseudo_tool_call,
    contains_internal_protocol,
    sanitize_visible_assistant_content,
)
from runtime.model_gateway.assistant_stream_frame import (
    assistant_message_ref,
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
from runtime.shared.tool_identity import permission_decision_id
from runtime.shared.queued_user_input_dispatcher import (
    chat_run_execution_attached,
    has_active_primary_chat_run,
    queued_input_admission_target,
    validate_queued_steer,
)
from runtime.shared.queued_user_input_store import QueuedUserInput
from runtime.shared.runtime_run_registry import RuntimeRun, TERMINAL_RUNTIME_RUN_STATUSES
from runtime.shared.stream_replay import sanitize_public_stream_event_data_for_replay
from sessions import SessionProjectBindingConflict, validate_session_id
from task_system.session_scope import assert_optional_session_scope, request_scope_from_query
from capability_system.capabilities.attachments import SUPPORTED_ATTACHMENT_IMAGE_SUFFIXES
from core.config import runtime_config
from core.project_layout import ProjectLayout

router = APIRouter()
logger = logging.getLogger(__name__)
TERMINAL_STREAM_EVENTS = {TURN_COMPLETED_EVENT}
TERMINAL_RUN_STATUSES = TERMINAL_RUNTIME_RUN_STATUSES
TASK_EXECUTOR_HANDOFF_REASONS = {"task_executor_scheduled"}
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
INTERNAL_STREAM_EVENTS = {
    "debug",
    "runtime_assembly_compiled",
    "runtime_assembly_bound",
    "runtime_invocation_packet",
    "runtime_control_signal_published",
    "runtime_control_signal_observed",
    "runtime_control_signal_consumed",
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
TOOL_FAILURE_FEEDBACK_RE = re.compile(
    r"^(?:[A-Za-z][A-Za-z0-9 _./-]{0,80}\s+failed|tool_policy_rejection):",
    flags=re.IGNORECASE,
)
LINE_NUMBERED_TOOL_OUTPUT_RE = re.compile(r"(?m)^\s*\d{1,6}\s*\|")
PUBLIC_EVENT_DATA_ALLOWLIST = {
    "chat_run_started": {"status"},
    CHAT_TURN_BOUND_EVENT: {
        "context_id",
        "status",
        "stream_run_id",
        "session_id",
        "turn_id",
        "active_turn_id",
        "turn_run_id",
        "message_id",
        "message_ref",
        "source_turn_event_id",
        "source_turn_event_offset",
        "runtime_event_id",
        "public_sequence_started_at",
        "created_at",
    },
    TASK_ORIGIN_BOUND_EVENT: {
        "status",
        "stream_run_id",
        "session_id",
        "turn_id",
        "active_turn_id",
        "turn_run_id",
        "task_run_id",
        "runtime_task_run_id",
        "message_id",
        "message_ref",
        "task_origin_binding",
        "active_turn",
        "source_handoff_event_id",
        "source_handoff_event_offset",
        "runtime_event_id",
        "created_at",
    },
    TASK_BRIDGE_STARTED_EVENT: {
        "bridge_id",
        "status",
        "stream_run_id",
        "event_log_id",
        "session_id",
        "turn_id",
        "active_turn_id",
        "turn_run_id",
        "task_run_id",
        "runtime_task_run_id",
        "message_id",
        "message_ref",
        "source_handoff_event_id",
        "source_handoff_event_offset",
        "runtime_event_id",
        "task_event_start_offset",
        "public_sequence_base",
        "created_at",
    },
    TASK_BRIDGE_TERMINAL_EVENT: {
        "bridge_id",
        "status",
        "stream_run_id",
        "session_id",
        "turn_id",
        "active_turn_id",
        "turn_run_id",
        "task_run_id",
        "runtime_task_run_id",
        "message_id",
        "message_ref",
        "terminal_reason",
        "completion_state",
        "source_task_event_id",
        "source_task_event_offset",
        "runtime_event_id",
        "commit_observed",
        "created_at",
    },
    "input_commit_gate": {"status", "message_ref"},
    "runtime_branch_decided": {"runtime_branch"},
    "single_agent_turn_started": {"runtime_branch", "allowed_action_types"},
    "model_action_request": {
        "request_id",
        "action_type",
        "public_progress_note",
        "public_action_state",
        "task_run_contract_seed",
        "active_work_control",
        "recovery_resume",
    },
    "model_action_admission": {
        "request_id",
        "action_type",
        "model_action_request",
        "admission",
        "runtime_event_id",
        "source_event_id",
    },
    "active_task_steer_accepted": {
        "summary",
        "status",
    },
    "runtime_status": {
        "title",
        "detail",
        "state",
        "status_kind",
        "phase",
        "reasoning_content_present",
        "reasoning_content",
        "reasoning_content_chars",
        "reasoning_content_estimated_tokens",
        "reasoning_content_sha256",
        "reasoning_projection_policy",
        "answer_channel",
        "answer_source",
        "runtime_task_run_id",
        "task_run_id",
        "runtime_event_id",
        "runtime_run_id",
        "created_at",
        "active_turn_id",
        "active_turn",
    },
    "stream_recovery": {
        "status",
        "reason",
        "code",
        "provider",
        "model",
        "stream_ref",
        "partial_utf8_bytes",
        "continuation_utf8_bytes",
        "recovery_mode",
        "recovery_call_status",
        "fallback_timeout_seconds",
        "directive_ref",
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
        "feedback_identity",
        "event",
    },
    ASSISTANT_PUBLIC_FEEDBACK_EVENT: {
        "step",
        "status",
        "summary",
        "public_progress_note",
        "agent_brief_output",
        "current_judgment",
        "next_action",
        "completion_status",
        "presentation_source",
        "feedback_identity",
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
        "title",
        "target",
        "arguments_preview",
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
        "failure_code",
        "model_error_code",
        "provider",
        "model",
        "retryable",
        "stopped_reason",
        "runtime_event_id",
        "source_task_event_id",
        "source_task_event_offset",
        "source_event_type",
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
    expected_task_run_id: str = Field(default="", max_length=240)
    cascade_subagents: str = Field(default="interrupt_for_resume", max_length=80)


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
    admission = queued_input_admission_target(host, session_id=validated_session_id)
    item = await asyncio.to_thread(
        host.queued_user_inputs.enqueue,
        session_id=validated_session_id,
        content=payload.message,
        client_message_id=payload.client_message_id,
        input_policy=str(admission.get("input_policy") or "auto"),
        expected_active_turn_id=str(admission.get("expected_active_turn_id") or ""),
        task_run_id=str(admission.get("task_run_id") or ""),
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
    cascade_policy = _validated_interrupt_cascade(request.cascade_subagents, mode=mode)
    reason = str(request.reason or "user_stop_from_chat").strip() or "user_stop_from_chat"
    host = runtime.harness_runtime.single_agent_runtime_host
    registry = host.run_registry
    active_turn = host.active_turn_registry.snapshot(run.session_id)
    expected_turn_id = str(request.expected_active_turn_id or "").strip()
    expected_task_run_id = str(request.expected_task_run_id or "").strip()
    active_turn_control: dict[str, Any] = {}
    if active_turn is not None:
        active_turn_control = host.active_turn_registry.mark_interrupting(
            session_id=run.session_id,
            expected_turn_id=expected_turn_id,
            expected_task_run_id=expected_task_run_id,
            reason=reason,
        )
        if not active_turn_control.get("accepted"):
            raise HTTPException(status_code=409, detail=active_turn_control)
        active_turn = host.active_turn_registry.snapshot(run.session_id)
    elif expected_turn_id or expected_task_run_id:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "active_turn_unavailable",
                "expected_active_turn_id": expected_turn_id,
                "expected_task_run_id": expected_task_run_id,
                "authority": "api.chat.runtime_interruption",
            },
        )

    root_task_run_id = _interrupt_root_task_run_id(
        run,
        active_turn=active_turn,
        expected_task_run_id=expected_task_run_id,
    )
    stream_control = await asyncio.to_thread(
        host.cancel_runtime_run_cells,
        runtime_run_sessions={run.stream_run_id: run.session_id},
        reason=reason,
    )
    task_control: dict[str, Any] = {}
    if root_task_run_id:
        gateway = TaskRunControlGateway(runtime_host=host, schedule_task_run_executor=None)
        task_control = await asyncio.to_thread(
            gateway.stop_task_run if mode == "hard_stop" else gateway.pause_task_run,
            root_task_run_id,
            reason=reason,
            requested_by="user",
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
    subagent_controls = await asyncio.to_thread(
        _cascade_interrupted_subagents,
        host,
        root_task_run_id=root_task_run_id,
        session_id=run.session_id,
        mode=mode,
        cascade_policy=cascade_policy,
        reason=reason,
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
        root_task_run_id=root_task_run_id,
        mode=mode,
        reason=reason,
        stream_control=stream_control,
        task_control=task_control,
        subagent_controls=subagent_controls,
        context_recovery_status=context_status,
        checkpoint=checkpoint,
    )
    accepted = bool(
        (not task_control or task_control.get("ok") is True)
        and (not stream_control or not stream_control.get("rejected"))
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
        "task_control": task_control,
        "stream_control": stream_control,
        "subagent_controls": subagent_controls,
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
    record = selection.record.to_dict() if selection.record is not None else {}
    interrupted_turn = selection.interrupted_turn.to_dict() if selection.interrupted_turn is not None else {}
    return {
        "session_id": validated_session_id,
        "available": bool(record or interrupted_turn),
        "record": record,
        "interrupted_turn": interrupted_turn,
        "context_recovery_status": context_status,
        "reason": selection.reason,
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
    admission = queued_input_admission_target(host, session_id=session_id)
    item = await asyncio.to_thread(
        enqueue,
        session_id=session_id,
        content=request.message,
        client_message_id=str(request.client_message_id or ""),
        input_policy=str(admission.get("input_policy") or "auto"),
        expected_active_turn_id=str(admission.get("expected_active_turn_id") or ""),
        task_run_id=str(admission.get("task_run_id") or ""),
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
    _attach_public_projection_frame(
        "chat_run_started",
        start_data,
        session_id=run.session_id,
        sequence=0,
    )
    start_event = replay.append_public_event(run, public_event_type="chat_run_started", data=start_data)
    current = registry.mark_event(run, latest_event_offset=start_event.offset, status="running")
    data = _turn_completed_data(
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
            admission = queued_input_admission_target(host, session_id=normalized)
            if str(admission.get("input_policy") or "").strip().lower() == "steer":
                retargeted = await asyncio.to_thread(
                    store.retarget_for_dispatch,
                    normalized,
                    next_item.queue_item_id,
                    input_policy="steer",
                    expected_active_turn_id=str(admission.get("expected_active_turn_id") or ""),
                    task_run_id=str(admission.get("task_run_id") or ""),
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
        expected_task_run_id=str(item.task_run_id or "") if item.input_policy == "steer" else "",
        editor_context=dict(item.editor_context or {}),
    )


async def _run_chat_to_event_log(runtime: Any, run: RuntimeRun, request: HarnessRuntimeRequest) -> None:
    host = runtime.harness_runtime.single_agent_runtime_host
    registry = host.run_registry
    replay = host.stream_replay
    terminal_event = ""
    bridge_context: ChatTaskBridgeContext | None = None
    turn_context: PublicTurnOutputContext | None = None
    task_handoff_observed = False
    projection_lifecycle = ProjectionLifecycleState()
    current = _safe_mark_run_running(registry, run)
    try:
        start_data = {"status": "running"}
        _attach_public_projection_frame(
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
            projections = _project_public_stream_event(event_type, event)
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
                if _is_task_executor_handoff_terminal(public_event_type, data):
                    bridged_task_run_id = _task_run_id_from_public_data(data) or event_task_run_id
                    if turn_context is None:
                        host.record_chat_turn_run_runtime_interruption_best_effort(
                            current,
                            code="task_bridge_context_missing",
                            reason="Task bridge handoff arrived before a public turn context was available.",
                            orphaned_by="api.chat.run_chat_to_event_log.task_bridge_context_missing",
                        )
                        return
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
                            },
                        )
                    task_handoff_observed = True
                    break
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
            if terminal_event or task_handoff_observed:
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
        if _bridge_context_has_live_bound_task(runtime, bridge_context) or _active_turn_has_live_bound_task(runtime, request.session_id):
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
        if _bridge_context_has_live_bound_task(runtime, bridge_context) or _active_turn_has_live_bound_task(runtime, request.session_id):
            host.record_chat_turn_run_runtime_interruption_best_effort(
                current,
                code="projection_stream_missing_task_bridge_terminal",
                reason="Chat stream ended while the active turn still had a live bound task.",
                orphaned_by="api.chat.run_chat_to_event_log.active_turn_task_missing_terminal",
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
        payload.setdefault("session_id", str(anchor.get("session_id") or session_id))
        payload.setdefault("turn_id", str(anchor.get("turn_id") or ""))
        payload.setdefault("active_turn_id", str(anchor.get("turn_id") or ""))
        payload.setdefault("turn_run_id", str(anchor.get("turn_run_id") or ""))
        payload.setdefault("message_id", str(anchor.get("message_id") or anchor.get("message_ref") or ""))
        payload.setdefault("message_ref", str(anchor.get("message_ref") or anchor.get("message_id") or ""))
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
        _attach_public_projection_frame(
            public_event_type,
            payload,
            session_id=session_id,
            sequence=next_sequence,
            lifecycle_state=projection_lifecycle,
            public_anchor=public_anchor,
        )
    replay_payload = _public_replay_stream_data(public_event_type, payload)
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
    if event_type not in {"harness_run_started", "single_agent_turn_started"}:
        return None
    refs = _runtime_run_refs_from_event(event)
    turn_run_id = str(refs.get("turn_run_id") or "").strip()
    turn_id = str(refs.get("active_turn_id") or _turn_id_from_turn_run_id(turn_run_id)).strip()
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
        for public_event_type, data in _project_public_stream_event(event_type, stream_event):
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
    public_terminal_reason = _public_terminal_reason(raw_terminal_reason)
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
        "terminal_reason": public_terminal_reason,
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
    terminal_data = _turn_completed_data(
        "task_run_lifecycle_finished",
        {
            "status": status,
            "turn_run_id": turn_run_id,
            "task_run_id": task_run_id,
            "terminal_reason": public_terminal_reason,
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


def _bridge_context_has_live_bound_task(runtime: Any, bridge_context: ChatTaskBridgeContext | None) -> bool:
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
    return task_run is not None and not is_stopped_or_terminal_task_run(task_run, runtime_host=host)


def _active_turn_has_live_bound_task(runtime: Any, session_id: str) -> bool:
    try:
        host = runtime.harness_runtime.single_agent_runtime_host
        active_turn = host.active_turn_registry.resolve_current(str(session_id or "").strip())
    except Exception:
        return False
    task_run_id = str(getattr(active_turn, "bound_task_run_id", "") or "").strip() if active_turn is not None else ""
    if not task_run_id:
        return False
    try:
        task_run = host.state_index.get_task_run(task_run_id)
    except Exception:
        return False
    return task_run is not None and not is_stopped_or_terminal_task_run(task_run, runtime_host=host)


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


def _is_task_executor_handoff_terminal(public_event_type: str, data: dict[str, Any]) -> bool:
    if public_event_type != TURN_COMPLETED_EVENT:
        return False
    candidates = (
        data.get("completion_state"),
        data.get("terminal_reason"),
        data.get("status"),
    )
    return any(str(candidate or "").strip().lower() in TASK_EXECUTOR_HANDOFF_REASONS for candidate in candidates) and bool(_task_run_id_from_public_data(data))


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


def _validated_interrupt_cascade(value: str, *, mode: str) -> str:
    cascade = str(value or "interrupt_for_resume").strip() or "interrupt_for_resume"
    if cascade not in {"interrupt_for_resume", "hard_stop", "leave_running"}:
        raise HTTPException(status_code=400, detail="unsupported_interrupt_cascade")
    if cascade == "leave_running" and mode != "hard_stop":
        raise HTTPException(status_code=400, detail="leave_running_cascade_not_allowed_for_chat_interrupt")
    return cascade


def _interrupt_root_task_run_id(
    run: RuntimeRun,
    *,
    active_turn: Any | None,
    expected_task_run_id: str = "",
) -> str:
    diagnostics = dict(run.diagnostics or {})
    candidates = [
        expected_task_run_id,
        getattr(active_turn, "bound_task_run_id", "") if active_turn is not None else "",
        diagnostics.get("runtime_task_run_id"),
        diagnostics.get("task_run_id"),
        diagnostics.get("public_anchor_task_run_id"),
    ]
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if normalized:
            return normalized
    return ""


def _cascade_interrupted_subagents(
    host: Any,
    *,
    root_task_run_id: str,
    session_id: str,
    mode: str,
    cascade_policy: str,
    reason: str,
) -> list[dict[str, Any]]:
    root_id = str(root_task_run_id or "").strip()
    if not root_id or cascade_policy == "leave_running":
        return []
    gateway = TaskRunControlGateway(runtime_host=host, schedule_task_run_executor=None)
    controls: list[dict[str, Any]] = []
    for child in _subagent_task_runs_for_parent(host, root_task_run_id=root_id, session_id=session_id):
        child_id = str(getattr(child, "task_run_id", "") or "").strip()
        if not child_id or child_id == root_id:
            continue
        if cascade_policy == "hard_stop" or mode == "hard_stop":
            result = gateway.stop_task_run(child_id, reason=reason, requested_by="parent_agent")
        else:
            result = gateway.pause_task_run(child_id, reason=reason, requested_by="parent_agent")
        controls.append(
            {
                "task_run_id": child_id,
                "parent_task_run_id": root_id,
                "control": result,
                "authority": "api.chat.runtime_interruption.subagent_cascade",
            }
        )
    return controls


def _subagent_task_runs_for_parent(host: Any, *, root_task_run_id: str, session_id: str) -> list[Any]:
    state_index = getattr(host, "state_index", None)
    list_session_task_runs = getattr(state_index, "list_session_task_runs", None)
    if not callable(list_session_task_runs):
        return []
    try:
        task_runs = list(list_session_task_runs(session_id) or [])
    except Exception:
        return []
    root_id = str(root_task_run_id or "").strip()
    children: list[Any] = []
    for task_run in task_runs:
        if str(getattr(task_run, "execution_runtime_kind", "") or "") != "subagent_task":
            continue
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
        parent_ids = _subagent_parent_task_run_ids(diagnostics)
        if root_id in parent_ids:
            children.append(task_run)
    return children


def _subagent_parent_task_run_ids(diagnostics: dict[str, Any]) -> set[str]:
    parent_ids: set[str] = set()
    for key in ("parent_task_run_id", "root_task_run_id", "supervisor_task_run_id"):
        value = str(diagnostics.get(key) or "").strip()
        if value:
            parent_ids.add(value)
    for key in ("origin", "subagent_control", "agent_control", "parent_agent"):
        payload = diagnostics.get(key)
        if not isinstance(payload, dict):
            continue
        for nested_key in ("parent_task_run_id", "root_task_run_id", "supervisor_task_run_id"):
            value = str(payload.get(nested_key) or "").strip()
            if value:
                parent_ids.add(value)
    return parent_ids


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
            "schema_version": str(package.get("schema_version") or ""),
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
    root_task_run_id: str,
    mode: str,
    reason: str,
    stream_control: dict[str, Any],
    task_control: dict[str, Any],
    subagent_controls: list[dict[str, Any]],
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
    task_run_id = str(root_task_run_id or "").strip()
    turn_id = str(getattr(active_turn, "turn_id", "") or diagnostics.get("turn_id") or diagnostics.get("active_turn_id") or "")
    turn_run_id = str(getattr(active_turn, "turn_run_id", "") or diagnostics.get("turn_run_id") or "")
    payload = {
        "signal_kind": "runtime_interruption_fact",
        "mode": mode,
        "reason": reason,
        "stream_run_id": run.stream_run_id,
        "session_id": run.session_id,
        "task_run_id": task_run_id,
        "turn_id": turn_id,
        "turn_run_id": turn_run_id,
        "stream_control": dict(stream_control or {}),
        "task_control": _control_fact(task_control),
        "subagent_controls": [_control_fact(dict(item.get("control") or item)) for item in list(subagent_controls or [])],
        "context_recovery_status": dict(context_recovery_status or {}),
        "checkpoint": dict(checkpoint or {}),
        "contract": {
            "system_role": "carry_runtime_facts_and_feedback_only",
            "agent_role": "decide_next_action_from_facts",
            "semantic_decision_owner": "agent",
        },
        "authority": "api.chat.runtime_interruption.signal",
    }
    try:
        event = publish(
            task_run_id or run.event_log_id,
            signal_type="runtime.interruption.fact",
            scope=RuntimeSignalScope(
                session_id=run.session_id,
                task_run_id=task_run_id,
                turn_id=turn_id,
                turn_run_id=turn_run_id,
            ),
            source_authority="api.chat.runtime_interruption",
            payload=payload,
            visibility="model_visible",
            refs={
                "stream_run_ref": run.stream_run_id,
                **({"task_run_ref": task_run_id} if task_run_id else {}),
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


def _control_fact(value: dict[str, Any]) -> dict[str, Any]:
    payload = dict(value or {})
    return {
        key: payload.get(key)
        for key in (
            "ok",
            "accepted",
            "task_run_id",
            "error",
            "reason",
            "authority",
            "control",
            "recovery_state",
        )
        if key in payload
    }


def _run_response(runtime: Any, run: RuntimeRun) -> dict[str, Any]:
    payload = run.to_dict()
    payload.pop("owner_process_id", None)
    payload.pop("owner_instance_id", None)
    execution_attached = chat_run_execution_attached(
        runtime.harness_runtime.single_agent_runtime_host,
        run,
        terminal_statuses=TERMINAL_RUN_STATUSES,
    )
    return {
        **payload,
        "chat_run_execution_attached": execution_attached,
        "is_reconnectable": run.reconnectable_until >= time.time()
        and run.status not in TERMINAL_RUN_STATUSES
        and execution_attached,
        "replay_url": f"/api/chat/runs/{run.stream_run_id}/events/replay",
        "live_ws_url": f"/api/chat/sessions/{run.session_id}/live",
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
    raw_data = {key: value for key, value in dict(event).items() if key != "type"}
    if normalized in INTERNAL_STREAM_EVENTS:
        return []
    if normalized == "model_action_request":
        data = _model_action_request_public_data(raw_data)
        return [(normalized, data)] if data else []
    if normalized == "agent_turn_terminal":
        return []
    if normalized == "runtime_evidence_projection_published":
        data = _runtime_evidence_projection_public_data(raw_data)
        return [(normalized, data)] if data else []
    if normalized == "agent_contract_feedback_required":
        data = _agent_contract_feedback_status_public_data(raw_data)
        return [("runtime_status", data)] if data else []
    if normalized == "harness_run_started" and _is_turn_trace_only_harness_start(event):
        return []
    if normalized in {"step_summary_recorded", "runtime_step_summary"}:
        data = _runtime_step_summary_data(raw_data)
        return [("runtime_step_summary", data)] if data else []
    if normalized == "stream_recovery":
        data = _stream_recovery_public_data(raw_data)
        return [(normalized, data)] if data else []
    if normalized == "task_model_action_wait_heartbeat":
        return []
    if normalized in {ASSISTANT_TEXT_DELTA_EVENT, ASSISTANT_TEXT_FINAL_EVENT, ASSISTANT_STREAM_REPAIR_EVENT}:
        data = _assistant_stream_public_data(normalized, raw_data)
        return [(normalized, data)] if data else []
    if _is_runtime_status_only_error_event(normalized, raw_data):
        return []
    if normalized in {"done", "error", "stopped"}:
        return [(TURN_COMPLETED_EVENT, _turn_completed_data(normalized, raw_data))]
    if normalized in {"answer_candidate", "assistant_text", "token"}:
        return []
    if normalized in {"model_action_admission", "model_action_admission_checked"}:
        control_events = _control_action_public_events(raw_data)
        return control_events or _tool_action_public_events(raw_data)
    if normalized == TOOL_ITEM_STARTED_EVENT:
        data = _tool_item_started_data(raw_data)
        return [(TOOL_ITEM_STARTED_EVENT, data)] if data else []
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
            "turn_id": str(raw_data.get("turn_id") or ""),
            "turn_run_id": str(raw_data.get("turn_run_id") or ""),
            "active_turn_id": str(raw_data.get("active_turn_id") or raw_data.get("turn_id") or ""),
        }
    return [(normalized, data)]


def _is_runtime_status_only_error_event(event_type: str, raw_data: dict[str, Any]) -> bool:
    if str(event_type or "").strip().lower() != "error":
        return False
    persist_policy = str(raw_data.get("answer_persist_policy") or "").strip().lower()
    finalization_policy = str(raw_data.get("answer_finalization_policy") or "").strip().lower()
    return (
        persist_policy == "runtime_status_only"
        or finalization_policy
        in {
            "no_agent_answer_runtime_unavailable",
            "no_agent_answer_runtime_status",
        }
    )


def _assistant_stream_public_data(event_type: str, raw_data: dict[str, Any]) -> dict[str, Any]:
    raw_event = _record(raw_data.get("event"))
    payload = _record(raw_event.get("payload") or raw_data.get("payload") or raw_data)
    refs = _record(raw_event.get("refs"))
    allowed = PUBLIC_EVENT_DATA_ALLOWLIST.get(event_type, set())
    data: dict[str, Any] = {}
    for key in allowed:
        value = payload.get(key)
        if value in ("", None):
            value = raw_data.get(key)
        if value not in ("", None):
            data[key] = value
    data.setdefault("turn_run_id", str(payload.get("turn_run_id") or refs.get("turn_run_ref") or raw_data.get("turn_run_id") or ""))
    data.setdefault("task_run_id", str(payload.get("task_run_id") or refs.get("task_run_ref") or raw_data.get("task_run_id") or raw_data.get("runtime_task_run_id") or ""))
    data.setdefault("runtime_event_id", str(raw_event.get("event_id") or raw_data.get("event_id") or ""))
    if event_type in {ASSISTANT_TEXT_DELTA_EVENT, ASSISTANT_TEXT_FINAL_EVENT} and not str(data.get("content") or ""):
        return {}
    if event_type == ASSISTANT_STREAM_REPAIR_EVENT and not str(data.get("replacement_content") or ""):
        return {}
    return _redact_public_stream_data({key: value for key, value in data.items() if value not in ("", None)})


def _stream_recovery_public_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    raw_event = _record(raw_data.get("event"))
    payload = _record(raw_event.get("payload") or raw_data.get("payload") or raw_data)
    allowed = PUBLIC_EVENT_DATA_ALLOWLIST.get("stream_recovery", set())
    data = {key: payload[key] for key in allowed if key in payload and payload[key] not in ("", None)}
    data["status"] = str(data.get("status") or payload.get("status") or "started")
    data["reason"] = str(data.get("reason") or payload.get("reason") or "partial_stream_error")
    data["runtime_event_id"] = str(raw_event.get("event_id") or raw_data.get("event_id") or "")
    return _redact_public_stream_data({key: value for key, value in data.items() if value not in ("", None)})


def _agent_contract_feedback_status_public_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    raw_event = _record(raw_data.get("event"))
    payload = _record(raw_event.get("payload") or raw_data.get("payload") or raw_data)
    refs = _record(raw_event.get("refs"))
    feedback = _record(payload.get("agent_contract_feedback") or raw_data.get("agent_contract_feedback"))
    if not feedback:
        return {}
    failure = _record(feedback.get("contract_failure"))
    reason = str(feedback.get("reason") or failure.get("reason") or "").strip()
    detail = _safe_public_action_text(feedback.get("agent_feedback") or reason)
    if not detail:
        detail = "需要 agent 根据执行契约重新选择下一步动作。"
    data = {
        "title": "动作契约需要修正",
        "detail": detail[:260],
        "state": "waiting",
        "status_kind": "agent_contract_feedback",
        "phase": str(feedback.get("phase") or ""),
        "turn_id": str(payload.get("turn_id") or feedback.get("turn_id") or refs.get("turn_ref") or ""),
        "active_turn_id": str(payload.get("turn_id") or feedback.get("turn_id") or refs.get("turn_ref") or ""),
        "turn_run_id": str(refs.get("turn_run_ref") or raw_data.get("turn_run_id") or ""),
        "task_run_id": str(refs.get("task_run_ref") or raw_data.get("task_run_id") or raw_data.get("runtime_task_run_id") or ""),
        "runtime_event_id": str(raw_event.get("event_id") or raw_data.get("event_id") or ""),
    }
    return _redact_public_stream_data({key: value for key, value in data.items() if value not in ("", None)})


def _runtime_evidence_projection_public_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    raw_event = _record(raw_data.get("event"))
    payload = _record(raw_event.get("payload") or raw_data.get("payload") or raw_data)
    refs = _record(raw_event.get("refs"))
    projection = _record(payload.get("evidence_projection") or raw_data.get("evidence_projection"))
    if not projection:
        return {}
    evidence_summary = _record(projection.get("evidence_projection"))
    file_summary = _record(projection.get("file_state_summary"))
    read_payload = _record(projection.get("read_evidence_payload"))
    file_state_count = file_summary.get("file_count")
    if file_state_count in ("", None):
        file_state_count = evidence_summary.get("file_state_count")
    read_evidence_ref_count = evidence_summary.get("read_evidence_ref_count")
    if read_evidence_ref_count in ("", None):
        read_evidence_refs = read_payload.get("read_evidence_refs")
        read_evidence_ref_count = len(read_evidence_refs) if isinstance(read_evidence_refs, list) else ""
    compact_projection = {
        "projection_ref": str(projection.get("projection_ref") or refs.get("evidence_projection_ref") or ""),
        "packet_id": str(projection.get("packet_id") or evidence_summary.get("read_evidence_packet_id") or refs.get("runtime_invocation_packet_ref") or ""),
        "file_state_summary": {
            "file_count": file_state_count,
            "truncated": bool(file_summary.get("truncated") is True),
        },
        "read_evidence_payload": {
            "read_evidence_injection_count": read_payload.get("read_evidence_injection_count"),
            "read_evidence_ref_count": read_evidence_ref_count,
            "read_evidence_injections_redacted": bool(read_payload.get("read_evidence_injections_redacted") is True),
        },
    }
    data = {
        "evidence_projection": compact_projection,
        "turn_id": str(projection.get("turn_id") or raw_data.get("turn_id") or ""),
        "active_turn_id": str(projection.get("turn_id") or raw_data.get("active_turn_id") or raw_data.get("turn_id") or ""),
        "turn_run_id": str(refs.get("turn_run_ref") or raw_data.get("turn_run_id") or ""),
        "task_run_id": str(projection.get("task_run_id") or refs.get("task_run_ref") or raw_data.get("task_run_id") or raw_data.get("runtime_task_run_id") or ""),
        "runtime_event_id": str(raw_event.get("event_id") or raw_data.get("event_id") or ""),
    }
    return _redact_public_stream_data({key: value for key, value in data.items() if value not in ("", None, [], {})})


def _turn_completed_data(source_event_type: str, raw_data: dict[str, Any]) -> dict[str, Any]:
    source = str(source_event_type or "").strip().lower()
    requested_status = str(raw_data.get("status") or "").strip().lower()
    status = requested_status if requested_status in {"completed", "failed", "stopped"} else "completed"
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
        "error_summary": _turn_error_summary(raw_data, fallback=terminal_reason) if status == "failed" else "",
        "failure_code": str(raw_data.get("failure_code") or raw_data.get("model_error_code") or raw_data.get("code") or ""),
        "model_error_code": str(raw_data.get("model_error_code") or ""),
        "provider": str(raw_data.get("provider") or ""),
        "model": str(raw_data.get("model") or ""),
        "retryable": raw_data.get("retryable") if isinstance(raw_data.get("retryable"), bool) else None,
        "stopped_reason": _safe_public_action_text(raw_data.get("reason") or raw_data.get("content")) if status == "stopped" else "",
        "runtime_event_id": str(raw_data.get("runtime_event_id") or raw_data.get("event_id") or ""),
        "source_task_event_id": str(raw_data.get("source_task_event_id") or ""),
        "source_task_event_offset": raw_data.get("source_task_event_offset"),
        "source_event_type": str(raw_data.get("source_event_type") or ""),
    }
    return {key: value for key, value in payload.items() if value not in ("", None)}


def _turn_error_summary(raw_data: dict[str, Any], *, fallback: str = "") -> str:
    for value in (
        raw_data.get("error_summary"),
        raw_data.get("user_message"),
        raw_data.get("message"),
        raw_data.get("error"),
        raw_data.get("content"),
        fallback,
    ):
        text = _safe_public_action_text(value)
        if text:
            return text[:260]
    return "处理失败"


def _model_action_request_public_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    request = _record(raw_data.get("model_action_request") or raw_data.get("action_request"))
    if not request:
        return {}
    action_type = str(request.get("action_type") or "").strip()
    if not action_type or action_type == "tool_call":
        return {}
    return _redact_public_stream_data(
        _drop_empty_public_data(
            {
                "request_id": str(request.get("request_id") or "").strip(),
                "action_type": action_type,
                "public_progress_note": _safe_public_action_text(request.get("public_progress_note")),
                "public_action_state": _record(request.get("public_action_state")),
                "task_run_contract_seed": _record(request.get("task_run_contract_seed")),
                "active_work_control": _record(request.get("active_work_control")),
                "recovery_resume": _record(request.get("recovery_resume")),
            }
        )
    )


def _control_action_public_events(raw_data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    raw_event = _record(raw_data.get("event"))
    payload = _semantic_event_payload(raw_data)
    request = _record(payload.get("model_action_request") or raw_data.get("model_action_request"))
    if not request:
        return []
    action_type = str(request.get("action_type") or "").strip()
    if action_type in {"", "tool_call", "tool_calls"}:
        return []
    admission = _record(payload.get("admission") or raw_data.get("admission"))
    runtime_event_id = str(raw_event.get("event_id") or "").strip()
    data = _drop_empty_public_data(
        {
            "request_id": str(request.get("request_id") or "").strip(),
            "action_type": action_type,
            "model_action_request": _model_action_request_public_data({"model_action_request": request}),
            "admission": _public_admission_data(admission),
            "runtime_event_id": runtime_event_id,
            "source_event_id": runtime_event_id,
        }
    )
    return [("model_action_admission", _redact_public_stream_data(data))] if data else []


def _public_admission_data(admission: dict[str, Any]) -> dict[str, Any]:
    if not admission:
        return {}
    return _drop_empty_public_data(
        {
            "admission_id": str(admission.get("admission_id") or "").strip(),
            "action_request_ref": str(admission.get("action_request_ref") or "").strip(),
            "decision": str(admission.get("decision") or "").strip(),
            "user_visible_reason": _safe_public_action_text(admission.get("user_visible_reason")),
            "system_reason": str(admission.get("system_reason") or "").strip(),
            "contract_errors": [
                str(item) for item in list(admission.get("contract_errors") or []) if str(item or "").strip()
            ],
            "resource_errors": [
                str(item) for item in list(admission.get("resource_errors") or []) if str(item or "").strip()
            ],
            "issue_category": str(admission.get("issue_category") or "").strip(),
            "issue_code": str(admission.get("issue_code") or "").strip(),
        }
    )


def _drop_empty_public_data(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(payload or {}).items()
        if value not in ("", None, [], {}, ())
    }


def _tool_action_public_events(raw_data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    request_items = _tool_call_requested_items(raw_data)
    if not request_items:
        return events
    for request_data in request_items:
        permission_data = _tool_permission_decided_data(raw_data, request_data=request_data)
        events.append((TOOL_CALL_REQUESTED_EVENT, request_data))
        if permission_data:
            events.append((TOOL_PERMISSION_DECIDED_EVENT, permission_data))
    return events


def _tool_call_requested_items(raw_data: dict[str, Any]) -> list[dict[str, Any]]:
    raw_event = _record(raw_data.get("event"))
    payload = _semantic_event_payload(raw_data)
    refs = _record(raw_event.get("refs"))
    request = _record(payload.get("model_action_request") or raw_data.get("model_action_request"))
    if not request:
        return []
    action_type = str(request.get("action_type") or "").strip().lower()
    if action_type not in {"tool_call", "tool_calls"}:
        return []
    tool_calls = _model_action_tool_calls(request)
    if not tool_calls:
        return []
    runtime_event_id = str(raw_event.get("event_id") or "").strip()
    request_id = str(
        request.get("request_id")
        or refs.get("action_request_ref")
        or refs.get("batch_action_request_ref")
        or runtime_event_id
        or ""
    ).strip()
    result: list[dict[str, Any]] = []
    for index, raw_tool in enumerate(tool_calls):
        tool = _record(raw_tool)
        tool_name = str(tool.get("tool_name") or tool.get("name") or "").strip()
        tool_call_id = str(tool.get("id") or tool.get("tool_call_id") or "").strip()
        if not tool_name or not tool_call_id or _is_agent_todo_tool_name(tool_name):
            continue
        args = _tool_call_args(tool, request=request if len(tool_calls) == 1 else {})
        target = _safe_public_tool_target(args, tool_name=tool_name)
        data: dict[str, Any] = {
            "item_id": tool_call_id,
            "request_id": request_id or tool_call_id,
            "tool_lifecycle_id": tool_call_id,
            "tool_call_id": tool_call_id,
            "turn_run_id": str(payload.get("turn_run_id") or refs.get("turn_run_ref") or raw_data.get("turn_run_id") or ""),
            "task_run_id": str(payload.get("task_run_id") or refs.get("task_run_ref") or raw_data.get("task_run_id") or raw_data.get("runtime_task_run_id") or ""),
            "tool_name": tool_name,
            "target": target,
            "arguments_preview": _tool_arguments_preview(args),
        }
        if runtime_event_id:
            data["runtime_event_id"] = f"{runtime_event_id}:tool:{index + 1}" if len(tool_calls) > 1 else runtime_event_id
            data["source_task_event_id"] = runtime_event_id
        result.append(_redact_public_stream_data({key: value for key, value in data.items() if value not in ("", None)}))
    return result


def _model_action_tool_calls(request: dict[str, Any]) -> list[dict[str, Any]]:
    action_type = str(request.get("action_type") or "").strip().lower()
    if action_type == "tool_call":
        tool = _record(request.get("tool_call"))
        return [tool] if tool else []
    raw_calls = request.get("tool_calls")
    if not isinstance(raw_calls, list):
        return []
    return [_record(item) for item in raw_calls if _record(item)]


def _tool_call_args(tool: dict[str, Any], *, request: dict[str, Any]) -> dict[str, Any]:
    for value in (
        tool.get("args"),
        tool.get("arguments"),
        tool.get("input"),
    ):
        parsed = _record_or_json_object(value)
        if parsed:
            return parsed
    return {}


def _record_or_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _tool_permission_decided_data(raw_data: dict[str, Any], *, request_data: dict[str, Any]) -> dict[str, Any]:
    raw_event = _record(raw_data.get("event"))
    payload = _semantic_event_payload(raw_data)
    refs = _record(raw_event.get("refs"))
    admission = _record(payload.get("admission") or payload.get("admission_decision") or raw_data.get("admission"))
    if not admission:
        return {}
    decision = str(admission.get("decision") or "").strip()
    tool_call_id = str(request_data.get("tool_call_id") or "").strip()
    if not tool_call_id:
        return {}
    permission_decision_id = _canonical_permission_decision_id(admission, tool_call_id=tool_call_id)
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


def _tool_item_started_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    raw_event = _record(raw_data.get("event"))
    payload = _record(raw_event.get("payload") or raw_data.get("payload") or raw_data)
    refs = _record(raw_event.get("refs"))
    tool_call_id = str(payload.get("tool_call_id") or "").strip()
    permission_decision_id = str(payload.get("permission_decision_id") or "").strip()
    tool_name = str(payload.get("tool_name") or "").strip()
    if not tool_call_id or not permission_decision_id or not tool_name:
        return {}
    data: dict[str, Any] = {
        "item_id": tool_call_id,
        "tool_lifecycle_id": str(payload.get("tool_lifecycle_id") or payload.get("item_id") or tool_call_id),
        "tool_call_id": tool_call_id,
        "permission_decision_id": permission_decision_id,
        "turn_run_id": str(payload.get("turn_run_id") or refs.get("turn_run_ref") or raw_data.get("turn_run_id") or ""),
        "task_run_id": str(payload.get("task_run_id") or refs.get("task_run_ref") or raw_data.get("task_run_id") or raw_data.get("runtime_task_run_id") or ""),
        "tool_name": tool_name,
        "title": _safe_public_action_text(payload.get("title")),
        "target": _safe_public_action_text(payload.get("target")),
        "arguments_preview": _safe_public_action_text(payload.get("arguments_preview")),
        "state": str(payload.get("state") or "running"),
    }
    event_id = str(raw_event.get("event_id") or "").strip()
    if event_id:
        data["runtime_event_id"] = event_id
    return _redact_public_stream_data({key: value for key, value in data.items() if value not in ("", None)})


def _tool_item_completed_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    observation, raw_event = _tool_observation_payload(raw_data)
    if not observation:
        return {}
    tool_observation = _tool_runtime_observation_payload(observation)
    tool_name = str(
        tool_observation.get("tool_name")
        or tool_observation.get("tool")
        or observation.get("tool_name")
        or observation.get("tool")
        or _record(tool_observation.get("result_envelope")).get("tool_name")
        or _record(observation.get("result_envelope")).get("tool_name")
        or ""
    ).strip()
    tool_call_id = _tool_call_id_from_observation(tool_observation) or _tool_call_id_from_observation(observation)
    if not tool_name or not tool_call_id:
        return {}
    tool_lifecycle_id = _tool_lifecycle_id_from_observation(
        tool_observation,
        observation,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
    )
    status = str(tool_observation.get("status") or observation.get("status") or "").strip().lower()
    state = "error" if status and status not in {"ok", "done", "completed", "success"} else "done"
    result_envelope = _record(tool_observation.get("result_envelope") or observation.get("result_envelope"))
    execution_receipt = _record(tool_observation.get("execution_receipt") or observation.get("execution_receipt") or result_envelope.get("execution_receipt"))
    operation_gate = _record(tool_observation.get("operation_gate") or observation.get("operation_gate"))
    admission = _record(operation_gate.get("admission"))
    refs = _record(raw_event.get("refs"))
    tool_args = _tool_args_from_observation(
        tool_observation,
        observation,
        result_envelope=result_envelope,
        execution_receipt=execution_receipt,
        tool_call_id=tool_call_id,
    )
    error_source = (
        tool_observation.get("error")
        or observation.get("error")
        or result_envelope.get("error")
        or execution_receipt.get("error")
    )
    error = _safe_tool_feedback_text(error_source) or _safe_public_action_text(error_source)
    observation_text = _safe_tool_observation_text(
        tool_observation,
        result_envelope=result_envelope,
        tool_name=tool_name,
    )
    data: dict[str, Any] = {
        "item_id": tool_call_id,
        "tool_lifecycle_id": tool_lifecycle_id,
        "tool_call_id": tool_call_id,
        "permission_decision_id": _permission_decision_id_from_observation(
            tool_observation,
            raw_observation=observation,
            admission=admission,
        ),
        "turn_run_id": str(tool_observation.get("caller_ref") or observation.get("caller_ref") or execution_receipt.get("caller_ref") or refs.get("turn_run_ref") or raw_data.get("turn_run_id") or ""),
        "task_run_id": str(observation.get("task_run_id") or tool_observation.get("task_run_id") or execution_receipt.get("task_run_id") or refs.get("task_run_ref") or raw_data.get("task_run_id") or raw_data.get("runtime_task_run_id") or ""),
        "tool_name": tool_name,
        "title": _safe_public_action_text(tool_observation.get("title") or observation.get("title") or result_envelope.get("title")),
        "target": _safe_public_tool_target(tool_args, tool_name=tool_name),
        "arguments_preview": _tool_arguments_preview(tool_args),
        "state": state,
        "observation": observation_text,
        "error": error if state == "error" else "",
        "duration_ms": execution_receipt.get("duration_ms"),
    }
    event_id = str(raw_event.get("event_id") or "").strip()
    if event_id:
        data["runtime_event_id"] = event_id
    return _redact_public_stream_data({key: value for key, value in data.items() if value not in ("", None)})


def _permission_decision_id_from_observation(
    observation: dict[str, Any],
    *,
    raw_observation: dict[str, Any],
    admission: dict[str, Any],
) -> str:
    observation = _tool_runtime_observation_payload(observation)
    result_envelope = _record(observation.get("result_envelope"))
    execution_receipt = _record(observation.get("execution_receipt") or result_envelope.get("execution_receipt"))
    admission_id = str(admission.get("admission_id") or admission.get("permission_decision_id") or "").strip()
    if admission_id:
        return admission_id
    admission_ref = _public_permission_decision_ref(
        execution_receipt.get("admission_ref") or result_envelope.get("admission_ref")
    )
    if admission_ref:
        return admission_ref
    request_ref = _public_permission_decision_ref(
        raw_observation.get("request_ref")
        or observation.get("request_ref")
        or result_envelope.get("action_request_id")
        or observation.get("action_request_id")
        or execution_receipt.get("action_request_id")
        or ""
    )
    if request_ref:
        return request_ref
    return ""


def _public_permission_decision_ref(value: Any) -> str:
    ref = str(value or "").strip()
    if not ref:
        return ""
    if ref.startswith("admission:toolinv:") or ref.startswith("toolinv:"):
        return ""
    if ref.startswith("admission:"):
        return ref
    return f"admission:{ref}"


def _canonical_permission_decision_id(admission: dict[str, Any] | None = None, *, tool_call_id: str = "") -> str:
    payload = admission or {}
    admission_id = str(payload.get("admission_id") or payload.get("permission_decision_id") or "").strip()
    normalized_tool_call_id = str(tool_call_id or "").strip()
    if admission_id and normalized_tool_call_id:
        return admission_id if normalized_tool_call_id in admission_id else f"{admission_id}:{normalized_tool_call_id}"
    return permission_decision_id(payload, tool_call_id=normalized_tool_call_id)


def _tool_lifecycle_id_from_observation(
    observation: dict[str, Any],
    raw_observation: dict[str, Any],
    *,
    tool_call_id: str,
    tool_name: str,
) -> str:
    observation = _tool_runtime_observation_payload(observation)
    result_envelope = _record(observation.get("result_envelope"))
    execution_receipt = _record(observation.get("execution_receipt") or result_envelope.get("execution_receipt"))
    lifecycle_id = str(
        observation.get("invocation_id")
        or raw_observation.get("invocation_id")
        or observation.get("tool_lifecycle_id")
        or result_envelope.get("tool_lifecycle_id")
        or execution_receipt.get("tool_lifecycle_id")
        or execution_receipt.get("tool_invocation_id")
        or ""
    ).strip()
    if lifecycle_id:
        return lifecycle_id
    return _tool_lifecycle_id(tool_call_id=tool_call_id, tool_name=tool_name)


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
        "message_id": str(payload.get("message_id") or payload.get("anchor_message_id") or payload.get("message_ref") or refs.get("message_ref") or ""),
        "message_ref": str(payload.get("message_ref") or payload.get("anchor_message_id") or refs.get("message_ref") or ""),
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


def _runtime_step_summary_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    raw_event = _record(raw_data.get("event"))
    payload = _record(raw_event.get("payload") or raw_data.get("payload") or raw_data)
    refs = _record(raw_event.get("refs"))
    visible_fields = {
        "summary": _safe_public_action_text(payload.get("summary")),
        "public_progress_note": _safe_public_action_text(payload.get("public_progress_note")),
        "agent_brief_output": _safe_public_action_text(payload.get("agent_brief_output")),
        "current_judgment": _safe_public_action_text(payload.get("current_judgment")),
        "next_action": _safe_public_action_text(payload.get("next_action")),
        "completion_status": _safe_public_action_text(payload.get("completion_status")),
    }
    if not any(visible_fields.values()):
        return {}
    data: dict[str, Any] = {
        "task_run_id": str(payload.get("task_run_id") or raw_event.get("task_run_id") or raw_data.get("task_run_id") or "").strip(),
        "step": str(payload.get("step") or "").strip(),
        "status": str(payload.get("status") or "running").strip() or "running",
        "presentation_source": str(payload.get("presentation_source") or "").strip(),
        "feedback_identity": str(
            payload.get("feedback_identity")
            or refs.get("action_request_ref")
            or refs.get("batch_action_request_ref")
            or refs.get("runtime_invocation_packet_ref")
            or ""
        ).strip(),
        **{key: value for key, value in visible_fields.items() if value},
    }
    event_id = str(raw_event.get("event_id") or raw_data.get("runtime_event_id") or raw_data.get("event_id") or "").strip()
    if event_id:
        data["runtime_event_id"] = event_id
    source_offset = raw_event.get("offset") or raw_data.get("source_task_event_offset") or raw_data.get("event_offset")
    if source_offset not in (None, ""):
        data["source_task_event_offset"] = source_offset
    source_event_id = str(raw_event.get("event_id") or raw_data.get("source_task_event_id") or "").strip()
    if source_event_id:
        data["source_task_event_id"] = source_event_id
    return _redact_public_stream_data({key: value for key, value in data.items() if value not in ("", None)})


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


def _tool_runtime_observation_payload(observation: dict[str, Any]) -> dict[str, Any]:
    payload = _record(observation.get("payload"))
    if payload and (
        payload.get("tool_name")
        or payload.get("result_envelope")
        or payload.get("execution_receipt")
        or payload.get("operation_gate")
    ):
        return payload
    return observation


def _tool_call_id_from_observation(observation: dict[str, Any]) -> str:
    observation = _tool_runtime_observation_payload(observation)
    result_envelope = _record(observation.get("result_envelope"))
    execution_receipt = _record(observation.get("execution_receipt") or result_envelope.get("execution_receipt"))
    return str(
        result_envelope.get("tool_call_id")
        or execution_receipt.get("tool_call_id")
        or ""
    ).strip()


def _tool_args_from_observation(
    observation: dict[str, Any],
    raw_observation: dict[str, Any],
    *,
    result_envelope: dict[str, Any],
    execution_receipt: dict[str, Any],
    tool_call_id: str,
) -> dict[str, Any]:
    for source in (observation, raw_observation, result_envelope, execution_receipt):
        args = _tool_args_from_payload(source)
        if args:
            return args
    operation_gate = _record(observation.get("operation_gate") or raw_observation.get("operation_gate") or result_envelope.get("operation_gate"))
    action_permit = _record(operation_gate.get("action_permit"))
    return _tool_args_from_payload(action_permit)


def _tool_args_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    source = _record(payload)
    for key in ("tool_args", "args", "arguments", "input"):
        parsed = _record_or_json_object(source.get(key))
        if parsed:
            return parsed
    tool_call = _record(source.get("tool_call"))
    if tool_call:
        return _tool_call_args(tool_call, request={})
    return {}


def _tool_lifecycle_id(*, tool_call_id: str, tool_name: str) -> str:
    normalized_call_id = str(tool_call_id or "").strip()
    if normalized_call_id:
        return normalized_call_id
    normalized_tool = str(tool_name or "tool").strip() or "tool"
    return f"tool:{normalized_tool}"


def _is_agent_todo_tool_name(tool_name: Any) -> bool:
    return str(tool_name or "").strip().lower() == "agent_todo"


def _safe_tool_observation_text(
    observation: dict[str, Any],
    *,
    result_envelope: dict[str, Any],
    tool_name: str = "",
) -> str:
    if str(tool_name or "").strip().lower() == "agent_todo":
        todo_summary = _agent_todo_observation_summary(observation, result_envelope=result_envelope)
        if todo_summary:
            return todo_summary
    for value in (
        result_envelope.get("text"),
        observation.get("text"),
        result_envelope.get("summary"),
        result_envelope.get("result"),
    ):
        text = _safe_public_action_text(value) or _safe_tool_feedback_text(value)
        if text:
            return text[:500]
    structured = _record(result_envelope.get("structured_payload"))
    for key in ("summary", "message", "error"):
        text = _safe_public_action_text(structured.get(key)) or _safe_tool_feedback_text(structured.get(key))
        if text:
            return text[:500]
    return ""


def _safe_tool_feedback_text(value: Any) -> str:
    text = sanitize_visible_assistant_content(str(value or "")).strip()
    if not text:
        return ""
    if LINE_NUMBERED_TOOL_OUTPUT_RE.search(text):
        return ""
    normalized = " ".join(text.split()).strip()
    if not TOOL_FAILURE_FEEDBACK_RE.match(normalized):
        return ""
    if looks_like_runtime_private_artifact_text(normalized):
        return ""
    if contains_internal_protocol(normalized) or contains_inline_pseudo_tool_call(normalized):
        return ""
    return normalized[:500]


def _agent_todo_observation_summary(observation: dict[str, Any], *, result_envelope: dict[str, Any]) -> str:
    payload = _record(observation.get("payload"))
    parsed: dict[str, Any] = {}
    for value in (
        result_envelope.get("structured_payload"),
        result_envelope.get("result"),
        result_envelope.get("text"),
        result_envelope.get("summary"),
        observation.get("structured_payload"),
        observation.get("result"),
        observation.get("text"),
        observation.get("summary"),
        payload.get("result"),
        payload.get("text"),
        payload.get("summary"),
    ):
        candidate = _record_or_json_object(value)
        if _is_agent_todo_payload(candidate):
            parsed = candidate
            break
    if not parsed:
        return ""
    status = str(parsed.get("status") or "").strip().lower()
    if status == "error":
        error = _safe_public_action_text(parsed.get("error")) or "任务清单更新失败。"
        return error[:240]
    items = [dict(item) for item in list(parsed.get("items") or []) if isinstance(item, dict)]
    total = len(items)
    if total <= 0:
        return "任务清单为空。"
    completed = sum(1 for item in items if str(item.get("status") or "").strip() == "completed")
    active_id = str(parsed.get("active_item_id") or "").strip()
    active_item = next(
        (
            item
            for item in items
            if str(item.get("todo_id") or "").strip() == active_id
            or str(item.get("status") or "").strip() == "in_progress"
        ),
        {},
    )
    active_text = _safe_public_action_text(active_item.get("active_form") or active_item.get("content"))
    if active_text:
        return f"任务清单：{completed}/{total} 已完成，正在：{active_text[:160]}。"
    return f"任务清单：{completed}/{total} 已完成。"


def _is_agent_todo_payload(value: dict[str, Any]) -> bool:
    if not value:
        return False
    if isinstance(value.get("items"), list):
        return True
    return any(str(value.get(key) or "").strip() for key in ("plan_id", "active_item_id", "status", "error"))


def _tool_arguments_preview(args: dict[str, Any]) -> str:
    if not args:
        return ""
    parts: list[str] = []
    priority = (
        "path",
        "file",
        "file_path",
        "target",
        "start_line",
        "line_count",
        "end_line",
        "range",
        "query",
        "pattern",
        "cwd",
        "command",
        "cmd",
        "script",
        "code",
        "url",
    )
    skipped = {"content", "replacement", "new_content", "old_content", "patch", "diff"}
    ordered_keys = [key for key in priority if key in args]
    ordered_keys.extend(key for key in sorted(args.keys()) if key not in ordered_keys and key not in skipped)
    for key in ordered_keys:
        value = args.get(key)
        if isinstance(value, (dict, list, tuple)):
            continue
        text = _safe_public_action_text(f"{key}={value}")
        if text:
            parts.append(text[:120] if key in {"command", "cmd", "script", "code"} else text[:80])
        if len(parts) >= 6:
            break
    return ", ".join(parts)[:240]


def _safe_public_tool_target(args: dict[str, Any], *, tool_name: str = "") -> str:
    keys = ["path", "file", "file_path", "target", "url", "query"]
    if _is_public_command_tool(tool_name):
        keys = ["command", "cmd", "script", "code", *keys]
    for key in keys:
        value = _safe_public_action_text(args.get(key))
        if value:
            return value[:180]
    return ""


def _is_public_command_tool(tool_name: str) -> bool:
    return str(tool_name or "").strip().lower() in {
        "bash",
        "cmd",
        "command",
        "powershell",
        "python_repl",
        "shell",
        "terminal",
    }


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


def _semantic_event_payload(raw_data: dict[str, Any]) -> dict[str, Any]:
    raw_event = _record(raw_data.get("event"))
    payload = _record(raw_event.get("payload") or raw_data.get("payload") or raw_data)
    preview = _record(payload.get("preview"))
    return preview or payload


def _int_value(value: Any, *, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


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
    label = _public_runtime_reason_label(reason)
    if label:
        return label
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
    if _looks_like_runtime_reason_code(reason):
        return "状态已更新"
    return reason


def _public_runtime_reason_label(reason: str) -> str:
    normalized = str(reason or "").strip()
    return {
        "insufficient_balance": "模型服务余额不足",
        "payment_required": "模型服务余额不足",
        "billing": "模型服务余额不足",
        "rate_limit": "模型请求触发限流",
        "timeout": "模型请求超时",
        "provider_unavailable": "模型服务暂时不可用",
        "provider_error": "模型调用失败",
        "single_agent_turn_model_failed": "模型调用失败",
        "model_runtime_unavailable": "模型运行时不可用",
        "configuration": "模型配置有误",
        "agent_contract_feedback_required": "动作合同未通过",
        "model_action_contract_feedback_required": "动作合同未通过",
        "model_action_recovery_required": "动作需要修正",
        "user_input_required": "等待你的确认",
        "waiting_executor": "等待继续",
        "waiting_user": "等待你的确认",
        "waiting_approval": "等待权限确认",
        "task_executor_scheduled": "任务已进入执行流程",
        "runtime_cell_missing_after_restart": "连接恢复后需要重新接续运行",
        "runtime_cell_cancelled": "输出流已取消",
        "missing_terminal_event": "输出流没有正常收口",
        "stream_exception": "输出流异常中断",
        "stream_cancelled": "输出流已取消",
        "tool_budget_exhausted": "本轮工具预算已用完",
        "single_turn_tool_iteration_limit": "本轮工具预算已用完",
        "single_agent_turn_empty_response": "agent 未生成可发布回复",
        "tool_limit_missing_answer": "agent 收口缺少可发布回复",
        "completed": "已完成",
        "failed": "处理失败",
        "stopped": "运行已停止",
        "aborted": "运行已停止",
        "cancelled": "运行已停止",
        "canceled": "运行已停止",
    }.get(normalized, "")


def _looks_like_runtime_reason_code(reason: str) -> bool:
    normalized = str(reason or "").strip()
    if not normalized:
        return False
    if any(ord(ch) > 127 for ch in normalized):
        return False
    return "_" in normalized or normalized.startswith(("task-", "task:", "stream-", "stream:", "runtime-", "runtime:"))


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
    lifecycle_state: ProjectionLifecycleState | None = None,
    public_anchor: dict[str, Any] | None = None,
) -> None:
    attach_public_projection_event(
        public_event_type,
        data,
        session_id=session_id,
        sequence=sequence,
        public_anchor=public_anchor,
        lifecycle_state=lifecycle_state,
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


def _public_replay_stream_data(public_event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    payload = _redact_public_stream_data(dict(data or {}))
    return sanitize_public_stream_event_data_for_replay(public_event_type, payload)


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
