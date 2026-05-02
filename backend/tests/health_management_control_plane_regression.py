from __future__ import annotations

import asyncio

from health_system import HealthRegistry
from operations import AgentRegistry
from tasks import TaskFlowRegistry


class FakeTestSystemService:
    def start(self, profile: str, scenario_ids: list[str]) -> dict[str, object]:
        return {
            "run_id": "test-run:fake-health",
            "profile": profile,
            "status": "running",
            "output_dir": "storage/test-runs/test-run:fake-health",
            "log_path": "storage/test-runs/test-run:fake-health/run.log",
            "started_at": 1.0,
            "ended_at": 0.0,
            "scenario_ids": scenario_ids,
        }


def test_health_report_issue_command_creates_receipt_report_and_issue(tmp_path) -> None:
    registry = HealthRegistry(tmp_path)

    response = asyncio.run(
        registry.submit_command(
            {
                "command_id": "health-command:test-report-issue",
                "command_type": "report_issue",
                "initiator_type": "user",
                "source": "regression",
                "payload": {
                    "title": "回归测试健康问题",
                    "owner_system": "health_system",
                    "severity": "medium",
                    "runtime_trace_refs": ["runtime-loop:test"],
                },
            }
        )
    )

    assert response["receipt"]["accepted"] is True
    assert response["receipt"]["health_issue_ref"]
    assert response["receipt"]["report_ref"]
    assert registry.get_command("health-command:test-report-issue") is not None
    assert registry.get_report(response["receipt"]["report_ref"]) is not None


def test_health_command_admission_rejects_blocked_operation(tmp_path) -> None:
    registry = HealthRegistry(tmp_path)

    response = asyncio.run(
        registry.submit_command(
            {
                "command_id": "health-command:test-blocked-operation",
                "command_type": "analyze_trace",
                "initiator_type": "agent",
                "initiator_ref": "agent:health:maintainer",
                "target_scope": "health_issue",
                "target_ref": "health:issue:sample-task-system-chain",
                "task_mode": "issue_triage",
                "payload": {"requested_operations": ["op.write_file"]},
            }
        )
    )

    assert response["receipt"]["accepted"] is False
    assert response["receipt"]["status"] == "rejected"
    assert "operation_blocked:op.write_file" in response["receipt"]["blocked_reasons"]


def test_task_system_exposes_generic_agent_task_connection_profile(tmp_path) -> None:
    overview = TaskFlowRegistry(tmp_path).build_agent_task_connection_overview(task_family="health")
    profiles = overview["profiles"]
    health_profile = next(item for item in profiles if item["agent_id"] == "agent:health:maintainer")

    assert overview["authority"] == "task_system.agent_task_connections"
    assert health_profile["owner_system"] == "health_system"
    assert "flow.health.issue_triage" in health_profile["flow_refs"]
    assert "xuannv__health_maintainer" in health_profile["projection_template_refs"]
    assert health_profile["validation_state"] == "valid"


def test_launch_health_test_command_records_health_test_run(tmp_path) -> None:
    registry = HealthRegistry(tmp_path)

    response = asyncio.run(
        registry.submit_command(
            {
                "command_id": "health-command:test-launch-health-test",
                "command_type": "launch_health_test",
                "initiator_type": "user",
                "payload": {
                    "profile": "functional",
                    "scenario_refs": ["health-scenario:static-contract"],
                },
            },
            test_system_service=FakeTestSystemService(),
        )
    )

    assert response["receipt"]["accepted"] is True
    assert response["receipt"]["test_run_ref"] == "test-run:fake-health"
    assert registry.list_health_test_runs()[0].scenario_refs == ("health-scenario:static-contract",)


def test_default_health_management_agent_configuration_is_bound_and_guarded(tmp_path) -> None:
    agent_registry = AgentRegistry(tmp_path)
    profile = agent_registry.get_capability_profile("agent:health:maintainer")
    connection = next(
        item
        for item in TaskFlowRegistry(tmp_path).list_agent_task_connection_profiles()
        if item.agent_id == "agent:health:maintainer"
    )

    assert profile is not None
    assert "op.write_file" in profile.blocked_operations
    assert "issue_triage" in connection.available_task_modes
    assert connection.default_runtime_lane_hint == "health_issue_read"
