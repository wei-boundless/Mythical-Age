from __future__ import annotations

from typing import Any

from capability_system.operation_registry import OperationDescriptor, OperationRegistry
from permissions import OperationGate, OperationGatePipelineContext, ResourcePolicy

from .models import ExternalMCPServerConfig


EXTERNAL_MCP_OPERATION_TYPE = "external_mcp"


def build_external_mcp_operation_id(server_id: str, tool_name: str) -> str:
    return f"op.external_mcp.{_slug(server_id)}.{_slug(tool_name)}"


def build_external_mcp_operation_descriptor(
    server: ExternalMCPServerConfig,
    tool: dict[str, Any],
) -> OperationDescriptor:
    annotations = dict(tool.get("annotations") or {})
    read_only = bool(annotations.get("readOnlyHint", True))
    destructive = bool(annotations.get("destructiveHint", not read_only))
    idempotent = bool(annotations.get("idempotentHint", read_only))
    open_world = bool(annotations.get("openWorldHint", True))
    tool_name = str(tool.get("name") or "").strip()
    title = str(tool.get("title") or tool_name or "External MCP tool")
    description = str(tool.get("description") or f"External MCP tool `{tool_name}` from `{server.server_id}`.")
    risk_tags = ["mcp_execution", "external_mcp"]
    if read_only:
        risk_tags.append("read_only")
    if open_world:
        risk_tags.append("network_open_world")
    if destructive:
        risk_tags.append("destructive")
    return OperationDescriptor(
        operation_id=build_external_mcp_operation_id(server.server_id, tool_name),
        operation_type=EXTERNAL_MCP_OPERATION_TYPE,
        title=title,
        capability_summary=description,
        provider=f"external_mcp:{server.server_id}",
        aliases=(f"external_mcp:{server.server_id}:{tool_name}",),
        input_contract=dict(tool.get("input_schema") or {"type": "object"}),
        output_contract=dict(tool.get("output_schema") or {"type": "object"}),
        input_contract_ref=f"external_mcp.{server.server_id}.{tool_name}.input",
        output_contract_ref=f"external_mcp.{server.server_id}.{tool_name}.output",
        risk_tags=tuple(sorted(set(risk_tags))),
        read_only=read_only,
        destructive=destructive,
        idempotent=idempotent,
        open_world=open_world,
        concurrency_safe=bool(annotations.get("concurrencySafeHint", False)),
        requires_user_interaction=destructive,
        requires_approval_by_default=destructive,
        max_result_size_chars=80_000,
        interrupt_behavior="defer",
        deferred_loading=True,
        metadata={
            "server_id": server.server_id,
            "tool_name": tool_name,
            "transport": server.transport,
            "annotations": annotations,
        },
    )


def check_external_mcp_tool_permission(
    *,
    server: ExternalMCPServerConfig,
    tool: dict[str, Any],
    permission_mode: str,
    tool_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    operation = build_external_mcp_operation_descriptor(server, tool)
    registry = OperationRegistry([operation])
    allowed_operations = server.allowed_operations or (operation.operation_id,)
    policy = ResourcePolicy(
        policy_id=f"respol:external-mcp:{server.server_id}",
        task_id="external-mcp",
        allowed_operations=tuple(allowed_operations),
        denied_operations=tuple(server.denied_operations),
        requires_approval_operations=tuple(server.requires_approval_operations),
        allowed_mcps=(server.server_id,),
        runtime_view_only=False,
        adopted=True,
        runtime_executable=True,
        diagnostics={
            "authority": "capability_system.mcp.client.permission",
            "deny_first_enforced_by": "OperationGate",
        },
    )
    result = OperationGate(registry).check(
        operation.operation_id,
        resource_policy=policy,
        directive_ref=f"external-mcp:{server.server_id}:{operation.metadata.get('tool_name')}",
        context=OperationGatePipelineContext(
            permission_mode=permission_mode,
            operation_input=dict(tool_input or {}),
        ),
    )
    return {
        "operation": operation.to_dict(),
        "resource_policy": policy.to_dict(),
        "gate": result.to_dict(),
        "authorized": result.allowed,
    }


def _slug(value: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").strip().lower()).strip("_")
    return normalized or "unknown"


