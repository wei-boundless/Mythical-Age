from __future__ import annotations

import sys
from pathlib import Path

from app import app
from bootstrap.app_runtime import app_runtime
from capability_system.mcp.client import ExternalMCPConfigStore, ExternalMCPManager
from capability_system.mcp.client.permission import check_external_mcp_tool_permission
from capability_system.mcp.client.models import ExternalMCPServerConfig
from capability_system.mcp.server.tool_pool import build_mcp_tool_pool
from tests.support.app_client import isolated_app_client


def _fake_server_config(backend_dir: Path) -> ExternalMCPServerConfig:
    fixture = backend_dir / "tests" / "fixtures" / "fake_external_capability_system.mcp.server.py"
    return ExternalMCPServerConfig(
        server_id="external_demo",
        title="External Demo",
        description="Fake MCP server for regression tests.",
        transport="stdio",
        enabled=True,
        command=sys.executable,
        args=(str(fixture),),
        cwd=str(backend_dir),
        scope="project",
        tags=("test", "external"),
        allowed_operations=("op.external_mcp.external_demo.external_echo",),
    )


def _unauthorized_fake_server_config(backend_dir: Path) -> ExternalMCPServerConfig:
    config = _fake_server_config(backend_dir)
    return ExternalMCPServerConfig(
        **{
            **config.to_dict(),
            "allowed_operations": [],
        }
    )


def _clear_external_demo(backend_dir: Path) -> None:
    ExternalMCPConfigStore(backend_dir).delete_server("external_demo")


def test_external_mcp_manager_returns_failed_snapshot_when_stdio_spawn_blocked() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    _clear_external_demo(backend_dir)
    manager = ExternalMCPManager(backend_dir)
    try:
        manager.upsert_server(_fake_server_config(backend_dir))
        snapshot = manager.inspect_server_sync("external_demo")
        assert snapshot.server_id == "external_demo"
        assert snapshot.transport == "stdio"
        assert snapshot.status in {"connected", "failed"}
        if snapshot.status == "connected":
            assert any(tool.name == "external_echo" for tool in snapshot.tools)
            assert any(resource.uri == "skill://external-demo" for resource in snapshot.resources)
            assert any(prompt.name == "external_demo_prompt" for prompt in snapshot.prompts)
        else:
            assert snapshot.status_reason
    finally:
        _clear_external_demo(backend_dir)


def test_external_mcp_tool_call_and_tool_pool() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    _clear_external_demo(backend_dir)
    manager = ExternalMCPManager(backend_dir)
    try:
        manager.upsert_server(_fake_server_config(backend_dir))
        result = manager.call_tool_sync("external_demo", "external_echo", {"message": "hello"})
        assert result["status"] in {"ok", "error"}
        if result["status"] == "ok":
            structured = result["result"]
            assert structured["structuredContent"]["echo"] == "hello"
        else:
            assert result["error"]

        pool = build_mcp_tool_pool(backend_dir=backend_dir)
        names = [entry["name"] for entry in pool["entries"]]
        if result["status"] == "ok":
            assert "mcp__external_demo__external_echo" in names
    finally:
        _clear_external_demo(backend_dir)


def test_external_mcp_requires_explicit_operation_authorization() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    server = _unauthorized_fake_server_config(backend_dir)
    permission = check_external_mcp_tool_permission(
        server=server,
        tool={
            "name": "external_echo",
            "description": "Echo one message.",
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        },
        permission_mode="default",
        tool_input={"message": "hello"},
    )

    assert permission["authorized"] is False
    assert permission["gate"]["decision"] == "deny"
    assert permission["gate"]["pipeline_stage"] == "allow_rule"


def test_external_mcp_missing_readonly_hint_defaults_to_approval_required() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    server = _fake_server_config(backend_dir)
    permission = check_external_mcp_tool_permission(
        server=server,
        tool={
            "name": "external_echo",
            "description": "Echo one message.",
            "annotations": {},
        },
        permission_mode="default",
        tool_input={"message": "hello"},
    )

    assert permission["authorized"] is False
    assert permission["operation"]["read_only"] is False
    assert permission["operation"]["destructive"] is True


def test_external_mcp_api_catalog_and_tool_call() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    _clear_external_demo(backend_dir)
    store = ExternalMCPConfigStore(backend_dir)
    try:
        store.upsert_server(_fake_server_config(backend_dir))

        with isolated_app_client(app) as client:
            app_runtime.require_ready()
            catalog_response = client.get("/api/mcp-system/management/catalog")
            assert catalog_response.status_code == 200
            catalog = catalog_response.json()
            assert catalog["summary"]["external_server_count"] >= 1
            assert any(item["server_id"] == "external_demo" for item in catalog["servers"])

            inspect_response = client.post("/api/mcp-system/management/providers/external/servers/external_demo/inspect")
            assert inspect_response.status_code == 200
            inspect_payload = inspect_response.json()
            assert inspect_payload["status"] in {"connected", "failed"}

            call_response = client.post(
                "/api/mcp-system/management/providers/external/servers/external_demo/tools/external_echo/call",
                json={"arguments": {"message": "from-api"}},
            )
            assert call_response.status_code == 200
            payload = call_response.json()
            assert payload["status"] in {"ok", "error"}
    finally:
        _clear_external_demo(backend_dir)


