from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, replace
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from api.deps import require_runtime
from harness.entrypoint import HarnessRuntimeRequest
from harness.runtime.projection.projector import ProjectionLifecycleState, attach_public_projection_event
from harness.runtime.public_progress import public_runtime_progress_summary
from harness.task_run_status import is_stopped_or_terminal_task_run
from integrations.vscode_connection import get_vscode_connection_store
from runtime.output_boundary import (
    contains_inline_pseudo_tool_call,
    contains_internal_protocol,
    sanitize_visible_assistant_content,
)
from runtime.model_gateway.assistant_stream_frame import (
    assistant_message_ref,
)
from runtime.output_stream.public_contract import (
    ASSISTANT_STREAM_REPAIR_EVENT,
    ASSISTANT_TEXT_DELTA_EVENT,
    ASSISTANT_TEXT_FINAL_EVENT,
    CHAT_TURN_BOUND_EVENT,
    SESSION_OUTPUT_COMMIT_ACK_EVENT,
    SESSION_OUTPUT_COMMIT_CHECKED_EVENT,
    SESSION_OUTPUT_COMMIT_FAILED_EVENT,
    SESSION_OUTPUT_COMMIT_SKIPPED_EVENT,
    TASK_BRIDGE_STARTED_EVENT,
    TASK_BRIDGE_TERMINAL_EVENT,
    TOOL_CALL_REQUESTED_EVENT,
    TOOL_ITEM_COMPLETED_EVENT,
    TOOL_ITEM_STARTED_EVENT,
    TOOL_PERMISSION_DECIDED_EVENT,
    TURN_COMPLETED_EVENT,
    event_requires_public_projection,
)
from runtime.shared.tool_identity import ensure_tool_call_id, permission_decision_id
from runtime.shared.runtime_run_registry import RuntimeRun
from runtime.shared.stream_replay import parse_stream_event_id
from sessions import SessionProjectBindingConflict, validate_session_id
from task_system.session_scope import assert_optional_session_scope

router = APIRouter()
logger = logging.getLogger(__name__)
TERMINAL_STREAM_EVENTS = {TURN_COMPLETED_EVENT}
TERMINAL_RUN_STATUSES = {"completed", "failed", "stopped", "orphaned"}
TASK_EXECUTOR_HANDOFF_REASONS = {"task_executor_scheduled"}
TASK_BRIDGE_PUBLIC_EVENT_TYPES = {
    ASSISTANT_STREAM_REPAIR_EVENT,
    ASSISTANT_TEXT_DELTA_EVENT,
    ASSISTANT_TEXT_FINAL_EVENT,
    "step_summary_recorded",
    "task_model_action_wait_heartbeat",
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
TASK_TERMINAL_STATUSES = {"completed", "failed", "blocked", "aborted", "cancelled", "canceled", "stopped", "waiting_executor", "waiting_user", "waiting_approval"}
TURN_CONTEXT_REQUIRED_PUBLIC_EVENTS = {
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
    payload_context = dict(payload_editor_context or {})
    if not allow_vscode_fallback:
        return payload_context
    vscode_context = get_vscode_connection_store().latest_editor_context(
        session_id,
        session_manager=session_manager,
    )
    if not payload_context:
        return vscode_context
    if not vscode_context:
        return payload_context
    return _merge_editor_contexts(payload_context, vscode_context)


def _merge_editor_contexts(payload_context: dict[str, Any], vscode_context: dict[str, Any]) -> dict[str, Any]:
    payload_active = dict(payload_context.get("active_file") or {})
    vscode_active = dict(vscode_context.get("active_file") or {})
    payload_visible = _editor_visible_file_list(payload_context)
    vscode_visible = _editor_visible_file_list(vscode_context)
    merged: dict[str, Any] = dict(payload_context)
    merged["workspace_roots"] = _dedupe_editor_context_values(
        list(payload_context.get("workspace_roots") or []) + list(vscode_context.get("workspace_roots") or [])
    )
    active_file = _merge_active_editor_file(payload_active, vscode_active)
    if active_file:
        merged["active_file"] = active_file
    elif "active_file" in merged:
        merged.pop("active_file", None)
    visible_files = _merge_visible_editor_files(payload_visible, vscode_visible)
    if visible_files:
        merged["visible_files"] = visible_files
    elif "visible_files" in merged:
        merged.pop("visible_files", None)
    diagnostics = _merge_editor_diagnostics(
        list(payload_context.get("diagnostics") or []),
        list(vscode_context.get("diagnostics") or []),
    )
    if diagnostics:
        merged["diagnostics"] = diagnostics
    elif "diagnostics" in merged:
        merged.pop("diagnostics", None)
    sources = _dedupe_editor_context_values([payload_context.get("source"), vscode_context.get("source")])
    if sources:
        merged["source"] = "+".join(str(item) for item in sources)
    merged["authority"] = "api.chat.effective_editor_context"
    merged["merge_reason"] = _editor_context_merge_reason(payload_active, vscode_active, payload_visible, vscode_visible)
    return {key: value for key, value in merged.items() if value not in (None, "", [], {})}


def _editor_visible_file_list(context: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in list(context.get("visible_files") or []) if isinstance(item, dict)]


def _merge_active_editor_file(payload_active: dict[str, Any], vscode_active: dict[str, Any]) -> dict[str, Any]:
    payload_path = str(payload_active.get("path") or payload_active.get("uri") or "").strip()
    vscode_path = str(vscode_active.get("path") or vscode_active.get("uri") or "").strip()
    if not payload_path:
        return dict(vscode_active)
    if not vscode_path or _normalized_editor_path(payload_path) != _normalized_editor_path(vscode_path):
        return dict(payload_active)
    merged = dict(vscode_active)
    merged.update(payload_active)
    for key in ("selection", "content_preview", "visible_ranges"):
        if not merged.get(key) and vscode_active.get(key):
            merged[key] = vscode_active.get(key)
    if vscode_active.get("dirty") is True:
        merged["dirty"] = True
    return {key: value for key, value in merged.items() if value not in (None, "", [], {})}


def _merge_visible_editor_files(payload_visible: list[dict[str, Any]], vscode_visible: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*payload_visible, *vscode_visible]:
        path = str(item.get("path") or item.get("uri") or "").strip()
        key = _normalized_editor_path(path)
        if not path or key in seen:
            continue
        seen.add(key)
        result.append({field: value for field, value in dict(item).items() if value not in (None, "", [], {})})
    return result[:20]


def _merge_editor_diagnostics(payload_diagnostics: list[Any], vscode_diagnostics: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for item in [*payload_diagnostics, *vscode_diagnostics]:
        marker = repr(item)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result[:50]


def _editor_context_merge_reason(
    payload_active: dict[str, Any],
    vscode_active: dict[str, Any],
    payload_visible: list[dict[str, Any]],
    vscode_visible: list[dict[str, Any]],
) -> str:
    if not payload_active and not payload_visible and (vscode_active or vscode_visible):
        return "payload_workspace_only_vscode_file_focus"
    payload_path = str(payload_active.get("path") or payload_active.get("uri") or "").strip()
    vscode_path = str(vscode_active.get("path") or vscode_active.get("uri") or "").strip()
    if payload_path and vscode_path and _normalized_editor_path(payload_path) == _normalized_editor_path(vscode_path):
        return "payload_active_file_enriched_from_vscode"
    return "payload_editor_context_preferred"


def _dedupe_editor_context_values(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.replace("\\", "/").rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _normalized_editor_path(value: str) -> str:
    return str(value or "").replace("\\", "/").rstrip("/").lower()


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
    bridge_context: ChatTaskBridgeContext | None = None
    turn_context: PublicTurnOutputContext | None = None
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
        start_event = replay.append_public_event(
            current,
            public_event_type="chat_run_started",
            data=start_data,
        )
        current = _safe_mark_run_event(registry, current, latest_event_offset=start_event.offset, status="running")
        async for event in runtime.harness_runtime.astream(request):
            event_type = str(event.get("type", "message") or "message")
            raw_refs = _runtime_run_refs_from_event(event)
            runtime_refs = _runtime_run_refs_for_public_event(runtime, request.session_id, event)
            event_task_run_id = raw_refs.get("task_run_id", "")
            runtime_turn_run_id = raw_refs.get("turn_run_id", "") or runtime_refs.get("turn_run_id", "")
            runtime_active_turn_id = raw_refs.get("active_turn_id", "") or runtime_refs.get("active_turn_id", "")
            if turn_context is None:
                created_turn_context = _public_turn_context_from_event(
                    run=run,
                    request=request,
                    event=event,
                    fallback_turn_run_id=runtime_turn_run_id,
                    fallback_turn_id=runtime_active_turn_id,
                    public_sequence_started_at=int(getattr(current, "latest_event_offset", -1) or -1) + 1,
                )
                if created_turn_context is not None:
                    turn_context = created_turn_context
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
                    continue
                if _is_task_executor_handoff_terminal(public_event_type, data):
                    bridged_task_run_id = _task_run_id_from_public_data(data) or runtime_refs.get("task_run_id", "")
                    if turn_context is None:
                        current = _append_chat_public_event(
                            registry=registry,
                            replay=replay,
                            current=current,
                            public_event_type=TURN_COMPLETED_EVENT,
                            data=_turn_completed_data(
                                "error",
                                {
                                    "status": "failed",
                                    "turn_run_id": runtime_turn_run_id,
                                    "task_run_id": bridged_task_run_id,
                                    "error": "运行中断",
                                    "code": "task_bridge_context_missing",
                                    "reason": "Task bridge handoff arrived before a public turn context was available.",
                                },
                            ),
                            session_id=request.session_id,
                            projection_lifecycle=projection_lifecycle,
                            runtime_task_run_id=bridged_task_run_id,
                            runtime_turn_run_id=runtime_turn_run_id,
                            runtime_active_turn_id=runtime_active_turn_id,
                        )
                        terminal_event = TURN_COMPLETED_EVENT
                        break
                    bridge_context = _chat_task_bridge_context_from_handoff(
                        run=run,
                        request=request,
                        turn_context=turn_context,
                        public_data=data,
                        source_event=event,
                        task_run_id=bridged_task_run_id,
                        public_sequence_base=int(getattr(current, "latest_event_offset", -1) or -1) + 1,
                    )
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
                    break
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
                    public_anchor=turn_context.anchor() if turn_context is not None else None,
                )
                terminal_event = public_event_type if public_event_type in TERMINAL_STREAM_EVENTS else terminal_event
                if public_event_type in TERMINAL_STREAM_EVENTS:
                    break
            if terminal_event or bridge_context is not None:
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
        if _bridge_context_has_live_bound_task(runtime, bridge_context):
            _safe_update_run(
                registry,
                run.stream_run_id,
                fallback=current,
                status="orphaned",
                terminal_event="",
                diagnostics={
                    "reason": "projection_stream_exception",
                    "failure_reason": str(exc) or "Chat stream failed.",
                    "runtime_task_run_id": bridge_context.task_run_id if bridge_context else "",
                    "active_turn_id": bridge_context.turn_id if bridge_context else "",
                    "chat_stream_bridge": "task_run",
                },
            )
            return
        logged = replay.append_public_event(
            current,
            public_event_type=TURN_COMPLETED_EVENT,
            data=_turn_completed_data(
                "error",
                {
                    "error": "运行中断",
                    "code": "stream_exception",
                    "reason": str(exc) or "Chat stream failed.",
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
        if _bridge_context_has_live_bound_task(runtime, bridge_context):
            _safe_update_run(
                registry,
                run.stream_run_id,
                fallback=current,
                status="orphaned",
                terminal_event="",
                diagnostics={
                    "reason": "projection_stream_missing_terminal",
                    "runtime_task_run_id": bridge_context.task_run_id if bridge_context else "",
                    "active_turn_id": bridge_context.turn_id if bridge_context else "",
                    "chat_stream_bridge": "task_run",
                },
            )
            return
        logged = replay.append_public_event(
            current,
            public_event_type=TURN_COMPLETED_EVENT,
            data=_turn_completed_data(
                "error",
                {
                    "error": "运行中断",
                    "code": "missing_terminal_event",
                    "reason": "Chat stream ended without a terminal event.",
                },
            ),
        )
        current = _safe_mark_run_event(current=current, registry=registry, latest_event_offset=logged.offset, status="failed", terminal_event=TURN_COMPLETED_EVENT)
        host.close_chat_turn_run_for_stream_failure_best_effort(
            current,
            code="missing_terminal_event",
            reason="Chat stream ended without a terminal event.",
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
    logged = replay.append_public_event(current, public_event_type=public_event_type, data=payload)
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


def _public_turn_context_from_event(
    *,
    run: RuntimeRun,
    request: HarnessRuntimeRequest,
    event: dict[str, Any],
    fallback_turn_run_id: str = "",
    fallback_turn_id: str = "",
    public_sequence_started_at: int = 0,
) -> PublicTurnOutputContext | None:
    event_type = str(event.get("type") or "").strip()
    if event_type not in {"harness_run_started", "single_agent_turn_started"}:
        return None
    refs = _runtime_run_refs_from_event(event)
    turn_run_id = str(refs.get("turn_run_id") or fallback_turn_run_id or "").strip()
    turn_id = str(refs.get("active_turn_id") or fallback_turn_id or _turn_id_from_turn_run_id(turn_run_id)).strip()
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
                output_observed = output_observed or terminal_output_state.get("output_observed", False)
                commit_observed = commit_observed or terminal_output_state.get("commit_observed", False)
                if terminal:
                    return current
            if _task_run_snapshot_is_terminal(host, normalized_task_run_id):
                current = _append_task_bridge_terminal_from_snapshot(
                    runtime,
                    run,
                    current,
                    request=request,
                    bridge_context=bridge_context,
                    projection_lifecycle=projection_lifecycle,
                    output_observed=output_observed,
                    commit_observed=commit_observed,
                )
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
            if public_event_type in {ASSISTANT_TEXT_DELTA_EVENT, ASSISTANT_TEXT_FINAL_EVENT, ASSISTANT_STREAM_REPAIR_EVENT}:
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


def _append_task_bridge_terminal_from_snapshot(
    runtime: Any,
    run: RuntimeRun,
    current: RuntimeRun,
    *,
    request: HarnessRuntimeRequest,
    bridge_context: ChatTaskBridgeContext,
    projection_lifecycle: ProjectionLifecycleState,
    output_observed: bool,
    commit_observed: bool,
) -> RuntimeRun:
    host = runtime.harness_runtime.single_agent_runtime_host
    task_run = _task_run_snapshot(host, bridge_context.task_run_id)
    context = _task_terminal_context_from_task_run(task_run, fallback_task_run_id=bridge_context.task_run_id)
    return _append_task_bridge_terminal(
        runtime,
        run,
        current,
        request=request,
        context=context,
        projection_lifecycle=projection_lifecycle,
        bridge_context=bridge_context,
        task_event=None,
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
    final_answer = _safe_visible_final_answer(context.get("final_answer"))
    if final_answer and (not output_observed or not commit_observed):
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
                "reason": "task_terminal_final_without_output_event" if not output_observed else "task_terminal_final_without_commit_event",
                "error": "运行中断",
                "summary": "task_terminal_final_without_output_event" if not output_observed else "task_terminal_final_without_commit_event",
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
            "error": "运行中断" if status == "failed" else "",
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
    return task_run is not None and not is_stopped_or_terminal_task_run(task_run)


def _task_run_snapshot_is_terminal(host: Any, task_run_id: str) -> bool:
    task_run = _task_run_snapshot(host, task_run_id)
    return str(task_run.get("status") or "").strip().lower() in TASK_TERMINAL_STATUSES


def _task_run_snapshot(host: Any, task_run_id: str) -> dict[str, Any]:
    try:
        task_run = host.state_index.get_task_run(task_run_id)
    except Exception:
        return {}
    if task_run is None:
        return {}
    if hasattr(task_run, "to_dict"):
        return dict(task_run.to_dict())
    return dict(task_run or {}) if isinstance(task_run, dict) else {}


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
    diagnostics = _record(task.get("diagnostics"))
    output_commit = _record(diagnostics.get("output_commit"))
    task_run_id = str(task.get("task_run_id") or lifecycle_payload.get("task_run_id") or fallback_task_run_id or "").strip()
    status = str(task.get("status") or lifecycle_payload.get("status") or "").strip().lower()
    terminal_reason = str(task.get("terminal_reason") or lifecycle_payload.get("terminal_reason") or status or "completed").strip()
    return {
        "task_run_id": task_run_id,
        "turn_id": str(diagnostics.get("turn_id") or _turn_id_from_task_run_id(task_run_id) or "").strip(),
        "turn_run_id": str(diagnostics.get("turn_run_id") or "").strip(),
        "status": status,
        "terminal_reason": terminal_reason,
        "final_answer": diagnostics.get("final_answer") or "",
        "message_ref": str(
            output_commit.get("anchor_message_id")
            or output_commit.get("message_ref")
            or output_commit.get("message_id")
            or ""
        ).strip(),
        "answer_source": str(diagnostics.get("answer_source") or "harness.loop.task_executor.completed"),
        "error_summary": "运行中断" if status in {"failed", "blocked"} else "",
    }


def _safe_visible_final_answer(value: Any) -> str:
    content = sanitize_visible_assistant_content(str(value or "")).strip()
    if not content:
        return ""
    if contains_internal_protocol(content) or contains_inline_pseudo_tool_call(content):
        return ""
    return content


def _public_turn_status_for_task_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status in {"completed", "waiting_executor", "waiting_user", "waiting_approval"}:
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


def _task_run_id_from_public_data(data: dict[str, Any]) -> str:
    for value in (data.get("task_run_id"), data.get("runtime_task_run_id")):
        normalized = str(value or "").strip()
        if normalized.startswith("taskrun:"):
            return normalized
    return ""


def _turn_id_from_task_run_id(task_run_id: str) -> str:
    normalized = str(task_run_id or "").strip()
    if not normalized.startswith("taskrun:"):
        return ""
    candidate = normalized[len("taskrun:"):]
    if not candidate.startswith("turn:"):
        return ""
    parts = candidate.split(":")
    for index in range(len(parts) - 1, 1, -1):
        if parts[index].isdigit():
            return ":".join(parts[: index + 1])
    return candidate


def _turn_id_from_turn_run_id(turn_run_id: str) -> str:
    normalized = str(turn_run_id or "").strip()
    if not normalized.startswith("turnrun:"):
        return ""
    candidate = normalized[len("turnrun:"):]
    return candidate if candidate.startswith("turn:") else ""


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
    if normalized in {"model_action_request", "agent_turn_terminal"}:
        return []
    if normalized == "harness_run_started" and _is_turn_trace_only_harness_start(event):
        return []
    raw_data = {key: value for key, value in dict(event).items() if key != "type"}
    if normalized in {"step_summary_recorded", "runtime_step_summary"}:
        data = _runtime_step_summary_data(raw_data)
        return [("runtime_step_summary", data)] if data else []
    if normalized == "task_model_action_wait_heartbeat":
        data = _task_model_wait_status_data(raw_data)
        return [("runtime_status", data)] if data else []
    if normalized in {ASSISTANT_TEXT_DELTA_EVENT, ASSISTANT_TEXT_FINAL_EVENT, ASSISTANT_STREAM_REPAIR_EVENT}:
        data = _assistant_stream_public_data(normalized, raw_data)
        return [(normalized, data)] if data else []
    if normalized in {"done", "error", "stopped"}:
        return [(TURN_COMPLETED_EVENT, _turn_completed_data(normalized, raw_data))]
    if normalized in {"answer_candidate", "assistant_text", "token"}:
        return []
    if normalized in {"model_action_admission", "model_action_admission_checked"}:
        return _tool_action_public_events(raw_data)
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
        "error_summary": "运行中断" if status == "failed" else "",
        "stopped_reason": _safe_public_action_text(raw_data.get("reason") or raw_data.get("content")) if status == "stopped" else "",
        "runtime_event_id": str(raw_data.get("runtime_event_id") or raw_data.get("event_id") or ""),
        "source_task_event_id": str(raw_data.get("source_task_event_id") or ""),
        "source_task_event_offset": raw_data.get("source_task_event_offset"),
        "source_event_type": str(raw_data.get("source_event_type") or ""),
    }
    return {key: value for key, value in payload.items() if value not in ("", None)}


def _tool_action_public_events(raw_data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    feedback_data = _model_action_feedback_step_data(raw_data)
    if feedback_data:
        events.append(("runtime_step_summary", feedback_data))
    request_items = _tool_call_requested_items(raw_data)
    if not request_items:
        return events
    for request_data in request_items:
        permission_data = _tool_permission_decided_data(raw_data, request_data=request_data)
        events.append((TOOL_CALL_REQUESTED_EVENT, request_data))
        if permission_data:
            events.append((TOOL_PERMISSION_DECIDED_EVENT, permission_data))
    return events


def _model_action_feedback_step_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    raw_event = _record(raw_data.get("event"))
    payload = _record(raw_event.get("payload") or raw_data)
    refs = _record(raw_event.get("refs"))
    request = _record(payload.get("model_action_request") or raw_data.get("model_action_request"))
    if not request:
        return {}
    action_state = _public_action_state(request.get("public_action_state"))
    content = (
        _safe_public_action_text(request.get("public_progress_note"))
        or _safe_public_action_text(action_state.get("current_judgment"))
    )
    if not content:
        return {}
    runtime_event_id = str(raw_event.get("event_id") or raw_data.get("event_id") or "").strip()
    feedback_identity = _model_action_feedback_identity(
        payload=payload,
        refs=refs,
        request=request,
        runtime_event_id=runtime_event_id,
    )
    feedback_event_id = f"model-action-feedback:{feedback_identity}" if feedback_identity else runtime_event_id
    data: dict[str, Any] = {
        "status": "running",
        "step": "model_action_public_feedback",
        "summary": content,
        "feedback_identity": feedback_identity,
        "public_progress_note": _safe_public_action_text(request.get("public_progress_note")),
        "current_judgment": _safe_public_action_text(action_state.get("current_judgment")),
        "next_action": _safe_public_action_text(action_state.get("next_action")),
        "turn_run_id": str(payload.get("turn_run_id") or refs.get("turn_run_ref") or raw_data.get("turn_run_id") or ""),
        "task_run_id": str(payload.get("task_run_id") or refs.get("task_run_ref") or raw_data.get("task_run_id") or raw_data.get("runtime_task_run_id") or ""),
        "runtime_event_id": feedback_event_id,
        "source_task_event_id": runtime_event_id,
        "presentation_source": "model_action.public_progress_note"
        if _safe_public_action_text(request.get("public_progress_note"))
        else "model_action.public_action_state",
    }
    return _redact_public_stream_data({key: value for key, value in data.items() if value not in ("", None)})


def _model_action_feedback_identity(
    *,
    payload: dict[str, Any],
    refs: dict[str, Any],
    request: dict[str, Any],
    runtime_event_id: str,
) -> str:
    return str(
        refs.get("batch_action_request_ref")
        or request.get("batch_action_request_ref")
        or refs.get("action_request_ref")
        or payload.get("action_request_ref")
        or request.get("action_request_ref")
        or refs.get("request_id")
        or payload.get("request_id")
        or request.get("request_id")
        or refs.get("runtime_invocation_packet_ref")
        or payload.get("runtime_invocation_packet_ref")
        or request.get("runtime_invocation_packet_ref")
        or runtime_event_id
        or ""
    ).strip()


def _tool_call_requested_items(raw_data: dict[str, Any]) -> list[dict[str, Any]]:
    raw_event = _record(raw_data.get("event"))
    payload = _record(raw_event.get("payload") or raw_data)
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
        tool = ensure_tool_call_id(
            _record(raw_tool),
            request_id=request_id or runtime_event_id or f"model-action:{index + 1}",
            ordinal=index if len(tool_calls) > 1 else None,
        )
        tool_name = str(tool.get("tool_name") or tool.get("name") or (request.get("tool_name") if len(tool_calls) == 1 else "") or "").strip()
        tool_call_id = str(tool.get("id") or tool.get("tool_call_id") or "").strip()
        if not tool_name or not tool_call_id or _is_agent_todo_tool_name(tool_name):
            continue
        args = _tool_call_args(tool, request=request if len(tool_calls) == 1 else {})
        target = _safe_public_tool_target(args)
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
        if not tool:
            tool = {
                "id": request.get("tool_call_id"),
                "name": request.get("tool_name"),
                "args": request.get("tool_args"),
            }
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
        request.get("tool_args"),
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
    payload = _record(raw_event.get("payload") or raw_data)
    refs = _record(raw_event.get("refs"))
    admission = _record(payload.get("admission") or payload.get("admission_decision") or raw_data.get("admission"))
    if not admission:
        return {}
    decision = str(admission.get("decision") or "").strip()
    tool_call_id = str(request_data.get("tool_call_id") or admission.get("action_request_ref") or "").strip()
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
    error = _safe_public_action_text(
        tool_observation.get("error")
        or observation.get("error")
        or result_envelope.get("error")
        or execution_receipt.get("error")
    )
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


def _task_model_wait_status_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    raw_event = _record(raw_data.get("event"))
    payload = _record(raw_event.get("payload") or raw_data.get("payload") or raw_data)
    refs = _record(raw_event.get("refs"))
    task_run_id = str(
        payload.get("task_run_id")
        or refs.get("task_run_ref")
        or raw_event.get("task_run_id")
        or raw_data.get("task_run_id")
        or raw_data.get("runtime_task_run_id")
        or ""
    ).strip()
    runtime_event_id = str(raw_event.get("event_id") or raw_data.get("runtime_event_id") or raw_data.get("event_id") or "").strip()
    source_event_id = str(raw_event.get("event_id") or raw_data.get("source_task_event_id") or "").strip()
    source_offset = raw_event.get("offset") or raw_data.get("source_task_event_offset") or raw_data.get("event_offset")
    data: dict[str, Any] = {
        "task_run_id": task_run_id,
        "status": "running",
        "state": "running",
        "title": "正在思考",
        "summary": "正在思考",
        "presentation_source": "runtime.model_wait",
        "status_kind": "model_wait_placeholder",
        "item_id": f"model-wait:{task_run_id}" if task_run_id else "",
    }
    if runtime_event_id:
        data["runtime_event_id"] = runtime_event_id
    if source_event_id:
        data["source_task_event_id"] = source_event_id
    if source_offset not in (None, ""):
        data["source_task_event_offset"] = source_offset
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
        text = _safe_public_action_text(value)
        if text:
            return text[:500]
    structured = _record(result_envelope.get("structured_payload"))
    for key in ("summary", "message", "error"):
        text = _safe_public_action_text(structured.get(key))
        if text:
            return text[:500]
    return ""


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
        parsed = _record_or_json_object(value)
        if parsed:
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
            parts.append(text[:120] if key == "command" else text[:80])
        if len(parts) >= 6:
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
        return "运行状态已更新"
    return reason


def _public_runtime_reason_label(reason: str) -> str:
    normalized = str(reason or "").strip()
    return {
        "user_input_required": "等待你的确认",
        "waiting_executor": "等待继续",
        "waiting_user": "等待你的确认",
        "waiting_approval": "等待权限确认",
        "task_executor_scheduled": "任务已进入执行流程",
        "background_executor_missing_after_restart": "连接恢复后需要重新接续运行",
        "missing_terminal_event": "输出流没有正常收口",
        "stream_exception": "输出流异常中断",
        "stream_cancelled": "输出流已取消",
        "completed": "已完成",
        "failed": "运行中断",
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
    if not active_turn_id:
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
