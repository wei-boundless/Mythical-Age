from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system import UnitDescriptor, build_base_unit_catalog


def test_base_unit_catalog_keeps_modular_units_without_decision_authority() -> None:
    catalog = build_base_unit_catalog()

    assert catalog.get("mcp.pdf") is not None
    assert catalog.get("mcp.retrieval") is not None
    assert catalog.get("memory.facade") is not None
    assert all(item.decision_authority is False for item in catalog.units.values())


def test_unit_descriptor_rejects_private_decision_authority() -> None:
    try:
        UnitDescriptor(
            unit_id="bad.mcp",
            unit_type="mcp",
            owner_module="backend.query.bad_mcp",
            decision_authority=True,
        )
    except ValueError as exc:
        assert "decision authority" in str(exc)
    else:
        raise AssertionError("unit descriptor with decision authority should be rejected")


