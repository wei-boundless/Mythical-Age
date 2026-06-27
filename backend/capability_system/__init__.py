from __future__ import annotations

from importlib import import_module


_EXPORTS: dict[str, tuple[str, str]] = {
    "BASE_UNIT_DESCRIPTORS": (".catalog_projection", "BASE_UNIT_DESCRIPTORS"),
    "CapabilityEndpoint": (".endpoint_projection", "CapabilityEndpoint"),
    "ResourceRuntimeView": (".permission_projection", "ResourceRuntimeView"),
    "TOOL_RISK_ORDER": (".catalog_projection", "TOOL_RISK_ORDER"),
    "TOOL_TYPE_OPTIONS": (".catalog_projection", "TOOL_TYPE_OPTIONS"),
    "UnitCatalog": (".catalog_projection", "UnitCatalog"),
    "UnitDescriptor": (".catalog_projection", "UnitDescriptor"),
    "agent_tool_bindings": (".catalog_projection", "agent_tool_bindings"),
    "build_capability_catalog": (".catalog_projection", "build_capability_catalog"),
    "build_capability_endpoints": (".endpoint_projection", "build_capability_endpoints"),
    "build_capability_units": (".unit_projection", "build_capability_units"),
    "build_base_unit_catalog": (".catalog_projection", "build_base_unit_catalog"),
    "build_orchestration_capability_items": (".catalog_projection", "build_orchestration_capability_items"),
    "build_operation_catalog": (".catalog_projection", "build_capability_catalog"),
    "build_resource_runtime_views": (".permission_projection", "build_resource_runtime_views"),
    "default_tool_type": (".catalog_projection", "default_tool_type"),
    "operation_tool_metadata": (".catalog_projection", "operation_tool_metadata"),
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
