from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import RuntimeConfigManager


def test_orchestration_plan_mode_defaults_to_shadow(tmp_path: Path) -> None:
    manager = RuntimeConfigManager(tmp_path / "config.json")

    assert manager.get_orchestration_plan_mode() == "shadow"


def test_orchestration_plan_mode_normalizes_unknown_values(tmp_path: Path) -> None:
    manager = RuntimeConfigManager(tmp_path / "config.json")

    saved = manager.set_orchestration_plan_mode("nonsense")

    assert saved["orchestration_plan_mode"] == "shadow"
    assert manager.get_orchestration_plan_mode() == "shadow"


def test_orchestration_plan_mode_accepts_legacy_shadow_primary(tmp_path: Path) -> None:
    manager = RuntimeConfigManager(tmp_path / "config.json")

    for mode in ["legacy", "shadow", "primary"]:
        manager.set_orchestration_plan_mode(mode)
        assert manager.get_orchestration_plan_mode() == mode


def test_runtime_config_partial_updates_preserve_orchestration_mode(tmp_path: Path) -> None:
    manager = RuntimeConfigManager(tmp_path / "config.json")

    manager.set_orchestration_plan_mode("primary")
    saved = manager.set_rag_mode(True)

    assert saved["rag_mode"] is True
    assert saved["orchestration_plan_mode"] == "primary"
    assert manager.get_orchestration_plan_mode() == "primary"
