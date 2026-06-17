from __future__ import annotations

from runtime.model_gateway.assistant_stream_frame import (
    ASSISTANT_STREAM_REPAIR_EVENT,
    ASSISTANT_TEXT_DELTA_EVENT,
    ASSISTANT_TEXT_FINAL_EVENT,
)


ASSISTANT_PUBLIC_FEEDBACK_EVENT = "assistant_public_feedback"
TOOL_ITEM_STARTED_EVENT = "tool_item_started"
TOOL_ITEM_COMPLETED_EVENT = "tool_item_completed"
TOOL_CALL_REQUESTED_EVENT = "tool_call_requested"
TOOL_PERMISSION_DECIDED_EVENT = "tool_permission_decided"
SESSION_OUTPUT_COMMIT_CHECKED_EVENT = "session_output_commit_checked"
SESSION_OUTPUT_COMMIT_ACK_EVENT = "session_output_commit_ack"
SESSION_OUTPUT_COMMIT_FAILED_EVENT = "session_output_commit_failed"
SESSION_OUTPUT_COMMIT_SKIPPED_EVENT = "session_output_commit_skipped"
CHAT_TURN_BOUND_EVENT = "chat_turn_bound"
TASK_BRIDGE_STARTED_EVENT = "task_bridge_started"
TASK_BRIDGE_TERMINAL_EVENT = "task_bridge_terminal"
TURN_COMPLETED_EVENT = "turn_completed"

ASSISTANT_BODY_EVENT_FAMILY = "assistant_body"
TOOL_CONTROL_EVENT_FAMILY = "tool_control"
RUNTIME_COMMIT_EVENT_FAMILY = "runtime_commit"
TURN_ANCHOR_TERMINAL_EVENT_FAMILY = "turn_anchor_terminal"
STATUS_TRACE_EVENT_FAMILY = "status_trace"

BODY_PUBLIC_CHANNEL = "body"
CONTROL_PUBLIC_CHANNEL = "control"
COMMIT_PUBLIC_CHANNEL = "commit"
TERMINAL_PUBLIC_CHANNEL = "terminal"
STATUS_PUBLIC_CHANNEL = "status"

TRANSCRIPT_PUBLIC_EVENTS = {
    ASSISTANT_PUBLIC_FEEDBACK_EVENT,
    ASSISTANT_TEXT_DELTA_EVENT,
    ASSISTANT_TEXT_FINAL_EVENT,
    ASSISTANT_STREAM_REPAIR_EVENT,
}

ITEM_LIFECYCLE_PUBLIC_EVENTS = {
    TOOL_CALL_REQUESTED_EVENT,
    TOOL_PERMISSION_DECIDED_EVENT,
    TOOL_ITEM_STARTED_EVENT,
    TOOL_ITEM_COMPLETED_EVENT,
}

TERMINAL_PUBLIC_EVENTS = {TURN_COMPLETED_EVENT}

COMMIT_PUBLIC_EVENTS = {
    SESSION_OUTPUT_COMMIT_CHECKED_EVENT,
    SESSION_OUTPUT_COMMIT_ACK_EVENT,
    SESSION_OUTPUT_COMMIT_FAILED_EVENT,
    SESSION_OUTPUT_COMMIT_SKIPPED_EVENT,
}

ANCHOR_PUBLIC_EVENTS = {
    CHAT_TURN_BOUND_EVENT,
    TASK_BRIDGE_STARTED_EVENT,
    TASK_BRIDGE_TERMINAL_EVENT,
}

LOSSLESS_PUBLIC_EVENTS = (
    TRANSCRIPT_PUBLIC_EVENTS
    | ITEM_LIFECYCLE_PUBLIC_EVENTS
    | TERMINAL_PUBLIC_EVENTS
    | COMMIT_PUBLIC_EVENTS
    | ANCHOR_PUBLIC_EVENTS
)

_PUBLIC_EVENT_FAMILY_BY_TYPE = {
    **{event_type: ASSISTANT_BODY_EVENT_FAMILY for event_type in TRANSCRIPT_PUBLIC_EVENTS},
    **{event_type: TOOL_CONTROL_EVENT_FAMILY for event_type in ITEM_LIFECYCLE_PUBLIC_EVENTS},
    **{event_type: RUNTIME_COMMIT_EVENT_FAMILY for event_type in COMMIT_PUBLIC_EVENTS},
    **{event_type: TURN_ANCHOR_TERMINAL_EVENT_FAMILY for event_type in TERMINAL_PUBLIC_EVENTS | ANCHOR_PUBLIC_EVENTS},
    "runtime_status": STATUS_TRACE_EVENT_FAMILY,
    "runtime_step_summary": STATUS_TRACE_EVENT_FAMILY,
    "tool_batch_group_started": STATUS_TRACE_EVENT_FAMILY,
    "active_task_steer_accepted": STATUS_TRACE_EVENT_FAMILY,
    "error": STATUS_TRACE_EVENT_FAMILY,
    "stopped": STATUS_TRACE_EVENT_FAMILY,
}

_PUBLIC_CHANNEL_BY_EVENT_FAMILY = {
    ASSISTANT_BODY_EVENT_FAMILY: BODY_PUBLIC_CHANNEL,
    TOOL_CONTROL_EVENT_FAMILY: CONTROL_PUBLIC_CHANNEL,
    RUNTIME_COMMIT_EVENT_FAMILY: COMMIT_PUBLIC_CHANNEL,
    TURN_ANCHOR_TERMINAL_EVENT_FAMILY: TERMINAL_PUBLIC_CHANNEL,
    STATUS_TRACE_EVENT_FAMILY: STATUS_PUBLIC_CHANNEL,
}


def is_lossless_public_event(event_type: str) -> bool:
    return str(event_type or "").strip() in LOSSLESS_PUBLIC_EVENTS


def public_event_family(event_type: str) -> str:
    return _PUBLIC_EVENT_FAMILY_BY_TYPE.get(str(event_type or "").strip(), STATUS_TRACE_EVENT_FAMILY)


def public_event_channel(event_type: str) -> str:
    return _PUBLIC_CHANNEL_BY_EVENT_FAMILY[public_event_family(event_type)]


def is_terminal_public_event(event_type: str) -> bool:
    return str(event_type or "").strip() in TERMINAL_PUBLIC_EVENTS


def event_requires_public_projection(event_type: str) -> bool:
    event = str(event_type or "").strip()
    if not event:
        return False
    return True
