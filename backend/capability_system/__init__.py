from __future__ import annotations

from importlib import import_module


_EXPORTS: dict[str, tuple[str, str]] = {
    "CapabilityEndpoint": (".endpoints", "CapabilityEndpoint"),
    "LOCAL_MCP_SERVER_NAME": (".mcp_registry", "LOCAL_MCP_SERVER_NAME"),
    "OperationDescriptor": (".operation_registry", "OperationDescriptor"),
    "OperationRegistry": (".operation_registry", "OperationRegistry"),
    "TOOL_RISK_ORDER": (".catalog", "TOOL_RISK_ORDER"),
    "TOOL_TYPE_OPTIONS": (".catalog", "TOOL_TYPE_OPTIONS"),
    "MCPRegistryEntry": (".mcp_registry", "MCPRegistryEntry"),
    "agent_tool_bindings": (".catalog", "agent_tool_bindings"),
    "build_capability_catalog": (".catalog", "build_capability_catalog"),
    "build_orchestration_capability_items": (".catalog", "build_orchestration_capability_items"),
    "build_capability_supply_package": (".supply", "build_capability_supply_package"),
    "build_capability_supply_package_from_base_dir": (".supply", "build_capability_supply_package_from_base_dir"),
    "build_capability_supply_package_from_catalog": (".supply", "build_capability_supply_package_from_catalog"),
    "build_operation_catalog": (".catalog", "build_capability_catalog"),
    "build_operation_requirement": ("task_system.contracts.capability_requirements", "build_operation_requirement"),
    "build_resource_policy_candidate": ("orchestration.resource_policy_builder", "build_resource_policy_candidate"),
    "build_resource_runtime_views": ("orchestration.resource_runtime_view", "build_resource_runtime_views"),
    "build_capability_endpoints": (".endpoints", "build_capability_endpoints"),
    "build_default_operation_registry": (".operation_registry", "build_default_operation_registry"),
    "build_mcp_catalog": (".mcp_registry", "build_mcp_catalog"),
    "default_tool_type": (".catalog", "default_tool_type"),
    "default_mcp_entries": (".mcp_registry", "default_mcp_entries"),
    "operation_tool_metadata": (".catalog", "operation_tool_metadata"),
    "set_skill_prompt_view": (".skill_authoring", "set_skill_prompt_view"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
