from __future__ import annotations

from importlib import import_module


_EXPORTS: dict[str, tuple[str, str]] = {
    "ExternalMCPConfigStore": (".client", "ExternalMCPConfigStore"),
    "ExternalMCPManager": (".client", "ExternalMCPManager"),
    "ExternalMCPResource": (".client", "ExternalMCPResource"),
    "ExternalMCPServerConfig": (".client", "ExternalMCPServerConfig"),
    "ExternalMCPSnapshot": (".client", "ExternalMCPSnapshot"),
    "ExternalMCPTool": (".client", "ExternalMCPTool"),
    "LocalCapabilityMCPExecutor": (".server.local_capability_server", "LocalCapabilityMCPExecutor"),
    "LocalMCPToolRequest": (".server.local_capability_server", "LocalMCPToolRequest"),
    "MCPManagementService": (".management_service", "MCPManagementService"),
    "MCPProviderServer": (".providers", "MCPProviderServer"),
    "MCPProviderTool": (".providers", "MCPProviderTool"),
    "build_external_mcp_operation_descriptor": (".client.permission", "build_external_mcp_operation_descriptor"),
    "build_external_mcp_operation_id": (".client.permission", "build_external_mcp_operation_id"),
    "build_mcp_tool_pool": (".server.tool_pool", "build_mcp_tool_pool"),
    "build_server": (".server.server", "build_server"),
    "check_external_mcp_tool_permission": (".client.permission", "check_external_mcp_tool_permission"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value
