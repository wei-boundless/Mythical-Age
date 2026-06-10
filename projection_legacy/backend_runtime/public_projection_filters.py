from __future__ import annotations

from typing import Any


def should_hide_public_tool_observation(tool_name: str, *values: Any) -> bool:
    return _is_sandbox_boundary_command_failure(tool_name, *values)


def _is_sandbox_boundary_command_failure(tool_name: str, *values: Any) -> bool:
    normalized_tool = str(tool_name or "").strip().lower()
    if not (
        normalized_tool in {"terminal", "shell", "powershell"}
        or "command" in normalized_tool
    ):
        return False
    haystack = " ".join(str(value or "").strip() for value in values if str(value or "").strip()).lower()
    return "absolute path outside the sandbox workspace" in haystack or (
        "outside the sandbox workspace" in haystack and "absolute path" in haystack
    )
