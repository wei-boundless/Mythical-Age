from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from capability_system.mcp.client import ExternalMCPServerConfig
from capability_system.mcp.management_service import MCPManagementService

router = APIRouter()


class ExternalMCPServerRequest(BaseModel):
    server_id: str = Field(..., min_length=2, max_length=64)
    title: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=800)
    transport: str = "stdio"
    enabled: bool = True
    command: str = Field(default="", max_length=400)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str = Field(default="", max_length=600)
    url: str = Field(default="", max_length=800)
    scope: str = "project"
    tags: list[str] = Field(default_factory=list)
    allowed_operations: list[str] = Field(default_factory=list)
    requires_approval_operations: list[str] = Field(default_factory=list)
    denied_operations: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExternalMCPToolCallRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


def _management_service() -> MCPManagementService:
    runtime = require_runtime()
    return MCPManagementService(runtime.base_dir, permission_mode=runtime.permission_service.current_mode())


def _request_to_config(payload: ExternalMCPServerRequest) -> ExternalMCPServerConfig:
    return ExternalMCPServerConfig(
        server_id=payload.server_id,
        title=payload.title,
        description=payload.description,
        transport=payload.transport,
        enabled=payload.enabled,
        command=payload.command,
        args=tuple(payload.args),
        env=dict(payload.env),
        cwd=payload.cwd,
        url=payload.url,
        scope=payload.scope,
        tags=tuple(payload.tags),
        allowed_operations=tuple(payload.allowed_operations),
        requires_approval_operations=tuple(payload.requires_approval_operations),
        denied_operations=tuple(payload.denied_operations),
        metadata=dict(payload.metadata),
    )


@router.get("/mcp-system/management/catalog")
def mcp_management_catalog() -> dict[str, Any]:
    return _management_service().build_catalog()


@router.put("/mcp-system/management/providers/external/servers/{server_id}")
def upsert_external_mcp_management_server(server_id: str, payload: ExternalMCPServerRequest) -> dict[str, Any]:
    config = _request_to_config(payload)
    if config.server_id != server_id:
        raise HTTPException(status_code=400, detail="server_id in path and payload must match")
    try:
        service = _management_service()
        service.upsert_external_server(config)
        return service.build_catalog()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown MCP provider") from exc


@router.delete("/mcp-system/management/providers/external/servers/{server_id}")
def delete_external_mcp_management_server(server_id: str) -> dict[str, Any]:
    try:
        service = _management_service()
        service.delete_external_server(server_id)
        return service.build_catalog()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown MCP provider") from exc


@router.post("/mcp-system/management/providers/{provider_id}/servers/{server_id}/inspect")
def inspect_mcp_management_server(provider_id: str, server_id: str) -> dict[str, Any]:
    try:
        return _management_service().inspect_server(provider_id, server_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown MCP provider or server") from exc


@router.post("/mcp-system/management/providers/{provider_id}/servers/{server_id}/tools/{tool_name}/preview")
def preview_mcp_management_tool(
    provider_id: str,
    server_id: str,
    tool_name: str,
    payload: ExternalMCPToolCallRequest,
) -> dict[str, Any]:
    try:
        return _management_service().preview_permission(provider_id, server_id, tool_name, payload.arguments)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown MCP provider, server, or tool") from exc


@router.post("/mcp-system/management/providers/{provider_id}/servers/{server_id}/tools/{tool_name}/call")
def call_mcp_management_tool(
    provider_id: str,
    server_id: str,
    tool_name: str,
    payload: ExternalMCPToolCallRequest,
) -> dict[str, Any]:
    try:
        return _management_service().call_tool(provider_id, server_id, tool_name, payload.arguments)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown MCP provider, server, or tool") from exc
