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
        "runtime_facts": {
            "context_resume_available": bool(resolved.context_resume_available),
            "context_resume_source": resolved.context_resume_source,
            "same_run_executable": bool(resolved.same_run_executable),
            "task_status": resolved.task_status,
            "executor_status": resolved.executor_status,
            "control_state": resolved.control_state,
        },
        "forbidden_actions": [
            "不要根据聊天文本中的“继续”猜测其他任务。",
            "不要伪造上一轮 assistant final message。",
            "不要把 runtime event log 当作完整用户可见答案直接输出。",
            "不要把 task_run 可执行性当作语义裁决；task 断开信息只是事实，是否继续由 agent 判断。",
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
        constraints.append("同运行续跑动作当前可调用；调用前仍必须由 agent 根据上下文、任务断开事实、最新文件状态和未完成验收项判断是否应该执行。")
    else:
        constraints.append("当前记录不允许直接调用同运行续跑动作；上下文事实仍可用于普通对话延续、重新规划、说明状态或请求确认。")
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
        "系统只提供事实、权限和信号，不替你决定是否继续任务。\n"
        "你需要根据用户目标、上下文、任务断开事实、最新文件状态和未完成验收项判断下一步：同运行续跑、重新规划、说明状态、请求确认，或先补证据。\n"
        "只有 runtime_facts.same_run_executable 与动作许可都成立时，才可以调用同运行续跑；否则不要伪造续跑。"
    )
