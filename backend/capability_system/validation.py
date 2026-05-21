from __future__ import annotations

from typing import Any

from .models import CapabilityValidationIssue


def validate_capability_catalog(
    *,
    skills: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    agent_bindings: dict[str, list[str]],
    mcps: list[dict[str, Any]] | None = None,
    capability_endpoints: list[dict[str, Any]] | None = None,
    capability_units: list[dict[str, Any]] | None = None,
    operations: list[dict[str, Any]] | None = None,
    task_operation_ids: list[str] | None = None,
) -> list[CapabilityValidationIssue]:
    issues: list[CapabilityValidationIssue] = []
    known_tools = {str(tool.get("name") or "") for tool in tools}
    tools_by_name = {str(tool.get("name") or ""): tool for tool in tools}
    operations_by_id = {str(operation.get("operation_id") or ""): operation for operation in list(operations or [])}
    known_operations = set(operations_by_id)

    for tool in tools:
        tool_name = str(tool.get("name") or "")
        operation_id = str(tool.get("operation_id") or "")
        if not operation_id:
            issues.append(
                CapabilityValidationIssue(
                    severity="error",
                    code="tool_missing_operation_id",
                    message=f"Tool {tool_name} is missing operation_id.",
                    subject=tool_name,
                )
            )
        elif known_operations and operation_id not in known_operations:
            issues.append(
                CapabilityValidationIssue(
                    severity="error",
                    code="tool_unknown_operation",
                    message=f"Tool {tool_name} maps to unknown operation {operation_id}.",
                    subject=tool_name,
                )
            )
        if _is_high_risk_tool(tool):
            operation = operations_by_id.get(operation_id)
            if operation is not None and not bool(operation.get("requires_approval_by_default")):
                issues.append(
                    CapabilityValidationIssue(
                        severity="error",
                        code="high_risk_tool_missing_approval",
                        message=f"High-risk tool {tool_name} maps to {operation_id} without default approval.",
                        subject=tool_name,
                    )
                )

    for agent_id, tool_names in agent_bindings.items():
        for tool_name in tool_names:
            if tool_name not in known_tools:
                issues.append(
                    CapabilityValidationIssue(
                        severity="warning",
                        code="agent_unknown_tool",
                        message=f"Agent {agent_id} owns unknown tool {tool_name}.",
                        subject=agent_id,
                    )
                )
                continue
            operation_id = str(tools_by_name[tool_name].get("operation_id") or "")
            if known_operations and operation_id not in known_operations:
                issues.append(
                    CapabilityValidationIssue(
                        severity="error",
                        code="agent_tool_unknown_operation",
                        message=f"Agent {agent_id} owns tool {tool_name} with unknown operation {operation_id}.",
                        subject=agent_id,
                    )
                )

    for mcp in list(mcps or []):
        mcp_id = str(mcp.get("mcp_id") or "")
        operation_id = str(mcp.get("operation_id") or "")
        if not operation_id:
            issues.append(
                CapabilityValidationIssue(
                    severity="error",
                    code="mcp_missing_operation_id",
                    message=f"MCP {mcp_id} is missing operation_id.",
                    subject=mcp_id,
                )
            )
            continue
        operation = operations_by_id.get(operation_id)
        if known_operations and operation is None:
            issues.append(
                CapabilityValidationIssue(
                    severity="error",
                    code="mcp_unknown_operation",
                    message=f"MCP {mcp_id} maps to unknown operation {operation_id}.",
                    subject=mcp_id,
                )
            )
            continue
        if operation is not None and str(operation.get("operation_type") or "") != "mcp":
            issues.append(
                CapabilityValidationIssue(
                    severity="error",
                    code="mcp_operation_type_mismatch",
                    message=f"MCP {mcp_id} maps to non-MCP operation {operation_id}.",
                    subject=mcp_id,
                )
            )
        if str(mcp.get("model_visibility") or "") != "not_direct_model_tool":
            issues.append(
                CapabilityValidationIssue(
                    severity="error",
                    code="mcp_model_visibility_invalid",
                    message=f"MCP {mcp_id} must not be exposed as a direct model tool.",
                    subject=mcp_id,
                )
            )

    for endpoint in list(capability_endpoints or []):
        endpoint_id = str(endpoint.get("endpoint_id") or "")
        kind = str(endpoint.get("kind") or "")
        operation_id = str(endpoint.get("operation_id") or "")
        if not endpoint_id:
            issues.append(
                CapabilityValidationIssue(
                    severity="error",
                    code="endpoint_missing_id",
                    message="Capability endpoint is missing endpoint_id.",
                    subject=kind,
                )
            )
        if known_operations and operation_id not in known_operations:
            issues.append(
                CapabilityValidationIssue(
                    severity="error",
                    code="endpoint_unknown_operation",
                    message=f"Endpoint {endpoint_id} maps to unknown operation {operation_id}.",
                    subject=endpoint_id,
                )
            )
            continue
        operation = operations_by_id.get(operation_id)
        operation_type = str((operation or {}).get("operation_type") or "")
        if kind == "tool" and operation is not None and operation_type in {"mcp", "agent"}:
            issues.append(
                CapabilityValidationIssue(
                    severity="error",
                    code="endpoint_tool_operation_type_mismatch",
                    message=f"Tool endpoint {endpoint_id} maps to {operation_type} operation {operation_id}.",
                    subject=endpoint_id,
                )
            )
        if kind == "mcp_endpoint" and operation is not None and operation_type != "mcp":
            issues.append(
                CapabilityValidationIssue(
                    severity="error",
                    code="endpoint_mcp_operation_type_mismatch",
                    message=f"MCP endpoint {endpoint_id} maps to non-MCP operation {operation_id}.",
                    subject=endpoint_id,
                )
            )
        if kind == "mcp_endpoint" and str(endpoint.get("model_visibility") or "") != "not_direct_model_tool":
            issues.append(
                CapabilityValidationIssue(
                    severity="error",
                    code="endpoint_mcp_model_visibility_invalid",
                    message=f"MCP endpoint {endpoint_id} must stay out of direct model tool exposure.",
                    subject=endpoint_id,
                )
            )

    seen_capability_ids: set[str] = set()
    for unit in list(capability_units or []):
        capability_id = str(unit.get("capability_id") or "").strip()
        if not capability_id:
            issues.append(
                CapabilityValidationIssue(
                    severity="error",
                    code="capability_unit_missing_id",
                    message="CapabilityUnit is missing capability_id.",
                    subject=str(unit.get("kind") or ""),
                )
            )
            continue
        if capability_id in seen_capability_ids:
            issues.append(
                CapabilityValidationIssue(
                    severity="error",
                    code="capability_unit_duplicate_id",
                    message=f"CapabilityUnit {capability_id} is duplicated.",
                    subject=capability_id,
                )
            )
        seen_capability_ids.add(capability_id)
        for operation_id in [str(item).strip() for item in list(unit.get("operation_ids") or []) if str(item).strip()]:
            if known_operations and operation_id not in known_operations:
                issues.append(
                    CapabilityValidationIssue(
                        severity="error",
                        code="capability_unit_unknown_operation",
                        message=f"CapabilityUnit {capability_id} references unknown operation {operation_id}.",
                        subject=capability_id,
                    )
                )
        if str(unit.get("kind") or "") == "mcp" and str(unit.get("provider_kind") or "") == "local":
            if str(unit.get("model_visibility") or "") != "not_direct_model_tool":
                issues.append(
                    CapabilityValidationIssue(
                        severity="error",
                        code="capability_unit_local_mcp_model_visibility_invalid",
                        message=f"Local MCP CapabilityUnit {capability_id} must not be exposed as a direct model tool.",
                        subject=capability_id,
                    )
                )

    alias_owner: dict[str, str] = {}
    for operation in list(operations or []):
        operation_id = str(operation.get("operation_id") or "")
        for alias in list(operation.get("aliases") or []):
            normalized_alias = str(alias or "").strip()
            if not normalized_alias:
                continue
            owner = alias_owner.get(normalized_alias)
            if owner and owner != operation_id:
                issues.append(
                    CapabilityValidationIssue(
                        severity="error",
                        code="duplicate_operation_alias",
                        message=f"Operation alias {normalized_alias} is shared by {owner} and {operation_id}.",
                        subject=normalized_alias,
                    )
                )
                continue
            alias_owner[normalized_alias] = operation_id

    for operation_id in list(task_operation_ids or []):
        if known_operations and operation_id not in known_operations:
            issues.append(
                CapabilityValidationIssue(
                    severity="error",
                    code="task_unknown_operation",
                    message=f"Task binding references unknown operation {operation_id}.",
                    subject=operation_id,
                )
            )

    return issues


def _is_high_risk_tool(tool: dict[str, Any]) -> bool:
    tags = {
        str(item or "").strip()
        for item in [
            *list(tool.get("capability_tags") or []),
            *list(tool.get("supported_modalities") or []),
            *list(tool.get("safety_tags") or []),
            *list(tool.get("route_hints") or []),
        ]
        if str(item or "").strip()
    }
    return bool(
        tool.get("is_destructive")
        or not bool(tool.get("is_read_only", True))
        or tags & {"shell", "destructive", "write", "local_write"}
    )
