from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .execution_planner import build_health_agent_execution_plan
from .models import HealthManagementCommand
from .registry_records import get_health_issue_by_id


AGENT_EXECUTION_COMMANDS = {"analyze_trace", "draft_case", "verify_fix"}


@dataclass(frozen=True, slots=True)
class HealthCommandRuntimeAdmission:
    command_id: str
    agent_id: str
    agent_profile_id: str
    health_action: str
    flow_id: str
    binding_id: str
    runtime_lane: str
    resource_policy_ref: str
    status: str
    task_execution_assembly_ref: str = ""
    task_body_orchestration_ref: str = ""
    runtime_spec_ref: str = ""
    blocked_reasons: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def admitted(self) -> bool:
        return self.status == "accepted"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blocked_reasons"] = list(self.blocked_reasons)
        payload["admitted"] = self.admitted
        return payload


def admit_health_command(base_dir: Path, command: HealthManagementCommand) -> HealthCommandRuntimeAdmission:
    """Fail-closed runtime admission for health commands that cross into agent execution."""
    if command.command_type not in AGENT_EXECUTION_COMMANDS:
        return HealthCommandRuntimeAdmission(
            command_id=command.command_id,
            agent_id="",
            agent_profile_id="",
            health_action=command.health_action,
            flow_id="",
            binding_id="",
            runtime_lane="",
            resource_policy_ref="",
            status="accepted",
            diagnostics={"reason": "command_does_not_require_agent_runtime"},
        )

    health_action = command.health_action or _default_health_action(command.command_type)
    issue_id = str(command.target_ref or command.payload.get("issue_id") or "").strip()
    issue = get_health_issue_by_id(base_dir, issue_id)
    if issue is None:
        return HealthCommandRuntimeAdmission(
            command_id=command.command_id,
            agent_id="",
            agent_profile_id="",
            health_action=health_action,
            flow_id="",
            binding_id="",
            runtime_lane="",
            resource_policy_ref="",
            task_execution_assembly_ref="",
            task_body_orchestration_ref="",
            runtime_spec_ref="",
            status="blocked",
            blocked_reasons=("health_issue_missing",),
            diagnostics={"command_type": command.command_type, "issue_id": issue_id},
        )

    plan = build_health_agent_execution_plan(
        base_dir,
        issue=issue,
        health_action=health_action,
        source="health_system.runtime_admission",
    )
    blocked = list(plan.blocked_reasons)
    diagnostics: dict[str, Any] = {
        "command_type": command.command_type,
        "flow": dict(plan.flow),
        "binding": dict(plan.binding),
        "task_execution_assembly": dict(plan.task_execution_assembly),
        "task_body_orchestration": dict(plan.task_body_orchestration),
        "agent_runtime_spec": dict(plan.agent_runtime_spec),
    }
    runtime_spec = dict(plan.agent_runtime_spec)
    if not runtime_spec:
        blocked.append("runtime_profile_missing")
    else:
        agent_id = str(runtime_spec.get("agent_id") or plan.agent_id).strip()
        diagnostics["runtime_spec_check_mode"] = "agent_runtime_spec_declared"
        diagnostics["workflow_id"] = plan.workflow_id
        requested_operations = tuple(
            str(item)
            for item in list(command.payload.get("requested_operations") or ("op.model_response",))
            if str(item)
        )
        profile = dict(plan.diagnostics.get("runtime_profile") or {})
        allowed_operations = tuple(str(item) for item in list(profile.get("allowed_operations") or []))
        blocked_operations = tuple(str(item) for item in list(profile.get("blocked_operations") or []))
        for operation_id in requested_operations:
            if operation_id in blocked_operations:
                blocked.append(f"operation_blocked:{operation_id}")
            if operation_id not in allowed_operations:
                blocked.append(f"operation_not_allowed:{operation_id}")
        if str(runtime_spec.get("runtime_lane") or "") != plan.runtime_lane:
            blocked.append("runtime_spec_lane_mismatch")
        allowed_runtime_lanes = tuple(str(item) for item in list(profile.get("allowed_runtime_lanes") or []))
        if plan.runtime_lane not in allowed_runtime_lanes:
            blocked.append("runtime_lane_not_allowed")

    unique_blocked = tuple(dict.fromkeys(item for item in blocked if item))
    status = "accepted"
    if unique_blocked:
        if any(item.startswith("operation_blocked:") or item.startswith("operation_not_allowed:") for item in unique_blocked):
            status = "rejected"
        else:
            status = "blocked"
    return HealthCommandRuntimeAdmission(
        command_id=command.command_id,
        agent_id=plan.agent_id,
        agent_profile_id=plan.agent_profile_id,
        health_action=health_action,
        flow_id=plan.flow_id,
        binding_id=plan.binding_id,
        runtime_lane=plan.runtime_lane,
        resource_policy_ref=plan.resource_policy_ref,
        task_execution_assembly_ref=str(plan.task_execution_assembly.get("assembly_id") or ""),
        task_body_orchestration_ref=str(plan.task_body_orchestration.get("orchestration_id") or ""),
        runtime_spec_ref=str(plan.agent_runtime_spec.get("runtime_spec_id") or ""),
        status=status,
        blocked_reasons=unique_blocked,
        diagnostics=diagnostics,
    )


def _default_health_action(command_type: str) -> str:
    if command_type == "draft_case":
        return "case_draft"
    if command_type == "verify_fix":
        return "fix_verification"
    return "issue_triage"
