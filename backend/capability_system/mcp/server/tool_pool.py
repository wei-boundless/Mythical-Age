from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from capability_system import build_default_operation_registry
from capability_system.local_mcp_registry import default_local_mcp_units
from capability_system.tool_runtime import ToolRuntime
from permissions import PermissionService
from capability_system.mcp.client import ExternalMCPManager


@dataclass(frozen=True, slots=True)
class ToolPoolEntry:
    entry_id: str
    entry_kind: str
    display_name: str
    route_family: str
    candidate_visibility: str
    model_visibility: str
    runtime_exposure: str
    requires_explicit_binding: bool
    discovery_priority: int
    name: str
    source: str
    operation_id: str
    route: str = ""
    description: str = ""
    input_schema_ref: str = ""
    read_only: bool = True
    destructive: bool = False
    idempotent: bool = True
    open_world: bool = False
    concurrency_safe: bool = False
    available_to_model: bool = True
    authorized: bool = True
    authorization_owner: str = "PermissionService/OperationGate"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_mcp_tool_pool(
    *,
    backend_dir: Path,
    permission_service: PermissionService | None = None,
    include_internal_tools: bool = True,
) -> dict[str, Any]:
    registry = build_default_operation_registry()
    entries: list[ToolPoolEntry] = []
    if include_internal_tools:
        tool_runtime = getattr(permission_service, "tool_runtime", None) or ToolRuntime(backend_dir)
        allowed_names = set(
            permission_service.allowed_tool_names()
            if permission_service is not None
            else [definition.name for definition in tool_runtime.definitions if definition.is_read_only]
        )
        for definition in tool_runtime.definitions:
            if definition.runtime_visibility != "main_runtime":
                continue
            if definition.prompt_exposure_policy == "hidden":
                continue
            entries.append(
                ToolPoolEntry(
                    entry_id=f"builtin_tool:{definition.name}",
                    entry_kind="builtin_tool",
                    display_name=definition.name,
                    route_family=_route_family_for_tool(definition),
                    candidate_visibility="route_scoped",
                    model_visibility="model_visible_when_authorized" if definition.name in allowed_names else "permission_hidden",
                    runtime_exposure="direct_builtin_tool",
                    requires_explicit_binding=not definition.safe_for_auto_route,
                    discovery_priority=0,
                    name=definition.name,
                    source="builtin_tool",
                    operation_id=definition.operation_id,
                    description=", ".join(definition.capability_tags),
                    input_schema_ref=definition.schema_identity,
                    read_only=definition.is_read_only,
                    destructive=definition.is_destructive,
                    concurrency_safe=definition.is_concurrency_safe,
                    authorized=definition.name in allowed_names,
                    available_to_model=definition.name in allowed_names,
                    diagnostics={
                        "runtime_visibility": definition.runtime_visibility,
                        "prompt_exposure_policy": definition.prompt_exposure_policy,
                        "safety_tags": list(definition.safety_tags),
                        "source_kind": "builtin_tool",
                    },
                )
            )
    for unit in default_local_mcp_units():
        operation = registry.get_operation(unit.operation_id)
        tool_name = f"mcp__langchain_agent__{unit.route}"
        entries.append(
            ToolPoolEntry(
                entry_id=f"local_mcp:{unit.route}",
                entry_kind="local_mcp",
                display_name=unit.name,
                route_family=unit.category,
                candidate_visibility="route_bound",
                model_visibility="runtime_bound_only",
                runtime_exposure="local_mcp_runtime",
                requires_explicit_binding=True,
                discovery_priority=100,
                name=tool_name,
                source="local_mcp",
                operation_id=unit.operation_id,
                route=unit.route,
                description=unit.summary,
                input_schema_ref=f"{unit.operation_id}.input",
                read_only=bool(operation.read_only if operation is not None else True),
                destructive=bool(operation.destructive if operation is not None else False),
                idempotent=bool(operation.idempotent if operation is not None else True),
                open_world=bool(operation.open_world if operation is not None else False),
                concurrency_safe=bool(operation.concurrency_safe if operation is not None else False),
                available_to_model=False,
                authorized=True,
                diagnostics={
                    "local_mcp_unit_id": unit.unit_id,
                    "model_visibility": "deferred_mcp_tool",
                    "tool_pool_policy": "listed_for_discovery_not_direct_prompt_injection",
                    "source_kind": "local_mcp",
                },
            )
        )
    try:
        external_catalog = ExternalMCPManager(
            backend_dir,
            permission_mode=permission_service.current_mode() if permission_service is not None else "default",
        ).build_catalog_sync()
    except Exception as exc:
        external_catalog = {
            "tool_pool": [],
            "diagnostics": {
                "external_mcp_error": str(exc),
            },
        }
    for item in list(external_catalog.get("tool_pool") or []):
        if not isinstance(item, dict):
            continue
        operation = dict(item.get("operation") or {})
        gate = dict(item.get("authorization") or {})
        entries.append(
            ToolPoolEntry(
                entry_id=f"external_mcp:{item.get('server_id') or ''}:{item.get('tool_name') or item.get('name') or ''}",
                entry_kind="external_mcp",
                display_name=str(item.get("name") or ""),
                route_family="external_mcp",
                candidate_visibility="external_discovery",
                model_visibility="permission_gated_external_tool_pool" if item.get("authorized", False) else "permission_hidden",
                runtime_exposure="external_mcp_client_call",
                requires_explicit_binding=True,
                discovery_priority=200,
                name=str(item.get("name") or ""),
                source="external_mcp",
                operation_id=str(operation.get("operation_id") or ""),
                route=str(item.get("server_id") or ""),
                description=str(item.get("description") or ""),
                input_schema_ref=str(operation.get("input_contract_ref") or ""),
                read_only=bool(operation.get("read_only", True)),
                destructive=bool(operation.get("destructive", False)),
                idempotent=bool(operation.get("idempotent", True)),
                open_world=bool(operation.get("open_world", True)),
                concurrency_safe=bool(operation.get("concurrency_safe", False)),
                available_to_model=bool(item.get("authorized", False)),
                authorized=bool(item.get("authorized", False)),
                authorization_owner="PermissionService/OperationGate",
                diagnostics={
                    "server_id": str(item.get("server_id") or ""),
                    "server_title": str(item.get("server_title") or ""),
                    "tool_name": str(item.get("tool_name") or ""),
                    "transport": str(item.get("transport") or ""),
                    "gate": gate,
                    "model_visibility": "external_mcp_tool_pool",
                    "source_kind": "external_mcp",
                },
            )
        )
    entries.sort(key=lambda item: (item.discovery_priority, _source_rank(item.entry_kind), item.name))
    return {
        "authority": "capability_system.mcp.server.tool_pool",
        "merge_policy": "stable_priority_then_kind_then_name",
        "dedupe_key": "entry_id",
        "prompt_cache_policy": "stable_sorted_sections",
        "entries": [entry.to_dict() for entry in _dedupe_entries(entries)],
    }


def _dedupe_entries(entries: list[ToolPoolEntry]) -> list[ToolPoolEntry]:
    result: list[ToolPoolEntry] = []
    seen: set[str] = set()
    for entry in entries:
        if entry.entry_id in seen:
            continue
        seen.add(entry.entry_id)
        result.append(entry)
    return result


def _source_rank(source: str) -> int:
    if source == "builtin_tool":
        return 0
    if source == "local_mcp":
        return 1
    return 2


def _route_family_for_tool(definition: Any) -> str:
    hints = [str(item or "").strip() for item in list(getattr(definition, "route_hints", []) or [])]
    for hint in hints:
        if hint and hint != "tool":
            return hint
    return "builtin_tool"


MCPToolPoolEntry = ToolPoolEntry


