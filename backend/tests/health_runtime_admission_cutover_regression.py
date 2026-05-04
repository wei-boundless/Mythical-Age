from __future__ import annotations

from health_system.models import HealthManagementCommand
from health_system.runtime_admission import admit_health_command
from health_system import HealthRegistry


def test_health_runtime_admission_consumes_formal_orchestration_objects(tmp_path) -> None:
    registry = HealthRegistry(tmp_path)
    issue = registry.create_issue(
        {
            "title": "运行准入对象切换验证",
            "owner_system": "health_system",
            "severity": "medium",
            "runtime_trace_refs": ["runtime-loop:test"],
        }
    )

    admission = admit_health_command(
        tmp_path,
        HealthManagementCommand(
            command_id="health-command:admission-cutover",
            command_type="analyze_trace",
            initiator_type="user",
            initiator_ref="",
            requested_by="",
            source="regression",
            conversation_session_ref="health-system",
            target_scope="health_issue",
            target_ref=issue.issue_id,
            task_mode="issue_triage",
            payload={"requested_operations": ["op.model_response"]},
        ),
    )

    assert admission.agent_id == "agent:3"
    assert admission.task_execution_assembly_ref.startswith("taskasm:")
    assert admission.task_body_orchestration_ref.startswith("orchestration:")
    assert admission.runtime_spec_ref.startswith("rtspec:")
    assert admission.diagnostics["task_execution_assembly"]["authority"] == "task_system.task_execution_assembly"
    assert admission.diagnostics["task_body_orchestration"]["authority"] == "orchestration.task_body_orchestration"
    assert admission.diagnostics["agent_runtime_spec"]["authority"] == "orchestration.agent_runtime_spec"
