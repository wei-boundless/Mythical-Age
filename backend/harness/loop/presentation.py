from __future__ import annotations

from typing import Any

from runtime.output_boundary import sanitize_visible_assistant_content


def final_answer_event(
    *,
    content: str,
    answer_source: str,
    terminal_reason: str = "completed",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "done",
        "content": sanitize_visible_assistant_content(str(content or "")),
        "answer_channel": "final_answer",
        "answer_source": answer_source,
        "answer_canonical_state": "final",
        "answer_persist_policy": "persist_canonical",
        "answer_finalization_policy": "assistant_final",
        "terminal_reason": terminal_reason,
        **dict(extra or {}),
    }


def error_event(*, content: str, code: str, reason: str = "") -> dict[str, Any]:
    return {
        "type": "error",
        "error": reason or code,
        "code": code,
        "content": sanitize_visible_assistant_content(str(content or "")),
        "answer_channel": "orchestration_fail_closed",
        "answer_source": "harness.loop.single_agent",
    }

