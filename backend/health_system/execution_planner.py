from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from orchestration import AgentRuntimeRegistry, build_orchestration_runtime_bundle
from tasks import TaskFlowRegistry
from tasks.assembly_builder import build_task_execution_assembly_bundle

from .constants import HEALTH_SESSION_ID, health_specific_task_id, normalize_health_agent_id
from .models import HealthIssue


@dataclass(frozen=True, slots=True)
class HealthAgentExecutionPlan:
    issue_id: str
    task_mode: str
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
    task_mode: str = "issue_triage",
    session_id: str = HEALTH_SESSION_ID,
    source: str = "health_system.execution_plan",
) -> HealthAgentExecutionPlan:
    task_mode = str(task_mode or "issue_triage").strip() or "issue_triage"
    task_registry = TaskFlowRegistry(base_dir)
    specific_task_id = health_specific_task_id(task_mode)
    specific_task = task_registry.get_specific_task_record(specific_task_id)
    if specific_task is None:
        raise KeyError(specific_task_id)
    flow = next((item for item in task_registry.list_flows() if item.flow_id == specific_task.default_flow_contract_id), None)
    if flow is None:
        raise KeyError(specific_task.default_flow_contract_id or task_mode)

    binding = task_registry.build_binding_for_flow(flow)
    task_id = f"task.health.{task_mode}:{issue.issue_id}"
    current_turn_context = {
        "authority": "health_system.current_turn_context",
        "selected_task_id": specific_task_id,
        "workflow_id": flow.default_workflow_id,
        "task_workflow_id": flow.default_workflow_id,
        "resolved_bindings": [
            {
                "binding_type": "health_issue",
                "issue_id": issue.issue_id,
                "issue_title": issue.title,
            }
        ],
        "explicit_inputs": {
            "capability_requests": ["health_issue"],
        },
    }
    user_goal = f"处理健康问题：{issue.title or issue.issue_id}"
    task_bundle = build_task_execution_assembly_bundle(
        base_dir=base_dir,
        session_id=session_id,
        user_goal=user_goal,
        task_id=task_id,
        source=source,
        current_turn_context=current_turn_context,
        query_understanding={
            "intent": "health_issue",
            "capability_requests": ["health_issue"],
            "route_hint": "health",
        },
    )
    runtime_profile = AgentRuntimeRegistry(base_dir).get_profile(binding.agent_id)
    orchestration_bundle = build_orchestration_runtime_bundle(
        base_dir=base_dir,
        session_id=session_id,
        task_id=task_id,
        user_goal=user_goal,
        task_assembly_bundle=task_bundle,
        current_turn_context=current_turn_context,
        memory_runtime_view=_memory_runtime_view(issue=issue, task_mode=task_mode),
        context_policy_result=_context_policy_result(binding=binding.to_dict()),
        agent_runtime_profile=runtime_profile,
    )
    task_execution_assembly = dict(task_bundle.get("task_execution_assembly") or {})
    task_body_orchestration = dict(orchestration_bundle.get("task_body_orchestration") or {})
    agent_runtime_spec = dict(orchestration_bundle.get("agent_runtime_spec") or {})

    blocked_reasons = list(binding.diagnostics.get("failures") or [])
    if binding.validation_state != "valid":
        blocked_reasons.append("binding_invalid")
    if normalize_health_agent_id(str(agent_runtime_spec.get("agent_id") or "")) != normalize_health_agent_id(binding.agent_id):
        blocked_reasons.append("runtime_spec_agent_mismatch")
    if str(agent_runtime_spec.get("runtime_lane") or "") != binding.runtime_lane:
        blocked_reasons.append("runtime_spec_lane_mismatch")
    if not bool(agent_runtime_spec.get("runtime_executable", True)):
        blocked_reasons.append("runtime_spec_not_executable")

    return HealthAgentExecutionPlan(
        issue_id=issue.issue_id,
        task_mode=task_mode,
        task_id=task_id,
        flow_id=flow.flow_id,
        binding_id=binding.binding_id,
        agent_id=normalize_health_agent_id(binding.agent_id),
        agent_profile_id=binding.agent_profile_id,
        workflow_id=binding.workflow_id,
        runtime_lane=binding.runtime_lane,
        resource_policy_ref=binding.resource_policy_ref,
        task_contract_ref=str(dict(task_bundle.get("task_contract") or {}).get("task_id") or task_id),
        task_execution_assembly=task_execution_assembly,
        task_body_orchestration=task_body_orchestration,
        agent_runtime_spec=agent_runtime_spec,
        task_contract=dict(task_bundle.get("task_contract") or {}),
        operation_requirement=dict(task_bundle.get("operation_requirement") or {}),
        flow=flow.to_dict(),
        binding=binding.to_dict(),
        blocked_reasons=tuple(dict.fromkeys(item for item in blocked_reasons if item)),
        diagnostics={
            "source": source,
            "specific_task_id": specific_task_id,
            "specific_task_record": specific_task.to_dict(),
            "task_bundle_status": str(task_bundle.get("status") or ""),
            "runtime_executable": bool(agent_runtime_spec.get("runtime_executable", True)),
            "runtime_profile": runtime_profile.to_dict() if runtime_profile is not None else {},
        },
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


def _memory_runtime_view(*, issue: HealthIssue, task_mode: str) -> dict[str, Any]:
    return {
        "view_id": f"health-memview:{issue.issue_id}:{task_mode}",
        "authority": "health_system.memory_runtime_view",
        "issue_ref": issue.issue_id,
        "conversation_ref": issue.conversation_ref,
        "runtime_trace_refs": list(issue.runtime_trace_refs),
        "prompt_manifest_refs": list(issue.prompt_manifest_refs),
        "memory_refs": list(issue.memory_refs),
        "assertion_refs": list(issue.assertion_refs),
    }


def _context_policy_result(binding: dict[str, Any]) -> dict[str, Any]:
    return {
        "authority": "health_system.context_policy",
        "memory_scope": str(binding.get("memory_scope") or "issue_local_readonly"),
        "allowed_context_sections": ["health_issue", "runtime_trace", "prompt_manifest", "assertions"],
    }
