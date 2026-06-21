from __future__ import annotations

import json
import re
from hashlib import sha1
from typing import Any

from harness.runtime.public_progress import public_runtime_progress_summary
from harness.runtime.runtime_private_text import looks_like_runtime_private_artifact_text


INTERNAL_TOKENS = {
    "action_type",
    "agent_turn_terminal",
    "assistant_message",
    "completion_status",
    "diagnostics",
    "model_action_request",
    "public_action_state",
    "public_progress_note",
    "runtime_invocation_packet",
    "task_control",
    "task_execution_packet",
    "task_executor_scheduled",
    "terminal_reason",
    "tool_call",
    "single_turn_tool_iteration_limit",
}


def public_text(value: Any, *, limit: int = 220) -> str:
    """Return user-visible text or an empty string.

    This function is intentionally fail-closed. It never falls back to raw
    stringified values after cleaning rejects them.
    """

    text = public_runtime_progress_summary(value).strip()
    if not text:
        return ""
    text = " ".join(text.split()).strip()
    if looks_structured_payload(text) or looks_internal_text(text):
        return ""
    if limit > 0 and len(text) > limit:
        return text[: max(1, limit - 1)] + "..."
    return text


def public_body_text(value: Any) -> str:
    """Return user-visible assistant body text without presentation truncation."""

    raw = str(value or "").strip()
    if not raw:
        return ""
    if not public_runtime_progress_summary(raw):
        return ""
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    if looks_structured_payload(normalized) or looks_internal_text(normalized):
        return ""
    return normalized


def public_state(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"failed", "error", "blocked"}:
        return "error"
    if normalized in {"completed", "complete", "success", "succeeded", "done"}:
        return "done"
    if normalized in {"waiting", "queued", "paused", "waiting_executor", "waiting_approval", "waiting_safe_boundary"}:
        return "waiting"
    if normalized in {"stopped", "aborted", "cancelled", "canceled"}:
        return "stopped"
    return "running"


def looks_structured_payload(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
        try:
            json.loads(text)
            return True
        except Exception:
            return True
    lowered = text.lower()
    return sum(1 for token in INTERNAL_TOKENS if token in lowered) >= 2


def looks_internal_text(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    if looks_like_runtime_private_artifact_text(text):
        return True
    if text in INTERNAL_TOKENS:
        return True
    if re.search(r"\b(taskrun|turnrun|agrun|toolinv|promptpkt):", text):
        return True
    return any(token in text for token in INTERNAL_TOKENS)


def compact(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


def stable_id(prefix: str, *parts: Any) -> str:
    seed = "|".join(str(part or "") for part in parts)
    return f"{prefix}:{sha1(seed.encode('utf-8', errors='ignore')).hexdigest()[:16]}"


def record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def text(value: Any) -> str:
    return str(value or "").strip()
