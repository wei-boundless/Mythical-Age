from __future__ import annotations

from pathlib import Path

from capability_system.mcp.client import ExternalMCPConfigStore
from capability_system.mcp.client.models import ExternalMCPServerConfig
from capability_system.mcp.management_service import MCPManagementService


def _clear(backend_dir: Path, server_id: str) -> None:
    try:
        ExternalMCPConfigStore(backend_dir).delete_server(server_id)
    except ValueError:
        pass


def test_mcp_management_catalog_unifies_local_and_external_without_inspecting_external() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    server_id = "http_demo"
    _clear(backend_dir, server_id)
    store = ExternalMCPConfigStore(backend_dir)
    try:
        store.upsert_server(
            ExternalMCPServerConfig(
                server_id=server_id,
                title="HTTP Demo",
                description="Unsupported transport should still appear in the unified management plane.",
                transport="streamable_http",
                enabled=True,
                url="http://127.0.0.1:65535/mcp",
            )
        )

        catalog = MCPManagementService(backend_dir).build_catalog()
        local_servers = [item for item in catalog["servers"] if item["provider_kind"] == "local"]
        external = next(item for item in catalog["servers"] if item["server_id"] == server_id)

        assert {item["server_id"] for item in local_servers} == {
            "mcp:knowledge:retrieval",
            "mcp:document:pdf",
            "mcp:data:structured",
        }
        assert external["provider_id"] == "external"
        assert external["status"] == "unsupported"
        assert external["status_reason"] == "transport_not_enabled_yet"
        assert external["tools"] == []
        assert catalog["summary"]["unsupported_count"] >= 1
    finally:
        _clear(backend_dir, server_id)


def test_local_mcp_permission_preview_fails_closed_without_resource_policy() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    service = MCPManagementService(backend_dir, include_external=False)

    preview = service.preview_permission("local", "mcp:document:pdf", "pdf", {"path": "docs/demo.pdf"})

    assert preview["authorized"] is False
    assert preview["operation_id"] == "op.mcp_pdf"
    assert preview["gate"]["pipeline_stage"] == "adopted_resource_policy_exists"
