from __future__ import annotations

from typing import Any

from runtime.output_boundary import canonical_output_decision_for_final_text, sanitize_visible_assistant_content


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


def error_event(
    *,
    content: str,
    code: str,
    reason: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "error",
        "error": reason or code,
        "code": code,
        "content": sanitize_visible_assistant_content(str(content or "")),
        "answer_channel": "orchestration_fail_closed",
        "answer_source": "harness.loop.single_agent",
        **dict(extra or {}),
    }

