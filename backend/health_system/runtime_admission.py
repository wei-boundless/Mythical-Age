from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from orchestration import AgentRuntimeRegistry
from tasks.flow_registry import TaskFlowRegistry

from .models import HealthManagementCommand


AGENT_EXECUTION_COMMANDS = {"analyze_trace", "draft_case", "verify_fix"}


@dataclass(frozen=True, slots=True)
class HealthCommandRuntimeAdmission:
    command_id: str
    agent_id: str
    agent_profile_id: str
    task_mode: str
    flow_id: str
    binding_id: str
    runtime_lane: str
    resource_policy_ref: str
    admitted: bool
    blocked_reasons: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blocked_reasons"] = list(self.blocked_reasons)
        return payload


def admit_health_command(base_dir: Path, command: HealthManagementCommand) -> HealthCommandRuntimeAdmission:
    """Fail-closed runtime admission for health commands that cross into agent execution."""
    if command.command_type not in AGENT_EXECUTION_COMMANDS:
        return HealthCommandRuntimeAdmission(
            command_id=command.command_id,
            agent_id="",
            agent_profile_id="",
            task_mode=command.task_mode,
            flow_id="",
            binding_id="",
            runtime_lane="",
            resource_policy_ref="",
            admitted=True,
            diagnostics={"reason": "command_does_not_require_agent_runtime"},
        )

    task_mode = command.task_mode or _default_task_mode(command.command_type)
    registry = TaskFlowRegistry(base_dir)
    flow = next((item for item in registry.list_flows() if item.task_mode == task_mode), None)
    if flow is None:
        return HealthCommandRuntimeAdmission(
            command_id=command.command_id,
            agent_id="",
            agent_profile_id="",
            task_mode=task_mode,
            flow_id="",
            binding_id="",
            runtime_lane="",
            resource_policy_ref="",
            admitted=False,
            blocked_reasons=("task_flow_missing",),
            diagnostics={"command_type": command.command_type},
        )

    binding = registry.build_binding_for_flow(flow)
    profile = AgentRuntimeRegistry(base_dir).get_profile(binding.agent_id)
    blocked = list(binding.diagnostics.get("failures") or [])
    diagnostics: dict[str, Any] = {
        "command_type": command.command_type,
        "flow": flow.to_dict(),
        "binding": binding.to_dict(),
    }
    if binding.validation_state != "valid":
        blocked.append("binding_invalid")
    if profile is None:
        blocked.append("runtime_profile_missing")
    else:
        diagnostics["runtime_profile"] = profile.to_dict()
        requested_operations = tuple(
            str(item)
            for item in list(command.payload.get("requested_operations") or ("op.model_response",))
            if str(item)
        )
        for operation_id in requested_operations:
            if operation_id in profile.blocked_operations:
                blocked.append(f"operation_blocked:{operation_id}")
            if operation_id not in profile.allowed_operations:
                blocked.append(f"operation_not_allowed:{operation_id}")
        if binding.runtime_lane not in profile.allowed_runtime_lanes:
            blocked.append("runtime_lane_not_allowed")
        if binding.workflow_id not in profile.allowed_workflow_ids:
            blocked.append("workflow_not_allowed")

    unique_blocked = tuple(dict.fromkeys(item for item in blocked if item))
    return HealthCommandRuntimeAdmission(
        command_id=command.command_id,
        agent_id=binding.agent_id,
        agent_profile_id=binding.agent_profile_id,
        task_mode=task_mode,
        flow_id=flow.flow_id,
        binding_id=binding.binding_id,
        runtime_lane=binding.runtime_lane,
        resource_policy_ref=binding.resource_policy_ref,
        admitted=not unique_blocked,
        blocked_reasons=unique_blocked,
        diagnostics=diagnostics,
    )


def _default_task_mode(command_type: str) -> str:
    if command_type == "draft_case":
        return "case_draft"
    if command_type == "verify_fix":
        return "fix_verification"
    return "issue_triage"
