from __future__ import annotations

import re
from typing import Any


_RUNTIME_PRIVATE_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:^|/)backend/mythical-agent/sessions/"),
    re.compile(r"(?:^|/)mythical-agent/sessions/"),
    re.compile(r"(?:^|/)backend/storage/session_environments/"),
    re.compile(r"(?:^|/)backend/storage/runtime_context/"),
    re.compile(r"(?:^|/)backend/storage/runtime_state/"),
    re.compile(r"(?:^|/)storage/sessions/"),
    re.compile(r"(?:^|/)storage/session_environments/"),
    re.compile(r"(?:^|/)storage/runtime_context/"),
    re.compile(r"(?:^|/)storage/runtime_state/"),
    re.compile(r"(?:^|/)runtime_context/(?:tool[-_]results|tool-results)(?:/|$)"),
    re.compile(r"(?:^|/)runtime_state/(?:tool[-_]results|tool-results)(?:/|$)"),
    re.compile(r"(?:^|/)runtime_state/dynamic_context/replacements(?:/|$)"),
    re.compile(r"(?:^|/)dynamic_context/replacements/replacement_[0-9a-f]{12,}\.json\b"),
    re.compile(r"(?:^|[\s/])replacement_[0-9a-f]{12,}\.json\b"),
    re.compile(r"\breplacement:[0-9a-f]{12,}\b"),
)


def looks_like_runtime_private_artifact_text(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    normalized = text.replace("\\", "/").lower()
    return any(pattern.search(normalized) for pattern in _RUNTIME_PRIVATE_TEXT_PATTERNS)
