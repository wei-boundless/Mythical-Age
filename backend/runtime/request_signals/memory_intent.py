from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


MemoryReadMode = Literal["none", "durable_exact", "session_state", "durable_semantic"]
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

MANUAL_MEMORY_READ_MARKERS = (
    "长期记忆",
    "记忆里",
    "你都记了什么",
    "你都长期记了什么",
    "你帮我记了什么",
    "你刚才帮我长期记住了什么",
    "你刚刚让我长期保留了哪几件事",
    "你刚刚让我长期保留了什么",
    "刚刚让我长期保留了哪几件事",
    "刚刚让我长期保留了什么",
    "what do you remember",
    "what have you remembered",
    "what's in long-term memory",
    "long-term memory",
)

SEMANTIC_MEMORY_READ_MARKERS = (
    "你记得",
    "你知道我",
    "我的偏好",
    "我偏好",
    "我习惯",
    "默认用什么",
    "我们项目重点",
    "还记得",
    "项目约定",
    "do you remember",
)

PREFERENCE_HINTS = (
    "喜欢",
    "偏好",
    "习惯",
    "风格",
    "回答方式",
    "称呼",
    "叫我",
    "怎么处理",
    "怎么做",
    "信息不足",
    "信息不够",
    "资料不足",
    "资料不够",
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
        "preferred_types": ["user"],
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
        "preferred_types": ["user"],
        "preferred_classes": ["preference"],
        "entity_markers": (
            "复杂问题",
            "复杂",
            "complex question",
            "complex questions",
        ),
        "recall_markers": (
            "怎么回答",
            "回答方式",
            "先给结论",
            "第一句",
            "how should you answer",
            "answer style",
            "reply style",
        ),
    },
    {
        "preferred_types": ["user"],
        "preferred_classes": ["preference"],
        "entity_markers": (
            "称呼",
            "叫我",
            "名字",
            "call me",
            "address me",
        ),
        "recall_markers": (
            "怎么",
            "什么",
            "应该",
            "之后",
            "以后",
            "how",
            "what",
            "should",
        ),
    },
    {
        "preferred_types": ["user"],
        "preferred_classes": ["preference"],
        "entity_markers": (
            "信息不足",
            "信息不够",
            "资料不足",
            "资料不够",
            "证据不足",
            "insufficient information",
            "not enough information",
        ),
        "recall_markers": (
            "怎么处理",
            "怎么做",
            "应该怎么",
            "先怎么",
            "处理",
            "做",
            "how should",
            "what should",
        ),
    },
    {
        "preferred_types": ["project"],
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

NEGATED_WRITE_MARKERS = (
    "不是要你长期记住",
    "不用长期记住",
    "不要长期记住",
    "别长期记住",
    "别记到长期记忆",
    "不要记到长期记忆",
    "不要记住",
    "别记住",
    "not for long-term memory",
    "do not remember this",
    "don't remember this",
)

FILE_RETURN_MARKERS = (
    "回到",
    "再回到",
    "继续看",
    "继续分析",
    "继续读",
    "继续处理",
)

FILE_SUFFIX_MARKERS = (".pdf", ".xlsx", ".csv", ".json", ".md")
FILE_KIND_MARKERS = ("pdf", "表格", "数据表", "dataset", "spreadsheet")


@dataclass(slots=True)
class MemoryIntent:
    intent: str = "general"
    memory_read_mode: MemoryReadMode = "none"
    memory_write_mode: MemoryWriteMode = "none"
    should_skip_rag: bool = False
    explicit_read_inventory: bool = False
    explicit_write_request: bool = False
    explicit_forget_request: bool = False
    ignore_memory: bool = False
    preferred_types: list[str] = field(default_factory=list)
    preferred_memory_classes: list[str] = field(default_factory=list)


def analyze_memory_intent(message: str) -> MemoryIntent:
    normalized = (message or "").strip()
    lowered = normalized.lower()
    if not normalized:
        return MemoryIntent()

    if _looks_like_ignore_memory_instruction(lowered):
        return MemoryIntent(
            intent="ignore_memory",
            ignore_memory=True,
            should_skip_rag=False,
        )

    if _looks_like_material_followup(lowered):
        return MemoryIntent()

    if _looks_like_task_or_file_followup(lowered):
        return MemoryIntent()

    query_profile = _match_durable_query_profile(lowered)
    is_question = normalized.endswith("?") or normalized.endswith("？") or any(
        lowered.startswith(prefix)
        for prefix in ("what ", "how ", "do you", "did you", "which ", "why ", "where ")
    )

    if _looks_like_manual_memory_query(lowered):
        preferred_types = query_profile[0] if query_profile is not None else _infer_preferred_types(lowered)
        preferred_classes = query_profile[1] if query_profile is not None else _infer_preferred_classes(lowered)
        return MemoryIntent(
            intent="durable_memory_query",
            memory_read_mode="durable_exact",
            should_skip_rag=True,
            explicit_read_inventory=True,
            preferred_types=preferred_types,
            preferred_memory_classes=preferred_classes,
        )

    if any(marker in lowered for marker in _lower_markers(SESSION_MARKERS)):
        return MemoryIntent(
            intent="session_continuity_query",
            memory_read_mode="session_state",
            should_skip_rag=True,
        )

    if (
        not is_question
        and not _looks_like_negative_memory_write(lowered)
        and any(marker in lowered for marker in _lower_markers(WRITE_MARKERS))
    ):
        return MemoryIntent(
            intent="durable_memory_statement",
            memory_write_mode="durable_fact",
            should_skip_rag=True,
            explicit_write_request=True,
            preferred_types=_infer_preferred_types(lowered),
            preferred_memory_classes=_infer_preferred_classes(lowered),
        )

    if (
        any(marker in lowered for marker in _lower_markers(SEMANTIC_MEMORY_READ_MARKERS))
        or query_profile is not None
        or _looks_like_memory_read_query(normalized, lowered)
    ):
        preferred_types = query_profile[0] if query_profile is not None else _infer_preferred_types(lowered)
        preferred_classes = query_profile[1] if query_profile is not None else _infer_preferred_classes(lowered)
        return MemoryIntent(
            intent="memory_read_signal",
            memory_read_mode="durable_semantic",
            should_skip_rag=True,
            preferred_types=preferred_types,
            preferred_memory_classes=preferred_classes,
        )

    return MemoryIntent()


def _infer_preferred_types(lowered: str) -> list[str]:
    preferred: list[str] = []
    if any(marker in lowered for marker in _lower_markers(PREFERENCE_HINTS)):
        preferred.append("user")
    if any(marker in lowered for marker in _lower_markers(PROJECT_HINTS)):
        preferred.append("project")
    if any(marker in lowered for marker in _lower_markers(WORKFLOW_HINTS)):
        preferred.append("project")
    if not preferred and any(marker in lowered for marker in _lower_markers(REFERENCE_HINTS)):
        preferred.append("reference")
    deduped: list[str] = []
    for item in preferred:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _infer_preferred_classes(lowered: str) -> list[str]:
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
        ("复杂问题", "怎么回答"),
        ("复杂问题", "先给结论"),
        ("复杂", "怎么回答"),
        ("回答", "先给结论"),
        ("称呼", "怎么"),
        ("称呼", "什么"),
        ("叫我", "什么"),
        ("叫我", "怎么"),
        ("信息不足", "怎么处理"),
        ("信息不足", "怎么做"),
        ("信息不足", "应该"),
        ("信息不够", "怎么处理"),
        ("资料不足", "怎么处理"),
        ("主线", "什么"),
        ("主线", "哪条"),
    )
    return any(left in lowered and right in lowered for left, right in patterns)


def _looks_like_manual_memory_query(lowered: str) -> bool:
    if any(marker in lowered for marker in _lower_markers(MANUAL_MEMORY_READ_MARKERS)):
        return True
    return (
        ("记了什么" in lowered or "记住了什么" in lowered)
        and any(marker in lowered for marker in _lower_markers(("长期", "记忆", "memory", "remember")))
    )


def _looks_like_negative_memory_write(lowered: str) -> bool:
    return any(marker in lowered for marker in _lower_markers(NEGATED_WRITE_MARKERS))


def _looks_like_ignore_memory_instruction(lowered: str) -> bool:
    return (
        ("ignore" in lowered and "memory" in lowered)
        or ("不要" in lowered and "记忆" in lowered)
        or ("别用" in lowered and "记忆" in lowered)
    )


def _looks_like_task_or_file_followup(lowered: str) -> bool:
    if not any(marker in lowered for marker in _lower_markers(FILE_RETURN_MARKERS)):
        return False
    return any(marker in lowered for marker in FILE_SUFFIX_MARKERS) or any(
        marker in lowered for marker in _lower_markers(FILE_KIND_MARKERS)
    )


def _looks_like_material_followup(lowered: str) -> bool:
    material_markers = (
        "只基于刚才",
        "基于刚才",
        "刚才这",
        "刚才的",
        "这前五",
        "这几条",
        "这些员工",
        "这些人",
        "上面这",
        "上面的",
        "不要回到全表",
        "不要全表",
        "不要重算",
        "子任务",
        "第一个和第三个",
        "只展开",
        "展开第二个",
    )
    return any(marker in lowered for marker in _lower_markers(material_markers))


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


