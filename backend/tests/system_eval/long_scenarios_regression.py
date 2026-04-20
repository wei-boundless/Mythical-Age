from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tests.system_eval.long_scenarios import SCENARIO_SETS, SCENARIOS, scenario_map


def test_long_scenarios_have_unique_ids_and_turns() -> None:
    ids = [scenario.id for scenario in SCENARIOS]
    assert ids
    assert len(ids) == len(set(ids))
    assert all(scenario.turns for scenario in SCENARIOS)


def test_long_scenarios_core_assets_exist() -> None:
    root = BACKEND_DIR
    required_paths = [
        "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
        "knowledge/E-commerce Data/inventory.xlsx",
        "knowledge/E-commerce Data/employees.xlsx",
    ]
    for relative_path in required_paths:
        assert (root / relative_path).exists(), relative_path


def test_long_scenario_sets_point_to_known_ids() -> None:
    scenarios = scenario_map()
    for scenario_ids in SCENARIO_SETS.values():
        for scenario_id in scenario_ids:
            assert scenario_id in scenarios
