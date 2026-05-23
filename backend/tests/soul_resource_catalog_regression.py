from __future__ import annotations

from pathlib import Path

from soul.facade import SoulFacade


def test_resource_catalog_builds_formal_soul_resources() -> None:
    catalog = SoulFacade(Path("backend")).build_resource_catalog()

    assert catalog["authority"] == "soul.resource_catalog"
    assert len(catalog["cards"]) >= 5
    assert {item["soul_id"] for item in catalog["cards"]} >= {"goumang", "hebo", "siyue", "zhurong", "xuannv"}
    assert catalog["work_prompts"]
    assert catalog["system_contracts"]
    assert catalog["common_contracts"]
    assert catalog["system_contracts"][0]["editable"] is False
    assert catalog["system_contracts"][0]["contract_layer"] == "protected_system"
    assert catalog["common_contracts"][0]["editable"] is True
    assert catalog["common_contracts"][0]["contract_layer"] == "user_common"
    assert "## 通用禁止条例" not in catalog["common_contracts"][0]["content"]
    assert catalog["manifestations"]
    assert {item["mode"] for item in catalog["modes"]} == {"role_mode", "standard_mode", "work_mode"}


def test_legacy_soul_catalog_exposes_resource_catalog_without_dropping_old_fields() -> None:
    catalog = SoulFacade(Path("backend")).build_catalog()

    assert "seeds" in catalog
    assert "static_files" in catalog
    assert "soul_profiles" in catalog
    assert "resource_catalog" in catalog
    assert catalog["resource_catalog"]["authority"] == "soul.resource_catalog"
    assert catalog["management"]["resource_catalog_enabled"] is True
    assert "system_contracts" in catalog["management"]["planes"]
    assert "work_prompts" in catalog["management"]["planes"]
