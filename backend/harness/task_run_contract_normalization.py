from __future__ import annotations

import re
from typing import Any

_NUMBERED_ITEM_RE = re.compile(r"(?:^|\s)\d+(?:[.)](?=\s|[\u4e00-\u9fff])\s*|、\s*)")
_BULLET_PREFIX_RE = re.compile(r"^[-*•]\s*")


def contract_string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return _dedupe_strings(_split_string_items(value))
    if isinstance(value, (list, tuple, set)):
        return _dedupe_strings(str(item or "").strip() for item in value)
    if value:
        return _dedupe_strings((str(value).strip(),))
    return ()


def contract_string_list(value: Any) -> list[str]:
    return list(contract_string_tuple(value))


def contract_dict_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    if isinstance(value, dict):
        return (dict(value),) if value else ()
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, dict) and item)


def contract_dict_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in contract_dict_tuple(value)]


def _split_string_items(value: str) -> list[str]:
    raw = str(value or "")
    text = " ".join(raw.split()).strip()
    if not text:
        return []
    numbered = [item.strip(" ;；,，") for item in _NUMBERED_ITEM_RE.split(text) if item.strip(" ;；,，")]
    if len(numbered) > 1:
        return numbered
    semicolon = [item.strip() for item in re.split(r"[;；]", text) if item.strip()]
    if len(semicolon) > 1:
        return semicolon
    lines = [_BULLET_PREFIX_RE.sub("", item.strip()) for item in raw.splitlines() if item.strip()]
    if len(lines) > 1:
        return [item for item in lines if item]
    return [text]


def _dedupe_strings(values: Any) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)
