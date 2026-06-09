from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from harness.runtime.public_progress import public_runtime_progress_summary


ActiveWorkTurnAction = Literal[
    "continue_active_work",
    "pause_active_work",
    "stop_active_work",
    "append_instruction_to_active_work",
    "answer_about_active_work",
    "ask_user",
    "answer_then_continue_active_work",
]

_ALLOWED_ACTIONS: set[str] = {
    "continue_active_work",
    "pause_active_work",
    "stop_active_work",
    "append_instruction_to_active_work",
    "answer_about_active_work",
    "ask_user",
    "answer_then_continue_active_work",
}
_CURRENT_WORK_ACTIONS = {
    "continue_active_work",
    "pause_active_work",
    "stop_active_work",
    "append_instruction_to_active_work",
    "answer_about_active_work",
    "answer_then_continue_active_work",
}
_ACTION_FIELD_ALIASES = (
    "action",
    "intent",
    "control_action",
    "active_work_action",
    "subaction",
    "operation",
)
_ACTION_ALIASES = {
    "continue": "continue_active_work",
    "resume": "continue_active_work",
    "resume_active_work": "continue_active_work",
    "continue_work": "continue_active_work",
    "continue_current_work": "continue_active_work",
    "pause": "pause_active_work",
    "pause_work": "pause_active_work",
    "pause_current_work": "pause_active_work",
    "stop": "stop_active_work",
    "cancel": "stop_active_work",
    "abort": "stop_active_work",
    "stop_work": "stop_active_work",
    "stop_current_work": "stop_active_work",
    "append_instruction": "append_instruction_to_active_work",
    "append_instructions": "append_instruction_to_active_work",
    "append_user_instruction": "append_instruction_to_active_work",
    "add_instruction": "append_instruction_to_active_work",
    "add_requirement": "append_instruction_to_active_work",
    "steer": "append_instruction_to_active_work",
    "status": "answer_about_active_work",
    "progress": "answer_about_active_work",
    "answer_status": "answer_about_active_work",
    "answer_about_work": "answer_about_active_work",
    "answer_then_continue": "answer_then_continue_active_work",
    "reply_then_continue": "answer_then_continue_active_work",
    "answer_then_resume": "answer_then_continue_active_work",
}
_NON_CONTROL_RESPONSE_ACTIONS = {
    "respond",
    "normal_response",
    "answer",
    "reply",
}


def active_work_action_from_payload(payload: dict[str, Any] | None) -> str:
    raw = dict(payload or {})
    for field in _ACTION_FIELD_ALIASES:
        action = _normalize_action_name(raw.get(field))
        if action:
            return action
    return ""


def _normalize_action_name(value: Any) -> str:
    action = str(value or "").strip()
    if not action:
        return ""
    normalized = action.lower().replace("-", "_").replace(" ", "_")
    return _ACTION_ALIASES.get(normalized, normalized)


@dataclass(frozen=True, slots=True)
class ActiveWorkContext:
    session_id: str
    active_work_id: str
    task_run_id: str
    status: str
    control_state: str = ""
    user_visible_goal: str = ""
    latest_progress: str = ""
    latest_step_name: str = ""
    resumable: bool = False
    running: bool = False
    paused: bool = False
    queued_user_instruction_count: int = 0
    execution_runtime_kind: str = ""
    continuation_kind: str = "active"
    same_run_allowed: bool = False
    authority: str = "harness.loop.active_work_context"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_model_dict(self) -> dict[str, Any]:
        payload = self.to_dict()
        payload.pop("task_run_id", None)
        payload.pop("authority", None)
        payload["current_work_id"] = self.active_work_id
        payload["status_label"] = active_work_status_label(self)
        return payload

@dataclass(frozen=True, slots=True)
class ActiveWorkTurnDecision:
    action: ActiveWorkTurnAction
    response: str = ""
    appended_instruction: str = ""
    reason: str = ""
    relation_to_current_work: str = "ambiguous"
    evidence: str = ""
    turn_response_policy: str = ""
    user_turn_kind: str = "ambiguous"
    answer_obligation: str = "unspecified"
    continuation_strategy: str = ""
    accepted: bool = True
    denied_reason: str = ""
    authority: str = "harness.loop.active_work_turn_decision"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def active_work_turn_decision_from_payload(payload: dict[str, Any] | None, *, user_message: str = "") -> ActiveWorkTurnDecision:
    raw = dict(payload or {})
    authority = str(raw.get("authority") or "harness.loop.active_work_turn_decision").strip()
    action = active_work_action_from_payload(raw)
    if authority != "harness.loop.active_work_turn_decision":
        return _denied_active_work_decision("active_work_turn_decision_authority_invalid")
    response = public_active_work_text(str(raw.get("response") or raw.get("final_answer") or ""))
    if action in _NON_CONTROL_RESPONSE_ACTIONS:
        return ActiveWorkTurnDecision(
            action="answer_about_active_work",
            response=response,
            reason="normalized_non_control_response",
            relation_to_current_work=_normalize_relation_to_current_work(
                raw.get("relation_to_current_work") or raw.get("relation")
            ),
            evidence=str(raw.get("evidence") or raw.get("routing_evidence") or "").strip(),
            turn_response_policy="answer_only",
            user_turn_kind=_normalize_user_turn_kind(raw.get("user_turn_kind") or raw.get("turn_kind") or raw.get("utterance_kind")),
            answer_obligation="direct_answer_required",
            continuation_strategy="none",
        )
    if action not in _ALLOWED_ACTIONS:
        return _denied_active_work_decision("active_work_control_action_not_allowed")
    appended_instruction = str(raw.get("appended_instruction") or "").strip()
    if action == "append_instruction_to_active_work" and not appended_instruction:
        appended_instruction = str(user_message or "").strip()
    relation_to_current_work = _normalize_relation_to_current_work(
        raw.get("relation_to_current_work") or raw.get("relation")
    )
    evidence = str(raw.get("evidence") or raw.get("routing_evidence") or "").strip()
    turn_response_policy = _normalize_turn_response_policy(raw.get("turn_response_policy"), action=action)
    user_turn_kind = _normalize_user_turn_kind(raw.get("user_turn_kind") or raw.get("turn_kind") or raw.get("utterance_kind"))
    answer_obligation = _normalize_answer_obligation(
        raw.get("answer_obligation") or raw.get("response_obligation"),
        user_turn_kind=user_turn_kind,
        turn_response_policy=turn_response_policy,
        action=action,
    )
    continuation_strategy = _normalize_continuation_strategy(
        raw.get("continuation_strategy") or raw.get("resume_strategy") or raw.get("continuation_mode"),
        action=action,
    )
    if action in _CURRENT_WORK_ACTIONS and relation_to_current_work != "current_work":
        denied_reason = (
            "active_work_relation_declared_independent"
            if relation_to_current_work == "independent_turn"
            else "active_work_relation_ambiguous"
        )
        return _denied_active_work_decision(
            denied_reason,
            reason=denied_reason,
            relation_to_current_work=relation_to_current_work,
            evidence=evidence,
            turn_response_policy=turn_response_policy,
            user_turn_kind=user_turn_kind,
            answer_obligation=answer_obligation,
            continuation_strategy=continuation_strategy,
        )
    return ActiveWorkTurnDecision(
        action=action,  # type: ignore[arg-type]
        response=response,
        appended_instruction=appended_instruction,
        reason=str(raw.get("reason") or "").strip(),
        relation_to_current_work=relation_to_current_work,
        evidence=evidence,
        turn_response_policy=turn_response_policy,
        user_turn_kind=user_turn_kind,
        answer_obligation=answer_obligation,
        continuation_strategy=continuation_strategy,
    )


def _denied_active_work_decision(
    denied_reason: str,
    *,
    reason: str = "",
    relation_to_current_work: str = "ambiguous",
    evidence: str = "",
    turn_response_policy: str = "",
    user_turn_kind: str = "ambiguous",
    answer_obligation: str = "unspecified",
    continuation_strategy: str = "",
) -> ActiveWorkTurnDecision:
    return ActiveWorkTurnDecision(
        action="ask_user",
        response="",
        reason=reason or denied_reason,
        relation_to_current_work=relation_to_current_work,
        evidence=evidence,
        turn_response_policy=turn_response_policy,
        user_turn_kind=user_turn_kind,
        answer_obligation=answer_obligation,
        continuation_strategy=continuation_strategy,
        accepted=False,
        denied_reason=denied_reason,
    )


def active_work_control_denial_reply(decision: ActiveWorkTurnDecision) -> str:
    reason = str(decision.denied_reason or decision.reason or "").strip()
    if reason == "active_work_relation_declared_independent":
        return "我没有控制当前工作，因为这次动作没有明确指向当前工作。请重新提出独立问题，或直接说明要继续、暂停、停止或补充当前工作。"
    if reason == "active_work_relation_ambiguous":
        return "我没有控制当前工作，因为这次动作没有明确指向当前工作。请直接说明要继续、暂停、停止、补充要求还是询问当前进展。"
    if reason == "active_work_control_action_not_allowed":
        return "我没有控制当前工作，因为本轮返回的当前工作动作不在允许范围内。请重新提出独立问题，或说明要继续、暂停、停止、补充要求还是询问当前进展。"
    return "我没有控制当前工作，因为本轮当前工作动作没有通过运行边界校验。请重新说明你要如何处理当前工作。"


def _normalize_relation_to_current_work(value: Any) -> str:
    relation = str(value or "").strip().lower()
    if relation in {"current_work", "current", "active_work", "task", "same_work"}:
        return "current_work"
    if relation in {"independent_turn", "independent", "new_turn", "unrelated", "normal_response"}:
        return "independent_turn"
    return "ambiguous"

def _normalize_turn_response_policy(value: Any, *, action: str) -> str:
    policy = str(value or "").strip().lower()
    if policy in {"answer_only", "answer_then_active_work"}:
        return policy
    if policy == "active_work_only":
        return "answer_then_active_work"
    if action == "answer_then_continue_active_work":
        return "answer_then_active_work"
    if action in {"normal_response", "start_new_work"}:
        return "answer_only"
    return "answer_then_active_work"


def _normalize_user_turn_kind(value: Any) -> str:
    kind = str(value or "").strip().lower()
    if kind in {"question", "ask", "status_question", "progress_question"}:
        return "question"
    if kind in {"complaint", "frustration", "critique", "status_critique", "latency_complaint"}:
        return "complaint"
    if kind in {"command", "instruction", "control", "request"}:
        return "command"
    if kind in {"mixed", "question_and_command", "ask_then_command"}:
        return "mixed"
    if kind in {"statement", "chat", "comment"}:
        return "statement"
    return "ambiguous"


def _normalize_answer_obligation(value: Any, *, user_turn_kind: str, turn_response_policy: str, action: str) -> str:
    obligation = str(value or "").strip().lower()
    if obligation in {"direct_answer_required", "answer_required", "must_answer", "answer_user_first"}:
        return "direct_answer_required"
    if obligation in {"acknowledgement_only", "ack_only", "ack"}:
        return "acknowledgement_only"
    if obligation in {"none", "no_answer_required"}:
        return "none"
    if user_turn_kind in {"question", "complaint", "mixed"}:
        return "direct_answer_required"
    if action == "answer_then_continue_active_work":
        return "direct_answer_required"
    if action in {"continue_active_work", "append_instruction_to_active_work", "pause_active_work", "stop_active_work"}:
        return "acknowledgement_only"
    if turn_response_policy == "answer_then_active_work":
        return "acknowledgement_only"
    return "unspecified"


def _normalize_continuation_strategy(value: Any, *, action: str) -> str:
    strategy = str(value or "").strip().lower()
    aliases = {
        "continue_same_run": "same_run_resume",
        "same_run": "same_run_resume",
        "resume": "same_run_resume",
        "resume_same_task": "same_run_resume",
        "running": "already_running",
        "record_instruction": "already_running",
        "wait": "defer",
        "ask_first": "defer",
        "no_resume": "none",
        "normal_response": "none",
    }
    strategy = aliases.get(strategy, strategy)
    if strategy in {"same_run_resume", "already_running", "defer", "none"}:
        return strategy
    if action in {"normal_response", "start_new_work", "answer_about_active_work", "ask_user", "pause_active_work", "stop_active_work"}:
        return "none"
    return ""


def public_active_work_text(value: str) -> str:
    text = str(value or "").strip()
    replacements = {
        "TaskRun": "当前工作",
        "task run": "当前工作",
        "runtime packet": "上下文",
        "执行器": "处理流程",
        "正式任务": "当前工作",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def active_work_status_label(context: ActiveWorkContext) -> str:
    if context.continuation_kind == "completed_iteration":
        return "已完成"
    if context.paused:
        return "已暂停"
    if context.control_state == "pause_requested":
        return "正在暂停"
    if context.control_state == "stop_requested":
        return "正在停止"
    if context.status in {"waiting_executor", "blocked"}:
        return "等待继续"
    if context.status == "waiting_approval":
        return "等待确认"
    if context.status in {"created", "running"}:
        return "正在处理"
    if context.status in {"completed", "success"}:
        return "已完成"
    if context.status in {"failed", "aborted", "cancelled", "error"}:
        return "已结束"
    return context.status or "处理中"


def active_work_status_reply(context: ActiveWorkContext) -> str:
    parts = [f"现在是{active_work_status_label(context)}。"]
    if context.user_visible_goal:
        parts.append(f"当前处理的是：{context.user_visible_goal}")
    if context.latest_progress:
        parts.append(f"最近进展：{context.latest_progress}")
    if context.paused:
        parts.append("你说继续后，我会从这里接着处理。")
    elif context.resumable:
        parts.append("目前可以继续推进。")
    elif context.running:
        parts.append("我会把新的进展继续更新在当前会话里。")
    return "\n".join(part for part in parts if part.strip())


def default_reply_for_action(action: str, context: ActiveWorkContext) -> str:
    if action == "continue_active_work":
        return "好，我接着处理。"
    if action == "pause_active_work":
        return "好，我先停在这里。后面你说继续，我会从这里接着做。"
    if action == "stop_active_work":
        return "好，我会停止当前处理。"
    if action == "append_instruction_to_active_work":
        return "收到，我会按这个补充方向继续处理。"
    if action == "answer_about_active_work":
        return active_work_status_reply(context)
    if action == "answer_then_continue_active_work":
        return "我先回答你这句话，然后继续处理当前工作。"
    return ""

def _public_progress_text(value: str) -> str:
    text = public_runtime_progress_summary(public_active_work_text(str(value or "").strip()))
    replacements = {
        "系统已为当前任务步骤装配 上下文，并交给 助手 判断下一步。": "正在整理上下文，准备继续处理。",
        "任务 上下文 已送入模型，系统正在等待 助手 返回任务动作。": "正在处理这一步。",
        "运行包已交给模型，等待 助手 返回下一步动作。": "正在处理这一步。",
        "任务执行器已被调度，正在接管 当前工作。": "正在准备继续处理。",
    }
    for source, target in replacements.items():
        if text == source:
            return target
    return text


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text and not _looks_internal_identifier(text):
            return text
    return ""


def _looks_internal_identifier(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(("task:", "taskrun:", "turn:", "turnrun:", "session:", "rtobj:"))
