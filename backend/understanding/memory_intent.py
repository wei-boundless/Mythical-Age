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

DURABLE_QUERY_PROFILES = (
    {
        "preferred_types": ["preference"],
        "preferred_classes": ["preference"],
        "entity_markers": PREFERENCE_HINTS,
        "recall_markers": (
            "怎么回答",
            "回答方式",
            "先给结论",
            "第一句",
            "answer style",
            "reply style",
            "conclusion first",
        ),
    },
    {
        "preferred_types": ["workflow"],
        "preferred_classes": ["work"],
        "entity_markers": WORKFLOW_HINTS,
        "recall_markers": (
            "默认用什么",
            "应该用什么",
            "用什么",
            "什么命令",
            "terminal syntax",
            "by default",
        ),
    },
    {
        "preferred_types": ["project"],
        "preferred_classes": ["work"],
        "entity_markers": PROJECT_HINTS,
        "recall_markers": (
            "重点",
            "主线",
            "优先",
            "方向",
            "先做什么",
            "priority",
            "focus",
            "direction",
        ),
    },
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
    query_profile = _match_durable_query_profile(lowered)
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

    if (
        any(marker in lowered for marker in _lower_markers(DURABLE_READ_MARKERS))
        or query_profile is not None
        or _looks_like_memory_read_query(normalized, lowered)
    ):
        preferred_types = query_profile[0] if query_profile is not None else _infer_preferred_types(normalized, lowered)
        preferred_classes = query_profile[1] if query_profile is not None else _infer_preferred_classes(normalized, lowered)
        return MemoryIntent(
            intent="durable_memory_query",
            memory_read_mode="durable_exact",
            should_skip_rag=True,
            preferred_types=preferred_types,
            preferred_memory_classes=preferred_classes,
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
        ("project", "priority"),
        ("project", "direction"),
        ("terminal", "default"),
        ("answer", "style"),
        ("conclusion", "first"),
        ("偏好", "什么"),
        ("默认", "什么"),
        ("项目", "重点"),
        ("项目", "主线"),
        ("项目", "方向"),
        ("主线", "什么"),
        ("主线", "哪条"),
        ("现阶段", "优先"),
        ("现在", "优先"),
    )
    return any(left in lowered and right in lowered for left, right in patterns)


def _match_durable_query_profile(lowered: str) -> tuple[list[str], list[str]] | None:
    for profile in DURABLE_QUERY_PROFILES:
        if _contains_any(lowered, profile["entity_markers"]) and _contains_any(lowered, profile["recall_markers"]):
            return (list(profile["preferred_types"]), list(profile["preferred_classes"]))
    return None


def _contains_any(text: str, markers: tuple[str, ...] | list[str]) -> bool:
    lowered_markers = _lower_markers(tuple(markers))
    return any(marker in text for marker in lowered_markers)


def _lower_markers(markers: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(marker.lower() for marker in markers)
