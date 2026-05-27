from __future__ import annotations

from typing import Any

from runtime.capabilities import build_current_turn_capability_plan, tool_instances_for_capability_plan


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
    task_operation: dict[str, Any] | None = None,
    capability_plan: Any = None,
) -> list[Any]:
    if capability_plan is not None:
        return tool_instances_for_capability_plan(
            tool_instances=tool_instances,
            capability_plan=capability_plan,
        )
    plan = build_current_turn_capability_plan(
        tool_instances=tool_instances,
        resource_policy=resource_policy,
        definitions_by_name=definitions_by_name,
        normalize_operation_id=normalize_operation_id,
        task_operation=task_operation,
        allowed_search_sources=allowed_search_sources,
        execution_permit=execution_permit,
    )
    return tool_instances_for_capability_plan(
        tool_instances=tool_instances,
        capability_plan=plan,
    )


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


