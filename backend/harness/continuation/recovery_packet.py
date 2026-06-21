from __future__ import annotations

import time
from typing import Any

from .record import ContinuationRecord, continuation_record_from_payload


def build_recovery_packet(
    record: ContinuationRecord | dict[str, Any],
    *,
    resume_intent: str = "status_only",
    user_resume_instruction: str = "",
) -> dict[str, Any]:
    resolved = record if isinstance(record, ContinuationRecord) else continuation_record_from_payload(record)
    if resolved is None:
        return {}
    packet_id = f"recpacket:{resolved.continuation_id}"
    confirmed_progress = [
        item
        for item in [
            resolved.latest_progress,
            resolved.last_completed_step,
            resolved.model_visible_summary,
        ]
        if str(item or "").strip()
    ][:5]
    resume_instruction = _bounded_resume_instruction(user_resume_instruction)
    return {
        "packet_id": packet_id,
        "continuation_id": resolved.continuation_id,
        "session_id": resolved.session_id,
        "task_run_id": resolved.task_run_id,
        "resume_intent": str(resume_intent or "status_only"),
        "user_resume_instruction": resume_instruction,
        "user_visible_goal": resolved.user_visible_goal,
        "confirmed_progress": confirmed_progress,
        "interruption_summary": _interruption_summary(resolved),
        "next_step_contract": resolved.next_recommended_step,
        "artifact_refs": [dict(item) for item in resolved.artifact_refs],
        "resume_constraints": _resume_constraints(resolved),
        "forbidden_actions": [
            "不要根据聊天文本中的“继续”猜测其他任务。",
            "不要伪造上一轮 assistant final message。",
            "不要把 runtime event log 当作完整用户可见答案直接输出。",
        ],
        "model_instruction": _model_instruction(resolved, user_resume_instruction=resume_instruction),
        "created_at": time.time(),
        "authority": "harness.continuation.recovery_packet",
    }


def _bounded_resume_instruction(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) <= 4000:
        return text
    return text[-4000:]


def _interruption_summary(record: ContinuationRecord) -> str:
    if record.recovery_cause == "runtime_restart":
        return "上一轮执行被连接恢复打断，任务已停在可恢复边界。"
    if record.recovery_cause:
        return f"任务停在可恢复边界：{record.recovery_cause}。"
    if record.state == "terminal_read_only":
        return "最近任务已经结束，只能作为只读结果参考。"
    return "任务停在可恢复边界。"


def _resume_constraints(record: ContinuationRecord) -> list[str]:
    constraints = [
        f"continuation_id 必须匹配：{record.continuation_id}",
        f"task_run_id 必须匹配：{record.task_run_id}",
    ]
    if record.resume_allowed:
        constraints.append("恢复后先核对最新文件状态和未完成验收项，再继续执行。")
    else:
        constraints.append("当前记录不允许直接续跑，必须说明状态或请求确认。")
    return constraints


def _model_instruction(record: ContinuationRecord, *, user_resume_instruction: str = "") -> str:
    user_line = (
        f"本次用户继续指令：{user_resume_instruction}\n"
        if str(user_resume_instruction or "").strip()
        else ""
    )
    return (
        "你正在恢复一个被中断的本地 Agent 任务。\n"
        f"当前恢复句柄已校验：continuation_id={record.continuation_id}，task_run_id={record.task_run_id}。\n"
        f"{record.model_visible_summary or '已确认该任务存在可恢复记录。'}\n"
        f"{user_line}"
        "你只允许在这个 task_run 范围内继续，不要从用户的自然语言“继续”猜测其他任务。\n"
        "继续前先核对最新文件状态、运行状态和未完成验收项；如果句柄失效或任务不可续跑，必须说明原因并停止。"
    )
