from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from permissions.models import PermissionDecision
from permissions.policy import mode_allows_tool, normalize_permission_mode
from tools.contracts import ToolScope, coerce_tool_scope
from tools.definitions import ToolDefinition


def list_allowed_tool_names(
    definitions: list[ToolDefinition],
    *,
    mode: str,
    allowed_tools: Iterable[str] | ToolScope | None = None,
) -> list[str]:
    scope = coerce_tool_scope(allowed_tools, reason="permission_list_allowed_tool_names")
    requested = set(scope.allowed_tools)
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
    allowed_tools: Iterable[str] | ToolScope | None = None,
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
    scope = coerce_tool_scope(allowed_tools, reason="permission_decision")
    requested = set(scope.allowed_tools)
    risk_tags = sorted(set(definition.safety_tags))
    checks: list[str] = []

    if direct_route and not definition.safe_for_auto_route:
        if _allows_explicit_read_only_direct_route(definition, tool_input):
            checks.append("route_eligibility:explicit_read_only")
        else:
            return PermissionDecision(
                False,
                "tool_not_safe_for_auto_route",
                tool_name=definition.name,
                mode=normalized_mode,
                checks=["route_eligibility"],
                risk_tags=risk_tags,
            )
    else:
        checks.append("route_eligibility")

    if not scope.allows(definition.name):
        return PermissionDecision(
            False,
            "tool_not_allowed_by_scope",
            allowed_tools=sorted(requested),
            tool_name=definition.name,
            mode=normalized_mode,
            checks=[*checks, f"{scope.source}_scope"],
            risk_tags=risk_tags,
        )
    checks.append(f"{scope.source}_scope")

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


def _allows_explicit_read_only_direct_route(definition: ToolDefinition, tool_input: Any | None) -> bool:
    if definition.name != "read_file" or not definition.is_read_only:
        return False
    if "read" not in set(definition.safety_tags):
        return False
    if not isinstance(tool_input, dict):
        return False
    raw_path = str(tool_input.get("path", "") or "").strip()
    if not raw_path or raw_path.startswith("-"):
        return False
    return True
