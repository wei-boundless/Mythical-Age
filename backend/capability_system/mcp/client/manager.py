from __future__ import annotations

import anyio
from pathlib import Path
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from .config_store import ExternalMCPConfigStore
from .models import (
    ExternalMCPPrompt,
    ExternalMCPResource,
    ExternalMCPServerConfig,
    ExternalMCPSnapshot,
    ExternalMCPTool,
)
from .permission import check_external_mcp_tool_permission


class ExternalMCPManager:
    def __init__(self, backend_dir: Path, *, permission_mode: str = "default") -> None:
        self.backend_dir = Path(backend_dir).resolve()
        self.config_store = ExternalMCPConfigStore(self.backend_dir)
        self.permission_mode = permission_mode

    def list_servers(self) -> list[ExternalMCPServerConfig]:
        return self.config_store.list_servers()

    def upsert_server(self, config: ExternalMCPServerConfig) -> ExternalMCPServerConfig:
        return self.config_store.upsert_server(config)

    def delete_server(self, server_id: str) -> None:
        self.config_store.delete_server(server_id)

    async def build_catalog(self) -> dict[str, Any]:
        servers = self.list_servers()
        snapshots = [(await self.inspect_server(server.server_id)).to_dict() for server in servers]
        merged_tool_pool = []
        for snapshot in snapshots:
            for tool in list(snapshot.get("tools") or []):
                permission = check_external_mcp_tool_permission(
                    server=next(server for server in servers if server.server_id == snapshot["server_id"]),
                    tool=tool,
                    permission_mode=self.permission_mode,
                )
                merged_tool_pool.append(
                    {
                        "name": f"mcp__{snapshot['server_id']}__{tool['name']}",
                        "source": "external_mcp",
                        "entry_id": f"external_mcp:{snapshot['server_id']}:{tool['name']}",
                        "entry_kind": "external_mcp",
                        "display_name": tool.get("title") or tool["name"],
                        "route_family": "external_mcp",
                        "candidate_visibility": "external_discovery",
                        "model_visibility": "permission_gated_external_tool_pool"
                        if permission["authorized"]
                        else "permission_hidden",
                        "runtime_exposure": "external_mcp_client_call",
                        "requires_explicit_binding": True,
                        "discovery_priority": 200,
                        "server_id": snapshot["server_id"],
                        "server_title": snapshot["title"],
                        "transport": snapshot["transport"],
                        "tool_name": tool["name"],
                        "description": tool.get("description") or "",
                        "authorized": bool(permission["authorized"]),
                        "authorization": permission["gate"],
                        "operation": permission["operation"],
                    }
                )
        merged_tool_pool.sort(key=lambda item: (item["server_id"], item["tool_name"]))
        return {
            "authority": "capability_system.mcp.client.catalog",
            "servers": [server.to_dict() for server in servers],
            "snapshots": snapshots,
            "summary": {
                "server_count": len(servers),
                "enabled_server_count": sum(1 for server in servers if server.enabled),
                "connected_server_count": sum(1 for item in snapshots if item.get("status") == "connected"),
                "tool_count": sum(len(list(item.get("tools") or [])) for item in snapshots),
                "resource_count": sum(len(list(item.get("resources") or [])) for item in snapshots),
                "prompt_count": sum(len(list(item.get("prompts") or [])) for item in snapshots),
            },
            "tool_pool": merged_tool_pool,
        }

    async def inspect_server(self, server_id: str) -> ExternalMCPSnapshot:
        server = self.config_store.get_server(server_id)
        if server is None:
            raise KeyError(server_id)
        if not server.enabled:
            return ExternalMCPSnapshot(
                server_id=server.server_id,
                title=server.title,
                transport=server.transport,
                enabled=False,
                scope=server.scope,
                status="disabled",
                status_reason="server_disabled",
            )
        if server.transport != "stdio":
            return ExternalMCPSnapshot(
                server_id=server.server_id,
                title=server.title,
                transport=server.transport,
                enabled=server.enabled,
                scope=server.scope,
                status="not_supported",
                status_reason="transport_not_enabled_yet",
                diagnostics={"url": server.url},
            )
        return await self._inspect_stdio_server(server)

    async def call_tool(self, server_id: str, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        server = self.config_store.get_server(server_id)
        if server is None:
            raise KeyError(server_id)
        if not server.enabled:
            return {"status": "error", "error": "server_disabled", "server_id": server_id}
        if server.transport != "stdio":
            return {"status": "error", "error": "transport_not_enabled_yet", "server_id": server_id}
        snapshot = await self._inspect_stdio_server(server)
        tool = next((item.to_dict() for item in snapshot.tools if item.name == tool_name), None)
        if tool is None:
            return {"status": "error", "error": "unknown_external_mcp_tool", "server_id": server_id, "tool_name": tool_name}
        permission = check_external_mcp_tool_permission(
            server=server,
            tool=tool,
            permission_mode=self.permission_mode,
            tool_input=dict(arguments or {}),
        )
        if not permission["authorized"]:
            return {
                "status": "error",
                "error": "operation_gate_denied",
                "server_id": server_id,
                "tool_name": tool_name,
                "authorization": permission,
            }
        params = StdioServerParameters(
            command=server.command,
            args=list(server.args),
            env=dict(server.env or {}) or None,
            cwd=server.cwd or None,
        )
        try:
            async with stdio_client(params) as streams:
                read_stream, write_stream = streams
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, dict(arguments or {}))
        except Exception as exc:
            return {
                "status": "error",
                "error": str(exc),
                "server_id": server_id,
                "tool_name": tool_name,
                "diagnostics": {"exception_type": type(exc).__name__},
            }
        return {
            "status": "ok",
            "server_id": server_id,
            "tool_name": tool_name,
            "authorization": permission,
            "result": _model_dump(result),
        }

    def build_catalog_sync(self) -> dict[str, Any]:
        try:
            return anyio.run(self.build_catalog)
        except RuntimeError as exc:
            servers = self.list_servers()
            snapshots = [
                ExternalMCPSnapshot(
                    server_id=server.server_id,
                    title=server.title,
                    transport=server.transport,
                    enabled=server.enabled,
                    scope=server.scope,
                    status="not_inspected",
                    status_reason="sync catalog requested while an event loop is already running",
                    diagnostics={"exception_type": type(exc).__name__},
                ).to_dict()
                for server in servers
            ]
            return {
                "authority": "capability_system.mcp.client.catalog",
                "servers": [server.to_dict() for server in servers],
                "snapshots": snapshots,
                "summary": {
                    "server_count": len(servers),
                    "enabled_server_count": sum(1 for server in servers if server.enabled),
                    "connected_server_count": sum(1 for item in snapshots if item.get("status") == "connected"),
                    "tool_count": sum(len(list(item.get("tools") or [])) for item in snapshots),
                    "resource_count": sum(len(list(item.get("resources") or [])) for item in snapshots),
                    "prompt_count": sum(len(list(item.get("prompts") or [])) for item in snapshots),
                },
                "tool_pool": [],
            }

    def inspect_server_sync(self, server_id: str) -> ExternalMCPSnapshot:
        return anyio.run(self.inspect_server, server_id)

    def call_tool_sync(self, server_id: str, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return anyio.run(self.call_tool, server_id, tool_name, arguments)

    async def _inspect_stdio_server(self, server: ExternalMCPServerConfig) -> ExternalMCPSnapshot:
        params = StdioServerParameters(
            command=server.command,
            args=list(server.args),
            env=dict(server.env or {}) or None,
            cwd=server.cwd or None,
        )
        try:
            async with stdio_client(params) as streams:
                read_stream, write_stream = streams
                async with ClientSession(read_stream, write_stream) as session:
                    initialize_result = await session.initialize()
                    tools_result = await session.list_tools()
                    resources_result = await session.list_resources()
                    prompts_result = await session.list_prompts()
        except Exception as exc:
            return ExternalMCPSnapshot(
                server_id=server.server_id,
                title=server.title,
                transport=server.transport,
                enabled=server.enabled,
                scope=server.scope,
                status="failed",
                status_reason=str(exc),
                diagnostics={"exception_type": type(exc).__name__},
            )
        return ExternalMCPSnapshot(
            server_id=server.server_id,
            title=server.title,
            transport=server.transport,
            enabled=server.enabled,
            scope=server.scope,
            status="connected",
            capabilities=_model_dump(getattr(initialize_result, "capabilities", {}) or {}),
            tools=[
                ExternalMCPTool(
                    name=str(tool.name or ""),
                    title=str(getattr(tool, "title", "") or ""),
                    description=str(getattr(tool, "description", "") or ""),
                    input_schema=_model_dump(getattr(tool, "inputSchema", {}) or {}),
                    output_schema=_model_dump(getattr(tool, "outputSchema", {}) or {}),
                    annotations=_model_dump(getattr(tool, "annotations", {}) or {}),
                    meta=_model_dump(getattr(tool, "meta", {}) or {}),
                )
                for tool in list(getattr(tools_result, "tools", []) or [])
            ],
            resources=[
                ExternalMCPResource(
                    uri=str(resource.uri or ""),
                    name=str(getattr(resource, "name", "") or ""),
                    title=str(getattr(resource, "title", "") or ""),
                    description=str(getattr(resource, "description", "") or ""),
                    mime_type=str(getattr(resource, "mimeType", "") or ""),
                    size=getattr(resource, "size", None),
                    annotations=_model_dump(getattr(resource, "annotations", {}) or {}),
                    meta=_model_dump(getattr(resource, "meta", {}) or {}),
                )
                for resource in list(getattr(resources_result, "resources", []) or [])
            ],
            prompts=[
                ExternalMCPPrompt(
                    name=str(prompt.name or ""),
                    title=str(getattr(prompt, "title", "") or ""),
                    description=str(getattr(prompt, "description", "") or ""),
                    arguments=[_model_dump(item) for item in list(getattr(prompt, "arguments", []) or [])],
                    meta=_model_dump(getattr(prompt, "meta", {}) or {}),
                )
                for prompt in list(getattr(prompts_result, "prompts", []) or [])
            ],
            diagnostics={
                "tool_cursor": str(getattr(tools_result, "nextCursor", "") or ""),
                "resource_cursor": str(getattr(resources_result, "nextCursor", "") or ""),
                "prompt_cursor": str(getattr(prompts_result, "nextCursor", "") or ""),
            },
        )


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _model_dump(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_model_dump(item) for item in value]
    return value
