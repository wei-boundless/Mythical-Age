from __future__ import annotations

from typing import Any

from runtime.model_gateway.assistant_stream_frame import (
    allows_assistant_body_projection,
    assistant_message_ref,
    assistant_text_final_event,
)
from harness.runtime.output_boundary import canonical_output_decision_for_final_text, sanitize_visible_assistant_content
from runtime.output_stream.public_contract import TURN_COMPLETED_EVENT


def final_answer_event(
    *,
    content: str,
    answer_source: str,
    answer_channel: str = "final_answer",
    terminal_reason: str = "completed",
    route: str = "",
    execution_posture: str = "",
    user_message: str = "",
    tool_name: str = "",
    retrieval_results: list[dict[str, object]] | None = None,
    has_tool_receipt: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decision = canonical_output_decision_for_final_text(
        str(content or ""),
        answer_channel=answer_channel,
        answer_source=answer_source,
        terminal_reason=terminal_reason,
        route=route,
        execution_posture=execution_posture,
        user_message=user_message,
        tool_name=tool_name,
        retrieval_results=retrieval_results,
        has_tool_receipt=has_tool_receipt,
    )
    return {
        "type": "done",
        **decision.to_payload(),
        "terminal_reason": terminal_reason,
        **dict(extra or {}),
    }


def assistant_body_final_event(
    *,
    content: str,
    answer_source: str,
    answer_channel: str,
    turn_id: str = "",
    turn_run_id: str = "",
    task_run_id: str = "",
    stream_ref: str = "",
    message_ref: str = "",
    sequence: int = 1,
    body_sequence: int = 1,
    terminal_reason: str = "completed",
    execution_posture: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decision = canonical_output_decision_for_final_text(
        str(content or ""),
        answer_channel=answer_channel,
        answer_source=answer_source,
        terminal_reason=terminal_reason,
        execution_posture=execution_posture,
    )
    if not str(decision.content or "").strip():
        return {}
    if not allows_assistant_body_projection(
        answer_channel=decision.answer_channel,
        answer_canonical_state=decision.canonical_state,
        answer_persist_policy=decision.persist_policy,
    ):
        return {}
    resolved_stream_ref = str(stream_ref or f"assistant-body:{turn_id or task_run_id or answer_channel}:{body_sequence}").strip()
    resolved_message_ref = str(message_ref or assistant_message_ref(turn_id=turn_id, stream_ref=resolved_stream_ref)).strip()
    return assistant_text_final_event(
        content=decision.content,
        stream_ref=resolved_stream_ref,
        message_ref=resolved_message_ref,
        turn_run_id=turn_run_id,
        task_run_id=task_run_id,
        sequence=max(1, int(sequence)),
        answer_channel=decision.answer_channel,
        answer_source=decision.answer_source,
        answer_canonical_state=decision.canonical_state,
        answer_persist_policy=decision.persist_policy,
        terminal_reason=terminal_reason,
        extra={
            "body_segment_id": resolved_stream_ref,
            "body_sequence": max(1, int(body_sequence)),
            "segment_sequence": max(1, int(sequence)),
            "segment_role": decision.answer_channel,
            "answer_finalization_policy": decision.finalization_policy,
            "answer_fallback_reason": decision.fallback_reason,
            "answer_selected_channel": decision.selected_channel,
            "answer_selected_source": decision.selected_source,
            "answer_leak_flags": list(decision.leak_flags),
            **dict(extra or {}),
        },
    )


def turn_completed_event(
    *,
    status: str,
    terminal_reason: str,
    turn_run_id: str = "",
    task_run_id: str = "",
    final_message_ref: str = "",
    completion_state: str = "",
    error_summary: str = "",
    stopped_reason: str = "",
) -> dict[str, Any]:
    payload = {
        "type": TURN_COMPLETED_EVENT,
        "status": str(status or "completed").strip() or "completed",
        "turn_run_id": str(turn_run_id or "").strip(),
        "task_run_id": str(task_run_id or "").strip(),
        "final_message_ref": str(final_message_ref or "").strip(),
        "terminal_reason": str(terminal_reason or "").strip() or "completed",
        "completion_state": str(completion_state or "").strip(),
        "error_summary": sanitize_visible_assistant_content(str(error_summary or "")),
        "stopped_reason": sanitize_visible_assistant_content(str(stopped_reason or "")),
    }
    return {key: value for key, value in payload.items() if value not in ("", None)}


def error_event(
    *,
    content: str,
    code: str,
    reason: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    public_content = sanitize_visible_assistant_content(str(content or "")).strip() or "运行中断"
    return {
        "type": "error",
        "error": public_content,
        "code": code,
        "content": public_content,
        "answer_channel": "harness_fail_closed",
        "answer_source": "harness.loop.single_agent",
        **dict(extra or {}),
    }

