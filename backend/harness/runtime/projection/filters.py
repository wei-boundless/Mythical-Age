from __future__ import annotations

from typing import Any

from .guards import public_text
from harness.runtime.public_progress import is_private_runtime_tool_name, looks_like_internal_runtime_artifact


def should_hide_public_tool_observation(*values: Any) -> bool:
    for value in values:
        if public_text(value, limit=220):
            return False
    return True


def should_hide_public_tool_call(*, tool_name: Any, values: list[Any] | tuple[Any, ...] = ()) -> bool:
    if is_private_runtime_tool_name(tool_name):
        return True
    for value in values:
        if looks_like_internal_runtime_artifact(value):
            return True
    return False
