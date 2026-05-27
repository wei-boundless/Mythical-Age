from __future__ import annotations

from capability_system.tool_definitions import ToolDefinition

PERMISSION_MODES = ("default", "plan", "accept_edits", "bypass")


def normalize_permission_mode(mode: str | None) -> str:
    normalized = str(mode or "default").strip().lower()
    if normalized in PERMISSION_MODES:
        return normalized
    return "default"


def mode_allows_tool(definition: ToolDefinition, *, mode: str) -> tuple[bool, str]:
    normalized_mode = normalize_permission_mode(mode)
    risk_tags = set(definition.safety_tags)

    if normalized_mode == "bypass":
        return True, "policy_allow_bypass"

    if normalized_mode == "plan":
        if not definition.is_read_only:
            return False, "policy_plan_requires_read_only"
        if risk_tags & {"write", "shell", "destructive"}:
            return False, "policy_plan_blocks_risky_tool"
        return True, "policy_allow_plan"

    if normalized_mode == "default":
        if risk_tags & {"shell", "destructive"}:
            return False, "policy_default_blocks_high_risk_tool"
        return True, "policy_allow_default"

    if risk_tags & {"destructive"}:
        return False, "policy_accept_edits_blocks_destructive_tool"
    return True, "policy_allow_accept_edits"


