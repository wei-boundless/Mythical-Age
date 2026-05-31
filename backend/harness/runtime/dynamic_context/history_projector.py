from __future__ import annotations

from typing import Any

from .models import compact_text, drop_empty


class HistoryProjector:
    def project(
        self,
        history: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        *,
        current_user_message: str = "",
        projection_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = dict(projection_policy or {})
        recent_limit = int(policy.get("recent_history_message_limit") or 6)
        normalized = [_normalize_message(item) for item in list(history or []) if isinstance(item, dict)]
        normalized = [item for item in normalized if item]
        recent = normalized[-recent_limit:]
        older_count = max(0, len(normalized) - len(recent))
        payload = {
            "context_summary": _context_summary(older_count),
            "pinned_facts": [],
            "recent_turns": recent,
            "active_tool_trajectory": _tool_trajectory(normalized[-max(recent_limit * 2, 12):]),
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


def _normalize_message(item: dict[str, Any]) -> dict[str, Any]:
    role = str(item.get("role") or item.get("type") or "user")
    content = compact_text(item.get("content") or item.get("text") or "", limit=1200)
    payload = {
        "role": role,
        "content": content,
    }
    if item.get("tool_call_id"):
        payload["tool_call_id"] = str(item.get("tool_call_id") or "")
    if item.get("tool_calls"):
        payload["tool_calls"] = item.get("tool_calls")
    return drop_empty(payload)


def _context_summary(older_count: int) -> str:
    if older_count <= 0:
        return ""
    return f"{older_count} earlier message-equivalent item(s) are omitted by dynamic context projection; rely on recent_turns, pinned_facts, and active observations."


def _tool_trajectory(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
                    "result_preview": compact_text(item.get("content") or "", limit=300),
                }
            )
    return trajectory[-8:]
