from __future__ import annotations

from typing import Any

from capability_system.tools.tool_surface import action_kind_for_surface_tool
from .guards import text


def action_kind_for_tool(tool_name: str, raw_target: Any = "") -> str:
    normalized = text(tool_name).lower()
    surface_kind = action_kind_for_surface_tool(normalized, raw_target)
    if surface_kind != "work":
        return surface_kind
    if any(token in normalized for token in ("search", "grep", "glob")):
        return "search"
    if any(token in normalized for token in ("read", "inspect", "stat")):
        return "read"
    if any(token in normalized for token in ("write", "edit", "patch")):
        return "edit"
    if "agent" in normalized:
        return "subagent"
    return surface_kind
