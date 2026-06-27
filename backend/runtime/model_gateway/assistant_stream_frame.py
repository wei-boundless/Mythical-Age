from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


ASSISTANT_STREAM_FRAME_SCHEMA_VERSION = "assistant_stream_frame.v1"
ASSISTANT_TEXT_DELTA_EVENT = "assistant_text_delta"
ASSISTANT_TEXT_FINAL_EVENT = "assistant_text_final"
ASSISTANT_STREAM_REPAIR_EVENT = "assistant_stream_repair"

_BODY_BLOCKED_ANSWER_CHANNELS = {
    "active_work_control",
    "opening_judgment",
    "orchestration_fail_closed",
    "runtime_control",
    "task_control",
}


def utf8_byte_length(value: str) -> int:
    return len(str(value or "").encode("utf-8"))


def content_sha256(value: str) -> str:
    digest = hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


@dataclass(frozen=True, slots=True)
class AssistantStreamFrame:
    frame_schema_version: str
    event_type: str
    frame_id: str
    stream_ref: str
    message_ref: str
    turn_run_id: str
    task_run_id: str
    sequence: int
    content: str
    content_utf8_start: int
    content_utf8_end: int
    content_utf8_bytes: int
    accumulated_utf8_bytes: int
    accumulated_sha256: str
    answer_channel: str = "conversation"
    answer_source: str = ""
    visibility: str = "public"
    markdown_state: dict[str, Any] = field(default_factory=dict)
    display_hint: dict[str, Any] = field(default_factory=dict)

    def to_event(self) -> dict[str, Any]:
        return {
            "type": self.event_type,
            "frame_schema_version": self.frame_schema_version,
            "event_type": self.event_type,
            "frame_id": self.frame_id,
            "stream_ref": self.stream_ref,
            "message_ref": self.message_ref,
            "turn_run_id": self.turn_run_id,
            "task_run_id": self.task_run_id,
            "sequence": self.sequence,
            "content": self.content,
            "content_utf8_start": self.content_utf8_start,
            "content_utf8_end": self.content_utf8_end,
            "content_utf8_bytes": self.content_utf8_bytes,
            "accumulated_utf8_bytes": self.accumulated_utf8_bytes,
            "accumulated_sha256": self.accumulated_sha256,
            "answer_channel": self.answer_channel,
            "answer_source": self.answer_source,
            "visibility": self.visibility,
            "markdown_state": dict(self.markdown_state),
            "display_hint": dict(self.display_hint),
        }


def assistant_message_ref(*, turn_id: str = "", stream_ref: str = "") -> str:
    ref = str(turn_id or "").strip() or str(stream_ref or "").strip() or "assistant"
    return f"{ref}:assistant"


def assistant_text_final_event(
    *,
    content: str,
    stream_ref: str,
    message_ref: str,
    turn_run_id: str = "",
    task_run_id: str = "",
    sequence: int,
    answer_channel: str,
    answer_source: str,
    answer_canonical_state: str = "stable_answer",
    answer_persist_policy: str = "persist_canonical",
    terminal_reason: str = "completed",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = str(content or "")
    return {
        "type": ASSISTANT_TEXT_FINAL_EVENT,
        "frame_schema_version": ASSISTANT_STREAM_FRAME_SCHEMA_VERSION,
        "event_type": ASSISTANT_TEXT_FINAL_EVENT,
        "stream_ref": str(stream_ref or ""),
        "message_ref": str(message_ref or ""),
        "turn_run_id": str(turn_run_id or ""),
        "task_run_id": str(task_run_id or ""),
        "sequence": int(sequence),
        "content": text,
        "content_utf8_bytes": utf8_byte_length(text),
        "content_sha256": content_sha256(text),
        "answer_channel": str(answer_channel or "conversation"),
        "answer_source": str(answer_source or ""),
        "answer_canonical_state": str(answer_canonical_state or "stable_answer"),
        "answer_persist_policy": str(answer_persist_policy or "persist_canonical"),
        "terminal_reason": str(terminal_reason or "completed"),
        **dict(extra or {}),
    }


def assistant_stream_repair_event(
    *,
    replacement_content: str,
    stream_ref: str,
    message_ref: str,
    turn_run_id: str = "",
    task_run_id: str = "",
    repair_sequence: int,
    applies_after_sequence: int,
    reason: str = "checksum_mismatch",
    expected_content_sha256: str = "",
) -> dict[str, Any]:
    text = str(replacement_content or "")
    return {
        "type": ASSISTANT_STREAM_REPAIR_EVENT,
        "frame_schema_version": ASSISTANT_STREAM_FRAME_SCHEMA_VERSION,
        "event_type": ASSISTANT_STREAM_REPAIR_EVENT,
        "stream_ref": str(stream_ref or ""),
        "message_ref": str(message_ref or ""),
        "turn_run_id": str(turn_run_id or ""),
        "task_run_id": str(task_run_id or ""),
        "repair_sequence": int(repair_sequence),
        "applies_after_sequence": int(applies_after_sequence),
        "reason": str(reason or "checksum_mismatch"),
        "expected_content_sha256": str(expected_content_sha256 or ""),
        "replacement_content": text,
        "replacement_content_sha256": content_sha256(text),
    }


def assistant_final_stream_events(
    normalizer: Any | None,
    *,
    content: str,
    answer_channel: str,
    answer_source: str,
    terminal_reason: str,
    answer_canonical_state: str,
    answer_persist_policy: str,
    stream_ref: str = "",
    message_ref: str = "",
    turn_run_id: str = "",
    task_run_id: str = "",
    extra: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    text = str(content or "")
    if not allows_assistant_body_projection(
        answer_channel=answer_channel,
        answer_canonical_state=answer_canonical_state,
        answer_persist_policy=answer_persist_policy,
    ):
        return []
    resolved_stream_ref = str(stream_ref or getattr(normalizer, "stream_ref", "") or "")
    resolved_message_ref = str(
        message_ref
        or getattr(normalizer, "message_ref", "")
        or assistant_message_ref(stream_ref=resolved_stream_ref)
    )
    resolved_turn_run_id = str(turn_run_id or getattr(normalizer, "turn_run_id", "") or "")
    resolved_task_run_id = str(task_run_id or getattr(normalizer, "task_run_id", "") or "")

    sequence = 1
    events: list[dict[str, Any]] = []
    if normalizer is not None:
        events.extend(normalizer.flush())
        normalizer.mark_final_content(text)
        sequence = normalizer.next_sequence()
        emitted_content = str(getattr(normalizer, "emitted_content", "") or "")
        latest_sequence = int(getattr(normalizer, "latest_sequence", 0) or 0)
        if latest_sequence > 0 and content_sha256(emitted_content) != content_sha256(text):
            events.append(
                assistant_stream_repair_event(
                    replacement_content=text,
                    stream_ref=resolved_stream_ref,
                    message_ref=resolved_message_ref,
                    turn_run_id=resolved_turn_run_id,
                    task_run_id=resolved_task_run_id,
                    repair_sequence=sequence,
                    applies_after_sequence=latest_sequence,
                    expected_content_sha256=content_sha256(emitted_content),
                )
            )
            sequence += 1

    events.append(
        assistant_text_final_event(
            content=text,
            stream_ref=resolved_stream_ref,
            message_ref=resolved_message_ref,
            turn_run_id=resolved_turn_run_id,
            task_run_id=resolved_task_run_id,
            sequence=sequence,
            answer_channel=answer_channel,
            answer_source=answer_source,
            answer_canonical_state=answer_canonical_state,
            answer_persist_policy=answer_persist_policy,
            terminal_reason=terminal_reason,
            extra=extra,
        )
    )
    return events


def allows_assistant_body_projection(
    *,
    answer_channel: str,
    answer_canonical_state: str,
    answer_persist_policy: str,
) -> bool:
    channel = str(answer_channel or "").strip()
    canonical_state = str(answer_canonical_state or "").strip()
    persist_policy = str(answer_persist_policy or "").strip()
    if channel in _BODY_BLOCKED_ANSWER_CHANNELS:
        return False
    if persist_policy in {"persist_debug_only", "do_not_persist"}:
        return False
    if canonical_state == "missing_answer":
        return False
    return True
