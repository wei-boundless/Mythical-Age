from __future__ import annotations

from pathlib import Path
from typing import Any

from capability_system.mcp.client import ExternalMCPManager
from capability_system.mcp.client.permission import (
    build_external_mcp_operation_descriptor,
    check_external_mcp_tool_permission,
)
from capability_system.mcp.providers import MCPProviderServer, MCPProviderTool


class ExternalMCPProvider:
    provider_id = "external"
    provider_kind = "external"

    def __init__(self, backend_dir: Path, *, permission_mode: str = "default") -> None:
        self.backend_dir = Path(backend_dir).resolve()
        self.permission_mode = permission_mode
        self.manager = ExternalMCPManager(self.backend_dir, permission_mode=permission_mode)

    def list_servers(self) -> list[MCPProviderServer]:
        servers: list[MCPProviderServer] = []
        for server in self.manager.list_servers():
            status = "disabled" if not server.enabled else "not_inspected"
            status_reason = "server_disabled" if not server.enabled else "manual_inspect_required"
            if server.enabled and server.transport != "stdio":
                status = "unsupported"
                status_reason = "transport_not_enabled_yet"
            servers.append(
                MCPProviderServer(
                    provider_id=self.provider_id,
                    server_id=server.server_id,
                    title=server.title,
                    description=server.description,
                    provider_kind=self.provider_kind,
                    transport=server.transport,
                    enabled=server.enabled,
                    status=status,
                    status_reason=status_reason,
                    diagnostics={
                        "external_config": server.to_dict(),
                        "scope": server.scope,
                        "tags": list(server.tags),
                        "snapshot_policy": "not_connected_during_catalog",
                    },
                )
            )
        return servers

    def upsert_server(self, config) -> None:
        self.manager.upsert_server(config)

    def delete_server(self, server_id: str) -> None:
        self.manager.delete_server(server_id)

    def inspect_server(self, server_id: str) -> MCPProviderServer:
        server = self.manager.config_store.get_server(server_id)
        if server is None:
            raise KeyError(server_id)
        snapshot = self.manager.inspect_server_sync(server_id)
        tools: list[MCPProviderTool] = []
        for tool in snapshot.tools:
            tool_payload = tool.to_dict()
            operation = build_external_mcp_operation_descriptor(server, tool_payload)
            tools.append(
                MCPProviderTool(
                    provider_id=self.provider_id,
                    server_id=server.server_id,
                    tool_name=tool.name,
                    title=tool.title or tool.name,
                    description=tool.description,
                    operation_id=operation.operation_id,
                    model_visibility="permission_gated_external_tool_pool",
                    input_schema=dict(tool.input_schema),
                    output_schema=dict(tool.output_schema),
                    annotations=dict(tool.annotations),
                    tags=tuple(server.tags),
                    diagnostics={"operation": operation.to_dict()},
                )
            )
        status = snapshot.status
        if status == "not_supported":
            status = "unsupported"
        return MCPProviderServer(
            provider_id=self.provider_id,
            server_id=snapshot.server_id,
            title=snapshot.title,
            description=server.description,
            provider_kind=self.provider_kind,
            transport=snapshot.transport,
            enabled=snapshot.enabled,
            status=status,
            status_reason=snapshot.status_reason,
            operation_ids=tuple(tool.operation_id for tool in tools),
            tools=tuple(tools),
            diagnostics={
                **dict(snapshot.diagnostics),
                "resource_count": len(snapshot.resources),
                "prompt_count": len(snapshot.prompts),
            },
        )

    def preview_permission(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        server = self.manager.config_store.get_server(server_id)
        if server is None:
            raise KeyError(server_id)
        snapshot = self.manager.inspect_server_sync(server_id)
        tool = next((item.to_dict() for item in snapshot.tools if item.name == tool_name), None)
        if tool is None:
            return {
                "authorized": False,
                "operation_id": "",
                "gate": {"decision": "deny", "reason": "unknown_external_mcp_tool"},
                "provider_kind": self.provider_kind,
                "server_id": server_id,
                "tool_name": tool_name,
            }
        permission = check_external_mcp_tool_permission(
            server=server,
            tool=tool,
            permission_mode=self.permission_mode,
            tool_input=dict(arguments or {}),
        )
        return {
            **permission,
            "provider_kind": self.provider_kind,
            "server_id": server_id,
            "tool_name": tool_name,
            "operation_id": str(dict(permission.get("operation") or {}).get("operation_id") or ""),
        }

    def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.manager.call_tool_sync(server_id, tool_name, arguments)
