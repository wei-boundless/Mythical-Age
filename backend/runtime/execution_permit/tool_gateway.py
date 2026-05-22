from __future__ import annotations

from typing import Any

from capability_system.search_policy import normalize_search_policy, tool_allowed_by_search_policy
from capability_system.tool_authorization import build_authorized_tool_set


def permit_visible_tool_names(permit: Any) -> tuple[str, ...]:
    return _dedupe(tuple(getattr(permit, "model_visible_tool_refs", ()) or getattr(permit, "visible_tools", ()) or ()))


def permit_dispatchable_tool_names(permit: Any) -> tuple[str, ...]:
    return _dedupe(tuple(getattr(permit, "dispatchable_tools", ()) or getattr(permit, "visible_tools", ()) or ()))


def tool_instances_for_policy_and_permit(
    *,
    tool_instances: list[Any] | None,
    resource_policy: Any,
    definitions_by_name: dict[str, Any],
    normalize_operation_id: Any,
    allowed_search_sources: set[str] | None = None,
    sandbox_policy: dict[str, Any] | None = None,
    execution_permit: dict[str, Any] | None = None,
) -> list[Any]:
    allowed_sources = allowed_search_sources if allowed_search_sources is not None else normalize_search_policy(None)
    allowed_operations = {
        str(normalize_operation_id(operation_id) if callable(normalize_operation_id) else operation_id)
        for operation_id in [
            *tuple(getattr(resource_policy, "allowed_operations", ()) or ()),
            *tuple(getattr(resource_policy, "requires_approval_operations", ()) or ()),
        ]
        if str(operation_id or "").strip()
    }
    permit_operations = {
        str(normalize_operation_id(operation_id) if callable(normalize_operation_id) else operation_id)
        for operation_id in list(dict(execution_permit or {}).get("allowed_operations") or [])
        if str(operation_id or "").strip()
    }
    if permit_operations:
        allowed_operations = allowed_operations & permit_operations
        allowed_operations.add("op.model_response")
    authorized = build_authorized_tool_set(
        tool_instances=tool_instances,
        definitions_by_name=definitions_by_name,
        allowed_operations=allowed_operations,
        runtime_lane="main_runtime",
        include_hidden=bool(dict(sandbox_policy or {}).get("enabled") is True),
    )
    filtered: list[Any] = []
    for tool in list(authorized.instances):
        tool_name = str(getattr(tool, "name", "") or "").strip()
        definition = definitions_by_name.get(tool_name)
        if definition is not None and not tool_allowed_by_search_policy(definition, allowed_sources):
            continue
        filtered.append(tool)
    return filtered


def _dedupe(values: tuple[Any, ...] | list[Any]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)
