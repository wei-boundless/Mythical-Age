from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from tools.mcp_adapter import MCP_COMPATIBLE_PROTOCOL_VERSION
from workers import LOCAL_WORKER_SERVER_NAME


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
    owner_agents: list[dict[str, str]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    annotations: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_capability_endpoints(
    *,
    workers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    endpoints = [_worker_endpoint(worker) for worker in workers]
    endpoints.sort(key=lambda item: (item.kind, item.server_name, item.name))
    return [endpoint.to_dict() for endpoint in endpoints]


def _worker_endpoint(worker: dict[str, Any]) -> CapabilityEndpoint:
    route = str(worker.get("route") or "").strip()
    worker_name = str(worker.get("name") or route)
    description = str(worker.get("description") or worker_name)
    agent_id = str(worker.get("agent_id") or "")
    server_name = str(worker.get("server_name") or LOCAL_WORKER_SERVER_NAME)
    return CapabilityEndpoint(
        endpoint_id=f"endpoint:worker:{route}",
        kind="local_worker",
        name=worker_name,
        title=worker_name,
        description=description,
        operation_id=str(worker.get("operation_id") or ""),
        protocol_family=str(worker.get("endpoint_protocol") or MCP_COMPATIBLE_PROTOCOL_VERSION),
        server_name=server_name,
        transport=str(worker.get("transport") or "in_process"),
        runtime_lane=str(worker.get("runtime_lane") or "worker"),
        invocation_mode="orchestrator_only",
        model_visibility=str(worker.get("model_visibility") or "not_direct_model_tool"),
        runtime_visibility="agent_internal",
        prompt_exposure_policy="hidden",
        resource_exposure_policy="handle_only",
        source_ref=str(worker.get("implementation_module") or ""),
        owner_agents=[{"agent_id": agent_id, "name": agent_id}] if agent_id else [],
        tags=[str(item) for item in list(worker.get("tags") or [])],
        input_schema={
            "input_modes": [str(item) for item in list(worker.get("input_modes") or [])],
        },
        output_schema={
            "output_modes": [str(item) for item in list(worker.get("output_modes") or [])],
        },
        annotations={
            "a2a_protocol_version": str(worker.get("a2a_protocol_version") or ""),
            "local_mcp_server": server_name,
        },
        metadata={
            "route": route,
            "mcp_profile": dict(worker.get("mcp_profile") or {}),
            "diagnostics": dict(worker.get("diagnostics") or {}),
        },
    )
