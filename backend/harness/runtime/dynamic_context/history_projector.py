from __future__ import annotations

from typing import Any

from .models import compact_text, drop_empty


COMPRESSED_CONTEXT_PREFIX = "[Compressed session context]"


class HistoryProjector:
    def project(
        self,
        history: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        *,
        current_user_message: str = "",
        session_context: dict[str, Any] | None = None,
        projection_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = dict(projection_policy or {})
        recent_limit = int(policy.get("recent_history_message_limit") or 6)
        message_char_limit = int(policy.get("history_message_chars") or 1200)
        session_payload = _session_context_projection(
            session_context,
            compressed_summary_chars=int(policy.get("compressed_summary_chars") or 4000),
        )
        normalized = [
            _normalize_message(item, content_limit=message_char_limit)
            for item in list(history or [])
            if isinstance(item, dict) and not _is_compressed_context_message(item)
        ]
        normalized = [item for item in normalized if item]
        recent = normalized[-recent_limit:]
        older_count = max(0, len(normalized) - len(recent))
        payload = {
            "session_context": session_payload,
            "context_summary": _context_summary(older_count),
            "pinned_facts": [],
            "recent_turns": recent,
            "active_tool_trajectory": _tool_trajectory(
                normalized[-max(recent_limit * 2, 12):],
                limit=int(policy.get("tool_trajectory_limit") or 8),
                result_preview_chars=int(policy.get("tool_trajectory_result_chars") or 300),
            ),
            "omitted_history": {
                "turn_count": older_count,
                "reason": "recent_history_message_limit",
            }
            if older_count
            else {},
            "current_user_message_ref": "volatile_current_request" if str(current_user_message or "").strip() else "",
            "authority": "harness.runtime.dynamic_context.history_projection",
        }
        return drop_empty(payload)


def _normalize_message(item: dict[str, Any], *, content_limit: int) -> dict[str, Any]:
    role = str(item.get("role") or item.get("type") or "user")
    content = compact_text(item.get("content") or item.get("text") or "", limit=max(300, int(content_limit or 1200)))
    payload = {
        "role": role,
        "content": content,
    }
    if item.get("tool_call_id"):
        payload["tool_call_id"] = str(item.get("tool_call_id") or "")
    if item.get("tool_calls"):
        payload["tool_calls"] = item.get("tool_calls")
    return drop_empty(payload)


def _session_context_projection(session_context: dict[str, Any] | None, *, compressed_summary_chars: int) -> dict[str, Any]:
    payload = dict(session_context or {})
    compressed = compact_text(
        payload.get("compressed_context") or payload.get("compressed_summary") or "",
        limit=max(1000, int(compressed_summary_chars or 4000)),
    )
    return drop_empty(
        {
            "compressed_summary": compressed,
            "authority": "harness.runtime.dynamic_context.session_context_projection" if compressed else "",
        }
    )


def _is_compressed_context_message(item: dict[str, Any]) -> bool:
    content = str(item.get("content") or item.get("text") or "")
    return content.startswith(COMPRESSED_CONTEXT_PREFIX)


def _context_summary(older_count: int) -> str:
    if older_count <= 0:
        return ""
    return f"{older_count} earlier message-equivalent item(s) are omitted by dynamic context projection; rely on recent_turns, pinned_facts, and active observations."


def _tool_trajectory(messages: list[dict[str, Any]], *, limit: int, result_preview_chars: int) -> list[dict[str, Any]]:
    trajectory: list[dict[str, Any]] = []
    for item in messages:
        if item.get("tool_calls"):
            trajectory.append(
                {
                    "role": str(item.get("role") or "assistant"),
                    "tool_calls": item.get("tool_calls"),
                }
            )
        elif str(item.get("role") or "") == "tool" or item.get("tool_call_id"):
            trajectory.append(
                {
                    "role": "tool",
                    "tool_call_id": str(item.get("tool_call_id") or ""),
                    "result_preview": compact_text(
                        item.get("content") or "",
                        limit=max(120, int(result_preview_chars or 300)),
                    ),
                }
            )
    return trajectory[-max(1, int(limit or 8)):]
