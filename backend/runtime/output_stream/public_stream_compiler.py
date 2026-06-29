from __future__ import annotations

import json
import re
from typing import Any

from harness.runtime.output_boundary import (
    contains_inline_pseudo_tool_call,
    contains_internal_protocol,
    sanitize_visible_assistant_content,
)
from harness.runtime.projection.projector import ProjectionLifecycleState, attach_public_projection_event
from harness.runtime.public_progress import public_runtime_progress_summary
from harness.runtime.runtime_private_text import looks_like_runtime_private_artifact_text
from runtime.model_gateway.assistant_stream_frame import (
    ASSISTANT_STREAM_REPAIR_EVENT,
    ASSISTANT_TEXT_DELTA_EVENT,
    ASSISTANT_TEXT_FINAL_EVENT,
)
from runtime.output_stream.public_contract import (
    ASSISTANT_PUBLIC_FEEDBACK_EVENT,
    CHAT_TURN_BOUND_EVENT,
    SESSION_OUTPUT_COMMIT_ACK_EVENT,
    SESSION_OUTPUT_COMMIT_CHECKED_EVENT,
    SESSION_OUTPUT_COMMIT_FAILED_EVENT,
    SESSION_OUTPUT_COMMIT_SKIPPED_EVENT,
    TASK_BRIDGE_STARTED_EVENT,
    TASK_BRIDGE_TERMINAL_EVENT,
    TASK_ORIGIN_BOUND_EVENT,
    TOOL_CALL_REQUESTED_EVENT,
    TOOL_ITEM_COMPLETED_EVENT,
    TOOL_ITEM_STARTED_EVENT,
    TOOL_PERMISSION_DECIDED_EVENT,
    TURN_COMPLETED_EVENT,
)
from runtime.shared.stream_replay import sanitize_public_stream_event_data_for_replay
from runtime.shared.tool_identity import permission_decision_id


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

LEGACY_BODY_WRITER_EVENTS = {"answer_candidate", "assistant_text", "token"}

TOOL_FAILURE_FEEDBACK_RE = re.compile(
    r"^(?:[A-Za-z][A-Za-z0-9 _./-]{0,80}\s+failed|tool_policy_rejection):",
    flags=re.IGNORECASE,
)
LINE_NUMBERED_TOOL_OUTPUT_RE = re.compile(r"(?m)^\s*\d{1,6}\s*\|")
PUBLIC_READ_WINDOW_MAX_CHARS = 50000
PUBLIC_READ_WINDOW_MAX_LINES = 500

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
        "session_id",
        "stream_run_id",
        "turn_id",
        "active_turn_id",
        "turn_run_id",
        "task_run_id",
        "message_id",
        "message_ref",
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
        "runtime_event_id",
        "source_task_event_id",
        "source_task_event_offset",
        "event",
    },
    ASSISTANT_PUBLIC_FEEDBACK_EVENT: {
        "session_id",
        "stream_run_id",
        "turn_id",
        "active_turn_id",
        "turn_run_id",
        "task_run_id",
        "message_id",
        "message_ref",
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
        "runtime_event_id",
        "source_task_event_id",
        "source_task_event_offset",
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
        "created_at",
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
        "created_at",
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
        "created_at",
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
        "content_window",
        "runtime_event_id",
        "created_at",
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


def project_public_stream_event(event_type: str, event: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    normalized = str(event_type or "message").strip() or "message"
    raw_data = {key: value for key, value in dict(event).items() if key != "type"}
    if normalized in INTERNAL_STREAM_EVENTS:
        return []
    if normalized == "model_action_request":
        data = _model_action_request_public_data(raw_data)
        return [(normalized, data)] if data else []
    if normalized == "agent_turn_terminal":
        data = _agent_turn_terminal_completed_data(raw_data)
        return [(TURN_COMPLETED_EVENT, data)] if data else []
    if normalized == "runtime_evidence_projection_published":
        data = _runtime_evidence_projection_public_data(raw_data)
        return [(normalized, data)] if data else []
    if normalized == "agent_contract_feedback_required":
        return []
    if normalized == "harness_run_started" and _is_turn_trace_only_harness_start(event):
        return []
    if normalized in {"step_summary_recorded", "runtime_step_summary"}:
        data = _runtime_step_summary_data(raw_data)
        return [("runtime_step_summary", data)] if data else []
    if normalized == ASSISTANT_PUBLIC_FEEDBACK_EVENT:
        data = _runtime_step_summary_data(raw_data)
        return [(ASSISTANT_PUBLIC_FEEDBACK_EVENT, data)] if data else []
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
        return [(TURN_COMPLETED_EVENT, turn_completed_data(normalized, raw_data))]
    if normalized in LEGACY_BODY_WRITER_EVENTS:
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
        data = {key: value for key, value in raw_data.items() if key not in INTERNAL_PUBLIC_DATA_KEYS}
    else:
        data = {key: raw_data[key] for key in allowed if key in raw_data}
    data = _redact_public_stream_data(data)
    if "terminal_reason" in data:
        data["terminal_reason"] = public_terminal_reason(data.get("terminal_reason"))
    if normalized == "runtime_branch_decided":
        data["runtime_branch"] = _public_runtime_branch(dict(data.get("runtime_branch") or {}))
    elif normalized == "single_agent_turn_started":
        data = {
            "runtime_branch": _public_runtime_branch(dict(data.get("runtime_branch") or {})),
            "allowed_action_types": list(data.get("allowed_action_types") or []),
            "turn_id": str(raw_data.get("turn_id") or ""),
            "turn_run_id": str(raw_data.get("turn_run_id") or ""),
            "active_turn_id": str(raw_data.get("active_turn_id") or raw_data.get("turn_id") or ""),
        }
    return [(normalized, data)]


def public_replay_stream_data(public_event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    payload = _redact_public_stream_data(dict(data or {}))
    return sanitize_public_stream_event_data_for_replay(public_event_type, payload)


def attach_public_projection_frame(
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


def turn_completed_data(source_event_type: str, raw_data: dict[str, Any]) -> dict[str, Any]:
    source = str(source_event_type or "").strip().lower()
    requested_status = str(raw_data.get("status") or "").strip().lower()
    status = requested_status if requested_status in {"completed", "failed", "stopped"} else "completed"
    if source == "error":
        status = "failed"
    elif source == "stopped":
        status = "stopped"
    terminal_reason = public_terminal_reason(
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


def _agent_turn_terminal_completed_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    raw_event = _record(raw_data.get("event"))
    payload = _record(raw_event.get("payload")) or _record(raw_data.get("payload")) or dict(raw_data or {})
    refs = _record(raw_event.get("refs"))
    event_run_id = str(raw_event.get("run_id") or "").strip()
    material = dict(payload or {})
    material["status"] = _turn_completed_status_from_agent_terminal(material.get("status") or material.get("state"))
    material.setdefault("turn_run_id", event_run_id if event_run_id.startswith("turnrun:") else "")
    material.setdefault("turn_id", str(refs.get("turn_ref") or ""))
    material.setdefault("runtime_event_id", str(raw_event.get("event_id") or raw_data.get("runtime_event_id") or ""))
    material.setdefault("source_event_type", "agent_turn_terminal")
    material.setdefault("completion_state", str(payload.get("completion_state") or payload.get("terminal_reason") or ""))
    return turn_completed_data("agent_turn_terminal", material)


def _turn_completed_status_from_agent_terminal(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status in {"failed", "error"}:
        return "failed"
    if status in {"stopped", "aborted", "cancelled", "canceled", "blocked"}:
        return "stopped"
    return "completed"


def public_terminal_reason(value: Any) -> str:
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
            "created_at": _public_created_at(raw_data, raw_event, payload, request, tool),
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
    permission_decision_id_value = _canonical_permission_decision_id(admission, tool_call_id=tool_call_id)
    data: dict[str, Any] = {
        "item_id": permission_decision_id_value,
        "request_id": str(request_data.get("request_id") or admission.get("action_request_ref") or ""),
        "tool_call_id": tool_call_id,
        "turn_run_id": str(payload.get("turn_run_id") or refs.get("turn_run_ref") or request_data.get("turn_run_id") or ""),
        "task_run_id": str(payload.get("task_run_id") or refs.get("task_run_ref") or request_data.get("task_run_id") or ""),
        "tool_name": str(request_data.get("tool_name") or ""),
        "permission_decision_id": permission_decision_id_value,
        "permission_decision": decision,
        "permission_reason": _safe_public_action_text(admission.get("user_visible_reason")),
        "system_reason": _safe_public_action_text(admission.get("system_reason")),
        "created_at": _public_created_at(raw_data, raw_event, payload, admission),
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
    permission_decision_id_value = str(payload.get("permission_decision_id") or "").strip()
    tool_name = str(payload.get("tool_name") or "").strip()
    if not tool_call_id or not permission_decision_id_value or not tool_name:
        return {}
    data: dict[str, Any] = {
        "item_id": tool_call_id,
        "tool_lifecycle_id": str(payload.get("tool_lifecycle_id") or payload.get("item_id") or tool_call_id),
        "tool_call_id": tool_call_id,
        "permission_decision_id": permission_decision_id_value,
        "turn_run_id": str(payload.get("turn_run_id") or refs.get("turn_run_ref") or raw_data.get("turn_run_id") or ""),
        "task_run_id": str(payload.get("task_run_id") or refs.get("task_run_ref") or raw_data.get("task_run_id") or raw_data.get("runtime_task_run_id") or ""),
        "tool_name": tool_name,
        "title": _safe_public_action_text(payload.get("title")),
        "target": _safe_public_action_text(payload.get("target")),
        "arguments_preview": _safe_public_action_text(payload.get("arguments_preview")),
        "state": str(payload.get("state") or "running"),
        "created_at": _public_created_at(raw_data, raw_event, payload),
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
    content_window = _read_file_content_window_payload(
        tool_name=tool_name,
        result_envelope=result_envelope,
        tool_args=tool_args,
    )
    created_at = _public_created_at(raw_data, raw_event, tool_observation, observation, execution_receipt)
    duration_ms = _public_duration_ms(
        execution_receipt,
        result_envelope,
        tool_observation,
        observation,
        completed_at=created_at,
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
        "duration_ms": duration_ms,
        "created_at": created_at,
    }
    if content_window:
        data["content_window"] = content_window
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
        "session_id": str(payload.get("session_id") or raw_data.get("session_id") or refs.get("session_ref") or "").strip(),
        "stream_run_id": str(payload.get("stream_run_id") or raw_data.get("stream_run_id") or "").strip(),
        "turn_id": str(payload.get("turn_id") or payload.get("active_turn_id") or raw_data.get("turn_id") or raw_data.get("active_turn_id") or refs.get("turn_ref") or "").strip(),
        "active_turn_id": str(payload.get("active_turn_id") or payload.get("turn_id") or raw_data.get("active_turn_id") or raw_data.get("turn_id") or refs.get("turn_ref") or "").strip(),
        "turn_run_id": str(payload.get("turn_run_id") or raw_data.get("turn_run_id") or refs.get("turn_run_ref") or "").strip(),
        "task_run_id": str(payload.get("task_run_id") or raw_event.get("task_run_id") or raw_data.get("task_run_id") or refs.get("task_run_ref") or "").strip(),
        "message_id": str(payload.get("message_id") or payload.get("message_ref") or raw_data.get("message_id") or raw_data.get("message_ref") or "").strip(),
        "message_ref": str(payload.get("message_ref") or payload.get("message_id") or raw_data.get("message_ref") or raw_data.get("message_id") or "").strip(),
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


def _read_file_content_window_payload(
    *,
    tool_name: str,
    result_envelope: dict[str, Any],
    tool_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_tool = str(tool_name or "").strip().lower()
    if normalized_tool not in {"read_file", "read_files", "read_path"}:
        return {}
    structured = _record(result_envelope.get("structured_payload"))
    result_payload = _record(result_envelope.get("result"))
    tool_result = _record(
        structured.get("tool_result")
        or result_envelope.get("tool_result")
        or result_payload.get("tool_result")
    )
    result_kind = str(tool_result.get("kind") or "").strip().lower()
    if result_kind == "read_file_reuse":
        return _read_file_reuse_content_window_payload(tool_result=tool_result)
    if str(tool_result.get("status") or result_envelope.get("status") or "").strip().lower() == "error":
        return {}
    raw_text = str(
        result_envelope.get("text")
        or tool_result.get("text")
        or result_payload.get("text")
        or ""
    )
    metadata_indicates_read = bool(
        result_kind in {"read_file", "text_file"}
        or tool_result.get("path")
        or tool_result.get("start_line") is not None
        or tool_result.get("end_line") is not None
    )
    if not raw_text.strip():
        return {}
    if not metadata_indicates_read and not LINE_NUMBERED_TOOL_OUTPUT_RE.search(raw_text):
        return {}
    args = dict(tool_args or {})
    if result_kind == "read_file_reuse":
        return {}
    clipped_text, preview_truncated, preview_lines = _bounded_read_window_text(raw_text)
    if not clipped_text.strip():
        return {}
    return {
        "kind": "read_file",
        "path": str(tool_result.get("path") or result_envelope.get("path") or args.get("path") or "").strip(),
        "text": clipped_text,
        "start_line": _public_int(tool_result.get("start_line") or args.get("start_line")),
        "end_line": _public_int(tool_result.get("end_line")),
        "returned_lines": _public_int(tool_result.get("returned_lines")),
        "line_count": _public_int(tool_result.get("line_count") or args.get("line_count")),
        "total_lines": _public_int(tool_result.get("total_lines")),
        "has_more": bool(tool_result.get("has_more") is True),
        "next_start_line": _public_int(tool_result.get("next_start_line")),
        "truncated": bool(tool_result.get("truncated") is True),
        "preview_lines": preview_lines,
        "preview_truncated": preview_truncated,
        "content_sha256": str(tool_result.get("content_sha256") or "").strip(),
        "authority": "runtime.output_stream.read_file_content_window.v1",
    }


def _read_file_reuse_content_window_payload(*, tool_result: dict[str, Any]) -> dict[str, Any]:
    path = str(tool_result.get("path") or "").strip()
    start_line = _public_int(tool_result.get("start_line"))
    end_line = _public_int(tool_result.get("end_line"))
    range_label = f"{start_line}-{end_line}" if start_line is not None and end_line is not None else ""
    refs = [
        str(tool_result.get("reused_observation_ref") or tool_result.get("observation_ref") or "").strip(),
        str(tool_result.get("exact_artifact_ref") or "").strip(),
        str(tool_result.get("reusable_result_ref") or "").strip(),
    ]
    ref_text = " / ".join(item for item in refs if item)
    rehydrated_text = str(tool_result.get("text") or "")
    content_available = bool(rehydrated_text)
    if rehydrated_text:
        clipped_text, preview_truncated, preview_lines = _bounded_read_window_text(rehydrated_text)
    else:
        text_parts = [
            "复用上次读取窗口：文件状态未变化，本次工具没有重新返回全文。",
            f"文件：{path}" if path else "",
            f"范围：{range_label} 行" if range_label else "",
            f"引用：{ref_text}" if ref_text else "",
        ]
        clipped_text, preview_truncated, preview_lines = _bounded_read_window_text("\n".join(item for item in text_parts if item))
    return {
        "kind": "read_file_reuse",
        "status": str(tool_result.get("status") or "reuse_unchanged").strip(),
        "content_available": content_available,
        "path": path,
        "text": clipped_text,
        "start_line": start_line,
        "end_line": end_line,
        "returned_lines": _public_int(tool_result.get("returned_lines")),
        "line_count": _public_int(tool_result.get("line_count")),
        "total_lines": _public_int(tool_result.get("total_lines")),
        "has_more": bool(tool_result.get("has_more") is True),
        "next_start_line": _public_int(tool_result.get("next_start_line")),
        "preview_lines": preview_lines,
        "preview_truncated": preview_truncated,
        "content_sha256": str(tool_result.get("content_sha256") or "").strip(),
        "reused_observation_ref": str(tool_result.get("reused_observation_ref") or tool_result.get("observation_ref") or "").strip(),
        "exact_artifact_ref": str(tool_result.get("exact_artifact_ref") or "").strip(),
        "reusable_result_ref": str(tool_result.get("reusable_result_ref") or "").strip(),
        "reuse_text_source": str(tool_result.get("reuse_text_source") or "").strip(),
        "authority": "runtime.output_stream.read_file_reuse_window.v1",
    }


def _public_created_at(*sources: dict[str, Any]) -> float | None:
    for source in sources:
        for key in ("created_at", "updated_at", "started_at", "completed_at"):
            value = source.get(key)
            try:
                timestamp = float(value)
            except (TypeError, ValueError):
                continue
            if timestamp > 0:
                return timestamp
    return None


def _public_duration_ms(*sources: dict[str, Any], completed_at: float | None = None) -> int | None:
    for source in sources:
        value = source.get("duration_ms")
        try:
            duration = float(value)
        except (TypeError, ValueError):
            continue
        if duration >= 0:
            return int(round(duration))
    started_at = _public_timestamp_for_keys(*sources, keys=("started_at", "created_at"))
    ended_at = _public_timestamp_for_keys(*sources, keys=("completed_at", "ended_at", "updated_at")) or completed_at
    if started_at and ended_at and ended_at >= started_at:
        return int(round((ended_at - started_at) * 1000))
    return None


def _public_timestamp_for_keys(*sources: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for source in sources:
        for key in keys:
            value = source.get(key)
            try:
                timestamp = float(value)
            except (TypeError, ValueError):
                continue
            if timestamp > 0:
                return timestamp
    return None


def _bounded_read_window_text(value: str) -> tuple[str, bool, int]:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    selected = lines[:PUBLIC_READ_WINDOW_MAX_LINES]
    line_truncated = len(lines) > len(selected)
    bounded = "\n".join(selected)
    char_truncated = len(bounded) > PUBLIC_READ_WINDOW_MAX_CHARS
    if char_truncated:
        bounded = bounded[:PUBLIC_READ_WINDOW_MAX_CHARS].rstrip()
    return bounded, bool(line_truncated or char_truncated), len(selected)


def _public_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


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


def _semantic_event_payload(raw_data: dict[str, Any]) -> dict[str, Any]:
    raw_event = _record(raw_data.get("event"))
    payload = _record(raw_event.get("payload") or raw_data.get("payload") or raw_data)
    preview = _record(payload.get("preview"))
    return preview or payload


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


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
