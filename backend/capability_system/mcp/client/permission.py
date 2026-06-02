from __future__ import annotations

from typing import Any

from permissions.operations import OperationDescriptor, OperationRegistry
from permissions import OperationGate, OperationGatePipelineContext, ResourceDecision, ResourcePolicy

from .models import ExternalMCPServerConfig


EXTERNAL_MCP_OPERATION_TYPE = "external_mcp"


def build_external_mcp_operation_id(server_id: str, tool_name: str) -> str:
    return f"op.external_mcp.{_slug(server_id)}.{_slug(tool_name)}"


def build_external_mcp_operation_descriptor(
    server: ExternalMCPServerConfig,
    tool: dict[str, Any],
) -> OperationDescriptor:
    annotations = dict(tool.get("annotations") or {})
    read_only = bool(annotations.get("readOnlyHint", False))
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
    allowed_operations, requires_approval_operations, denied_operations, decision = _external_mcp_policy_decision(
        server=server,
        operation=operation,
        permission_mode=permission_mode,
    )
    policy = ResourcePolicy(
        policy_id=f"respol:external-mcp:{server.server_id}",
        task_id="external-mcp",
        allowed_operations=allowed_operations,
        denied_operations=denied_operations,
        requires_approval_operations=requires_approval_operations,
        allowed_mcps=(server.server_id,),
        runtime_view_only=False,
        adopted=True,
        runtime_executable=True,
        decisions=(decision,),
        diagnostics={
            "authority": "capability_system.mcp.client.permission",
            "deny_first_enforced_by": "OperationGate",
            "config_authorizes_operation": operation.operation_id in set(server.allowed_operations),
            "risk_requires_approval": bool(operation.requires_approval_by_default or operation.destructive),
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


def _external_mcp_policy_decision(
    *,
    server: ExternalMCPServerConfig,
    operation: OperationDescriptor,
    permission_mode: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], ResourceDecision]:
    operation_id = operation.operation_id
    configured_allowed = {str(item or "").strip() for item in tuple(server.allowed_operations or ()) if str(item or "").strip()}
    configured_denied = {str(item or "").strip() for item in tuple(server.denied_operations or ()) if str(item or "").strip()}
    configured_requires_approval = {
        str(item or "").strip()
        for item in tuple(server.requires_approval_operations or ())
        if str(item or "").strip()
    }
    if operation_id in configured_denied:
        return (
            (),
            (),
            (operation_id,),
            ResourceDecision(
                operation_id=operation_id,
                decision="deny",
                reason="external MCP operation denied by server configuration",
                risk_tags=operation.risk_tags,
            ),
        )
    if operation_id not in configured_allowed:
        return (
            (),
            (),
            (),
            ResourceDecision(
                operation_id=operation_id,
                decision="deny",
                reason="external MCP operation is not explicitly authorized by server configuration",
                risk_tags=operation.risk_tags,
            ),
        )
    mode = str(permission_mode or "default").strip().lower()
    if mode in {"full_access", "bypass"}:
        return (
            (operation_id,),
            (),
            (),
            ResourceDecision(
                operation_id=operation_id,
                decision="allow",
                reason=f"external MCP operation allowed by permission mode {mode}",
                risk_tags=operation.risk_tags,
                diagnostics={"permission_mode": mode},
            ),
        )
    if operation_id in configured_requires_approval or operation.requires_approval_by_default or operation.destructive:
        return (
            (),
            (operation_id,),
            (),
            ResourceDecision(
                operation_id=operation_id,
                decision="requires_approval",
                reason="external MCP operation requires approval before execution",
                risk_tags=operation.risk_tags,
                requires_user_approval=True,
                approval_channel="runtime_approval",
                diagnostics={"permission_mode": mode},
            ),
        )
    return (
        (operation_id,),
        (),
        (),
        ResourceDecision(
            operation_id=operation_id,
            decision="allow",
            reason="external MCP read-only operation explicitly authorized by server configuration",
            risk_tags=operation.risk_tags,
            diagnostics={"permission_mode": mode},
        ),
    )


def _slug(value: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").strip().lower()).strip("_")
    return normalized or "unknown"


