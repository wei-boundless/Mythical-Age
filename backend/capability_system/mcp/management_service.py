from __future__ import annotations

from pathlib import Path
from typing import Any

from capability_system.mcp.external_provider import ExternalMCPProvider
from capability_system.mcp.client import ExternalMCPServerConfig
from capability_system.mcp.local_provider import LocalMCPProvider
from permissions import ResourcePolicy


class MCPManagementService:
    def __init__(
        self,
        backend_dir: Path,
        *,
        permission_mode: str = "default",
        resource_policy: ResourcePolicy | None = None,
        include_external: bool = True,
    ) -> None:
        self.backend_dir = Path(backend_dir).resolve()
        self.permission_mode = permission_mode
        self.providers = [
            LocalMCPProvider(
                self.backend_dir,
                resource_policy=resource_policy,
                permission_mode=permission_mode,
            )
        ]
        if include_external:
            self.providers.append(ExternalMCPProvider(self.backend_dir, permission_mode=permission_mode))

    def list_servers(self) -> list[dict[str, Any]]:
        return [
            server.to_dict()
            for provider in self.providers
            for server in provider.list_servers()
        ]

    def inspect_server(self, provider_id: str, server_id: str) -> dict[str, Any]:
        provider = self._provider(provider_id)
        return provider.inspect_server(server_id).to_dict()

    def build_catalog(self) -> dict[str, Any]:
        servers = self.list_servers()
        tools = [
            {
                **tool,
                "provider_kind": server["provider_kind"],
                "transport": server["transport"],
                "status": server["status"],
            }
            for server in servers
            for tool in list(server.get("tools") or [])
        ]
        return {
            "authority": "capability_system.mcp.management_service",
            "providers": [
                {
                    "provider_id": provider.provider_id,
                    "provider_kind": provider.provider_kind,
                }
                for provider in self.providers
            ],
            "servers": servers,
            "tools": tools,
            "summary": {
                "provider_count": len(self.providers),
                "server_count": len(servers),
                "local_server_count": sum(1 for item in servers if item.get("provider_kind") == "local"),
                "external_server_count": sum(1 for item in servers if item.get("provider_kind") == "external"),
                "tool_count": len(tools),
                "unsupported_count": sum(1 for item in servers if item.get("status") == "unsupported"),
                "failed_count": sum(1 for item in servers if item.get("status") == "failed"),
            },
        }

    def preview_permission(
        self,
        provider_id: str,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        provider = self._provider(provider_id)
        return provider.preview_permission(server_id, tool_name, arguments)

    def call_tool(
        self,
        provider_id: str,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        provider = self._provider(provider_id)
        return provider.call_tool(server_id, tool_name, arguments)

    def upsert_external_server(self, config: ExternalMCPServerConfig) -> None:
        provider = self._provider("external")
        if not isinstance(provider, ExternalMCPProvider):
            raise KeyError("external")
        provider.upsert_server(config)

    def delete_external_server(self, server_id: str) -> None:
        provider = self._provider("external")
        if not isinstance(provider, ExternalMCPProvider):
            raise KeyError("external")
        provider.delete_server(server_id)

    def _provider(self, provider_id: str):
        target = str(provider_id or "").strip()
        for provider in self.providers:
            if provider.provider_id == target or provider.provider_kind == target:
                return provider
        raise KeyError(provider_id)


