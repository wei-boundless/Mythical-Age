from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


MemoryWriteAction = Literal["durable_fact", "session_only", "ignore"]
MemoryClass = Literal["work", "preference"]


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

PREFERENCE_MARKERS = (
    "我喜欢",
    "我更喜欢",
    "我的偏好",
    "我偏好",
    "我习惯",
    "以后默认",
    "先讲结论",
    "输出风格",
    "回答风格",
    "i prefer",
    "my preference",
    "prefer you to",
    "conclusion first",
    "answer style",
    "reply style",
)

WORK_MARKERS = (
    "我们项目",
    "项目重点",
    "工作流",
    "流程是",
    "规范",
    "约定",
    "终端命令",
    "默认用 powershell",
    "our project",
    "project focus",
    "workflow",
    "terminal command",
    "terminal commands",
    "powershell",
    "from now on",
    "we always prefer",
    "default terminal",
)


@dataclass(slots=True)
class MemoryWriteDecision:
    action: MemoryWriteAction
    reason: str
    memory_type: str | None = None
    memory_class: MemoryClass | None = None
    tags: list[str] = field(default_factory=list)


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

    if any(marker in lowered for marker in _lower_markers(WORK_MARKERS)):
        return MemoryWriteDecision(
            action="durable_fact",
            reason="stable_work_convention",
            memory_type=_infer_work_memory_type(lowered),
            memory_class="work",
            tags=["work"],
        )

    if any(marker in lowered for marker in _lower_markers(PREFERENCE_MARKERS)):
        return MemoryWriteDecision(
            action="durable_fact",
            reason="stable_user_preference",
            memory_type="preference",
            memory_class="preference",
            tags=["preference"],
        )

    return MemoryWriteDecision(action="ignore", reason="not_durable")


def _infer_work_memory_type(lowered: str) -> str:
    if any(
        marker in lowered
        for marker in (
            "workflow",
            "process",
            "terminal command",
            "terminal commands",
            "powershell",
            "default terminal",
            "工作流",
            "流程",
            "规范",
            "终端命令",
            "命令",
        )
    ):
        return "workflow"
    if any(
        marker in lowered
        for marker in (
            "our project",
            "project focus",
            "architecture",
            "memory",
            "rag",
            "项目",
            "项目重点",
            "架构",
        )
    ):
        return "project"
    return "reference"


def _lower_markers(markers: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(marker.lower() for marker in markers)
