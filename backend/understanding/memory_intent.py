from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


MemoryReadMode = Literal["none", "durable_exact", "session_state"]
MemoryWriteMode = Literal["none", "durable_fact", "session_state"]


SESSION_MARKERS = (
    "刚刚",
    "刚才",
    "上次",
    "前面",
    "之前",
    "做到哪",
    "进行到哪",
    "where did we stop",
    "what were we doing",
    "what did we do just now",
)

WRITE_MARKERS = (
    "记住",
    "记一下",
    "别忘了",
    "以后默认",
    "以后都",
    "我们约定",
    "记到长期记忆",
    "remember",
    "remember that",
    "don't forget",
    "from now on",
    "always prefer",
)

DURABLE_READ_MARKERS = (
    "你记得",
    "你知道我",
    "我的偏好",
    "我偏好",
    "我习惯",
    "默认用什么",
    "我们项目重点",
    "长期记忆",
    "记忆里",
    "还记得",
    "项目约定",
    "do you remember",
    "what do you remember",
    "what terminal syntax should we use",
    "how should you answer",
    "what should we prioritize",
)

PREFERENCE_HINTS = (
    "喜欢",
    "偏好",
    "习惯",
    "风格",
    "回答方式",
    "i prefer",
    "preference",
    "answer style",
    "reply style",
    "conclusion first",
)

PROJECT_HINTS = (
    "项目",
    "project",
    "重点",
    "主线",
    "优先推进",
    "focus",
    "prioritize",
)

WORKFLOW_HINTS = (
    "powershell",
    "终端",
    "命令",
    "流程",
    "工作流",
    "规范",
    "terminal",
    "syntax",
    "workflow",
)

REFERENCE_HINTS = (
    "reference",
    "资料",
    "背景",
)


@dataclass(slots=True)
class MemoryIntent:
    intent: str = "general"
    memory_read_mode: MemoryReadMode = "none"
    memory_write_mode: MemoryWriteMode = "none"
    should_skip_rag: bool = False
    preferred_types: list[str] = field(default_factory=list)
    preferred_memory_classes: list[str] = field(default_factory=list)


def analyze_memory_intent(message: str) -> MemoryIntent:
    normalized = (message or "").strip()
    lowered = normalized.lower()
    is_question = normalized.endswith("?") or normalized.endswith("？") or any(
        lowered.startswith(prefix)
        for prefix in ("what ", "how ", "do you", "did you", "which ", "why ", "where ")
    )

    if any(marker in lowered for marker in _lower_markers(SESSION_MARKERS)):
        return MemoryIntent(
            intent="session_continuity_query",
            memory_read_mode="session_state",
            should_skip_rag=True,
        )

    if any(marker in lowered for marker in _lower_markers(DURABLE_READ_MARKERS)) or _looks_like_memory_read_query(normalized, lowered):
        return MemoryIntent(
            intent="durable_memory_query",
            memory_read_mode="durable_exact",
            should_skip_rag=True,
            preferred_types=_infer_preferred_types(normalized, lowered),
            preferred_memory_classes=_infer_preferred_classes(normalized, lowered),
        )

    if not is_question and any(marker in lowered for marker in _lower_markers(WRITE_MARKERS)):
        return MemoryIntent(
            intent="durable_memory_statement",
            memory_write_mode="durable_fact",
            should_skip_rag=True,
            preferred_types=_infer_preferred_types(normalized, lowered),
            preferred_memory_classes=_infer_preferred_classes(normalized, lowered),
        )

    return MemoryIntent()


def _infer_preferred_types(message: str, lowered: str) -> list[str]:
    preferred: list[str] = []
    if any(marker in lowered for marker in _lower_markers(PREFERENCE_HINTS)):
        preferred.append("preference")
    if any(marker in lowered for marker in _lower_markers(PROJECT_HINTS)):
        preferred.append("project")
    if any(marker in lowered for marker in _lower_markers(WORKFLOW_HINTS)):
        preferred.append("workflow")
    if not preferred and any(marker in lowered for marker in _lower_markers(REFERENCE_HINTS)):
        preferred.append("reference")
    return preferred


def _infer_preferred_classes(message: str, lowered: str) -> list[str]:
    preferred: list[str] = []
    if any(marker in lowered for marker in _lower_markers(PREFERENCE_HINTS)):
        preferred.append("preference")
    if any(marker in lowered for marker in _lower_markers(PROJECT_HINTS + WORKFLOW_HINTS + REFERENCE_HINTS)):
        preferred.append("work")
    if not preferred:
        return []

    deduped: list[str] = []
    for item in preferred:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _looks_like_memory_read_query(message: str, lowered: str) -> bool:
    patterns = (
        ("project", "focus"),
        ("terminal", "default"),
        ("answer", "style"),
        ("conclusion", "first"),
        ("偏好", "什么"),
        ("默认", "什么"),
        ("项目", "重点"),
    )
    return any(left in lowered and right in lowered for left, right in patterns)


def _lower_markers(markers: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(marker.lower() for marker in markers)
