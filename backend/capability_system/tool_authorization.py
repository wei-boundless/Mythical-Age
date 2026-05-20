from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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


def build_tool_authorization_index(definitions: list[Any] | tuple[Any, ...]) -> ToolAuthorizationIndex:
    definitions_by_name: dict[str, Any] = {}
    operations_by_tool_name: dict[str, str] = {}
    for definition in definitions:
        tool_name = str(definition.name or "").strip()
        operation_id = str(definition.operation_id or "").strip()
        if not tool_name:
            continue
        definitions_by_name[tool_name] = definition
        if operation_id:
            operations_by_tool_name[tool_name] = operation_id
    return ToolAuthorizationIndex(
        definitions_by_name=definitions_by_name,
        operations_by_tool_name=operations_by_tool_name,
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
    runtime_lane: str = "main_runtime",
    include_hidden: bool = False,
) -> AuthorizedToolSet:
    if not allowed_operations:
        return AuthorizedToolSet()

    instances: list[Any] = []
    tool_names: list[str] = []
    operation_ids: list[str] = []
    filtered_out: list[dict[str, str]] = []
    for tool in list(tool_instances or []):
        tool_name = str(getattr(tool, "name", "") or "").strip()
        definition = definitions_by_name.get(tool_name)
        if definition is None:
            filtered_out.append({"tool_name": tool_name, "reason": "missing_tool_definition"})
            continue
        operation_id = str(definition.operation_id or "").strip()
        if not operation_id:
            filtered_out.append({"tool_name": tool_name, "reason": "missing_operation_id"})
            continue
        if operation_id not in allowed_operations:
            filtered_out.append({"tool_name": tool_name, "operation_id": operation_id, "reason": "operation_not_allowed"})
            continue
        if runtime_lane == "main_runtime" and definition.runtime_visibility != "main_runtime" and not include_hidden:
            filtered_out.append({"tool_name": tool_name, "operation_id": operation_id, "reason": "not_main_runtime_visible"})
            continue
        if not include_hidden and definition.prompt_exposure_policy != "schema_only":
            filtered_out.append({"tool_name": tool_name, "operation_id": operation_id, "reason": "not_prompt_schema_visible"})
            continue
        instances.append(tool)
        tool_names.append(tool_name)
        operation_ids.append(operation_id)

    return AuthorizedToolSet(
        instances=tuple(instances),
        tool_names=tuple(tool_names),
        operation_ids=tuple(operation_ids),
        filtered_out=tuple(filtered_out),
    )
