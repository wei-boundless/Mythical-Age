from __future__ import annotations

import re


_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

_CHINESE_UNITS = {
    "十": 10,
    "百": 100,
    "千": 1000,
}


def extract_page_hints(query: str) -> tuple[int, ...]:
    text = str(query or "")
    hints: list[int] = []
    for pattern in (
        r"第\s*(\d+)\s*页",
        r"page\s*(\d+)",
    ):
        for value in re.findall(pattern, text, flags=re.IGNORECASE):
            page = _positive_int(value)
            if page:
                hints.append(page)
    for value in re.findall(r"第\s*([零〇一二两三四五六七八九十百千]+)\s*页", text):
        page = parse_chinese_number(value)
        if page:
            hints.append(page)
    return tuple(dict.fromkeys(hints))


def has_page_hint(query: str) -> bool:
    return bool(extract_page_hints(query))


def parse_chinese_number(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return _positive_int(text)
    total = 0
    current = 0
    seen = False
    for char in text:
        if char in _CHINESE_DIGITS:
            current = _CHINESE_DIGITS[char]
            seen = True
            continue
        unit = _CHINESE_UNITS.get(char)
        if unit is None:
            return None
        if current == 0:
            current = 1
        total += current * unit
        current = 0
        seen = True
    if not seen:
        return None
    total += current
    return total if total > 0 else None


def _positive_int(value: object) -> int | None:
    try:
        page = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None
