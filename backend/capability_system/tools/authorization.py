from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from capability_system.tools.contracts import is_prompt_visible_tool_policy


@dataclass(frozen=True, slots=True)
class AuthorizedToolSet:
    instances: tuple[Any, ...] = ()
    tool_names: tuple[str, ...] = ()
    operation_ids: tuple[str, ...] = ()
    filtered_out: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_names": list(self.tool_names),
            "operation_ids": list(self.operation_ids),
            "filtered_out": [dict(item) for item in self.filtered_out],
        }


@dataclass(frozen=True, slots=True)
class ToolAuthorizationIndex:
    definitions_by_name: dict[str, Any] = field(default_factory=dict)
    operations_by_tool_name: dict[str, str] = field(default_factory=dict)
    operation_ids_by_tool_name: dict[str, tuple[str, ...]] = field(default_factory=dict)


def build_tool_authorization_index(definitions: list[Any] | tuple[Any, ...]) -> ToolAuthorizationIndex:
    definitions_by_name: dict[str, Any] = {}
    operations_by_tool_name: dict[str, str] = {}
    operation_ids_by_tool_name: dict[str, tuple[str, ...]] = {}
    for definition in definitions:
        tool_name = str(definition.name or "").strip()
        operation_id = str(definition.operation_id or "").strip()
        if not tool_name:
            continue
        definitions_by_name[tool_name] = definition
        if operation_id:
            operations_by_tool_name[tool_name] = operation_id
        operation_ids_by_tool_name[tool_name] = _definition_operation_ids(definition)
    return ToolAuthorizationIndex(
        definitions_by_name=definitions_by_name,
        operations_by_tool_name=operations_by_tool_name,
        operation_ids_by_tool_name=operation_ids_by_tool_name,
    )


def resolve_tool_operation_id(
    tool_name: str | None,
    *,
    definitions_by_name: dict[str, Any],
) -> str:
    definition = definitions_by_name.get(str(tool_name or "").strip())
    if definition is None:
        return ""
    return str(definition.operation_id or "").strip()


def build_authorized_tool_set(
    *,
    tool_instances: list[Any] | tuple[Any, ...] | None,
    definitions_by_name: dict[str, Any],
    allowed_operations: set[str],
    include_hidden: bool = False,
) -> AuthorizedToolSet:
    if not allowed_operations:
        return AuthorizedToolSet()

    instances_by_name = {
        str(getattr(tool, "name", "") or "").strip(): tool
        for tool in list(tool_instances or [])
        if str(getattr(tool, "name", "") or "").strip()
    }
    instances: list[Any] = []
    tool_names: list[str] = []
    operation_ids: list[str] = []
    filtered_out: list[dict[str, str]] = []
    for tool_name, definition in definitions_by_name.items():
        tool_name = str(tool_name or "").strip()
        if not tool_name:
            continue
        operation_ids_for_tool = _definition_operation_ids(definition)
        primary_operation_id = str(definition.operation_id or "").strip()
        if not operation_ids_for_tool:
            filtered_out.append({"tool_name": tool_name, "reason": "missing_operation_id"})
            continue
        allowed_for_tool = tuple(operation_id for operation_id in operation_ids_for_tool if operation_id in allowed_operations)
        if not allowed_for_tool:
            filtered_out.append(
                {
                    "tool_name": tool_name,
                    "operation_ids": ",".join(operation_ids_for_tool),
                    "reason": "operation_not_allowed",
                }
            )
            continue
        if not include_hidden and not is_prompt_visible_tool_policy(definition.prompt_exposure_policy):
            filtered_out.append(
                {
                    "tool_name": tool_name,
                    "operation_id": primary_operation_id or allowed_for_tool[0],
                    "operation_ids": ",".join(allowed_for_tool),
                    "reason": "not_prompt_schema_visible",
                }
            )
            continue
        tool = instances_by_name.get(tool_name)
        if tool is not None:
            instances.append(tool)
        tool_names.append(tool_name)
        operation_ids.extend(allowed_for_tool)
    for tool_name in sorted(set(instances_by_name) - set(definitions_by_name)):
        filtered_out.append({"tool_name": tool_name, "reason": "missing_tool_definition"})

    return AuthorizedToolSet(
        instances=tuple(instances),
        tool_names=tuple(tool_names),
        operation_ids=tuple(_dedupe(operation_ids)),
        filtered_out=tuple(filtered_out),
    )


def _definition_operation_ids(definition: Any) -> tuple[str, ...]:
    operation_ids: list[str] = []
    primary = str(getattr(definition, "operation_id", "") or "").strip()
    if primary:
        operation_ids.append(primary)
    for operation_id in dict(getattr(definition, "action_operation_ids", {}) or {}).values():
        value = str(operation_id or "").strip()
        if value:
            operation_ids.append(value)
    return tuple(_dedupe(operation_ids))


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


