from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tests.system_eval.long_scenarios import SCENARIO_SETS, SCENARIOS, scenario_map
from tests.system_eval.long_runner import (
    _completion_failure_check,
    _completion_from_done_payload,
    _turn_is_professional_task,
)


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
        "tests/fixtures/sandbox_file_ops/source_brief.md",
        "tests/fixtures/professional_task_suite/buggy_counter.py",
        "tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json",
        "tests/fixtures/professional_task_suite/ops_incident_snapshot.json",
        "tests/fixtures/professional_task_suite/node_status_filter_contract.json",
    ]
    for relative_path in required_paths:
        assert (root / relative_path).exists(), relative_path


def test_long_scenario_sets_point_to_known_ids() -> None:
    scenarios = scenario_map()
    for scenario_ids in SCENARIO_SETS.values():
        for scenario_id in scenario_ids:
            assert scenario_id in scenarios


def test_long_scenarios_are_rebuilt_around_batches_and_a_sixty_turn_marathon() -> None:
    by_id = scenario_map()

    assert "research-brief-and-document-resume" in by_id
    assert "commerce-ops-data-live-switch" in by_id
    assert "memory-preference-and-cross-session-recall" in by_id
    assert "compound-task-decomposition-and-focus-return" in by_id
    assert "task-system-light-web-game-acceptance" in by_id
    assert "task-system-short-story-coordination-acceptance" in by_id
    assert "sandbox-file-ops-acceptance" in by_id
    assert "professional-code-fix-acceptance" in by_id
    assert "professional-test-report-triage" in by_id
    assert "professional-doc-data-analysis" in by_id
    assert "professional-feature-slice-acceptance" in by_id
    assert "professional-ops-troubleshooting" in by_id
    assert "professional-deep-code-execution" in by_id
    assert "professional-iterative-game-delivery" in by_id
    assert "permission-boundary-and-safe-fallback" in by_id
    assert "multi-session-workbench-isolation" in by_id
    assert "sixty-turn-real-user-marathon" in by_id

    assert len(by_id["sixty-turn-real-user-marathon"].turns) >= 60
    assert "mega" in SCENARIO_SETS
    assert SCENARIO_SETS["mega"] == ("sixty-turn-real-user-marathon",)
    assert "batches" in SCENARIO_SETS
    assert "sandbox-file-ops-acceptance" in SCENARIO_SETS["batches"]
    assert SCENARIO_SETS["sandbox"] == ("sandbox-file-ops-acceptance",)
    assert SCENARIO_SETS["professional_tasks"] == (
        "professional-code-fix-acceptance",
        "professional-test-report-triage",
        "professional-doc-data-analysis",
        "professional-feature-slice-acceptance",
        "professional-ops-troubleshooting",
        "professional-game-multifile-delivery",
        "professional-iterative-game-delivery",
    )
    assert SCENARIO_SETS["professional_deep"] == ("professional-deep-code-execution",)
    assert "task_acceptance" in SCENARIO_SETS
    assert SCENARIO_SETS["task_acceptance"] == (
        "task-system-light-web-game-acceptance",
        "professional-game-multifile-delivery",
        "task-system-short-story-coordination-acceptance",
    )


def test_long_scenarios_collectively_cover_runtime_capabilities() -> None:
    covered: set[str] = set()
    for scenario in SCENARIOS:
        covered.update(scenario.coverage)

    expected = {
        "chat",
        "rag",
        "pdf_followup",
        "structured_followup",
        "tool_route",
        "topic_switch",
        "session_memory",
        "durable_memory",
        "memory_boundary",
        "permissions",
        "tasks",
        "settings",
        "sse",
        "context_compaction",
        "session_isolation",
        "stress",
        "professional_task",
        "code_fix",
        "test_report",
        "feature_slice",
        "ops",
    }
    assert expected.issubset(covered)


def test_long_runner_uses_run_outcome_as_completion_authority() -> None:
    completion = {
        "status": "partial",
        "completed": False,
        "terminal_reason": "partial_contract_failed",
        "missing_deliverables": ["verification_evidence"],
    }
    done_payload = {"completion": completion, "task_result": {"completion": {"completed": True}}}

    assert _completion_from_done_payload(done_payload) == completion
    assert "completion.completed=false" in _completion_failure_check(completion)
    assert "verification_evidence" in _completion_failure_check(completion)


def test_long_runner_requires_completion_envelope_for_professional_turn() -> None:
    scenarios = scenario_map()
    turn = scenarios["professional-iterative-game-delivery"].turns[0]

    assert _turn_is_professional_task(turn=turn, inferred={"task_contract": {}}) is True
