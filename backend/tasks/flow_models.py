from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskFlowDefinition:
    flow_id: str
    task_mode: str
    task_family: str
    title: str
    input_contract_id: str
    output_contract_id: str
    default_agent_id: str
    default_workflow_id: str
    default_projection_template_id: str
    default_runtime_lane: str
    default_memory_scope: str
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskAgentBinding:
    binding_id: str
    task_id: str
    flow_id: str
    agent_id: str
    agent_profile_id: str
    runtime_lane: str
    projection_template_id: str
    skill_workflow_id: str
    memory_scope: str
    output_contract_id: str
    resource_policy_ref: str = ""
    validation_state: str = "unchecked"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CoordinationTaskDefinition:
    coordination_task_id: str
    title: str
    coordination_mode: str
    coordinator_agent_id: str
    participant_agent_ids: tuple[str, ...] = ()
    topology_template_id: str = ""
    shared_context_policy: str = "explicit_refs_only"
    memory_sharing_policy: str = "isolated_by_default"
    handoff_policy: str = "filtered_handoff"
    conflict_resolution_policy: str = "coordinator_review"
    output_merge_policy: str = "coordinator_final_merge"
    stop_conditions: tuple[str, ...] = ()
    enabled: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["participant_agent_ids"] = list(self.participant_agent_ids)
        payload["stop_conditions"] = list(self.stop_conditions)
        return payload


@dataclass(frozen=True, slots=True)
class TopologyTemplate:
    template_id: str
    title: str
    nodes: tuple[dict[str, Any], ...] = ()
    edges: tuple[dict[str, Any], ...] = ()
    handoff_rules: tuple[dict[str, Any], ...] = ()
    join_policy: str = "explicit_join"
    failure_policy: str = "fail_closed"
    terminal_policy: str = "coordinator_terminal"
    enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["nodes"] = [dict(item) for item in self.nodes]
        payload["edges"] = [dict(item) for item in self.edges]
        payload["handoff_rules"] = [dict(item) for item in self.handoff_rules]
        return payload
