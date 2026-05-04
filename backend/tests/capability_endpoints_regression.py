from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capability_system.endpoints import build_capability_endpoints
from capability_system import build_default_operation_registry, build_mcp_catalog


def test_capability_endpoints_only_include_mcp_endpoints() -> None:
    mcps = build_mcp_catalog(build_default_operation_registry())
    endpoints = build_capability_endpoints(mcps=mcps)

    by_id = {endpoint["endpoint_id"]: endpoint for endpoint in endpoints}
    assert {endpoint["kind"] for endpoint in endpoints} == {"mcp_endpoint"}
    assert by_id["endpoint:mcp:pdf"]["kind"] == "mcp_endpoint"
    assert by_id["endpoint:mcp:pdf"]["invocation_mode"] == "orchestrator_only"
    assert by_id["endpoint:mcp:pdf"]["model_visibility"] == "not_direct_model_tool"
