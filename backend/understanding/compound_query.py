from __future__ import annotations

import re


SPLIT_DELIMITERS = ("/", "／", ";", "；", "\n")
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


def split_compound_query(message: str) -> list[str]:
    normalized = (message or "").strip()
    if not normalized:
        return []

    bracket_split = _split_bracketed_query(normalized)
    if bracket_split:
        return bracket_split

    direct_split = _split_direct_compound_query(normalized)
    if direct_split:
        return direct_split

    return [normalized]


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
