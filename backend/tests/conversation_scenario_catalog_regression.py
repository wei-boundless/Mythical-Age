from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from conversation_scenario_catalog import REQUIRED_COVERAGE, SCENARIOS, coverage_index, scenario_ids


def test_conversation_scenario_ids_are_unique() -> None:
    ids = scenario_ids()
    assert ids
    assert len(ids) == len(set(ids))


def test_conversation_scenarios_cover_required_capabilities() -> None:
    covered = set(coverage_index())
    assert REQUIRED_COVERAGE.issubset(covered)


def test_conversation_scenarios_include_long_acceptance_memory_and_stress_tracks() -> None:
    by_id = {scenario.id: scenario for scenario in SCENARIOS}

    assert "full-workbench-journey" in by_id
    assert len(by_id["full-workbench-journey"].turns) >= 10

    assert "durable-memory-write-and-semantic-recall" in by_id
    assert "durable_memory" in by_id["durable-memory-write-and-semantic-recall"].coverage

    stress_scenarios = [scenario for scenario in SCENARIOS if scenario.execution_mode == "stress"]
    assert len(stress_scenarios) >= 2
    assert any(
        scenario.stress_profile is not None and scenario.stress_profile.parallel_sessions > 1
        for scenario in stress_scenarios
    )
    assert any(
        scenario.stress_profile is not None and scenario.stress_profile.bulky_turns > 0
        for scenario in stress_scenarios
    )


def test_conversation_scenarios_link_to_existing_regressions() -> None:
    for scenario in SCENARIOS:
        assert scenario.related_regressions, f"{scenario.id} should link back to executable regressions"
        assert scenario.expected_artifacts, f"{scenario.id} should declare expected artifacts"
        assert scenario.assertions, f"{scenario.id} should declare assertions"
        assert scenario.failure_modes, f"{scenario.id} should declare likely failure modes"
        assert len(scenario.turns) >= 3, f"{scenario.id} should be a real conversation scenario"
