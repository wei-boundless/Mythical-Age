from __future__ import annotations

import re
from typing import Any


_WAIT_ROUND_RE = re.compile(r"等待轮次[:：]\s*\d+\s*。?")
_ACTION_RE = re.compile(r"(?:agent|助手)?\s*已返回(?:任务)?动作请求[:：]\s*([a-zA-Z_]+)\s*。?", re.IGNORECASE)

_ACTION_SUMMARIES = {
    "respond": "已完成下一步判断，正在整理回复。",
    "ask_user": "需要补充信息，正在准备向你确认。",
    "tool_call": "正在执行必要操作，随后会根据结果继续。",
    "request_task_run": "已确认需要持续处理，正在建立后续步骤。",
    "request_registered_engagement": "已匹配到可承接的处理流程，正在开始推进。",
    "block": "当前步骤遇到边界，正在收口说明。",
}


def public_action_progress_summary(action_type: Any) -> str:
    normalized = str(action_type or "").strip().lower()
    return _ACTION_SUMMARIES.get(normalized, "已完成下一步判断。")


def public_runtime_progress_summary(summary: Any) -> str:
    """Project internal runtime progress into language safe for normal chat UI."""

    text = str(summary or "").strip()
    if not text:
        return ""

    matched = _ACTION_RE.search(text)
    if matched:
        return public_action_progress_summary(matched.group(1))

    normalized = _WAIT_ROUND_RE.sub("", text).strip()
    replacements = (
        ("模型调用仍在进行中，系统继续等待 agent 动作返回。", "仍在处理中，正在等待下一步结果。"),
        ("任务模型调用仍在进行中，系统继续等待 agent 动作返回。", "仍在处理中，正在等待下一步结果。"),
        ("agent 返回的动作请求未通过协议校验；系统已把校验错误作为观察回灌，要求 agent 修正后继续。", "当前步骤输出格式不完整，正在自动修正后继续。"),
        ("agent 返回的任务动作未通过协议校验；系统已把校验错误作为观察回灌，要求 agent 修正下一步动作格式后继续。", "当前步骤输出格式不完整，正在自动修正后继续。"),
        ("系统已完成动作准入检查：allow。", "安全边界已确认。"),
        ("系统已执行一次有边界的只读观察，并把结果回灌给 agent。", "已完成一次必要观察，正在根据结果继续。"),
        ("系统已执行 agent 请求的任务工具调用，并把真实观察回灌给 agent。", "工具调用已完成，正在根据结果继续。"),
        ("工具调用失败；系统已把失败原因作为观察交还给 agent，由 agent 调整路径、参数或执行方式继续推进。", "工具调用失败，正在根据失败原因调整处理路径。"),
        ("agent 尝试收尾，但合同证据不足；系统已把缺口作为观察回灌。", "当前结果还缺少验收证据，正在补齐。"),
        ("客户端或上游流已断开，系统已终止本轮模型等待并关闭 turn 运行记录。", "连接已中断，本轮处理已停止。"),
        ("本轮缺少 runtime assembly，系统已按 fail-closed 停止。", "当前处理缺少必要上下文，已停止以避免错误执行。"),
        ("模型调用失败，运行时已按 fail-closed 停止。", "处理失败，已停止以避免错误执行。"),
        ("本轮动作请求多次未通过协议校验，运行时已按 fail-closed 停止。", "当前步骤多次无法形成有效结果，已停止以避免错误执行。"),
        ("模型重复提交了同一个动作请求，运行时已停止以避免重复执行。", "检测到重复处理，已停止以避免重复执行。"),
    )
    for source, replacement in replacements:
        if normalized == source:
            return replacement

    normalized = normalized.replace("runtime packet", "上下文")
    normalized = normalized.replace("RuntimeInvocationPacket", "上下文")
    normalized = normalized.replace("runtime assembly", "上下文")
    normalized = normalized.replace("TaskRun", "当前工作")
    normalized = normalized.replace("task run", "当前工作")
    normalized = normalized.replace("正式任务生命周期", "处理流程")
    normalized = normalized.replace("正式任务", "当前工作")
    normalized = normalized.replace("任务运行时", "上下文")
    normalized = normalized.replace("任务动作", "下一步")
    normalized = normalized.replace("动作请求", "下一步判断")
    normalized = normalized.replace("准入检查", "安全边界检查")
    normalized = normalized.replace("回灌", "交回")
    normalized = re.sub(r"\bagent\b\s*", "助手", normalized, flags=re.IGNORECASE)
    normalized = normalized.replace("执行器", "处理流程")
    normalized = normalized.replace("系统已", "已")
    normalized = normalized.replace("运行时", "处理流程")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def public_runtime_progress_title(*, step: Any = "", status: Any = "", fallback: str = "处理进展") -> str:
    step_text = str(step or "")
    status_text = str(status or "")
    if "packet" in step_text or "runtime" in step_text or "context" in step_text:
        return "整理上下文"
    if "waiting" in step_text:
        return "等待结果"
    if "model_action_invocation_started" in step_text or "model_action_received" in step_text:
        return "思考下一步"
    if "tool" in step_text or "observation" in step_text:
        return "执行操作"
    if "repair" in step_text or "verification" in step_text:
        return "补齐证据"
    if "completed" in step_text or status_text == "completed":
        return "步骤已完成"
    if status_text.startswith("wait"):
        return "等待继续"
    return fallback
