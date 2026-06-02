from __future__ import annotations

from typing import Any


_ACTION_SUMMARIES = {
    "respond": "已完成下一步判断，正在整理回复。",
    "ask_user": "需要补充信息，正在准备向你确认。",
    "tool_call": "正在执行必要操作，随后会根据结果继续。",
    "request_task_run": "已确认需要持续处理，正在建立后续步骤。",
    "request_registered_engagement": "已匹配到可承接的处理流程，正在开始推进。",
    "block": "当前步骤遇到边界，正在收口说明。",
}

_DEPRECATED_STATUS_REWRITES = {
    "已收到请求，正在装配会话上下文、工具边界和运行配置。": "已收到请求，正在准备处理。",
    "已更新本轮上下文，包含会话历史、工具边界和运行配置。": "已同步会话上下文。",
    "已接上当前工作，正在装配最新观察、产物和用户要求。": "已接上当前工作，正在同步最新进展。",
    "已更新本轮上下文，包含最新观察、产物和用户补充要求。": "已同步最新进展。",
}


def public_action_progress_summary(action_type: Any) -> str:
    normalized = str(action_type or "").strip().lower()
    return _ACTION_SUMMARIES.get(normalized, "已完成下一步判断。")


def public_runtime_progress_summary(summary: Any) -> str:
    """Normalize a public progress sentence without rewriting its meaning."""

    text = str(summary or "").strip()
    if not text:
        return ""
    normalized = " ".join(text.split()).strip()
    normalized = _DEPRECATED_STATUS_REWRITES.get(normalized, normalized)
    return _public_role_label(normalized)


def _public_role_label(text: str) -> str:
    if text.startswith("agent "):
        return "助手" + text[len("agent ") :]
    if text.startswith("Agent "):
        return "助手" + text[len("Agent ") :]
    return text


def public_runtime_progress_title(*, step: Any = "", status: Any = "", fallback: str = "处理进展") -> str:
    step_text = str(step or "")
    status_text = str(status or "")
    if step_text.startswith(("runtime_invocation_packet", "task_execution_packet_compiled")):
        return "整理上下文"
    if step_text.startswith(("model_action_waiting", "task_model_action_waiting")):
        return "等待结果"
    if step_text.startswith(("model_action_invocation_started", "model_action_received", "task_model_action_invocation_started")):
        return "确认下一步"
    if step_text.startswith(("task_tool_", "tool_", "executor_observation", "bounded_observation")):
        return "执行操作"
    if step_text.startswith(("task_completion_repair", "model_action_protocol_repair", "verification")):
        return "补齐证据"
    if step_text.endswith("completed") or status_text == "completed":
        return "步骤已完成"
    if status_text.startswith("wait"):
        return "等待继续"
    return fallback
