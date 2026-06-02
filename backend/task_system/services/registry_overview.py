from __future__ import annotations

from typing import Any

from task_system.registry.flow_models import (
    AgentTaskCarryingProfile,
    AgentTaskConnectionProfile,
    GeneralTaskProfile,
    TaskAgentBinding,
    TaskAssignment,
    TaskFlowDefinition,
)


class TaskRegistryOverviewBuilder:
    def __init__(self, registry: Any) -> None:
        self.registry = registry

    def build_binding_for_flow(self, flow: TaskFlowDefinition) -> TaskAgentBinding:
        agent = self.registry.agent_registry.get_agent(flow.default_agent_id)
        profile = self.registry.agent_runtime_registry.get_profile(flow.default_agent_id)
        diagnostics: dict[str, Any] = {}
        failures: list[str] = []
        if agent is None:
            failures.append("agent_missing")
        elif agent.lifecycle_state not in {"enabled", "system_builtin"}:
            failures.append("agent_not_enabled")
        if profile is None:
            failures.append("runtime_profile_missing")
        else:
            _validate_contains(failures, diagnostics, "memory_scope", flow.default_memory_scope, profile.allowed_memory_scopes)
        self._validate_workflow_ref(failures, diagnostics, flow.default_workflow_id)
        return TaskAgentBinding(
            binding_id=f"binding:{flow.flow_id}:{flow.default_agent_id}",
            task_id=str(flow.metadata.get("task_id") or flow.metadata.get("task_assignment_id") or f"task.{flow.flow_id.removeprefix('flow.')}"),
            flow_id=flow.flow_id,
            agent_id=flow.default_agent_id,
            agent_profile_id=profile.agent_profile_id if profile is not None else "",
            workflow_id=flow.default_workflow_id,
            memory_scope=flow.default_memory_scope,
            output_contract_id=flow.output_contract_id,
            resource_policy_ref=f"resource-policy:{flow.flow_id}:candidate",
            validation_state="valid" if not failures else "invalid",
            diagnostics={**diagnostics, "failures": failures},
        )

    def build_link_permission_matrix(self) -> dict[str, Any]:
        bindings = self.registry.list_bindings()
        return {
            "authority": "task_system.link_permission_matrix",
            "rows": [
                {
                    "agent_id": item.agent_id,
                    "agent_profile_id": item.agent_profile_id,
                    "task_ref": item.task_id,
                    "workflow": item.workflow_id,
                    "memory_scope": item.memory_scope,
                    "output_contract": item.output_contract_id,
                    "validation_state": item.validation_state,
                    "blocked_reasons": list(item.diagnostics.get("failures") or []),
                }
                for item in bindings
            ],
        }

    def list_agent_task_connection_profiles(self, *, owner_system: str = "") -> list[AgentTaskConnectionProfile]:
        flows = self.registry.list_flows()
        bindings = self.registry.list_bindings()
        profiles: list[AgentTaskConnectionProfile] = []
        for agent in self.registry.agent_registry.list_agents():
            if owner_system and agent.owner_system != owner_system:
                continue
            agent_bindings = [item for item in bindings if item.agent_id == agent.agent_id]
            agent_flows = [flow for flow in flows if any(binding.flow_id == flow.flow_id for binding in agent_bindings)]
            capability = self.registry.agent_runtime_registry.get_profile(agent.agent_id)
            blocked_reasons = tuple(
                dict.fromkeys(
                    reason
                    for binding in agent_bindings
                    for reason in list(binding.diagnostics.get("failures") or [])
                    if reason
                )
            )
            validation_state = "valid" if agent_bindings and not blocked_reasons else "invalid" if blocked_reasons else "unbound"
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
                    task_refs=tuple(
                        dict.fromkeys(
                            str(flow.metadata.get("task_id") or flow.metadata.get("task_assignment_id") or f"task.{flow.flow_id.removeprefix('flow.')}")
                            for flow in agent_flows
                        )
                    ),
                    flow_refs=tuple(flow.flow_id for flow in agent_flows),
                    binding_refs=tuple(binding.binding_id for binding in agent_bindings),
                    workflow_refs=tuple(dict.fromkeys(binding.workflow_id for binding in agent_bindings if binding.workflow_id)),
                    default_flow_ref=default_flow.flow_id if default_flow is not None else "",
                    default_workflow_ref=default_binding.workflow_id if default_binding is not None else "",
                    validation_state=validation_state,
                    blocked_reasons=blocked_reasons,
                    diagnostics={
                        "agent": agent.to_dict(),
                        "runtime_profile_present": capability is not None,
                        "flow_count": len(agent_flows),
                        "binding_count": len(agent_bindings),
                    },
                )
            )
        return profiles

    def build_agent_task_connection_overview(self, *, owner_system: str = "") -> dict[str, Any]:
        profiles = self.list_agent_task_connection_profiles(owner_system=owner_system)
        return {
            "authority": "task_system.agent_task_connections",
            "profiles": [item.to_dict() for item in profiles],
            "summary": {
                "profile_count": len(profiles),
                "invalid_profile_count": sum(1 for item in profiles if item.validation_state == "invalid"),
            },
            "diagnostics": {
                "owner_system_filter": owner_system,
            },
        }

    def list_agent_task_carrying_profiles(self) -> list[AgentTaskCarryingProfile]:
        general_profiles = self.registry.list_general_task_profiles()
        assignments = self.registry.list_task_assignments()
        bindings = self.registry.list_bindings()
        binding_by_flow = {item.flow_id: item for item in bindings}
        workflow_ids = {item.workflow_id for item in self.registry.workflow_registry.list_workflows()}
        profiles: list[AgentTaskCarryingProfile] = []
        for agent in self.registry.agent_registry.list_agents():
            carried_general = [item for item in general_profiles if item.default_agent_id == agent.agent_id]
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
            blocked_reasons = list(
                self._agent_assignment_failures(
                    agent.agent_id,
                    carried_general,
                    carried_specific,
                    workflow_ids=workflow_ids,
                )
            )
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
        agents = {item.agent_id for item in self.registry.agent_registry.list_agents()}
        workflows = {item.workflow_id for item in self.registry.workflow_registry.list_workflows()}
        general_profiles = self.registry.list_general_task_profiles()
        assignments = self.registry.list_task_assignments()
        carrying_profiles = self.list_agent_task_carrying_profiles()
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
        for profile in carrying_profiles:
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

    def build_overview(self) -> dict[str, Any]:
        agent_catalog = self.registry.agent_registry.build_catalog()
        flows = self.registry.list_flows()
        bindings = self.registry.list_bindings()
        general_profiles = self.registry.list_general_task_profiles()
        task_assignments = self.registry.list_task_assignments()
        task_domains = self.registry.list_task_domains()
        invalid_bindings = [item for item in bindings if item.validation_state != "valid"]
        flow_contract_bindings = self.registry.list_flow_contract_bindings()
        explicit_flow_contract_bindings = self.registry.list_explicit_flow_contract_bindings()
        execution_policies = self.registry.list_task_execution_policies()
        explicit_execution_policies = self.registry.list_explicit_task_execution_policies()
        communication_protocols = self.registry.list_task_communication_protocols()
        return {
            "authority": "task_system.overview",
            "summary": {
                "agent_count": agent_catalog["summary"]["agent_count"],
                "main_agent_count": agent_catalog["summary"]["main_agent_count"],
                "builtin_agent_count": agent_catalog["summary"]["builtin_agent_count"],
                "custom_agent_count": agent_catalog["summary"]["custom_agent_count"],
                "system_manager_agent_count": agent_catalog["summary"]["system_manager_agent_count"],
                "subagent_enabled_agent_count": agent_catalog["summary"].get("subagent_enabled_agent_count", 0),
                "general_task_count": len(general_profiles),
                "specific_task_count": len(task_assignments),
                "task_flow_count": len(flows),
                "enabled_task_flow_count": sum(1 for item in flows if item.enabled),
                "runtime_recipe_protocol": "task_graph_derived",
                "task_template_count": 0,
                "enabled_task_template_count": 0,
                "task_domain_count": len(task_domains),
                "flow_contract_binding_count": len(explicit_flow_contract_bindings),
                "derived_flow_contract_binding_count": _derived_count(
                    flow_contract_bindings,
                    explicit_flow_contract_bindings,
                    key_attr="binding_id",
                ),
                "effective_flow_contract_binding_count": len(flow_contract_bindings),
                "execution_policy_count": len(explicit_execution_policies),
                "derived_execution_policy_count": _derived_count(
                    execution_policies,
                    explicit_execution_policies,
                    key_attr="policy_id",
                ),
                "effective_execution_policy_count": len(execution_policies),
                "communication_protocol_count": len(communication_protocols),
                "invalid_binding_count": len(invalid_bindings),
                "invalid_template_count": 0,
            },
            "agents": agent_catalog["agents"],
            "task_domains": [item.to_dict() for item in task_domains],
            "general_task_profiles": [item.to_dict() for item in general_profiles],
            "specific_task_records": [item.to_dict() for item in self.registry.list_specific_task_records()],
            "task_assignments": [item.to_dict() for item in task_assignments],
            "flows": [item.to_dict() for item in flows],
            "bindings": [item.to_dict() for item in bindings],
            "flow_contract_bindings": [item.to_dict() for item in flow_contract_bindings],
            "agent_execution_policies": [item.to_dict() for item in execution_policies],
            "templates": [],
            "template_validation_matrix": _removed_template_protocol_matrix(),
            "communication_protocols": [item.to_dict() for item in communication_protocols],
            "link_permission_matrix": self.build_link_permission_matrix(),
            "agent_task_connections": self.build_agent_task_connection_overview(),
            "agent_carrying_profiles": self.build_agent_carrying_overview(),
            "connection_diagnostics": self.build_connection_diagnostics(),
        }

    def _agent_assignment_failures(
        self,
        agent_id: str,
        general_profiles: list[GeneralTaskProfile],
        assignments: list[TaskAssignment],
        workflow_ids: set[str] | None = None,
    ) -> tuple[str, ...]:
        workflow_ids = workflow_ids if workflow_ids is not None else {
            item.workflow_id for item in self.registry.workflow_registry.list_workflows()
        }
        failures: list[str] = []
        if any(item.default_workflow_id and item.default_workflow_id not in workflow_ids for item in general_profiles):
            failures.append("general_workflow_missing")
        if any(item.workflow_id and item.workflow_id not in workflow_ids for item in assignments):
            failures.append("specific_workflow_missing")
        if agent_id == "agent:0" and not general_profiles:
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

    def _validate_workflow_ref(
        self,
        failures: list[str],
        diagnostics: dict[str, Any],
        workflow_id: str,
    ) -> None:
        value = str(workflow_id or "").strip()
        if not value:
            failures.append("workflow_missing")
            diagnostics["workflow"] = {"value": value, "status": "missing"}
            return
        if self.registry.workflow_registry.get_workflow(value) is not None:
            return
        failures.append("workflow_missing")
        diagnostics["workflow"] = {"value": value, "status": "missing"}


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


def _derived_count(effective_items: list[Any], explicit_items: list[Any], *, key_attr: str) -> int:
    explicit_keys = {
        str(getattr(item, key_attr, "") or "").strip()
        for item in explicit_items
        if str(getattr(item, key_attr, "") or "").strip()
    }
    return sum(
        1
        for item in effective_items
        if str(getattr(item, key_attr, "") or "").strip()
        and str(getattr(item, key_attr, "") or "").strip() not in explicit_keys
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


def _removed_template_protocol_matrix() -> dict[str, Any]:
    return {
        "authority": "task_system.runtime_recipe_validation",
        "status": "removed",
        "rows": [],
        "template_protocol_removed": True,
        "replacement": "TaskGraph + runtime.recipe",
    }


