from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from tools.definitions import ToolDefinition, get_tool_definition_map


MCP_COMPATIBLE_PROTOCOL_VERSION = "mcp-compatible.v1"
DEFAULT_LOCAL_SERVER_NAME = "local-tools"


@dataclass(frozen=True, slots=True)
class MCPToolView:
    """Local MCP-compatible view for one tool definition.

    This is intentionally an adapter envelope, not a real MCP transport
    implementation. It gives runtime/agents one stable tool-facing contract
    while keeping concrete tool details behind the tool layer.
    """

    protocol_version: str
    server_name: str
    tool_name: str
    schema_identity: str
    runtime_visibility: str
    prompt_exposure_policy: str
    resource_exposure_policy: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    annotations: dict[str, Any] = field(default_factory=dict)
    contract: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_event_metadata(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "server_name": self.server_name,
            "tool_name": self.tool_name,
            "schema_identity": self.schema_identity,
            "runtime_visibility": self.runtime_visibility,
            "prompt_exposure_policy": self.prompt_exposure_policy,
            "resource_exposure_policy": self.resource_exposure_policy,
        }


def build_mcp_tool_view(
    definition: ToolDefinition,
    *,
    server_name: str = DEFAULT_LOCAL_SERVER_NAME,
) -> MCPToolView:
    tool_name = str(definition.name or "").strip()
    schema_identity = str(definition.schema_identity or "").strip() or f"{server_name}/{tool_name}"
    execution_contract = definition.contract
    resolution_contract = definition.resolution_contract
    output_contract = definition.output_contract
    return MCPToolView(
        protocol_version=MCP_COMPATIBLE_PROTOCOL_VERSION,
        server_name=server_name,
        tool_name=tool_name,
        schema_identity=schema_identity,
        runtime_visibility=str(definition.runtime_visibility or "main_runtime"),
        prompt_exposure_policy=str(definition.prompt_exposure_policy or "schema_only"),
        resource_exposure_policy=str(definition.resource_exposure_policy or "none"),
        input_schema={
            "required": list(execution_contract.required_inputs),
            "optional": list(execution_contract.optional_inputs),
            "required_bindings": list(execution_contract.required_bindings),
            "path_field": str(resolution_contract.path_field or ""),
            "path_kind": str(resolution_contract.path_kind or ""),
            "binding_field": str(resolution_contract.binding_field or ""),
        },
        output_schema={
            "display_mode": str(output_contract.display_mode or ""),
            "finalization_policy": str(output_contract.finalization_policy or ""),
            "persistence_policy": str(output_contract.persistence_policy or ""),
        },
        annotations={
            "read_only_hint": bool(definition.is_read_only),
            "destructive_hint": bool(definition.is_destructive),
            "concurrency_safe_hint": bool(definition.is_concurrency_safe),
            "safe_for_auto_route": bool(definition.safe_for_auto_route),
            "capability_tags": list(definition.capability_tags),
            "supported_modalities": list(definition.supported_modalities),
            "safety_tags": list(definition.safety_tags),
        },
        contract={
            "execution": execution_contract.to_dict(),
            "resolution": resolution_contract.to_dict(),
            "output": output_contract.to_dict(),
            "projection": definition.projection_contract.to_dict(),
        },
    )


def get_mcp_tool_view(tool_name: str | None) -> MCPToolView | None:
    definition = get_tool_definition_map().get(str(tool_name or "").strip())
    if definition is None:
        return None
    return build_mcp_tool_view(definition)


def build_mcp_tool_catalog(*, include_agent_internal: bool = True) -> dict[str, Any]:
    views = []
    for definition in get_tool_definition_map().values():
        view = build_mcp_tool_view(definition)
        if not include_agent_internal and view.runtime_visibility == "agent_internal":
            continue
        views.append(view.to_dict())
    return {
        "protocol_version": MCP_COMPATIBLE_PROTOCOL_VERSION,
        "server_name": DEFAULT_LOCAL_SERVER_NAME,
        "tools": views,
    }
