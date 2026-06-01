from __future__ import annotations

from pathlib import Path
from typing import Any

from capability_system.mcp.local_registry import default_local_mcp_units, get_local_mcp_unit
from capability_system.mcp.providers import MCPProviderServer, MCPProviderTool
from capability_system.mcp.server.local_capability_server import LocalCapabilityMCPExecutor, LocalMCPToolRequest
from permissions.operations import build_default_operation_registry
from permissions import OperationGate, OperationGatePipelineContext, ResourcePolicy


class LocalMCPProvider:
    provider_id = "local"
    provider_kind = "local"

    def __init__(
        self,
        backend_dir: Path,
        *,
        resource_policy: ResourcePolicy | None = None,
        permission_mode: str = "default",
    ) -> None:
        self.backend_dir = Path(backend_dir).resolve()
        self.resource_policy = resource_policy
        self.permission_mode = permission_mode
        self.operation_registry = build_default_operation_registry()

    def list_servers(self) -> list[MCPProviderServer]:
        return [self._server_for_unit(unit, inspected=False) for unit in default_local_mcp_units()]

    def inspect_server(self, server_id: str) -> MCPProviderServer:
        unit = self._unit_by_server_id(server_id)
        if unit is None:
            raise KeyError(server_id)
        return self._server_for_unit(unit, inspected=True)

    def preview_permission(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        unit = self._unit_by_server_id(server_id) or get_local_mcp_unit(tool_name)
        if unit is None:
            return {
                "authorized": False,
                "operation_id": "",
                "gate": {"decision": "deny", "reason": "unknown_local_mcp_tool"},
            }
        result = OperationGate(self.operation_registry).check(
            unit.operation_id,
            resource_policy=self.resource_policy,
            directive_ref=f"mcp-preview:local:{unit.route}",
            context=OperationGatePipelineContext(
                permission_mode=self.permission_mode,
                operation_input={
                    "operation_id": unit.operation_id,
                    "route": unit.route,
                    "tool_name": unit.name,
                    **dict(arguments or {}),
                },
            ),
        )
        return {
            "authorized": result.allowed,
            "operation_id": unit.operation_id,
            "gate": result.to_dict(),
            "provider_kind": self.provider_kind,
            "server_id": unit.mcp_id,
            "tool_name": unit.name,
        }

    def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        unit = self._unit_by_server_id(server_id) or get_local_mcp_unit(tool_name)
        if unit is None:
            return {"status": "error", "error": "unknown_local_mcp_tool", "server_id": server_id, "tool_name": tool_name}
        args = dict(arguments or {})
        executor = LocalCapabilityMCPExecutor(
            backend_dir=self.backend_dir,
            resource_policy=self.resource_policy,
            permission_mode=self.permission_mode,
        )
        return executor.execute_sync(
            LocalMCPToolRequest(
                route=unit.route,
                query=str(args.get("query") or ""),
                session_id=str(args.get("session_id") or "mcp-session"),
                path=str(args.get("path") or ""),
                mode=str(args.get("mode") or ""),
                top_k=int(args.get("top_k") or 5),
                constraints=dict(args.get("constraints") or {}),
            )
        )

    def _server_for_unit(self, unit: Any, *, inspected: bool) -> MCPProviderServer:
        tool = MCPProviderTool(
            provider_id=self.provider_id,
            server_id=unit.mcp_id,
            tool_name=unit.name,
            title=unit.title,
            description=unit.summary,
            operation_id=unit.operation_id,
            model_visibility="not_direct_model_tool",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    unit.request_path_parameter or "path": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            annotations={"readOnlyHint": True, "localMcpUnit": unit.unit_id},
            tags=tuple(unit.tags),
            diagnostics={
                "unit_id": unit.unit_id,
                "route": unit.route,
                "worker_execution_kind": unit.worker_execution_kind,
            },
        )
        return MCPProviderServer(
            provider_id=self.provider_id,
            server_id=unit.mcp_id,
            title=unit.title,
            description=unit.summary,
            provider_kind=self.provider_kind,
            transport="in_process",
            enabled=unit.status == "active",
            status="active" if inspected else "not_inspected",
            status_reason="" if unit.status == "active" else unit.status,
            operation_ids=(unit.operation_id,),
            tools=(tool,),
            diagnostics={
                "unit_id": unit.unit_id,
                "route": unit.route,
                "implementation_module": unit.implementation_module,
                "model_visibility": "not_direct_model_tool",
                "inspect_mode": "local_static_snapshot" if inspected else "catalog_snapshot",
            },
        )

    def _unit_by_server_id(self, server_id: str) -> Any | None:
        target = str(server_id or "").strip()
        for unit in default_local_mcp_units():
            if unit.mcp_id == target or unit.route == target or unit.name == target or unit.unit_id == target:
                return unit
        return None


