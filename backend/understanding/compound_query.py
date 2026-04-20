from __future__ import annotations

import re


SPLIT_DELIMITERS = ("/", "／", ";", "；", "\n")
RESOURCE_PATH_PATTERN = re.compile(
    r"(?i)(?:^|[\s:：'\"“”‘’(（])(?:[A-Za-z]:[\\/]|\.{0,2}[\\/]|knowledge[\\/])[^\r\n]+?\.(pdf|xlsx|csv|json|md|txt)\b"
)
SEQUENCE_MARKERS = ("最后再", "接下来", "然后", "接着", "随后", "最后", "再", "先")
FOLLOWUP_SEQUENCE_MARKERS = ("最后再", "接下来", "然后", "接着", "随后", "最后", "再")
INTRO_PREFIXES = (
    "帮我",
    "请",
    "麻烦",
    "在知识库中查询",
    "在知识库里查询",
    "从知识库中查询",
    "从知识库里查询",
    "从我的数据库中查询",
    "从我的数据库里查询",
    "从数据库中查询",
    "从数据库里查询",
)

QUERY_VERB_PREFIXES = (
    "查询",
    "查找",
    "查",
    "看看",
    "说明",
    "解释",
)
SEQUENCE_ACTION_PREFIXES = (
    "请",
    "帮我",
    "麻烦",
    "给我",
    "告诉我",
    "把",
    "查",
    "查询",
    "搜",
    "搜索",
    "总结",
    "分析",
    "说明",
    "解释",
    "统计",
    "列出",
    "汇总",
    "切到",
    "回到",
    "打开",
    "看",
    "看看",
    "读",
    "读取",
    "对比",
    "展开",
    "按",
    "整理",
    "补",
    "补上",
    "加",
    "加上",
)

SEQUENCE_MARKER_PATTERN = re.compile(
    r"(?:^|[，,；;\s])(?P<marker>"
    + "|".join(re.escape(marker) for marker in SEQUENCE_MARKERS)
    + r")(?P<tail>\s*(?:"
    + "|".join(re.escape(prefix) for prefix in SEQUENCE_ACTION_PREFIXES)
    + r"))"
)


def split_compound_query(message: str) -> list[str]:
    normalized = (message or "").strip()
    if not normalized:
        return []

    primary_split = _resolve_primary_split(normalized)
    return _flatten_atomic_subtasks(primary_split)


def _resolve_primary_split(message: str) -> list[str]:
    bracket_split = _split_bracketed_query(message)
    if bracket_split:
        return bracket_split

    direct_split = _split_direct_compound_query(message)
    if direct_split:
        return direct_split

    sequential_split = _split_sequential_query(message)
    if sequential_split:
        return sequential_split

    return [message]


def _flatten_atomic_subtasks(parts: list[str]) -> list[str]:
    queue = [part.strip() for part in parts if part and part.strip()]
    flattened: list[str] = []

    while queue:
        current = queue.pop(0)
        nested = _split_sequential_query(current)
        if nested and len(nested) >= 2:
            queue = nested + queue
            continue
        flattened.append(current)

    return flattened


def _split_bracketed_query(message: str) -> list[str] | None:
    match = re.match(r"^(?P<prefix>.*?)[（(](?P<body>.+)[）)]\s*$", message)
    if not match:
        return None

    body = match.group("body").strip()
    parts = _split_body(body)
    if len(parts) < 2:
        return None

    return parts


def _split_direct_compound_query(message: str) -> list[str] | None:
    if not any(delimiter in message for delimiter in SPLIT_DELIMITERS):
        return None
    if "/" in message and RESOURCE_PATH_PATTERN.search(message):
        return None

    parts = _split_body(message)
    if len(parts) < 2:
        return None
    normalized_parts = _strip_shared_intro(parts)
    return normalized_parts if len(normalized_parts) >= 2 else parts


def _split_body(text: str) -> list[str]:
    pattern = r"\s*(?:/|／|;|；|\n)+\s*"
    raw_parts = [part.strip(" \t\r\n，,。；;") for part in re.split(pattern, text) if part.strip()]
    return [part for part in raw_parts if part]


def _normalize_prefix(prefix: str) -> str:
    cleaned = prefix.strip()
    for starter in INTRO_PREFIXES:
        if cleaned.startswith(starter):
            return cleaned
    return cleaned


def _strip_shared_intro(parts: list[str]) -> list[str]:
    if not parts:
        return parts

    first = parts[0].strip()
    for starter in sorted(INTRO_PREFIXES, key=len, reverse=True):
        if not first.startswith(starter):
            continue
        remainder = first[len(starter) :].strip()
        remainder = remainder.lstrip("：:，, ")
        for verb in QUERY_VERB_PREFIXES:
            if remainder.startswith(verb):
                remainder = remainder[len(verb) :].strip()
                remainder = remainder.lstrip("：:，, ")
                break
        if not remainder:
            return parts
        return [remainder, *parts[1:]]
    return parts


def _split_sequential_query(message: str) -> list[str] | None:
    matches = list(SEQUENCE_MARKER_PATTERN.finditer(message))
    if not matches:
        return None
    if not any(match.group("marker") in FOLLOWUP_SEQUENCE_MARKERS for match in matches):
        return None

    boundaries = [0]
    for match in matches:
        marker_start = match.start("marker")
        if marker_start > 0 and marker_start not in boundaries:
            boundaries.append(marker_start)

    if len(boundaries) < 2:
        return None

    boundaries.sort()
    segments: list[str] = []
    for index, start in enumerate(boundaries):
        end = boundaries[index + 1] if index + 1 < len(boundaries) else len(message)
        segment = _clean_sequence_segment(message[start:end])
        if segment:
            segments.append(segment)

    return segments if len(segments) >= 2 else None


def _clean_sequence_segment(segment: str) -> str:
    cleaned = segment.strip(" \t\r\n，,。；;")
    for starter in sorted(INTRO_PREFIXES, key=len, reverse=True):
        if not cleaned.startswith(starter):
            continue
        remainder = cleaned[len(starter) :].strip()
        if any(remainder.startswith(marker) for marker in SEQUENCE_MARKERS):
            cleaned = remainder
            break

    for marker in SEQUENCE_MARKERS:
        if not cleaned.startswith(marker):
            continue
        remainder = cleaned[len(marker) :].strip()
        remainder = remainder.lstrip("：:，, ")
        if _looks_like_sequential_action(remainder):
            cleaned = remainder
            break

    return cleaned.strip(" \t\r\n，,。；;")


def _looks_like_sequential_action(text: str) -> bool:
    return any(text.startswith(prefix) for prefix in SEQUENCE_ACTION_PREFIXES)
