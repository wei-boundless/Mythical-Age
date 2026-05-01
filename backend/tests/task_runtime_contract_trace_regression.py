from __future__ import annotations

import asyncio

from api.experiments import get_task_runtime_contract_snapshots
from experiments.task_runtime_contract_trace import build_task_runtime_contract_snapshots


def test_task_runtime_contract_snapshots_cover_acceptance_cases() -> None:
    payload = build_task_runtime_contract_snapshots()
    snapshots = {item["scenario_id"]: item for item in payload["snapshots"]}

    assert payload["status"] == "runtime"
    assert payload["snapshot_count"] == 3
    assert set(snapshots) == {
        "search_official_material",
        "local_read_and_summarize",
        "modify_then_review",
    }
    for snapshot in snapshots.values():
        assert snapshot["validation"]["passed"] is True
        assert snapshot["status"] == "runtime"
        assert snapshot["operation_requirement"]["authority"] == "candidate_only"
        assert snapshot["runtime_executable"] is True


def test_task_runtime_contract_snapshots_preserve_scenario_boundaries() -> None:
    payload = build_task_runtime_contract_snapshots()
    snapshots = {item["scenario_id"]: item for item in payload["snapshots"]}

    search_operations = _operations(snapshots["search_official_material"])
    local_operations = _operations(snapshots["local_read_and_summarize"])
    modify_operations = _operations(snapshots["modify_then_review"])

    assert "op.web_search" in search_operations
    assert "op.fetch_url" in search_operations
    assert "op.web_search" not in local_operations
    assert "op.edit_file" in modify_operations


def test_task_runtime_contract_snapshots_api_is_runtime() -> None:
    payload = asyncio.run(get_task_runtime_contract_snapshots())

    assert payload["status"] == "runtime"
    assert payload["invariants"]["runtime_executable"] is True
    assert all(item["validation"]["passed"] for item in payload["snapshots"])


def _operations(snapshot: dict[str, object]) -> set[str]:
    requirement = snapshot["operation_requirement"]
    assert isinstance(requirement, dict)
    return {
        str(item)
        for item in [
            *list(requirement.get("required_operations") or []),
            *list(requirement.get("optional_operations") or []),
        ]
    }
