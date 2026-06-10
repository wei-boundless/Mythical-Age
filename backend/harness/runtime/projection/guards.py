from __future__ import annotations

import json
import re
from hashlib import sha1
from typing import Any

from harness.runtime.public_progress import public_runtime_progress_summary


SUPPRESSED_PUBLIC_TEXT = {
    "",
    "assistant_message",
    "done",
    "completed",
    "running",
    "working",
    "success",
    "true",
    "false",
    "null",
    "none",
    "开始处理",
    "处理完成",
    "处理已完成",
    "处理结束",
    "正在处理",
    "正在处理当前请求",
    "正在处理当前请求。",
    "正在处理任务",
    "正在建立任务运行",
    "正在建立任务运行。",
    "已开始处理",
    "已开始处理当前请求",
    "已开始处理当前请求。",
    "任务执行器已接管",
    "任务执行器已接管，正在推进第一步。",
    "已接手任务，正在整理执行步骤。",
    "工具调用已完成，正在根据结果继续。",
    "工具返回成功，正在根据结果继续。",
    "工具返回了结构化结果，正在根据结果继续。",
    "正在判断下一步动作。",
    "工具检查次数达到边界",
}

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
    lowered = text.lower()
    if text in SUPPRESSED_PUBLIC_TEXT or lowered in SUPPRESSED_PUBLIC_TEXT:
        return ""
    if looks_structured_payload(text) or looks_internal_text(text):
        return ""
    if limit > 0 and len(text) > limit:
        return text[: max(1, limit - 1)] + "..."
    return text


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
