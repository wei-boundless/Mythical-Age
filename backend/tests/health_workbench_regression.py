from __future__ import annotations

from health_system.workbench import HealthWorkbenchBuilder


def test_health_workbench_projects_user_task_overview(tmp_path):
    payload = HealthWorkbenchBuilder(tmp_path).build_overview()

    assert payload["authority"] == "health_system.workbench"
    assert set(payload["summary"]) >= {
        "inbox_count",
        "open_issue_count",
        "verification_resource_count",
        "evidence_gap_count",
        "failed_run_count",
        "feature_count",
    }
    assert isinstance(payload["inbox_items"], list)
    assert isinstance(payload["features"], list)
    assert isinstance(payload["verification_resources"], list)
    assert payload["source_refs"]["verification_resources"] == "health_system.verification_resources"
    assert payload["source_refs"]["gate_projection"] == "health_system.gate_projection"
    assert payload["recommended_actions"]


def test_health_workbench_inbox_items_have_navigation_contract(tmp_path):
    payload = HealthWorkbenchBuilder(tmp_path).build_overview()

    assert payload["inbox_items"]
    first_item = payload["inbox_items"][0]
    assert first_item["subject_type"] in {"health_issue", "verification_run"}
    assert first_item["subject_id"]
    assert first_item["primary_action"]
    assert first_item["evidence_state"] in {"linked", "missing"}


def test_health_workbench_uses_formal_verification_and_gate_objects(tmp_path):
    payload = HealthWorkbenchBuilder(tmp_path).build_overview()

    assert all(item.get("authority") != "test_system.harness_map" for item in payload.get("features", []))
    assert isinstance(payload["recent_runs"], list)
    if payload["recent_runs"]:
        assert payload["recent_runs"][0]["authority"] == "health_system.verification_run"
