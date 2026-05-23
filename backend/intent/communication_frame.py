from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

USER_POSTURES = {"ask", "explore", "execute", "correct", "continue", "review", "dissatisfied", "conversation"}
AGENT_POSTURES = {
    "answer",
    "clarify",
    "plan_first",
    "execute",
    "review_first",
    "repair_understanding",
    "continue_task",
}
COLLABORATION_MODES = {"conversation", "planning", "implementation", "verification", "long_task"}
CLARIFICATION_POLICIES = {"ask_now", "proceed_with_assumption", "no_clarification_needed"}
PROGRESS_POLICIES = {"none", "brief_updates", "todo_required"}
FINAL_RESPONSE_CONTRACTS = {
    "direct_answer",
    "implementation_report",
    "findings_first",
    "verification_report",
    "planning_report",
}


@dataclass(frozen=True, slots=True)
class CommunicationFrame:
    frame_id: str
    user_posture: str
    agent_posture: str
    collaboration_mode: str
    clarification_policy: str
    progress_policy: str
    final_response_contract: str
    latest_user_instruction_priority: bool = True
    evidence: dict[str, Any] = field(default_factory=dict)
    authority: str = "intent.communication_frame"

    def __post_init__(self) -> None:
        if self.authority != "intent.communication_frame":
            raise ValueError("CommunicationFrame authority must be intent.communication_frame")
        if not self.frame_id:
            raise ValueError("CommunicationFrame requires frame_id")
        if self.user_posture not in USER_POSTURES:
            raise ValueError(f"Invalid user_posture: {self.user_posture}")
        if self.agent_posture not in AGENT_POSTURES:
            raise ValueError(f"Invalid agent_posture: {self.agent_posture}")
        if self.collaboration_mode not in COLLABORATION_MODES:
            raise ValueError(f"Invalid collaboration_mode: {self.collaboration_mode}")
        if self.clarification_policy not in CLARIFICATION_POLICIES:
            raise ValueError(f"Invalid clarification_policy: {self.clarification_policy}")
        if self.progress_policy not in PROGRESS_POLICIES:
            raise ValueError(f"Invalid progress_policy: {self.progress_policy}")
        if self.final_response_contract not in FINAL_RESPONSE_CONTRACTS:
            raise ValueError(f"Invalid final_response_contract: {self.final_response_contract}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = dict(self.evidence or {})
        return payload


def build_communication_frame(
    message: str,
    *,
    action_intent: str = "",
    user_provided_flow: tuple[str, ...] | list[str] = (),
    ambiguity_points: tuple[str, ...] | list[str] = (),
    forbidden_actions: tuple[str, ...] | list[str] = (),
    query_understanding: dict[str, Any] | None = None,
) -> CommunicationFrame:
    text = str(message or "").strip()
    lowered = text.lower()
    query = dict(query_understanding or {})
    user_posture = _user_posture(lowered)
    agent_posture = _agent_posture(
        user_posture=user_posture,
        action_intent=action_intent,
        ambiguity_points=tuple(ambiguity_points or ()),
        forbidden_actions=tuple(forbidden_actions or ()),
    )
    mode = _collaboration_mode(
        user_posture=user_posture,
        action_intent=action_intent,
        user_provided_flow=tuple(user_provided_flow or ()),
        query_understanding=query,
    )
    return CommunicationFrame(
        frame_id=f"communication:{_slug(text)[:48] or 'runtime'}",
        user_posture=user_posture,
        agent_posture=agent_posture,
        collaboration_mode=mode,
        clarification_policy=_clarification_policy(
            agent_posture=agent_posture,
            ambiguity_points=tuple(ambiguity_points or ()),
            forbidden_actions=tuple(forbidden_actions or ()),
        ),
        progress_policy=_progress_policy(mode=mode, user_provided_flow=tuple(user_provided_flow or ())),
        final_response_contract=_final_response_contract(user_posture=user_posture, action_intent=action_intent, mode=mode),
        latest_user_instruction_priority=True,
        evidence={
            "posture_markers": _posture_markers(lowered),
            "model_turn_decision": dict(query.get("model_turn_decision") or {}),
        },
    )


def _user_posture(lowered: str) -> str:
    if _has_any(lowered, ("不对", "不是", "你错", "纠正", "修正理解", "不要这样", "不是让你")):
        return "correct"
    if _has_any(lowered, ("奇怪", "不满", "敷衍", "藏私", "糊弄", "差不多就是不对")):
        return "dissatisfied"
    if _has_any(lowered, ("继续", "接着", "下一步", "往下", "推进")):
        return "continue"
    if _has_any(lowered, ("审查", "review", "检查一下", "评审")):
        return "review"
    if _has_any(lowered, ("设计", "规划", "计划", "方案", "架构", "怎么做")):
        return "explore"
    if _has_any(lowered, ("做", "实现", "开发", "修复", "修改", "写入", "生成", "创建", "执行", "开始")):
        return "execute"
    if _has_any(lowered, ("解释", "说明", "为什么", "是什么", "吗", "?")):
        return "ask"
    return "conversation"


def _agent_posture(
    *,
    user_posture: str,
    action_intent: str,
    ambiguity_points: tuple[str, ...],
    forbidden_actions: tuple[str, ...],
) -> str:
    if user_posture in {"correct", "dissatisfied"}:
        return "repair_understanding"
    if user_posture == "continue":
        return "continue_task"
    if user_posture == "review":
        return "review_first"
    if ambiguity_points and action_intent in {"modify", "create", "execute"}:
        return "clarify"
    if "modify_workspace" in set(forbidden_actions):
        return "plan_first" if action_intent in {"modify", "create", "execute"} else "answer"
    if user_posture == "explore":
        return "plan_first"
    if user_posture == "execute" or action_intent in {"modify", "create"}:
        return "execute"
    return "answer"


def _collaboration_mode(
    *,
    user_posture: str,
    action_intent: str,
    user_provided_flow: tuple[str, ...],
    query_understanding: dict[str, Any],
) -> str:
    if user_posture == "review" or action_intent == "verify":
        return "verification"
    if user_posture == "explore":
        return "planning"
    if action_intent in {"modify", "create"}:
        return "long_task" if len(user_provided_flow) >= 3 else "implementation"
    return "conversation"


def _clarification_policy(
    *,
    agent_posture: str,
    ambiguity_points: tuple[str, ...],
    forbidden_actions: tuple[str, ...],
) -> str:
    if agent_posture == "clarify":
        return "ask_now"
    if ambiguity_points or forbidden_actions:
        return "proceed_with_assumption"
    return "no_clarification_needed"


def _progress_policy(*, mode: str, user_provided_flow: tuple[str, ...]) -> str:
    if mode == "long_task" or len(user_provided_flow) >= 3:
        return "todo_required"
    if mode in {"implementation", "verification"}:
        return "brief_updates"
    return "none"


def _final_response_contract(*, user_posture: str, action_intent: str, mode: str) -> str:
    if user_posture == "review":
        return "findings_first"
    if mode == "verification" or action_intent == "verify":
        return "verification_report"
    if mode == "planning" or user_posture == "explore":
        return "planning_report"
    if mode in {"implementation", "long_task"}:
        return "implementation_report"
    return "direct_answer"


def _posture_markers(lowered: str) -> list[str]:
    markers = ["纠偏", "继续", "审查", "设计", "执行", "解释", "不满"]
    return [marker for marker in markers if marker in lowered]


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _slug(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").lower()).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "runtime"
