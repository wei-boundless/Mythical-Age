from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capability_system.validation import validate_capability_catalog
from capability_system import build_default_operation_registry, build_mcp_catalog


def test_mcps_are_registered_as_local_capability_endpoints() -> None:
    registry = build_default_operation_registry()
    mcps = build_mcp_catalog(registry)
    by_route = {mcp["route"]: mcp for mcp in mcps}

    assert set(by_route) == {"retrieval", "pdf", "structured_data"}
    assert by_route["retrieval"]["operation_id"] == "op.mcp_retrieval"
    assert by_route["pdf"]["operation_id"] == "op.mcp_pdf"
    assert by_route["structured_data"]["operation_id"] == "op.mcp_structured_data"
    assert all(mcp["server_name"] == "local-capability-endpoints" for mcp in mcps)
    assert all(mcp["endpoint_protocol"] == "mcp-compatible.v1" for mcp in mcps)
    assert all(mcp["model_visibility"] == "not_direct_model_tool" for mcp in mcps)


def test_mcp_catalog_validates_against_operation_registry() -> None:
    registry = build_default_operation_registry()
    mcps = build_mcp_catalog(registry)
    operations = [operation.to_dict() for operation in registry.list_operations()]

    issues = validate_capability_catalog(
        skills=[],
        tools=[],
        agent_bindings={},
        mcps=mcps,
        operations=operations,
    )

    assert not [issue for issue in issues if issue.code.startswith("mcp_")]


