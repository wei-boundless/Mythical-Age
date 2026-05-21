from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from capability_system.mcp.client import ExternalMCPManager, ExternalMCPServerConfig

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


def _manager() -> ExternalMCPManager:
    runtime = require_runtime()
    return ExternalMCPManager(runtime.base_dir, permission_mode=runtime.permission_service.current_mode())


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


@router.get("/mcp-system/catalog")
async def mcp_system_catalog() -> dict[str, Any]:
    return await _manager().build_catalog()


@router.post("/mcp-system/servers")
async def create_mcp_server(payload: ExternalMCPServerRequest) -> dict[str, Any]:
    manager = _manager()
    try:
        manager.upsert_server(_request_to_config(payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await manager.build_catalog()


@router.put("/mcp-system/servers/{server_id}")
async def update_mcp_server(server_id: str, payload: ExternalMCPServerRequest) -> dict[str, Any]:
    manager = _manager()
    config = _request_to_config(payload)
    if config.server_id != server_id:
        raise HTTPException(status_code=400, detail="server_id in path and payload must match")
    try:
        manager.upsert_server(config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await manager.build_catalog()


@router.delete("/mcp-system/servers/{server_id}")
async def delete_mcp_server(server_id: str) -> dict[str, Any]:
    manager = _manager()
    try:
        manager.delete_server(server_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await manager.build_catalog()


@router.post("/mcp-system/servers/{server_id}/inspect")
async def inspect_mcp_server(server_id: str) -> dict[str, Any]:
    manager = _manager()
    try:
        snapshot = await manager.inspect_server(server_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown MCP server") from exc
    return snapshot.to_dict()


@router.post("/mcp-system/servers/{server_id}/tools/{tool_name}/call")
async def call_mcp_tool(server_id: str, tool_name: str, payload: ExternalMCPToolCallRequest) -> dict[str, Any]:
    manager = _manager()
    try:
        return await manager.call_tool(server_id, tool_name, payload.arguments)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown MCP server") from exc
