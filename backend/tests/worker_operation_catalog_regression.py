from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capability_system.validation import validate_capability_catalog
from capability_system import build_default_operation_registry, build_worker_catalog


def test_workers_are_registered_as_local_mcp_operation_endpoints() -> None:
    registry = build_default_operation_registry()
    workers = build_worker_catalog(registry)
    by_route = {worker["route"]: worker for worker in workers}

    assert set(by_route) == {"retrieval", "pdf", "structured_data"}
    assert by_route["retrieval"]["operation_id"] == "op.worker_retrieval"
    assert by_route["pdf"]["operation_id"] == "op.worker_pdf"
    assert by_route["structured_data"]["operation_id"] == "op.worker_structured_data"
    assert all(worker["server_name"] == "local-workers" for worker in workers)
    assert all(worker["endpoint_protocol"] == "mcp-compatible.v1" for worker in workers)
    assert all(worker["model_visibility"] == "not_direct_model_tool" for worker in workers)


def test_worker_catalog_validates_against_operation_registry() -> None:
    registry = build_default_operation_registry()
    workers = build_worker_catalog(registry)
    operations = [operation.to_dict() for operation in registry.list_operations()]

    issues = validate_capability_catalog(
        skills=[],
        tools=[],
        agent_bindings={},
        workers=workers,
        operations=operations,
    )

    assert not [issue for issue in issues if issue.code.startswith("worker_")]
