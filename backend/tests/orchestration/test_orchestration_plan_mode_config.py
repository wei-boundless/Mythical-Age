from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import RuntimeConfigManager


def test_orchestration_plan_mode_defaults_to_plan_only(tmp_path: Path) -> None:
    manager = RuntimeConfigManager(tmp_path / "config.json")

    assert manager.get_orchestration_plan_mode() == "plan_only"


def test_orchestration_plan_mode_normalizes_unknown_values(tmp_path: Path) -> None:
    manager = RuntimeConfigManager(tmp_path / "config.json")

    saved = manager.set_orchestration_plan_mode("nonsense")

    assert saved["orchestration_plan_mode"] == "plan_only"
    assert manager.get_orchestration_plan_mode() == "plan_only"


def test_orchestration_plan_mode_accepts_legacy_plan_only_primary(tmp_path: Path) -> None:
    manager = RuntimeConfigManager(tmp_path / "config.json")

    for mode in ["legacy", "plan_only", "primary"]:
        manager.set_orchestration_plan_mode(mode)
        assert manager.get_orchestration_plan_mode() == mode


def test_orchestration_plan_mode_maps_legacy_shadow_to_plan_only(tmp_path: Path) -> None:
    manager = RuntimeConfigManager(tmp_path / "config.json")

    saved = manager.set_orchestration_plan_mode("shadow")

    assert saved["orchestration_plan_mode"] == "plan_only"
    assert manager.get_orchestration_plan_mode() == "plan_only"


def test_runtime_config_partial_updates_preserve_orchestration_mode(tmp_path: Path) -> None:
    manager = RuntimeConfigManager(tmp_path / "config.json")

    manager.set_orchestration_plan_mode("primary")
    saved = manager.set_rag_mode(True)

    assert saved["rag_mode"] is True
    assert saved["orchestration_plan_mode"] == "primary"
    assert manager.get_orchestration_plan_mode() == "primary"


def test_primary_entry_selection_defaults_to_disabled_and_can_toggle(tmp_path: Path) -> None:
    manager = RuntimeConfigManager(tmp_path / "config.json")

    assert manager.get_primary_entry_selection_enabled() is False

    saved = manager.set_primary_entry_selection_enabled(True)

    assert saved["primary_entry_selection_enabled"] is True
    assert manager.get_primary_entry_selection_enabled() is True


def test_primary_entry_takeover_defaults_to_disabled_and_can_toggle(tmp_path: Path) -> None:
    manager = RuntimeConfigManager(tmp_path / "config.json")

    assert manager.get_primary_entry_takeover_enabled() is False

    saved = manager.set_primary_entry_takeover_enabled(True)

    assert saved["primary_entry_takeover_enabled"] is True
    assert manager.get_primary_entry_takeover_enabled() is True
