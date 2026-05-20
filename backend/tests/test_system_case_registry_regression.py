from __future__ import annotations

from pathlib import Path

from health_system.maintenance.test_system.case_registry import case_registry_payload, cases_for_profile
from health_system.maintenance.test_system.harness_map import build_harness_map
from health_system.maintenance.test_system.harness_records import HarnessRecordBook, ManagedTestCase
from health_system.maintenance.test_system.service import TestSystemService


BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_case_registry_has_required_layers_and_profiles() -> None:
    payload = case_registry_payload()

    assert payload["layers"] == ("chain", "functional", "system", "scenario")
    assert set(payload["profiles"]) >= {"chain", "functional", "system", "scenario", "stable", "full"}
    assert isinstance(payload["candidate_cases"], list)
    assert payload["profiles"]["chain"]["case_count"] > 0
    assert payload["profiles"]["functional"]["case_count"] >= payload["profiles"]["chain"]["case_count"]
    assert payload["profiles"]["full"]["case_count"] >= payload["profiles"]["system"]["case_count"]


def test_active_registered_test_files_exist() -> None:
    for profile in ("chain", "functional", "system", "scenario"):
        for case in cases_for_profile(profile):
            assert (BACKEND_DIR / case.path).exists(), f"missing registered test file: {case.path}"


def test_harness_map_makes_cases_traceable_to_features_and_pass_criteria() -> None:
    payload = build_harness_map(
        records=HarnessRecordBook(),
        agent_report={"summary": {}, "findings": []},
    )

    assert payload["authority"] == "test_system.harness_map"
    assert payload["summary"]["feature_count"] > 0
    assert payload["features"]
    assert payload["cases"]
    assert all(case["feature_id"] for case in payload["cases"])
    assert all(case["path"] for case in payload["cases"])
    assert all(case["problem_statement"] for case in payload["cases"])
    assert all(case["pass_criteria"] for case in payload["cases"])
    assert payload["link_contract"]["case_to_pass"]


def test_harness_map_includes_front_managed_cases() -> None:
    payload = build_harness_map(
        records=HarnessRecordBook(
            managed_cases=(
                ManagedTestCase(
                    case_id="managed.semantic.demo",
                    title="语义回答候选用例",
                    owner_system="test_system",
                    problem_statement="回答没有覆盖用户约束。",
                    pass_criteria=("回答覆盖用户约束。",),
                    profiles=("functional",),
                ),
            )
        ),
        agent_report={"summary": {}, "findings": []},
    )

    managed = next(case for case in payload["cases"] if case["case_id"] == "managed.semantic.demo")
    assert managed["reason"] == "front_managed_case"
    assert managed["problem_statement"] == "回答没有覆盖用户约束。"
    assert payload["summary"]["managed_case_count"] == 1


def test_harness_map_keeps_managed_long_scenario_turns() -> None:
    payload = build_harness_map(
        records=HarnessRecordBook(
            managed_cases=(
                ManagedTestCase(
                    case_id="managed.long.demo",
                    title="多轮恢复情景",
                    layer="scenario",
                    profiles=("long_core",),
                    scenario_turns=(
                        {
                            "turn_id": "turn-1",
                            "user": "先建立任务目标。",
                            "expected": "系统记住目标。",
                            "assistant_hint": "main",
                        },
                    ),
                ),
            )
        ),
        agent_report={"summary": {}, "findings": []},
    )

    managed = next(case for case in payload["cases"] if case["case_id"] == "managed.long.demo")
    assert managed["scenario_turns"][0]["user"] == "先建立任务目标。"
    assert managed["profiles"] == ["long_core"]


def test_test_system_exposes_real_long_scenario_catalog() -> None:
    payload = TestSystemService().long_scenarios()

    assert payload["authority"] == "test_system.long_scenarios"
    assert payload["scenarios"]
    game = next(item for item in payload["scenarios"] if item["scenario_id"] == "task-system-light-web-game-acceptance")
    story = next(item for item in payload["scenarios"] if item["scenario_id"] == "task-system-short-story-coordination-acceptance")
    sandbox = next(item for item in payload["scenarios"] if item["scenario_id"] == "sandbox-file-ops-acceptance")
    marathon = next(item for item in payload["scenarios"] if item["scenario_id"] == "sixty-turn-real-user-marathon")
    assert "task_acceptance" in game["profile_refs"]
    assert "task_acceptance" in story["profile_refs"]
    assert "task_acceptance" in game["scenario_sets"]
    assert "task_acceptance" in story["scenario_sets"]
    assert "sandbox" in sandbox["profile_refs"]
    assert "sandbox" in sandbox["scenario_sets"]
    assert any("sandbox" in turn["content"].lower() for turn in sandbox["turns"])
    assert "marathon" in marathon["profile_refs"]
    assert len(marathon["turns"]) >= 60
