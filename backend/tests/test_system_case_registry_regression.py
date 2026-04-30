from __future__ import annotations

from pathlib import Path

from test_system.case_registry import case_registry_payload, cases_for_profile, legacy_cases


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


def test_legacy_query_cases_are_registered_but_not_in_curated_profiles() -> None:
    legacy_paths = {case.path for case in legacy_cases()}
    assert "tests/legacy/query_planner_legacy.py" in legacy_paths
    assert "tests/legacy/query_runtime_route_guard_legacy.py" in legacy_paths

    curated_paths = {case.path for case in cases_for_profile("full")}
    assert not legacy_paths & curated_paths
