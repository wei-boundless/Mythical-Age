from __future__ import annotations

from typing import Any

from .guards import public_text


def should_hide_public_tool_observation(*values: Any) -> bool:
    for value in values:
        if public_text(value, limit=220):
            return False
    return True
