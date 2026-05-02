from __future__ import annotations

from .models import HealthTestScenario


def default_health_test_scenarios() -> tuple[HealthTestScenario, ...]:
    return (
        HealthTestScenario(
            scenario_id="health-scenario:static-contract",
            title="静态契约验证",
            category="static_contract",
            owner_system="health_system",
            required_flows=("flow.health.issue_triage", "flow.health.trace_analysis"),
            expected_invariants={
                "binding_validation": "valid",
                "template_validation_matrix": "present",
                "link_permission_matrix": "present",
            },
            source_test_refs=("backend/tests/task_template_registry_regression.py",),
            tags=("contract", "task_system", "health"),
        ),
        HealthTestScenario(
            scenario_id="health-scenario:runtime-happy-path",
            title="健康运行时主路径验证",
            category="runtime_happy_path",
            owner_system="health_system",
            required_flows=("flow.health.issue_triage", "flow.health.fix_verification"),
            expected_invariants={
                "checkpoint": "written",
                "terminal_commit": "recorded",
                "trace_report": "readable",
            },
            source_test_refs=("backend/tests/task_run_state_machine_regression.py",),
            tags=("runtime_loop", "checkpoint", "health"),
        ),
        HealthTestScenario(
            scenario_id="health-scenario:fault-injection",
            title="故障注入与拒绝路径验证",
            category="fault_injection",
            owner_system="health_system",
            required_flows=("flow.health.trace_analysis",),
            expected_invariants={
                "permission_denied": "reported",
                "invalid_binding": "rejected",
                "blocked_operation": "receipt_created",
            },
            source_test_refs=("backend/tests/tool_authorization_regression.py",),
            tags=("fault", "permission", "admission"),
        ),
        HealthTestScenario(
            scenario_id="health-scenario:recovery-replay",
            title="恢复重放验证",
            category="recovery_replay",
            owner_system="health_system",
            required_flows=("flow.health.issue_triage",),
            expected_invariants={
                "idempotency_token": "honored",
                "replay_denied": "reported",
                "ledger_consistency": "checked",
            },
            source_test_refs=("backend/tests/runtime_recovery_idempotency_regression.py",),
            tags=("recovery", "replay", "ledger"),
        ),
        HealthTestScenario(
            scenario_id="health-scenario:cutover-readiness",
            title="切流准备度验证",
            category="cutover_readiness",
            owner_system="health_system",
            required_flows=("flow.health.issue_triage", "flow.health.fix_verification"),
            expected_invariants={
                "required_scenarios": "passed_or_reported",
                "blockers": "listed",
                "rollback_plan_ref": "present",
            },
            source_test_refs=("backend/tests/run_regression_gate.py",),
            tags=("readiness", "cutover", "report"),
        ),
        HealthTestScenario(
            scenario_id="health-scenario:agent-management",
            title="健康管理 Agent 管理链路验证",
            category="health_agent_management",
            owner_system="health_system",
            required_flows=("flow.health.issue_triage", "flow.health.trace_analysis"),
            expected_invariants={
                "conversation_session": "created",
                "delegated_command": "receipted",
                "dock_not_primary_entry": "documented",
            },
            source_test_refs=("frontend/src/components/health/HealthAgentDock.tsx",),
            tags=("agent", "conversation", "control_plane"),
        ),
    )
