from __future__ import annotations

import re
from typing import Any


_GENERIC_PUBLIC_PROGRESS = {
    "",
    "开始处理",
    "处理完成",
    "处理已完成",
    "处理结束",
    "正在处理",
    "正在处理当前请求",
    "正在处理当前步骤",
    "正在处理任务",
    "正在思考",
    "正在整理回复",
    "等待模型输出",
    "已开始处理",
    "已开始处理当前请求",
    "工具调用已完成，正在根据结果继续。",
    "工具返回成功，正在根据结果继续。",
    "工具返回了结构化结果，正在根据结果继续。",
}

_DEPRECATED_STATUS_REWRITES = {
    "已收到请求，正在装配会话上下文、工具边界和运行配置。": "已收到请求，正在准备处理。",
    "已更新本轮上下文，包含会话历史、工具边界和运行配置。": "已同步会话上下文。",
    "已接上当前工作，正在装配最新观察、产物和用户要求。": "已接上当前工作，正在同步最新进展。",
    "已更新本轮上下文，包含最新观察、产物和用户补充要求。": "已同步最新进展。",
}

_PUBLIC_ERROR_REWRITES = {
    "Image generation is not configured": "生图服务没有配置",
    "image generation is not configured": "生图服务没有配置",
    "task_executor_schedule_failed": "任务调度失败",
    "single_turn_tool_iteration_limit": "工具检查次数达到边界",
    "repeated_admission_denial": "重复未获准动作",
}


def public_action_progress_summary(action_type: Any) -> str:
    return ""


def public_runtime_progress_summary(summary: Any) -> str:
    """Normalize a public progress sentence without rewriting its meaning."""

    text = str(summary or "").strip()
    if not text:
        return ""
    normalized = " ".join(text.split()).strip()
    normalized = _DEPRECATED_STATUS_REWRITES.get(normalized, normalized)
    normalized = _public_progress_scrub(normalized)
    if _is_generic_public_progress(normalized):
        return ""
    return _public_role_label(normalized)


def _is_generic_public_progress(text: str) -> bool:
    compact = _compact_public_progress(text)
    generic = {_compact_public_progress(item) for item in _GENERIC_PUBLIC_PROGRESS}
    return compact in generic


def _compact_public_progress(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip("。.!！?？,，;；:：").lower()


def _public_progress_scrub(text: str) -> str:
    normalized = text
    for source, replacement in _PUBLIC_ERROR_REWRITES.items():
        normalized = normalized.replace(source, replacement)
    normalized = _rewrite_raw_tool_failure(normalized)
    normalized = re.sub(r"当前处理已停止\s*[:：]", "当前步骤遇到阻塞：", normalized)
    normalized = re.sub(
        r"当前\s*image_generate\s*的\s*agent_auto_retry_allowed\s*为\s*false\s*[，,]\s*agent_retry_policy\s*为\s*do_not_auto_retry\s*[，,]",
        "当前图像工具不允许自动重试，",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"[（(]\s*target\s+id\s*[:：]\s*[^)）]+[)）]", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\btarget[_\s]+id\s*[:：]\s*[A-Za-z0-9_.:*\-\u4e00-\u9fff]+", "相关产物", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"target_id", "图像目标", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"target\s+id", "图像目标", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"[（(]\s*错误代码\s*[:：]\s*[^)）]+[)）]", "", normalized)
    normalized = normalized.replace("image_generation_failed", "生图失败")
    normalized = normalized.replace("agent_auto_retry_allowed", "自动重试")
    normalized = normalized.replace("agent_retry_policy", "重试策略")
    normalized = normalized.replace("bounded_retry_with_backoff", "有限退避重试")
    normalized = normalized.replace("do_not_auto_retry", "不自动重试")
    normalized = re.sub(r"\s+([，。；：、])", r"\1", normalized)
    normalized = re.sub(r"([（(])\s+", r"\1", normalized)
    normalized = re.sub(r"\s+([）)])", r"\1", normalized)
    return normalized.strip()


def _rewrite_raw_tool_failure(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    if re.search(r"\bold_text not found\b", normalized, flags=re.IGNORECASE):
        return "文件更新未完成：当前内容与预期不一致，需要先读取最新片段再修改。"
    if re.match(r"^Edit failed:\s*file does not exist\b", normalized, flags=re.IGNORECASE):
        return "文件更新未完成：目标文件不存在，需要先确认路径。"
    if re.match(r"^Edit failed:\s*path is a directory\b", normalized, flags=re.IGNORECASE):
        return "文件更新未完成：目标是目录，需要重新确认文件路径。"
    if re.match(r"^Edit failed:", normalized, flags=re.IGNORECASE):
        return "文件更新未完成，需要根据返回结果调整后继续。"
    if re.match(r"^Read failed:", normalized, flags=re.IGNORECASE):
        return "读取未完成，需要重新确认读取范围后继续。"
    if re.match(r"^Write failed:", normalized, flags=re.IGNORECASE):
        return "写入未完成，需要确认目标路径和写入条件后继续。"
    return normalized


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
        return "等待模型输出"
    if step_text.startswith(("model_action_invocation_started", "model_action_received", "task_model_action_invocation_started")):
        return "正在思考"
    if step_text.startswith(("task_tool_", "tool_", "executor_observation", "bounded_observation")):
        return "等待结果返回"
    if step_text.startswith(("task_completion_repair", "model_action_protocol_repair", "verification")):
        return "补齐证据"
    if step_text.endswith("completed") or status_text == "completed":
        return "步骤已完成"
    if status_text.startswith("wait"):
        return "等待继续"
    return fallback
