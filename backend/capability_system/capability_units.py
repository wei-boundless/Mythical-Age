from __future__ import annotations

from typing import Any

from .models import (
    CapabilityDependency,
    CapabilityHealth,
    CapabilityPermissionView,
    CapabilityUnit,
)


def build_capability_units(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    operations = {
        str(operation.get("operation_id") or "").strip(): operation
        for operation in list(catalog.get("operations") or [])
        if isinstance(operation, dict) and str(operation.get("operation_id") or "").strip()
    }
    units: list[CapabilityUnit] = []
    units.extend(_skill_units(catalog, operations))
    units.extend(_tool_units(catalog, operations))
    units.extend(_mcp_units(catalog, operations))
    return [unit.to_dict() for unit in units]


def _skill_units(catalog: dict[str, Any], operations: dict[str, dict[str, Any]]) -> list[CapabilityUnit]:
    result: list[CapabilityUnit] = []
    for skill in [item for item in list(catalog.get("skills") or []) if isinstance(item, dict)]:
        runtime = skill.get("runtime") if isinstance(skill.get("runtime"), dict) else {}
        prompt = skill.get("prompt_view") if isinstance(skill.get("prompt_view"), dict) else {}
        name = str(runtime.get("name") or "").strip()
        operation_ids = tuple(_skill_operation_ids(runtime))
        capability_id = f"skill:{name}"
        dependencies = tuple(
            CapabilityDependency(capability_id, f"operation:{operation_id}", "requires_operation")
            for operation_id in operation_ids
        ) + tuple(
            CapabilityDependency(capability_id, str(capability_ref), "requires_capability")
            for capability_ref in list(runtime.get("requires_capabilities") or [])
            if str(capability_ref).strip()
        )
        activation_policy = str(runtime.get("activation_policy") or "").strip()
        status = "disabled" if activation_policy == "disabled" else "active"
        result.append(
            CapabilityUnit(
                capability_id=capability_id,
                kind="skill",
                title=str(prompt.get("title") or runtime.get("title") or name).strip(),
                summary=str(prompt.get("capability") or runtime.get("description") or "").strip(),
                operation_ids=operation_ids,
                provider="skill_registry",
                provider_kind="builtin",
                runtime_visibility=str(runtime.get("context_mode") or "").strip(),
                model_visibility="selected_skill_only" if activation_policy != "disabled" else "disabled",
                risk=_risk_for_operations(operation_ids, operations),
                resource_policy="declared_operations",
                status=status,
                source_ref=str(runtime.get("path") or "").strip(),
                dependencies=dependencies,
                health=CapabilityHealth(status=status, reason="" if operation_ids else "missing_declared_operations"),
                permission_view=CapabilityPermissionView(
                    capability_id=capability_id,
                    operation_ids=operation_ids,
                    reasons=("skill_declares_operation_dependencies",) if operation_ids else ("skill_missing_operation_dependencies",),
                ),
                display_facets={
                    "preferred_route": str(runtime.get("preferred_route") or ""),
                    "activation_policy": activation_policy,
                    "capability_tags": list(runtime.get("capability_tags") or []),
                },
                diagnostics={"validation_errors": list(skill.get("validation_errors") or [])},
            )
        )
    return result


def _tool_units(catalog: dict[str, Any], operations: dict[str, dict[str, Any]]) -> list[CapabilityUnit]:
    result: list[CapabilityUnit] = []
    for tool in [item for item in list(catalog.get("tools") or []) if isinstance(item, dict)]:
        name = str(tool.get("name") or "").strip()
        operation_id = str(tool.get("operation_id") or "").strip()
        operation = operations.get(operation_id, {})
        metadata = tool.get("operation_metadata") if isinstance(tool.get("operation_metadata"), dict) else {}
        capability_id = f"tool:{name}"
        result.append(
            CapabilityUnit(
                capability_id=capability_id,
                kind="tool",
                title=str(tool.get("display_name") or operation.get("title") or name).strip(),
                summary=str(tool.get("description") or operation.get("capability_summary") or "").strip(),
                operation_ids=(operation_id,) if operation_id else (),
                provider="tool_registry",
                provider_kind="builtin",
                transport="in_process",
                runtime_visibility=str(tool.get("runtime_visibility") or ""),
                model_visibility=str(tool.get("prompt_exposure_policy") or ""),
                risk=tuple(str(item) for item in list(operation.get("risk_tags") or tool.get("safety_tags") or []) if str(item).strip()),
                resource_policy=str(tool.get("resource_exposure_policy") or ""),
                status="active",
                source_ref=str(tool.get("module") or ""),
                dependencies=(
                    (CapabilityDependency(capability_id, f"operation:{operation_id}", "maps_to_operation"),)
                    if operation_id
                    else ()
                ),
                health=CapabilityHealth(status="active", reason="" if operation_id in operations else "unknown_operation"),
                permission_view=CapabilityPermissionView(
                    capability_id=capability_id,
                    operation_ids=(operation_id,) if operation_id else (),
                    reasons=("tool_maps_to_operation",) if operation_id else ("tool_missing_operation",),
                ),
                display_facets={
                    "tool_type": metadata.get("tool_type"),
                    "source_class": metadata.get("source_class"),
                    "risk_level": metadata.get("risk_level"),
                },
                diagnostics={"schema_identity": tool.get("schema_identity")},
            )
        )
    return result


def _mcp_units(catalog: dict[str, Any], operations: dict[str, dict[str, Any]]) -> list[CapabilityUnit]:
    management = catalog.get("mcp_management") if isinstance(catalog.get("mcp_management"), dict) else {}
    servers = [item for item in list(management.get("servers") or []) if isinstance(item, dict)]
    result: list[CapabilityUnit] = []
    for server in servers:
        provider_kind = str(server.get("provider_kind") or "")
        provider_id = str(server.get("provider_id") or provider_kind)
        server_id = str(server.get("server_id") or "")
        tools = [item for item in list(server.get("tools") or []) if isinstance(item, dict)]
        if not tools:
            result.append(
                CapabilityUnit(
                    capability_id=f"mcp:{provider_id}:{server_id}",
                    kind="mcp",
                    title=str(server.get("title") or server_id),
                    summary=str(server.get("description") or ""),
                    operation_ids=tuple(str(item) for item in list(server.get("operation_ids") or []) if str(item)),
                    provider=f"mcp:{provider_id}:{server_id}",
                    provider_kind=provider_kind,
                    transport=str(server.get("transport") or ""),
                    runtime_visibility="mcp_provider",
                    model_visibility="not_direct_model_tool" if provider_kind == "local" else "permission_gated",
                    risk=_risk_for_operations(tuple(server.get("operation_ids") or ()), operations),
                    resource_policy="provider_tool_operation",
                    status=str(server.get("status") or "not_inspected"),
                    source_ref=server_id,
                    health=CapabilityHealth(
                        status=str(server.get("status") or "not_inspected"),
                        reason=str(server.get("status_reason") or ""),
                        diagnostics=dict(server.get("diagnostics") or {}),
                    ),
                    permission_view=CapabilityPermissionView(
                        capability_id=f"mcp:{provider_id}:{server_id}",
                        operation_ids=tuple(str(item) for item in list(server.get("operation_ids") or []) if str(item)),
                        reasons=("mcp_provider_server",),
                    ),
                )
            )
            continue
        for tool in tools:
            operation_id = str(tool.get("operation_id") or "").strip()
            tool_name = str(tool.get("tool_name") or "").strip()
            capability_id = f"mcp:{provider_id}:{server_id}:{tool_name}"
            result.append(
                CapabilityUnit(
                    capability_id=capability_id,
                    kind="mcp",
                    title=str(tool.get("title") or tool_name or server.get("title") or server_id),
                    summary=str(tool.get("description") or server.get("description") or ""),
                    operation_ids=(operation_id,) if operation_id else (),
                    provider=f"mcp:{provider_id}:{server_id}",
                    provider_kind=provider_kind,
                    transport=str(server.get("transport") or tool.get("transport") or ""),
                    runtime_visibility="mcp_tool",
                    model_visibility=str(tool.get("model_visibility") or "permission_gated"),
                    risk=_risk_for_operations((operation_id,) if operation_id else (), operations),
                    resource_policy="provider_tool_operation",
                    status=str(server.get("status") or "not_inspected"),
                    source_ref=f"{server_id}:{tool_name}",
                    dependencies=(
                        (CapabilityDependency(capability_id, f"operation:{operation_id}", "maps_to_operation"),)
                        if operation_id
                        else ()
                    ),
                    health=CapabilityHealth(
                        status=str(server.get("status") or "not_inspected"),
                        reason=str(server.get("status_reason") or ""),
                        diagnostics=dict(tool.get("diagnostics") or {}),
                    ),
                    permission_view=CapabilityPermissionView(
                        capability_id=capability_id,
                        operation_ids=(operation_id,) if operation_id else (),
                        reasons=("mcp_tool_maps_to_operation",) if operation_id else ("mcp_tool_missing_operation",),
                    ),
                    display_facets={
                        "server_id": server_id,
                        "provider_id": provider_id,
                        "tool_name": tool_name,
                    },
                )
            )
    return result


def _risk_for_operations(operation_ids: tuple[str, ...] | list[str], operations: dict[str, dict[str, Any]]) -> tuple[str, ...]:
    risks: list[str] = []
    for operation_id in operation_ids:
        operation = operations.get(str(operation_id or ""))
        if not operation:
            continue
        risks.extend(str(item) for item in list(operation.get("risk_tags") or []) if str(item).strip())
    return tuple(dict.fromkeys(risks))


def _skill_operation_ids(runtime: dict[str, Any]) -> list[str]:
    explicit = [
        str(item).strip()
        for item in list(runtime.get("requires_operations") or [])
        if str(item).strip()
    ]
    if explicit:
        return explicit
    route = str(runtime.get("preferred_route") or "").strip()
    if route.startswith("op."):
        return [route]
    return {
        "rag": ["op.mcp_retrieval"],
        "retrieval": ["op.mcp_retrieval"],
        "pdf": ["op.mcp_pdf"],
        "structured_data": ["op.mcp_structured_data"],
        "data": ["op.mcp_structured_data"],
    }.get(route, [])
