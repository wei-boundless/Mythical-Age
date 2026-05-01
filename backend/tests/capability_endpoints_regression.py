from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capabilities.endpoints import build_capability_endpoints
from operations import build_default_operation_registry
from workers import build_worker_catalog


def test_capability_endpoints_only_include_local_workers() -> None:
    workers = build_worker_catalog(build_default_operation_registry())
    endpoints = build_capability_endpoints(workers=workers)

    by_id = {endpoint["endpoint_id"]: endpoint for endpoint in endpoints}
    assert {endpoint["kind"] for endpoint in endpoints} == {"local_worker"}
    assert by_id["endpoint:worker:pdf"]["kind"] == "local_worker"
    assert by_id["endpoint:worker:pdf"]["invocation_mode"] == "orchestrator_only"
    assert by_id["endpoint:worker:pdf"]["model_visibility"] == "not_direct_model_tool"
