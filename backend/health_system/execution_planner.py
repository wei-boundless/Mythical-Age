from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .agent_config import (
    HEALTH_AGENT_CONFIG_BLOCK_REASON,
    HEALTH_AGENT_ID,
    HEALTH_SESSION_ID,
    health_agent_unavailable_diagnostics,
)
from .models import HealthIssue


@dataclass(frozen=True, slots=True)
class HealthAgentExecutionPlan:
    issue_id: str
    health_action: str
    task_id: str
    flow_id: str
    binding_id: str
    agent_id: str
    agent_profile_id: str
    workflow_id: str
    runtime_lane: str
    resource_policy_ref: str
    task_contract_ref: str
    task_execution_assembly: dict[str, Any]
    task_body_orchestration: dict[str, Any]
    agent_runtime_spec: dict[str, Any]
    task_contract: dict[str, Any] = field(default_factory=dict)
    operation_requirement: dict[str, Any] = field(default_factory=dict)
    flow: dict[str, Any] = field(default_factory=dict)
    binding: dict[str, Any] = field(default_factory=dict)
    blocked_reasons: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "health_system.agent_execution_plan"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blocked_reasons"] = list(self.blocked_reasons)
        return payload


def build_health_agent_execution_plan(
    base_dir: Path,
    *,
    issue: HealthIssue,
    health_action: str = "issue_triage",
    session_id: str = HEALTH_SESSION_ID,
    source: str = "health_system.execution_plan",
) -> HealthAgentExecutionPlan:
    del base_dir, session_id, source
    health_action = str(health_action or "issue_triage").strip() or "issue_triage"
    return HealthAgentExecutionPlan(
        issue_id=issue.issue_id,
        health_action=health_action,
        task_id="",
        flow_id="",
        binding_id="",
        agent_id=HEALTH_AGENT_ID,
        agent_profile_id="",
        workflow_id="",
        runtime_lane="",
        resource_policy_ref="",
        task_contract_ref="",
        task_execution_assembly={},
        task_body_orchestration={},
        agent_runtime_spec={},
        task_contract={},
        operation_requirement={},
        flow={},
        binding={},
        blocked_reasons=(HEALTH_AGENT_CONFIG_BLOCK_REASON,),
        diagnostics=health_agent_unavailable_diagnostics(health_action=health_action),
    )


def build_health_agent_run_preview(plan: HealthAgentExecutionPlan, *, issue: HealthIssue) -> dict[str, Any]:
    blocked = list(plan.blocked_reasons)
    return {
        "authority": "health_system.agent_run_preview",
        "status": "blocked" if blocked else "ready",
        "issue": issue.to_dict(),
        "flow": dict(plan.flow),
        "binding": dict(plan.binding),
        "task_execution_assembly": dict(plan.task_execution_assembly),
        "task_body_orchestration": dict(plan.task_body_orchestration),
        "agent_runtime_spec": dict(plan.agent_runtime_spec),
        "blocked_reasons": blocked,
        "reason": blocked[0] if blocked else "",
        "runtime_directive_lane": {
            "lane_id": f"lane:{plan.runtime_lane}:{issue.issue_id}",
            "lane_type": plan.runtime_lane,
            "agent_id": plan.agent_id,
            "agent_profile_id": plan.agent_profile_id,
            "task_id": plan.task_id,
            "task_execution_assembly_ref": str(plan.task_execution_assembly.get("assembly_id") or ""),
            "task_body_orchestration_ref": str(plan.task_body_orchestration.get("orchestration_id") or ""),
            "runtime_spec_ref": str(plan.agent_runtime_spec.get("runtime_spec_id") or ""),
            "memory_scope": str(dict(plan.binding).get("memory_scope") or ""),
            "output_contract_id": str(plan.agent_runtime_spec.get("output_contract_ref") or dict(plan.binding).get("output_contract_id") or ""),
        },
        "diagnostics": {
            **dict(plan.diagnostics),
            "plan_authority": plan.authority,
        },
    }



