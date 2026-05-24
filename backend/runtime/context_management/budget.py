from __future__ import annotations

import json
from typing import Any


def estimate_text_bytes(value: Any) -> int:
    return len(str(value or "").encode("utf-8", errors="replace"))


def estimate_json_bytes(value: Any) -> int:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        text = str(value or "")
    return estimate_text_bytes(text)

