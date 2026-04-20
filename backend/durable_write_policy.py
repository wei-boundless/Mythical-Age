from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


MemoryWriteAction = Literal["durable_fact", "session_only", "ignore"]
MemoryClass = Literal["work", "preference"]
DurableMemoryType = Literal["user", "feedback", "project", "reference"]
CandidateDecision = Literal["accept", "needs_confirmation", "session_only", "reject"]


@dataclass(slots=True)
class MemoryWriteDecision:
    action: MemoryWriteAction
    reason: str
    memory_type: DurableMemoryType | None = None
    memory_class: MemoryClass | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DurableCandidateDecision:
    action: CandidateDecision
    reason: str
    memory_type: DurableMemoryType
    memory_class: MemoryClass
    confidence: str


EMOTIONAL_ATTACHMENT_MARKERS = (
    "我爱上了你",
    "我爱上你了",
    "我爱你",
    "我离不开你",
    "我想和你在一起",
    "和你恋爱",
    "love you",
    "fall in love with you",
)

EMOTION_STATE_MARKERS = (
    "我很难过",
    "我很伤心",
    "我很焦虑",
    "我很孤独",
    "我现在很",
    "我今天很",
    "i feel sad",
    "i feel anxious",
    "i feel lonely",
)

TESTING_MARKERS = (
    "情景测试",
    "测试一下",
    "我在测试",
    "memory system",
    "testing memory",
    "scenario test",
)

PROJECT_POLICY_MARKERS = (
    "长期记忆",
    "durable memory",
    "exact-first",
    "memory policy",
    "记忆策略",
    "记忆规则",
)

USER_PREFERENCE_MARKERS = (
    "我喜欢",
    "我更喜欢",
    "我的偏好",
    "我偏好",
    "我习惯",
    "先给结论",
    "先讲结论",
    "输出风格",
    "回答风格",
    "称呼我",
    "用中文",
    "i prefer",
    "my preference",
    "prefer you to",
    "conclusion first",
    "answer style",
    "reply style",
    "call me",
)

PROJECT_FACT_MARKERS = (
    "我们项目",
    "项目重点",
    "项目主线",
    "项目方向",
    "项目长期",
    "架构",
    "memory",
    "rag",
    "our project",
    "project focus",
    "project direction",
    "architecture",
    "mainline",
)

REFERENCE_MARKERS = (
    "文档在",
    "资料在",
    "地址是",
    "链接是",
    "仓库在",
    "wiki",
    "notion",
    "url",
    "link",
    "repo is",
    "document is",
)

STATIC_PROFILE_RULE_MARKERS = (
    "powershell",
    "终端命令",
    "terminal command",
    "terminal commands",
    "default terminal",
    "工作流",
    "workflow",
    "流程",
    "规范",
    "约定",
    "多模态资料入库",
    "embedding 和索引",
)

FEEDBACK_MARKERS = (
    "不要",
    "别再",
    "应该",
    "请改成",
    "下次",
    "纠正一下",
    "do not",
    "don't",
    "should",
    "instead",
    "next time",
)

SESSION_ONLY_MARKERS = (
    "今天",
    "现在",
    "刚刚",
    "这次",
    "当前任务",
    "正在",
)

REJECT_MARKERS = (
    "你在干什么",
    "查的不对",
    "不对",
    "错了",
)


def evaluate_memory_write(content: str) -> MemoryWriteDecision:
    normalized = (content or "").strip()
    lowered = normalized.lower()
    if not normalized:
        return MemoryWriteDecision(action="ignore", reason="empty")

    if any(marker in lowered for marker in _lower_markers(EMOTIONAL_ATTACHMENT_MARKERS)):
        return MemoryWriteDecision(
            action="session_only",
            reason="emotional_attachment_to_agent",
            tags=["emotion", "session-only"],
        )

    if any(marker in lowered for marker in _lower_markers(EMOTION_STATE_MARKERS)):
        return MemoryWriteDecision(
            action="session_only",
            reason="transient_emotional_state",
            tags=["emotion", "session-only"],
        )

    if any(marker in lowered for marker in _lower_markers(STATIC_PROFILE_RULE_MARKERS)):
        return MemoryWriteDecision(
            action="ignore",
            reason="static_profile_rule",
            tags=["profile-rule"],
        )

    if any(marker in lowered for marker in _lower_markers(TESTING_MARKERS)) and any(
        marker in lowered for marker in _lower_markers(PROJECT_POLICY_MARKERS)
    ):
        return MemoryWriteDecision(
            action="durable_fact",
            reason="memory_policy_feedback",
            memory_type="project",
            memory_class="work",
            tags=["memory-policy", "testing"],
        )

    if any(marker in lowered for marker in _lower_markers(FEEDBACK_MARKERS)) and any(
        marker in lowered for marker in _lower_markers(USER_PREFERENCE_MARKERS + PROJECT_FACT_MARKERS)
    ):
        return MemoryWriteDecision(
            action="durable_fact",
            reason="stable_feedback",
            memory_type="feedback",
            memory_class="work",
            tags=["feedback"],
        )

    if any(marker in lowered for marker in _lower_markers(PROJECT_FACT_MARKERS)):
        return MemoryWriteDecision(
            action="durable_fact",
            reason="stable_project_fact",
            memory_type="project",
            memory_class="work",
            tags=["project"],
        )

    if any(marker in lowered for marker in _lower_markers(USER_PREFERENCE_MARKERS)):
        return MemoryWriteDecision(
            action="durable_fact",
            reason="stable_user_preference",
            memory_type="user",
            memory_class="preference",
            tags=["user-preference"],
        )

    if any(marker in lowered for marker in _lower_markers(REFERENCE_MARKERS)):
        return MemoryWriteDecision(
            action="durable_fact",
            reason="stable_reference_pointer",
            memory_type="reference",
            memory_class="work",
            tags=["reference"],
        )

    return MemoryWriteDecision(action="ignore", reason="not_durable")


def evaluate_candidate_text(
    text: str,
    *,
    source_kind: str,
    fallback_type: str = "project",
    fallback_class: str = "work",
) -> DurableCandidateDecision:
    normalized = (text or "").strip().lower()
    if any(marker in normalized for marker in REJECT_MARKERS):
        return DurableCandidateDecision(
            action="reject",
            reason="meta_or_correction_noise",
            memory_type=_normalize_memory_type(fallback_type),
            memory_class=_normalize_memory_class(fallback_class),
            confidence="low",
        )

    if any(marker in normalized for marker in SESSION_ONLY_MARKERS):
        return DurableCandidateDecision(
            action="session_only",
            reason="short_lived_session_state",
            memory_type=_normalize_memory_type(fallback_type),
            memory_class=_normalize_memory_class(fallback_class),
            confidence="low",
        )

    decision = evaluate_memory_write(text)
    if decision.action == "session_only":
        return DurableCandidateDecision(
            action="session_only",
            reason=decision.reason,
            memory_type=_normalize_memory_type(fallback_type),
            memory_class=_normalize_memory_class(fallback_class),
            confidence="low",
        )

    if decision.action != "durable_fact" or decision.memory_type is None or decision.memory_class is None:
        if source_kind == "session_convention":
            return DurableCandidateDecision(
                action="reject",
                reason="static_profile_rule",
                memory_type="project",
                memory_class="work",
                confidence="low",
            )
        return DurableCandidateDecision(
            action="needs_confirmation",
            reason="candidate_needs_more_confirmation",
            memory_type=_normalize_memory_type(fallback_type),
            memory_class=_normalize_memory_class(fallback_class),
            confidence="medium",
        )

    confidence = "high" if decision.memory_type in {"user", "project", "feedback"} else "medium"
    return DurableCandidateDecision(
        action="accept",
        reason=decision.reason,
        memory_type=decision.memory_type,
        memory_class=decision.memory_class,
        confidence=confidence,
    )


def _normalize_memory_type(value: str) -> DurableMemoryType:
    lowered = str(value or "project").strip().lower()
    if lowered == "preference":
        return "user"
    if lowered == "workflow":
        return "project"
    if lowered in {"user", "feedback", "project", "reference"}:
        return lowered
    return "project"


def _normalize_memory_class(value: str) -> MemoryClass:
    lowered = str(value or "work").strip().lower()
    if lowered == "preference":
        return "preference"
    return "work"


def _lower_markers(markers: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(marker.lower() for marker in markers)
