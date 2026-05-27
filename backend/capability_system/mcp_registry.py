from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from capability_system.mcp_adapter import MCP_COMPATIBLE_PROTOCOL_VERSION
from .local_mcp_registry import default_local_mcp_units
from .operation_registry import OperationRegistry


LOCAL_MCP_SERVER_NAME = "local-capability-endpoints"


@dataclass(frozen=True, slots=True)
class MCPRegistryEntry:
    mcp_id: str
    unit_id: str
    route: str
    name: str
    description: str
    operation_id: str
    implementation_module: str
    endpoint_protocol: str = MCP_COMPATIBLE_PROTOCOL_VERSION
    transport: str = "in_process"
    server_name: str = LOCAL_MCP_SERVER_NAME
    runtime_lane: str = "mcp"
    model_visibility: str = "not_direct_model_tool"
    input_modes: list[str] = field(default_factory=list)
    output_modes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    mcp_profile: dict[str, Any] = field(default_factory=dict)
    operation: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_mcp_entries(operation_registry: OperationRegistry | None = None) -> list[MCPRegistryEntry]:
    registry = operation_registry
    entries: list[MCPRegistryEntry] = []
    for unit in default_local_mcp_units():
        operation = registry.get_operation(unit.operation_id) if registry is not None else None
        entries.append(
            MCPRegistryEntry(
                mcp_id=unit.mcp_id,
                unit_id=unit.unit_id,
                route=unit.route,
                name=str(unit.title or unit.name),
                description=str(unit.summary),
                operation_id=unit.operation_id,
                implementation_module=unit.implementation_module,
                input_modes=list(unit.default_input_modes or []),
                output_modes=list(unit.default_output_modes or []),
                tags=list(unit.tags),
                mcp_profile={
                    "unit_id": unit.unit_id,
                    "category": unit.category,
                    "source_kind": unit.source_kind,
                },
                operation=operation.to_dict() if operation is not None else {},
                diagnostics={
                    "operation_registered": operation is not None,
                    "operation_type": str(operation.operation_type if operation is not None else ""),
                    "local_mcp_unit_id": unit.unit_id,
                    "mcp_compatible": True,
                    "direct_model_tool": False,
                },
            )
        )
    return entries


def build_mcp_catalog(operation_registry: OperationRegistry | None = None) -> list[dict[str, Any]]:
    return [entry.to_dict() for entry in default_mcp_entries(operation_registry)]


