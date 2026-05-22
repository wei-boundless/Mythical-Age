from __future__ import annotations

from .models import HealthTestScenario


def default_health_test_scenarios() -> tuple[HealthTestScenario, ...]:
    return (
        HealthTestScenario(
            scenario_id="health-scenario:monitoring-projection",
            title="健康监测投影验证",
            category="monitoring_projection",
            owner_system="health_system",
            required_flows=(),
            expected_invariants={
                "runtime_facts": "read_only",
                "health_signals": "derived_by_health_system",
                "issue_conversion": "explicit_user_or_command_action",
            },
            source_test_refs=("backend/tests/health_monitoring_system_regression.py",),
            tags=("monitoring", "runtime_facts", "health"),
        ),
        HealthTestScenario(
            scenario_id="health-scenario:agent-config-rebuild",
            title="健康 Agent 配置重建验证",
            category="agent_config",
            owner_system="health_system",
            required_flows=(),
            expected_invariants={
                "agent_identity": "agent:3_registered",
                "old_runtime_profile": "absent",
                "agent_execution": "fail_closed_until_rebuilt",
            },
            source_test_refs=("backend/tests/health_management_control_plane_regression.py",),
            tags=("agent", "config", "fail_closed"),
        ),
    )
