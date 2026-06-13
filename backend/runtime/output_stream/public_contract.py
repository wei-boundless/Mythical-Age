from __future__ import annotations

from runtime.model_gateway.assistant_stream_frame import (
    ASSISTANT_STREAM_REPAIR_EVENT,
    ASSISTANT_TEXT_DELTA_EVENT,
    ASSISTANT_TEXT_FINAL_EVENT,
)


TOOL_ITEM_STARTED_EVENT = "tool_item_started"
TOOL_ITEM_COMPLETED_EVENT = "tool_item_completed"
TOOL_CALL_REQUESTED_EVENT = "tool_call_requested"
TOOL_PERMISSION_DECIDED_EVENT = "tool_permission_decided"
SESSION_OUTPUT_COMMIT_CHECKED_EVENT = "session_output_commit_checked"
SESSION_OUTPUT_COMMIT_ACK_EVENT = "session_output_commit_ack"
SESSION_OUTPUT_COMMIT_FAILED_EVENT = "session_output_commit_failed"
SESSION_OUTPUT_COMMIT_SKIPPED_EVENT = "session_output_commit_skipped"
TURN_COMPLETED_EVENT = "turn_completed"

TRANSCRIPT_PUBLIC_EVENTS = {
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

LOSSLESS_PUBLIC_EVENTS = (
    TRANSCRIPT_PUBLIC_EVENTS
    | ITEM_LIFECYCLE_PUBLIC_EVENTS
    | TERMINAL_PUBLIC_EVENTS
    | COMMIT_PUBLIC_EVENTS
)


def is_lossless_public_event(event_type: str) -> bool:
    return str(event_type or "").strip() in LOSSLESS_PUBLIC_EVENTS


def is_terminal_public_event(event_type: str) -> bool:
    return str(event_type or "").strip() in TERMINAL_PUBLIC_EVENTS


def event_requires_public_projection(event_type: str) -> bool:
    event = str(event_type or "").strip()
    if not event:
        return False
    return True
