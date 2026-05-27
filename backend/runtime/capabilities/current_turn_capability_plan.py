from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from capability_system.search_policy import normalize_search_policy, tool_allowed_by_search_policy
from capability_system.tool_authorization import build_authorized_tool_set


@dataclass(frozen=True, slots=True)
class CurrentTurnCapabilityPlan:
    allowed_operations: tuple[str, ...]
    model_visible_tools: tuple[str, ...]
    dispatchable_tools: tuple[str, ...]
    denied_operations: tuple[str, ...]
    filtered_tools: tuple[dict[str, str], ...]
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_operations": list(self.allowed_operations),
            "model_visible_tools": list(self.model_visible_tools),
            "dispatchable_tools": list(self.dispatchable_tools),
            "denied_operations": list(self.denied_operations),
            "filtered_tools": [dict(item) for item in self.filtered_tools],
            "diagnostics": dict(self.diagnostics),
            "authority": "runtime.current_turn_capability_plan",
        }


def build_current_turn_capability_plan(
    *,
    tool_instances: list[Any] | tuple[Any, ...] | None,
    resource_policy: Any,
    definitions_by_name: dict[str, Any],
    normalize_operation_id: Any,
    task_operation: dict[str, Any] | None = None,
    allowed_search_sources: set[str] | None = None,
    execution_permit: dict[str, Any] | None = None,
) -> CurrentTurnCapabilityPlan:
    operation = dict(task_operation or {})
    requirement = dict(operation.get("operation_requirement") or {})
    permit = dict(execution_permit or operation.get("execution_permit") or {})
    source_operations = {
        "operation_requirement.required": _normalize_operations(
            requirement.get("required_operations"),
            normalize_operation_id=normalize_operation_id,
        ),
        "operation_requirement.optional": _normalize_operations(
            requirement.get("optional_operations"),
            normalize_operation_id=normalize_operation_id,
        ),
        "execution_permit.allowed": _normalize_operations(
            permit.get("allowed_operations"),
            normalize_operation_id=normalize_operation_id,
        ),
        "resource_policy.allowed": _normalize_operations(
            getattr(resource_policy, "allowed_operations", ()),
            normalize_operation_id=normalize_operation_id,
        ),
        "resource_policy.requires_approval": _normalize_operations(
            getattr(resource_policy, "requires_approval_operations", ()),
            normalize_operation_id=normalize_operation_id,
        ),
        "resource_policy.not_executable": _normalize_operations(
            getattr(resource_policy, "not_executable_operations", ()),
            normalize_operation_id=normalize_operation_id,
        ),
    }
    denied_operations = _normalize_operations(
        [
            *list(requirement.get("denied_operations") or ()),
            *list(getattr(resource_policy, "denied_operations", ()) or ()),
        ],
        normalize_operation_id=normalize_operation_id,
    )
    denied_set = set(denied_operations)
    allowed_operations = _dedupe(
        [
            "op.model_response",
            *source_operations["operation_requirement.required"],
            *source_operations["operation_requirement.optional"],
            *source_operations["execution_permit.allowed"],
            *source_operations["resource_policy.allowed"],
            *source_operations["resource_policy.requires_approval"],
            *source_operations["resource_policy.not_executable"],
        ]
    )
    allowed_operations = tuple(
        operation_id
        for operation_id in allowed_operations
        if operation_id == "op.model_response" or operation_id not in denied_set
    )

    permit_visible_tools = _dedupe(
        [
            *list(permit.get("model_visible_tool_refs") or ()),
            *list(permit.get("visible_tools") or ()),
        ]
    )
    permit_dispatchable_tools = _dedupe(
        [
            *list(permit.get("dispatchable_tools") or ()),
            *permit_visible_tools,
        ]
    )
    requested_tool_names = permit_visible_tools or _tool_names_for_operations(
        allowed_operations,
        definitions_by_name=definitions_by_name,
    )
    requested_dispatchable_tools = permit_dispatchable_tools or requested_tool_names

    allowed_search = allowed_search_sources if allowed_search_sources is not None else normalize_search_policy(None)
    include_hidden = bool(permit_visible_tools)
    authorized = build_authorized_tool_set(
        tool_instances=tool_instances,
        definitions_by_name=definitions_by_name,
        allowed_operations=set(allowed_operations),
        runtime_lane="main_runtime",
        include_hidden=include_hidden,
    )
    authorized_by_name = {
        str(getattr(tool, "name", "") or "").strip(): tool
        for tool in list(authorized.instances)
        if str(getattr(tool, "name", "") or "").strip()
    }
    filtered_tools = [dict(item) for item in list(authorized.filtered_out)]
    visible_tools: list[str] = []
    for tool_name in requested_tool_names:
        definition = definitions_by_name.get(tool_name)
        if definition is None:
            filtered_tools.append({"tool_name": tool_name, "reason": "missing_tool_definition"})
            continue
        operation_id = str(getattr(definition, "operation_id", "") or "").strip()
        if operation_id not in set(allowed_operations):
            filtered_tools.append({"tool_name": tool_name, "operation_id": operation_id, "reason": "operation_not_allowed"})
            continue
        if not tool_allowed_by_search_policy(definition, allowed_search):
            filtered_tools.append({"tool_name": tool_name, "operation_id": operation_id, "reason": "search_policy_blocked"})
            continue
        if tool_name not in authorized_by_name:
            filtered_tools.append({"tool_name": tool_name, "operation_id": operation_id, "reason": "not_authorized_for_runtime"})
            continue
        visible_tools.append(tool_name)

    visible_tuple = _dedupe(visible_tools)
    dispatchable_tuple = tuple(tool for tool in requested_dispatchable_tools if tool in set(visible_tuple))
    return CurrentTurnCapabilityPlan(
        allowed_operations=allowed_operations,
        model_visible_tools=visible_tuple,
        dispatchable_tools=dispatchable_tuple or visible_tuple,
        denied_operations=denied_operations,
        filtered_tools=tuple(filtered_tools),
        diagnostics={
            "source_operations": {key: list(value) for key, value in source_operations.items()},
            "permit_visible_tools": list(permit_visible_tools),
            "permit_dispatchable_tools": list(permit_dispatchable_tools),
            "requested_tool_names": list(requested_tool_names),
            "include_hidden_tools": include_hidden,
            "allowed_search_sources": sorted(str(item) for item in allowed_search),
        },
    )


def tool_instances_for_capability_plan(
    *,
    tool_instances: list[Any] | tuple[Any, ...] | None,
    capability_plan: CurrentTurnCapabilityPlan | dict[str, Any],
) -> list[Any]:
    plan = capability_plan.to_dict() if hasattr(capability_plan, "to_dict") else dict(capability_plan or {})
    visible = {
        str(item or "").strip()
        for item in list(plan.get("model_visible_tools") or [])
        if str(item or "").strip()
    }
    if not visible:
        return []
    return [
        tool
        for tool in list(tool_instances or [])
        if str(getattr(tool, "name", "") or "").strip() in visible
    ]


def _tool_names_for_operations(
    operation_ids: tuple[str, ...] | list[str],
    *,
    definitions_by_name: dict[str, Any],
) -> tuple[str, ...]:
    requested = {str(item or "").strip() for item in list(operation_ids or []) if str(item or "").strip()}
    names: list[str] = []
    for tool_name, definition in definitions_by_name.items():
        operation_id = str(getattr(definition, "operation_id", "") or "").strip()
        if operation_id and operation_id in requested:
            names.append(str(tool_name).strip())
    return _dedupe(names)


def _normalize_operations(values: Any, *, normalize_operation_id: Any) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in list(values or []):
        text = str(value or "").strip()
        if not text:
            continue
        if callable(normalize_operation_id):
            text = str(normalize_operation_id(text) or "").strip()
        if text:
            normalized.append(text)
    return _dedupe(normalized)


def _dedupe(values: Any) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)


