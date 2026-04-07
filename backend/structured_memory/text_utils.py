from __future__ import annotations

import re
import unicodedata

from runtime_encoding import count_mojibake_markers


def repair_mojibake(text: str) -> str:
    if not text:
        return text

    candidates = [text]
    for encoding in ("cp1252", "latin-1", "gb18030", "gbk"):
        try:
            repaired = text.encode(encoding).decode("utf-8")
        except UnicodeError:
            continue
        if repaired != text:
            candidates.append(repaired)

    return max(candidates, key=_text_quality_score)


def normalize_storage_text(text: str) -> str:
    repaired = repair_mojibake(text or "")
    return repaired.replace("\r\n", "\n").replace("\r", "\n").strip()


def _text_quality_score(text: str) -> int:
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_noise = sum(1 for char in text if "\u00c0" <= char <= "\u017f")
    replacement_noise = text.count("\ufffd")
    private_use_noise = sum(1 for char in text if unicodedata.category(char) == "Co")
    mojibake_noise = count_mojibake_markers(text) * 12
    return cjk_count * 4 - latin_noise - replacement_noise * 4 - private_use_noise * 4 - mojibake_noise
