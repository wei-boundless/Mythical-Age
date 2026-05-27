from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.skill_routes import skill_operation_ids_from_runtime, skill_operation_ids_from_skill


def test_skill_route_mapping_prefers_explicit_required_operations() -> None:
    runtime = {
        "preferred_route": "pdf",
        "requires_operations": ["op.custom_pdf", " op.audit "],
    }

    assert skill_operation_ids_from_runtime(runtime) == ["op.custom_pdf", "op.audit"]


def test_skill_route_mapping_maps_known_routes_without_duplication() -> None:
    assert skill_operation_ids_from_runtime({"preferred_route": "pdf"}) == ["op.mcp_pdf"]
    assert skill_operation_ids_from_runtime({"preferred_route": "rag"}) == ["op.mcp_retrieval"]
    assert skill_operation_ids_from_runtime({"preferred_route": "structured_data"}) == ["op.mcp_structured_data"]


def test_skill_route_mapping_allows_operation_id_routes() -> None:
    assert skill_operation_ids_from_runtime({"preferred_route": "op.custom_operation"}) == ["op.custom_operation"]


def test_skill_route_mapping_unknown_route_is_empty() -> None:
    assert skill_operation_ids_from_runtime({"preferred_route": "unknown-route"}) == []


def test_skill_route_mapping_accepts_full_skill_payload() -> None:
    skill = {
        "runtime": {
            "preferred_route": "data",
            "requires_operations": [],
        }
    }

    assert skill_operation_ids_from_skill(skill) == ["op.mcp_structured_data"]


