from __future__ import annotations

from pathlib import Path
from typing import Any

from operations import AgentRegistry

from .flow_models import CoordinationTaskDefinition, TaskAgentBinding, TaskFlowDefinition, TopologyTemplate


def default_task_flows() -> tuple[TaskFlowDefinition, ...]:
    return (
        TaskFlowDefinition(
            flow_id="flow.health.issue_triage",
            task_mode="issue_triage",
            task_family="health",
            title="健康问题分诊",
            input_contract_id="HealthIssue",
            output_contract_id="HealthTriageResult",
            default_agent_id="agent:health:maintainer",
            default_workflow_id="workflow.health.issue_triage",
            default_projection_template_id="xuannv__health_maintainer",
            default_runtime_lane="health_issue_read",
            default_memory_scope="issue_local_readonly",
        ),
        TaskFlowDefinition(
            flow_id="flow.health.trace_analysis",
            task_mode="trace_analysis",
            task_family="health",
            title="健康链路分析",
            input_contract_id="HealthTrace",
            output_contract_id="HealthTraceAnalysis",
            default_agent_id="agent:health:maintainer",
            default_workflow_id="workflow.health.trace_analysis",
            default_projection_template_id="xuannv__health_maintainer",
            default_runtime_lane="health_trace_read",
            default_memory_scope="health_trace_readonly",
        ),
        TaskFlowDefinition(
            flow_id="flow.health.case_draft",
            task_mode="case_draft",
            task_family="health",
            title="复现用例草案",
            input_contract_id="HealthIssue",
            output_contract_id="HealthCaseDraftProposal",
            default_agent_id="agent:health:maintainer",
            default_workflow_id="workflow.health.case_draft",
            default_projection_template_id="xuannv__health_maintainer",
            default_runtime_lane="case_draft_candidate",
            default_memory_scope="issue_local_readonly",
        ),
        TaskFlowDefinition(
            flow_id="flow.health.fix_verification",
            task_mode="fix_verification",
            task_family="health",
            title="修复验证",
            input_contract_id="HealthIssueWithBeforeAfterTrace",
            output_contract_id="HealthFixVerificationProposal",
            default_agent_id="agent:health:maintainer",
            default_workflow_id="workflow.health.fix_verification",
            default_projection_template_id="xuannv__health_maintainer",
            default_runtime_lane="fix_verification_candidate",
            default_memory_scope="health_trace_readonly",
        ),
    )


def default_coordination_tasks() -> tuple[CoordinationTaskDefinition, ...]:
    return (
        CoordinationTaskDefinition(
            coordination_task_id="coord.health.repair_review",
            title="健康修复协作草案",
            coordination_mode="review_merge",
            coordinator_agent_id="agent:main",
            participant_agent_ids=("agent:health:maintainer",),
            topology_template_id="topology.health.repair_review",
            stop_conditions=("all_participants_reported", "coordinator_final_merge"),
            enabled=False,
            metadata={"candidate_only": True},
        ),
    )


def default_topology_templates() -> tuple[TopologyTemplate, ...]:
    return (
        TopologyTemplate(
            template_id="topology.health.repair_review",
            title="健康修复拓扑草案",
            nodes=(
                {"node_id": "health_triage", "agent_id": "agent:health:maintainer", "lane": "health_issue_read"},
                {"node_id": "fix_verification", "agent_id": "agent:health:maintainer", "lane": "fix_verification_candidate"},
                {"node_id": "final_merge", "agent_id": "agent:main", "lane": "final_integration"},
            ),
            edges=(
                {"from": "health_triage", "to": "fix_verification", "policy": "issue_refs_only"},
                {"from": "fix_verification", "to": "final_merge", "policy": "structured_result_only"},
            ),
            enabled=False,
        ),
    )


class TaskFlowRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.agent_registry = AgentRegistry(self.base_dir)

    def list_flows(self) -> list[TaskFlowDefinition]:
        return list(default_task_flows())

    def list_bindings(self) -> list[TaskAgentBinding]:
        return [self.build_binding_for_flow(flow) for flow in self.list_flows()]

    def list_coordination_tasks(self) -> list[CoordinationTaskDefinition]:
        return list(default_coordination_tasks())

    def list_topology_templates(self) -> list[TopologyTemplate]:
        return list(default_topology_templates())

    def build_binding_for_flow(self, flow: TaskFlowDefinition) -> TaskAgentBinding:
        agent = self.agent_registry.get_agent(flow.default_agent_id)
        profile = self.agent_registry.get_capability_profile(flow.default_agent_id)
        diagnostics: dict[str, Any] = {}
        failures: list[str] = []
        if agent is None:
            failures.append("agent_missing")
        elif agent.lifecycle_state not in {"enabled", "system_builtin"}:
            failures.append("agent_not_enabled")
        if profile is None:
            failures.append("capability_profile_missing")
        else:
            _validate_contains(failures, diagnostics, "task_mode", flow.task_mode, profile.allowed_task_modes)
            _validate_contains(failures, diagnostics, "runtime_lane", flow.default_runtime_lane, profile.allowed_runtime_lanes)
            _validate_contains(failures, diagnostics, "skill_workflow", flow.default_workflow_id, profile.allowed_skill_workflows)
            _validate_contains(
                failures,
                diagnostics,
                "projection_template",
                flow.default_projection_template_id,
                profile.allowed_projection_templates,
            )
            _validate_contains(failures, diagnostics, "memory_scope", flow.default_memory_scope, profile.allowed_memory_scopes)
            _validate_contains(failures, diagnostics, "output_contract", flow.output_contract_id, profile.output_contracts)
        return TaskAgentBinding(
            binding_id=f"binding:{flow.flow_id}:{flow.default_agent_id}",
            task_id=f"task-template:{flow.task_mode}",
            flow_id=flow.flow_id,
            agent_id=flow.default_agent_id,
            agent_profile_id=profile.agent_profile_id if profile is not None else "",
            runtime_lane=flow.default_runtime_lane,
            projection_template_id=flow.default_projection_template_id,
            skill_workflow_id=flow.default_workflow_id,
            memory_scope=flow.default_memory_scope,
            output_contract_id=flow.output_contract_id,
            resource_policy_ref=f"resource-policy:{flow.flow_id}:candidate",
            validation_state="valid" if not failures else "invalid",
            diagnostics={**diagnostics, "failures": failures},
        )

    def build_link_permission_matrix(self) -> dict[str, Any]:
        bindings = self.list_bindings()
        return {
            "authority": "task_system.link_permission_matrix",
            "rows": [
                {
                    "agent_id": item.agent_id,
                    "agent_profile_id": item.agent_profile_id,
                    "task_mode": next((flow.task_mode for flow in self.list_flows() if flow.flow_id == item.flow_id), ""),
                    "runtime_lane": item.runtime_lane,
                    "skill_workflow": item.skill_workflow_id,
                    "projection_template": item.projection_template_id,
                    "memory_scope": item.memory_scope,
                    "output_contract": item.output_contract_id,
                    "validation_state": item.validation_state,
                    "blocked_reasons": list(item.diagnostics.get("failures") or []),
                }
                for item in bindings
            ],
        }

    def build_overview(self) -> dict[str, Any]:
        agent_catalog = self.agent_registry.build_catalog()
        flows = self.list_flows()
        bindings = self.list_bindings()
        coordination_tasks = self.list_coordination_tasks()
        invalid_bindings = [item for item in bindings if item.validation_state != "valid"]
        return {
            "authority": "task_system.overview",
            "summary": {
                "agent_count": agent_catalog["summary"]["agent_count"],
                "visible_sub_agent_count": agent_catalog["summary"]["sub_agent_count"],
                "task_flow_count": len(flows),
                "enabled_task_flow_count": sum(1 for item in flows if item.enabled),
                "coordination_task_count": len(coordination_tasks),
                "invalid_binding_count": len(invalid_bindings),
            },
            "agents": agent_catalog["agents"],
            "flows": [item.to_dict() for item in flows],
            "bindings": [item.to_dict() for item in bindings],
            "coordination_tasks": [item.to_dict() for item in coordination_tasks],
            "topology_templates": [item.to_dict() for item in self.list_topology_templates()],
            "link_permission_matrix": self.build_link_permission_matrix(),
        }


def _validate_contains(
    failures: list[str],
    diagnostics: dict[str, Any],
    field: str,
    value: str,
    allowed: tuple[str, ...],
) -> None:
    if value not in allowed:
        failures.append(f"{field}_not_allowed")
        diagnostics[field] = {"value": value, "allowed": list(allowed)}
