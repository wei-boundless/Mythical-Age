from __future__ import annotations

from pathlib import Path
from typing import Any

from operations import AgentRegistry

from .flow_models import (
    AgentTaskCarryingProfile,
    AgentTaskConnectionProfile,
    CoordinationTaskDefinition,
    GeneralTaskProfile,
    TaskAgentBinding,
    TaskAssignment,
    TaskFlowDefinition,
    TopologyTemplate,
)
from .template_registry import TaskTemplateRegistry
from skill_system import SkillWorkflowRegistry


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


def _storage_root(base_dir: Path) -> Path:
    return Path(base_dir) / "storage" / "tasks"


def _flows_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_flows.json"


def _general_profiles_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "general_task_profiles.json"


def _assignments_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_assignments.json"


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        import json

        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    return loaded if isinstance(loaded, dict) else fallback


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def default_general_task_profiles() -> tuple[GeneralTaskProfile, ...]:
    return (
        GeneralTaskProfile(
            profile_id="general.conversation.default",
            title="通用对话任务",
            default_agent_id="agent:main",
            default_workflow_id="",
            default_projection_template_id="primary_agent_default",
            input_contract_id="UserMessage",
            output_contract_id="AssistantFinalAnswer",
            conversation_entry_policy="user_dialogue_to_main_agent",
            enabled=True,
            metadata={"managed_by": "task_system"},
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
        self.template_registry = TaskTemplateRegistry(self.base_dir)
        self.workflow_registry = SkillWorkflowRegistry(self.base_dir)

    def list_general_task_profiles(self) -> list[GeneralTaskProfile]:
        payload = _read_json(
            _general_profiles_path(self.base_dir),
            {"profiles": [item.to_dict() for item in default_general_task_profiles()]},
        )
        profiles: list[GeneralTaskProfile] = []
        for item in list(payload.get("profiles") or []):
            if not isinstance(item, dict):
                continue
            profiles.append(
                GeneralTaskProfile(
                    profile_id=str(item.get("profile_id") or ""),
                    title=str(item.get("title") or ""),
                    default_agent_id=str(item.get("default_agent_id") or "agent:main"),
                    default_workflow_id=str(item.get("default_workflow_id") or ""),
                    default_projection_template_id=str(item.get("default_projection_template_id") or ""),
                    input_contract_id=str(item.get("input_contract_id") or ""),
                    output_contract_id=str(item.get("output_contract_id") or ""),
                    conversation_entry_policy=str(item.get("conversation_entry_policy") or "user_dialogue_to_main_agent"),
                    enabled=bool(item.get("enabled", True)),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return profiles

    def upsert_general_task_profile(
        self,
        *,
        profile_id: str,
        title: str,
        default_agent_id: str,
        default_workflow_id: str,
        default_projection_template_id: str = "",
        input_contract_id: str = "",
        output_contract_id: str = "",
        conversation_entry_policy: str = "user_dialogue_to_main_agent",
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> GeneralTaskProfile:
        target = str(profile_id or "").strip()
        if not target.startswith("general."):
            raise ValueError("profile_id must start with general.")
        profile = GeneralTaskProfile(
            profile_id=target,
            title=str(title or target).strip(),
            default_agent_id=str(default_agent_id or "agent:main").strip() or "agent:main",
            default_workflow_id=str(default_workflow_id or "").strip(),
            default_projection_template_id=str(default_projection_template_id or "").strip(),
            input_contract_id=str(input_contract_id or "").strip(),
            output_contract_id=str(output_contract_id or "").strip(),
            conversation_entry_policy=str(conversation_entry_policy or "user_dialogue_to_main_agent").strip(),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        profiles = [item for item in self.list_general_task_profiles() if item.profile_id != target]
        profiles.append(profile)
        _write_json(_general_profiles_path(self.base_dir), {"profiles": [item.to_dict() for item in profiles]})
        return profile

    def list_flows(self) -> list[TaskFlowDefinition]:
        payload = _read_json(
            _flows_path(self.base_dir),
            {"flows": [item.to_dict() for item in default_task_flows()]},
        )
        flows = []
        for item in list(payload.get("flows") or []):
            if not isinstance(item, dict):
                continue
            flows.append(
                TaskFlowDefinition(
                    flow_id=str(item.get("flow_id") or ""),
                    task_mode=str(item.get("task_mode") or ""),
                    task_family=str(item.get("task_family") or ""),
                    title=str(item.get("title") or ""),
                    input_contract_id=str(item.get("input_contract_id") or ""),
                    output_contract_id=str(item.get("output_contract_id") or ""),
                    default_agent_id=str(item.get("default_agent_id") or ""),
                    default_workflow_id=str(item.get("default_workflow_id") or ""),
                    default_projection_template_id=str(item.get("default_projection_template_id") or ""),
                    default_runtime_lane=str(item.get("default_runtime_lane") or ""),
                    default_memory_scope=str(item.get("default_memory_scope") or ""),
                    enabled=bool(item.get("enabled", True)),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return flows

    def get_flow(self, flow_id: str) -> TaskFlowDefinition | None:
        target = str(flow_id or "").strip()
        return next((item for item in self.list_flows() if item.flow_id == target), None)

    def upsert_flow(
        self,
        *,
        flow_id: str,
        task_mode: str,
        task_family: str,
        title: str,
        input_contract_id: str,
        output_contract_id: str,
        default_agent_id: str,
        default_workflow_id: str,
        default_projection_template_id: str,
        default_runtime_lane: str,
        default_memory_scope: str,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> TaskFlowDefinition:
        normalized_flow_id = str(flow_id or "").strip()
        if not normalized_flow_id.startswith("flow."):
            raise ValueError("flow_id must start with flow.")
        flow = TaskFlowDefinition(
            flow_id=normalized_flow_id,
            task_mode=str(task_mode or "").strip(),
            task_family=str(task_family or "").strip(),
            title=str(title or normalized_flow_id).strip(),
            input_contract_id=str(input_contract_id or "").strip(),
            output_contract_id=str(output_contract_id or "").strip(),
            default_agent_id=str(default_agent_id or "").strip(),
            default_workflow_id=str(default_workflow_id or "").strip(),
            default_projection_template_id=str(default_projection_template_id or "").strip(),
            default_runtime_lane=str(default_runtime_lane or "").strip(),
            default_memory_scope=str(default_memory_scope or "").strip(),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        flows = [item for item in self.list_flows() if item.flow_id != normalized_flow_id]
        flows.append(flow)
        _write_json(_flows_path(self.base_dir), {"flows": [item.to_dict() for item in flows]})
        return flow

    def list_task_assignments(self) -> list[TaskAssignment]:
        payload = _read_json(
            _assignments_path(self.base_dir),
            {"assignments": [self._assignment_from_flow(flow).to_dict() for flow in self.list_flows()]},
        )
        assignments: list[TaskAssignment] = []
        for item in list(payload.get("assignments") or []):
            if not isinstance(item, dict):
                continue
            assignments.append(_assignment_from_dict(item))
        return assignments

    def upsert_task_assignment(
        self,
        *,
        task_id: str,
        task_title: str,
        task_kind: str,
        task_family: str,
        task_mode: str,
        flow_id: str,
        default_agent_id: str,
        participant_agent_ids: tuple[str, ...] = (),
        workflow_id: str = "",
        workflow_file_ref: str = "",
        projection_template_id: str = "",
        input_contract_id: str = "",
        output_contract_id: str = "",
        task_structure: dict[str, Any] | None = None,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> TaskAssignment:
        target = str(task_id or "").strip()
        if not target.startswith("task."):
            raise ValueError("task_id must start with task.")
        normalized_flow_id = str(flow_id or f"flow.{target.removeprefix('task.')}").strip()
        if not normalized_flow_id.startswith("flow."):
            raise ValueError("flow_id must start with flow.")
        assignment = TaskAssignment(
            task_id=target,
            task_title=str(task_title or target).strip(),
            task_kind=str(task_kind or "specific_task").strip(),
            task_family=str(task_family or "").strip(),
            task_mode=str(task_mode or "").strip(),
            flow_id=normalized_flow_id,
            default_agent_id=str(default_agent_id or "agent:main").strip() or "agent:main",
            participant_agent_ids=tuple(str(item).strip() for item in participant_agent_ids if str(item).strip()),
            workflow_id=str(workflow_id or "").strip(),
            workflow_file_ref=str(workflow_file_ref or "").strip(),
            projection_template_id=str(projection_template_id or "").strip(),
            input_contract_id=str(input_contract_id or "").strip(),
            output_contract_id=str(output_contract_id or "").strip(),
            task_structure=dict(task_structure or {}),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        assignments = [item for item in self.list_task_assignments() if item.task_id != target]
        assignments.append(assignment)
        _write_json(_assignments_path(self.base_dir), {"assignments": [item.to_dict() for item in assignments]})
        self.upsert_flow(
            flow_id=assignment.flow_id,
            task_mode=assignment.task_mode,
            task_family=assignment.task_family,
            title=assignment.task_title,
            input_contract_id=assignment.input_contract_id,
            output_contract_id=assignment.output_contract_id,
            default_agent_id=assignment.default_agent_id,
            default_workflow_id=assignment.workflow_id,
            default_projection_template_id=assignment.projection_template_id,
            default_runtime_lane=str(assignment.task_structure.get("runtime_lane_hint") or ""),
            default_memory_scope=str(assignment.task_structure.get("memory_scope_hint") or ""),
            enabled=assignment.enabled,
            metadata={**assignment.metadata, "task_assignment_id": assignment.task_id},
        )
        return assignment

    def _assignment_from_flow(self, flow: TaskFlowDefinition) -> TaskAssignment:
        workflow = self.workflow_registry.get_workflow(flow.default_workflow_id)
        return TaskAssignment(
            task_id=f"task.{flow.task_family}.{flow.task_mode}",
            task_title=flow.title,
            task_kind="specific_task",
            task_family=flow.task_family,
            task_mode=flow.task_mode,
            flow_id=flow.flow_id,
            default_agent_id=flow.default_agent_id or "agent:main",
            participant_agent_ids=(),
            workflow_id=flow.default_workflow_id,
            workflow_file_ref=f"workflow:{flow.default_workflow_id}" if flow.default_workflow_id else "",
            projection_template_id=flow.default_projection_template_id,
            input_contract_id=flow.input_contract_id,
            output_contract_id=flow.output_contract_id,
            task_structure={
                "runtime_lane_hint": flow.default_runtime_lane,
                "memory_scope_hint": flow.default_memory_scope,
                "workflow_steps": [dict(item) for item in workflow.steps] if workflow is not None else [],
            },
            enabled=flow.enabled,
            metadata={**flow.metadata, "source_flow_id": flow.flow_id},
        )

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

    def list_agent_task_connection_profiles(
        self,
        *,
        owner_system: str = "",
        task_family: str = "",
    ) -> list[AgentTaskConnectionProfile]:
        flows = self.list_flows()
        bindings = self.list_bindings()
        topologies = self.list_topology_templates()
        profiles: list[AgentTaskConnectionProfile] = []
        for agent in self.agent_registry.list_agents():
            agent_bindings = [item for item in bindings if item.agent_id == agent.agent_id]
            agent_flows = [flow for flow in flows if any(binding.flow_id == flow.flow_id for binding in agent_bindings)]
            if owner_system and agent.owner_system != owner_system:
                continue
            if task_family and not any(flow.task_family == task_family for flow in agent_flows):
                continue
            capability = self.agent_registry.get_capability_profile(agent.agent_id)
            topology_refs = tuple(
                template.template_id
                for template in topologies
                if any(dict(node).get("agent_id") == agent.agent_id for node in template.nodes)
            )
            blocked_reasons = tuple(
                dict.fromkeys(
                    reason
                    for binding in agent_bindings
                    for reason in list(binding.diagnostics.get("failures") or [])
                    if reason
                )
            )
            profile_validation_state = "valid" if agent_bindings and not blocked_reasons else "invalid" if blocked_reasons else "unbound"
            default_flow = agent_flows[0] if agent_flows else None
            default_binding = agent_bindings[0] if agent_bindings else None
            profiles.append(
                AgentTaskConnectionProfile(
                    profile_id=f"agent-task-connection:{agent.agent_id}",
                    agent_id=agent.agent_id,
                    agent_profile_id=capability.agent_profile_id if capability is not None else "",
                    owner_system=agent.owner_system,
                    profile_type=agent.profile_type,
                    lifecycle_state=agent.lifecycle_state,
                    task_family_refs=tuple(dict.fromkeys(flow.task_family for flow in agent_flows)),
                    available_task_modes=tuple(dict.fromkeys(flow.task_mode for flow in agent_flows)),
                    flow_refs=tuple(flow.flow_id for flow in agent_flows),
                    binding_refs=tuple(binding.binding_id for binding in agent_bindings),
                    projection_template_refs=tuple(
                        dict.fromkeys(binding.projection_template_id for binding in agent_bindings if binding.projection_template_id)
                    ),
                    skill_workflow_refs=tuple(
                        dict.fromkeys(binding.skill_workflow_id for binding in agent_bindings if binding.skill_workflow_id)
                    ),
                    topology_refs=topology_refs,
                    default_flow_ref=default_flow.flow_id if default_flow is not None else "",
                    default_projection_template_ref=default_binding.projection_template_id if default_binding is not None else "",
                    default_skill_workflow_ref=default_binding.skill_workflow_id if default_binding is not None else "",
                    default_runtime_lane_hint=default_binding.runtime_lane if default_binding is not None else "",
                    validation_state=profile_validation_state,
                    blocked_reasons=blocked_reasons,
                    diagnostics={
                        "agent": agent.to_dict(),
                        "capability_profile_present": capability is not None,
                        "flow_count": len(agent_flows),
                        "binding_count": len(agent_bindings),
                        "topology_count": len(topology_refs),
                    },
                )
            )
        return profiles

    def build_agent_task_connection_overview(
        self,
        *,
        owner_system: str = "",
        task_family: str = "",
    ) -> dict[str, Any]:
        profiles = self.list_agent_task_connection_profiles(owner_system=owner_system, task_family=task_family)
        task_families = {family for profile in profiles for family in profile.task_family_refs}
        topology_refs = {topology for profile in profiles for topology in profile.topology_refs}
        return {
            "authority": "task_system.agent_task_connections",
            "profiles": [item.to_dict() for item in profiles],
            "summary": {
                "profile_count": len(profiles),
                "invalid_profile_count": sum(1 for item in profiles if item.validation_state == "invalid"),
                "task_family_count": len(task_families),
                "topology_count": len(topology_refs),
            },
            "diagnostics": {
                "owner_system_filter": owner_system,
                "task_family_filter": task_family,
            },
        }

    def list_agent_task_carrying_profiles(self) -> list[AgentTaskCarryingProfile]:
        general_profiles = self.list_general_task_profiles()
        assignments = self.list_task_assignments()
        bindings = self.list_bindings()
        binding_by_flow = {item.flow_id: item for item in bindings}
        profiles: list[AgentTaskCarryingProfile] = []
        for agent in self.agent_registry.list_agents():
            carried_general = [
                item
                for item in general_profiles
                if item.default_agent_id == agent.agent_id
            ]
            carried_specific = [
                item
                for item in assignments
                if item.default_agent_id == agent.agent_id or agent.agent_id in set(item.participant_agent_ids)
            ]
            workflow_refs = tuple(
                dict.fromkeys(
                    [
                        *(item.default_workflow_id for item in carried_general if item.default_workflow_id),
                        *(item.workflow_id for item in carried_specific if item.workflow_id),
                    ]
                )
            )
            projection_refs = tuple(
                dict.fromkeys(
                    [
                        *(item.default_projection_template_id for item in carried_general if item.default_projection_template_id),
                        *(item.projection_template_id for item in carried_specific if item.projection_template_id),
                    ]
                )
            )
            blocked_reasons = list(self._agent_assignment_failures(agent.agent_id, carried_general, carried_specific))
            for assignment in carried_specific:
                binding = binding_by_flow.get(assignment.flow_id)
                if binding is not None and binding.validation_state != "valid":
                    blocked_reasons.extend(str(item) for item in list(binding.diagnostics.get("failures") or []) if item)
            validation_state = "valid" if (carried_general or carried_specific) and not blocked_reasons else "invalid" if blocked_reasons else "unbound"
            profiles.append(
                AgentTaskCarryingProfile(
                    agent_id=agent.agent_id,
                    display_name=agent.display_name,
                    profile_type=agent.profile_type,
                    owner_system=agent.owner_system,
                    lifecycle_state=agent.lifecycle_state,
                    carried_general_task_refs=tuple(item.profile_id for item in carried_general),
                    carried_specific_task_refs=tuple(item.task_id for item in carried_specific),
                    workflow_refs=workflow_refs,
                    projection_template_refs=projection_refs,
                    validation_state=validation_state,
                    blocked_reasons=tuple(dict.fromkeys(blocked_reasons)),
                    diagnostics={
                        "general_task_count": len(carried_general),
                        "specific_task_count": len(carried_specific),
                        "workflow_count": len(workflow_refs),
                    },
                )
            )
        return profiles

    def build_agent_carrying_overview(self) -> dict[str, Any]:
        profiles = self.list_agent_task_carrying_profiles()
        return {
            "authority": "task_system.agent_carrying_profiles",
            "profiles": [item.to_dict() for item in profiles],
            "summary": {
                "profile_count": len(profiles),
                "invalid_profile_count": sum(1 for item in profiles if item.validation_state == "invalid"),
                "unbound_profile_count": sum(1 for item in profiles if item.validation_state == "unbound"),
            },
        }

    def build_connection_diagnostics(self) -> dict[str, Any]:
        agents = {item.agent_id for item in self.agent_registry.list_agents()}
        workflows = {item.workflow_id for item in self.workflow_registry.list_workflows()}
        general_profiles = self.list_general_task_profiles()
        assignments = self.list_task_assignments()
        issues: list[dict[str, Any]] = []
        for profile in general_profiles:
            self._append_ref_issue(issues, profile.profile_id, "general_task", "default_agent_id", profile.default_agent_id, agents)
            if profile.default_workflow_id:
                self._append_ref_issue(issues, profile.profile_id, "general_task", "workflow_id", profile.default_workflow_id, workflows)
            else:
                issues.append(_diagnostic_issue(profile.profile_id, "general_task", "workflow_missing", "default_workflow_id"))
        for assignment in assignments:
            self._append_ref_issue(issues, assignment.task_id, "specific_task", "default_agent_id", assignment.default_agent_id, agents)
            for participant_id in assignment.participant_agent_ids:
                self._append_ref_issue(issues, assignment.task_id, "specific_task", "participant_agent_id", participant_id, agents)
            if assignment.workflow_id:
                self._append_ref_issue(issues, assignment.task_id, "specific_task", "workflow_id", assignment.workflow_id, workflows)
            else:
                issues.append(_diagnostic_issue(assignment.task_id, "specific_task", "workflow_missing", "workflow_id"))
            if not assignment.input_contract_id:
                issues.append(_diagnostic_issue(assignment.task_id, "specific_task", "input_contract_missing", "input_contract_id"))
            if not assignment.output_contract_id:
                issues.append(_diagnostic_issue(assignment.task_id, "specific_task", "output_contract_missing", "output_contract_id"))
        for profile in self.list_agent_task_carrying_profiles():
            if profile.validation_state == "unbound":
                issues.append(_diagnostic_issue(profile.agent_id, "agent", "agent_without_task", "carried_tasks"))
            for reason in profile.blocked_reasons:
                issues.append(_diagnostic_issue(profile.agent_id, "agent", reason, "task_connection"))
        return {
            "authority": "task_system.connection_diagnostics",
            "issues": issues,
            "summary": {
                "issue_count": len(issues),
                "blocking_issue_count": sum(1 for item in issues if item.get("severity") == "blocking"),
            },
        }

    def _agent_assignment_failures(
        self,
        agent_id: str,
        general_profiles: list[GeneralTaskProfile],
        assignments: list[TaskAssignment],
    ) -> tuple[str, ...]:
        failures: list[str] = []
        if any(item.default_workflow_id and self.workflow_registry.get_workflow(item.default_workflow_id) is None for item in general_profiles):
            failures.append("general_workflow_missing")
        if any(item.workflow_id and self.workflow_registry.get_workflow(item.workflow_id) is None for item in assignments):
            failures.append("specific_workflow_missing")
        if agent_id == "agent:main" and not general_profiles:
            failures.append("main_agent_without_general_task")
        return tuple(dict.fromkeys(failures))

    def _append_ref_issue(
        self,
        issues: list[dict[str, Any]],
        object_id: str,
        object_type: str,
        field: str,
        value: str,
        allowed: set[str],
    ) -> None:
        if not value or value not in allowed:
            issues.append(_diagnostic_issue(object_id, object_type, f"{field}_missing_ref", field, value=value))

    def build_overview(self) -> dict[str, Any]:
        agent_catalog = self.agent_registry.build_catalog()
        flows = self.list_flows()
        bindings = self.list_bindings()
        general_profiles = self.list_general_task_profiles()
        task_assignments = self.list_task_assignments()
        coordination_tasks = self.list_coordination_tasks()
        templates = self.template_registry.list_templates()
        template_validation_matrix = self.template_registry.build_validation_matrix()
        invalid_bindings = [item for item in bindings if item.validation_state != "valid"]
        return {
            "authority": "task_system.overview",
            "summary": {
                "agent_count": agent_catalog["summary"]["agent_count"],
                "main_agent_count": agent_catalog["summary"]["main_agent_count"],
                "system_management_agent_count": agent_catalog["summary"]["system_management_agent_count"],
                "worker_sub_agent_count": agent_catalog["summary"]["worker_sub_agent_count"],
                "general_task_count": len(general_profiles),
                "specific_task_count": len(task_assignments),
                "task_flow_count": len(flows),
                "enabled_task_flow_count": sum(1 for item in flows if item.enabled),
                "task_template_count": len(templates),
                "enabled_task_template_count": sum(1 for item in templates if item.enabled),
                "coordination_task_count": len(coordination_tasks),
                "invalid_binding_count": len(invalid_bindings),
                "invalid_template_count": sum(
                    1
                    for item in list(template_validation_matrix.get("rows") or [])
                    if str(item.get("validation_state") or "") != "valid"
                ),
            },
            "agents": agent_catalog["agents"],
            "general_task_profiles": [item.to_dict() for item in general_profiles],
            "task_assignments": [item.to_dict() for item in task_assignments],
            "flows": [item.to_dict() for item in flows],
            "bindings": [item.to_dict() for item in bindings],
            "templates": [item.to_dict() for item in templates],
            "template_validation_matrix": template_validation_matrix,
            "coordination_tasks": [item.to_dict() for item in coordination_tasks],
            "topology_templates": [item.to_dict() for item in self.list_topology_templates()],
            "link_permission_matrix": self.build_link_permission_matrix(),
            "agent_task_connections": self.build_agent_task_connection_overview(),
            "agent_carrying_profiles": self.build_agent_carrying_overview(),
            "connection_diagnostics": self.build_connection_diagnostics(),
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


def _assignment_from_dict(payload: dict[str, Any]) -> TaskAssignment:
    return TaskAssignment(
        task_id=str(payload.get("task_id") or ""),
        task_title=str(payload.get("task_title") or ""),
        task_kind=str(payload.get("task_kind") or "specific_task"),
        task_family=str(payload.get("task_family") or ""),
        task_mode=str(payload.get("task_mode") or ""),
        flow_id=str(payload.get("flow_id") or ""),
        default_agent_id=str(payload.get("default_agent_id") or "agent:main"),
        participant_agent_ids=tuple(str(item) for item in list(payload.get("participant_agent_ids") or []) if str(item)),
        workflow_id=str(payload.get("workflow_id") or ""),
        workflow_file_ref=str(payload.get("workflow_file_ref") or ""),
        projection_template_id=str(payload.get("projection_template_id") or ""),
        input_contract_id=str(payload.get("input_contract_id") or ""),
        output_contract_id=str(payload.get("output_contract_id") or ""),
        task_structure=dict(payload.get("task_structure") or {}),
        enabled=bool(payload.get("enabled", True)),
        metadata=dict(payload.get("metadata") or {}),
    )


def _diagnostic_issue(
    object_id: str,
    object_type: str,
    reason: str,
    field: str,
    *,
    value: str = "",
) -> dict[str, Any]:
    return {
        "object_id": object_id,
        "object_type": object_type,
        "reason": reason,
        "field": field,
        "value": value,
        "severity": "blocking" if reason != "agent_without_task" else "warning",
    }
