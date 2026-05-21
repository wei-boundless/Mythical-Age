from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


MCP_STATUS_ACTIVE = "active"
MCP_STATUS_CONNECTED = "connected"
MCP_STATUS_DISABLED = "disabled"
MCP_STATUS_FAILED = "failed"
MCP_STATUS_NOT_INSPECTED = "not_inspected"
MCP_STATUS_UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class MCPProviderTool:
    provider_id: str
    server_id: str
    tool_name: str
    title: str
    description: str
    operation_id: str
    model_visibility: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    annotations: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tags"] = list(self.tags)
        return payload


@dataclass(frozen=True, slots=True)
class MCPProviderServer:
    provider_id: str
    server_id: str
    title: str
    description: str
    provider_kind: str
    transport: str
    enabled: bool
    status: str
    status_reason: str = ""
    operation_ids: tuple[str, ...] = ()
    tools: tuple[MCPProviderTool, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["operation_ids"] = list(self.operation_ids)
        payload["tools"] = [tool.to_dict() for tool in self.tools]
        return payload


class MCPProvider(Protocol):
    provider_id: str
    provider_kind: str

    def list_servers(self) -> list[MCPProviderServer]:
        ...

    def inspect_server(self, server_id: str) -> MCPProviderServer:
        ...

    def preview_permission(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...

    def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...
