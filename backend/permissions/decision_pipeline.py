from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from permissions.models import PermissionDecision
from permissions.policy import mode_allows_tool, normalize_permission_mode
from tools.definitions import ToolDefinition


def list_allowed_tool_names(
    definitions: list[ToolDefinition],
    *,
    mode: str,
    allowed_tools: Iterable[str] | None = None,
) -> list[str]:
    requested = {item.strip() for item in (allowed_tools or []) if item and item.strip()}
    names: list[str] = []
    for definition in definitions:
        if requested and definition.name not in requested:
            continue
        allowed, _reason = mode_allows_tool(definition, mode=mode)
        if allowed:
            names.append(definition.name)
    return names


def decide_tool_permission(
    definition: ToolDefinition,
    *,
    mode: str,
    allowed_tools: Iterable[str] | None = None,
    direct_route: bool = False,
    tool_input: Any | None = None,
    tool_instance: Any | None = None,
) -> PermissionDecision:
    normalized_mode = normalize_permission_mode(mode)
    allowed_names = list_allowed_tool_names(
        [definition],
        mode=normalized_mode,
        allowed_tools=allowed_tools,
    )
    requested = {item.strip() for item in (allowed_tools or []) if item and item.strip()}
    risk_tags = sorted(set(definition.safety_tags))
    checks: list[str] = []

    if direct_route and not definition.safe_for_auto_route:
        return PermissionDecision(
            False,
            "tool_not_safe_for_auto_route",
            tool_name=definition.name,
            mode=normalized_mode,
            checks=["route_eligibility"],
            risk_tags=risk_tags,
        )
    checks.append("route_eligibility")

    if requested and definition.name not in requested:
        return PermissionDecision(
            False,
            "tool_not_allowed_by_scope",
            allowed_tools=sorted(requested),
            tool_name=definition.name,
            mode=normalized_mode,
            checks=[*checks, "skill_scope"],
            risk_tags=risk_tags,
        )
    checks.append("skill_scope")

    allowed, reason = mode_allows_tool(definition, mode=normalized_mode)
    if not allowed:
        return PermissionDecision(
            False,
            reason,
            allowed_tools=allowed_names,
            tool_name=definition.name,
            mode=normalized_mode,
            checks=[*checks, "policy"],
            risk_tags=risk_tags,
        )
    checks.append("policy")

    validation_error = _run_local_validation(tool_instance, tool_input)
    if validation_error is not None:
        return PermissionDecision(
            False,
            validation_error,
            allowed_tools=allowed_names,
            tool_name=definition.name,
            mode=normalized_mode,
            checks=[*checks, "tool_validation"],
            risk_tags=risk_tags,
        )
    checks.append("tool_validation")

    return PermissionDecision(
        True,
        "allowed",
        allowed_tools=allowed_names,
        tool_name=definition.name,
        mode=normalized_mode,
        checks=checks,
        risk_tags=risk_tags,
    )


def _run_local_validation(tool_instance: Any | None, tool_input: Any | None) -> str | None:
    if tool_instance is None:
        return None

    validator = getattr(tool_instance, "validate_permission", None)
    if callable(validator):
        result = validator(tool_input)
        if result in {None, True}:
            return None
        if result is False:
            return "tool_validation_failed"
        return str(result)

    validator = getattr(tool_instance, "validate_input", None)
    if callable(validator):
        result = validator(tool_input)
        if result in {None, True}:
            return None
        if result is False:
            return "tool_validation_failed"
        return str(result)

    return None
