from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from capability_system.mcp_adapter import MCP_COMPATIBLE_PROTOCOL_VERSION
from .mcp_registry import LOCAL_MCP_SERVER_NAME


@dataclass(frozen=True, slots=True)
class CapabilityEndpoint:
    endpoint_id: str
    kind: str
    name: str
    title: str
    description: str
    operation_id: str
    protocol_family: str
    server_name: str
    transport: str
    runtime_lane: str
    invocation_mode: str
    model_visibility: str
    runtime_visibility: str
    prompt_exposure_policy: str
    resource_exposure_policy: str
    source_ref: str = ""
    owner_units: list[dict[str, str]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    annotations: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_capability_endpoints(
    *,
    mcps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    endpoints = [_mcp_endpoint(mcp) for mcp in mcps]
    endpoints.sort(key=lambda item: (item.kind, item.server_name, item.name))
    return [endpoint.to_dict() for endpoint in endpoints]


def _mcp_endpoint(mcp: dict[str, Any]) -> CapabilityEndpoint:
    route = str(mcp.get("route") or "").strip()
    mcp_name = str(mcp.get("name") or route)
    description = str(mcp.get("description") or mcp_name)
    unit_id = str(mcp.get("unit_id") or "")
    server_name = str(mcp.get("server_name") or LOCAL_MCP_SERVER_NAME)
    return CapabilityEndpoint(
        endpoint_id=f"endpoint:mcp:{route}",
        kind="mcp_endpoint",
        name=mcp_name,
        title=mcp_name,
        description=description,
        operation_id=str(mcp.get("operation_id") or ""),
        protocol_family=str(mcp.get("endpoint_protocol") or MCP_COMPATIBLE_PROTOCOL_VERSION),
        server_name=server_name,
        transport=str(mcp.get("transport") or "in_process"),
        runtime_lane=str(mcp.get("runtime_lane") or "mcp"),
        invocation_mode="orchestrator_only",
        model_visibility=str(mcp.get("model_visibility") or "not_direct_model_tool"),
        runtime_visibility="agent_internal",
        prompt_exposure_policy="hidden",
        resource_exposure_policy="handle_only",
        source_ref=str(mcp.get("implementation_module") or ""),
        owner_units=[{"unit_id": unit_id, "name": mcp_name}] if unit_id else [],
        tags=[str(item) for item in list(mcp.get("tags") or [])],
        input_schema={
            "input_modes": [str(item) for item in list(mcp.get("input_modes") or [])],
        },
        output_schema={
            "output_modes": [str(item) for item in list(mcp.get("output_modes") or [])],
        },
        annotations={
            "mcp_server": server_name,
        },
        metadata={
            "route": route,
            "mcp_profile": dict(mcp.get("mcp_profile") or {}),
            "diagnostics": dict(mcp.get("diagnostics") or {}),
        },
    )
