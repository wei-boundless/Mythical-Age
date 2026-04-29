from __future__ import annotations

import asyncio

from api.experiments import get_task_operation_preview_snapshots
from experiments.task_operation_preview_trace import build_task_operation_preview_snapshots


def test_task_operation_preview_snapshots_cover_acceptance_cases() -> None:
    payload = build_task_operation_preview_snapshots()
    snapshots = {item["scenario_id"]: item for item in payload["snapshots"]}

    assert payload["status"] == "preview_only"
    assert payload["snapshot_count"] == 3
    assert set(snapshots) == {
        "search_official_material",
        "local_read_and_summarize",
        "modify_then_review",
    }
    for snapshot in snapshots.values():
        assert snapshot["validation"]["passed"] is True
        assert snapshot["status"] == "preview_only"
        assert snapshot["operation_requirement"]["authority"] == "candidate_only"
        assert snapshot["resource_policy_preview"]["preview_only"] is True
        assert snapshot["resource_policy_preview"]["adopted"] is False
        assert snapshot["control_kernel_result"]["status"] == "blocked"
        assert snapshot["control_kernel_result"]["directives"] == []
        assert snapshot["control_kernel_result"]["execution_graph"]["nodes"] == []
        assert snapshot["control_kernel_diagnostics"]["runtime_directive_enabled"] is False
        assert snapshot["control_kernel_diagnostics"]["runtime_executable"] is False


def test_task_operation_preview_snapshots_preserve_scenario_boundaries() -> None:
    payload = build_task_operation_preview_snapshots()
    snapshots = {item["scenario_id"]: item for item in payload["snapshots"]}

    search_decisions = _decisions(snapshots["search_official_material"])
    local_decisions = _decisions(snapshots["local_read_and_summarize"])
    modify_decisions = _decisions(snapshots["modify_then_review"])

    assert search_decisions["op.web_search"]["decision"] == "allow"
    assert search_decisions["op.fetch_url"]["decision"] == "allow"
    assert search_decisions["op.write_file"]["decision"] == "deny"
    assert "op.web_search" not in local_decisions
    assert modify_decisions["op.edit_file"]["decision"] == "requires_approval"
    assert "op.edit_file" in snapshots["modify_then_review"]["control_kernel_diagnostics"]["requires_approval_operations"]


def test_task_operation_preview_snapshots_api_is_read_only_preview() -> None:
    payload = asyncio.run(get_task_operation_preview_snapshots())

    assert payload["status"] == "preview_only"
    assert payload["invariants"]["runtime_directive_enabled"] is False
    assert payload["invariants"]["execution_nodes"] == 0
    assert all(item["validation"]["passed"] for item in payload["snapshots"])


def _decisions(snapshot: dict[str, object]) -> dict[str, dict[str, object]]:
    policy = snapshot["resource_policy_preview"]
    assert isinstance(policy, dict)
    return {
        str(item["operation_id"]): item
        for item in policy["decisions"]
        if isinstance(item, dict)
    }
