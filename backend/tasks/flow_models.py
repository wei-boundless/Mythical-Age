from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskFlowDefinition:
    flow_id: str
    task_family: str
    title: str
    input_contract_id: str
    output_contract_id: str
    default_agent_id: str
    default_workflow_id: str
    default_runtime_lane: str
    default_memory_scope: str
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GeneralTaskProfile:
    profile_id: str
    title: str
    default_agent_id: str
    default_workflow_id: str
    entry_channel: str = "main_conversation"
    default_projection_id: str = ""
    input_contract_id: str = ""
    output_contract_id: str = ""
    conversation_entry_policy: str = "user_dialogue_to_main_agent"
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskAssignment:
    task_id: str
    task_title: str
    task_kind: str
    task_family: str
    flow_id: str
    runtime_lane: str = ""
    default_agent_id: str = "agent:0"
    participant_agent_ids: tuple[str, ...] = ()
    workflow_id: str = ""
    workflow_file_ref: str = ""
    projection_id: str = ""
    input_contract_id: str = ""
    output_contract_id: str = ""
    safety_policy: dict[str, Any] = field(default_factory=dict)
    task_structure: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("default_agent_id", None)
        payload.pop("participant_agent_ids", None)
        task_structure = dict(payload.get("task_structure") or {})
        chain_type = str(task_structure.get("execution_chain_type") or task_structure.get("chain_type") or "").strip()
        if not chain_type:
            chain_type = (
                "coordination_chain"
                if task_structure.get("task_graph_id") or task_structure.get("graph_id")
                else "single_agent_chain"
            )
        payload["execution_chain_type"] = chain_type
        return payload

    def to_legacy_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["participant_agent_ids"] = list(self.participant_agent_ids)
        return payload


@dataclass(frozen=True, slots=True)
class SpecificTaskRecord:
    task_id: str
    task_title: str
    task_family: str
    description: str = ""
    enabled: bool = True
    runtime_lane: str = ""
    input_contract_id: str = ""
    output_contract_id: str = ""
    acceptance_profile_id: str = ""
    default_flow_contract_id: str = ""
    default_workflow_id: str = ""
    default_projection_policy: str = ""
    task_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskDomainRecord:
    domain_id: str
    task_family: str
    title: str
    description: str = ""
    enabled: bool = True
    sort_order: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskProjectionBinding:
    binding_id: str
    task_id: str
    projection_selection_mode: str = "task_default"
    allowed_projection_ids: tuple[str, ...] = ()
    default_projection_id: str = ""
    projection_required: bool = False
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_projection_binding"

    def __post_init__(self) -> None:
        if self.authority != "task_system.task_projection_binding":
            raise ValueError("TaskProjectionBinding authority must be task_system.task_projection_binding")
        if not self.binding_id:
            raise ValueError("TaskProjectionBinding requires binding_id")
        if not self.task_id:
            raise ValueError("TaskProjectionBinding requires task_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_projection_ids"] = list(self.allowed_projection_ids)
        return payload


@dataclass(frozen=True, slots=True)
class TaskFlowContractBinding:
    binding_id: str
    task_id: str
    flow_contract_id: str
    override_policy: str = "task_default"
    verification_gate_profile: str = ""
    fallback_policy: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_flow_contract_binding"

    def __post_init__(self) -> None:
        if self.authority != "task_system.task_flow_contract_binding":
            raise ValueError("TaskFlowContractBinding authority must be task_system.task_flow_contract_binding")
        if not self.binding_id:
            raise ValueError("TaskFlowContractBinding requires binding_id")
        if not self.task_id:
            raise ValueError("TaskFlowContractBinding requires task_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskAgentAdoptionPlan:
    plan_id: str
    task_id: str
    adoption_mode: str
    default_agent_id: str = "agent:0"
    allow_worker_agent_spawn: bool = False
    worker_agent_blueprint_id: str = ""
    worker_agent_naming_rule: str = ""
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_agent_adoption_plan"

    def __post_init__(self) -> None:
        if self.authority != "task_system.task_agent_adoption_plan":
            raise ValueError("TaskAgentAdoptionPlan authority must be task_system.task_agent_adoption_plan")
        if not self.plan_id:
            raise ValueError("TaskAgentAdoptionPlan requires plan_id")
        if not self.task_id:
            raise ValueError("TaskAgentAdoptionPlan requires task_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        metadata = dict(payload.get("metadata") or {})
        payload["execution_policy_id"] = payload["plan_id"].replace("taskadopt:", "taskexecpol:", 1)
        execution_chain_type = str(metadata.get("execution_chain_type") or "").strip()
        if not execution_chain_type:
            execution_chain_type = (
                "coordination_chain"
                if metadata.get("task_graph_id")
                or metadata.get("graph_id")
                or self.allow_worker_agent_spawn
                else "single_agent_chain"
            )
        payload["execution_chain_type"] = execution_chain_type
        payload["authority"] = "task_system.task_execution_policy"
        payload["runtime_agent_selection_policy"] = str(metadata.get("runtime_agent_selection_policy") or "orchestration_default")
        payload["task_level"] = str(metadata.get("task_level") or "standard")
        payload["task_privilege"] = str(metadata.get("task_privilege") or "bounded")
        return payload

    def to_legacy_dict(self) -> dict[str, Any]:
        return self.to_dict()


@dataclass(frozen=True, slots=True)
class TaskMemoryRequestProfile:
    profile_id: str
    task_id: str
    requested_memory_layers: tuple[str, ...] = ()
    requested_topics: tuple[str, ...] = ()
    memory_priority: str = "normal"
    writeback_policy: str = "task_default"
    allow_long_term_memory: bool = False
    memory_scope_hint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_memory_request_profile"

    def __post_init__(self) -> None:
        if self.authority != "task_system.task_memory_request_profile":
            raise ValueError("TaskMemoryRequestProfile authority must be task_system.task_memory_request_profile")
        if not self.profile_id:
            raise ValueError("TaskMemoryRequestProfile requires profile_id")
        if not self.task_id:
            raise ValueError("TaskMemoryRequestProfile requires task_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["requested_memory_layers"] = list(self.requested_memory_layers)
        payload["requested_topics"] = list(self.requested_topics)
        return payload


@dataclass(frozen=True, slots=True)
class TaskAgentBinding:
    binding_id: str
    task_id: str
    flow_id: str
    agent_id: str
    agent_profile_id: str
    runtime_lane: str
    workflow_id: str
    memory_scope: str
    output_contract_id: str
    resource_policy_ref: str = ""
    validation_state: str = "unchecked"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentTaskCarryingProfile:
    agent_id: str
    display_name: str
    profile_type: str
    owner_system: str
    lifecycle_state: str
    carried_general_task_refs: tuple[str, ...] = ()
    carried_specific_task_refs: tuple[str, ...] = ()
    workflow_refs: tuple[str, ...] = ()
    projection_refs: tuple[str, ...] = ()
    validation_state: str = "unchecked"
    blocked_reasons: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "carried_general_task_refs",
            "carried_specific_task_refs",
            "workflow_refs",
            "projection_refs",
            "blocked_reasons",
        ):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True, slots=True)
class CoordinationTaskDefinition:
    graph_id: str
    title: str
    coordination_mode: str
    coordinator_agent_id: str
    task_family: str = ""
    domain_id: str = ""
    agent_group_id: str = ""
    participant_agent_ids: tuple[str, ...] = ()
    topology_template_id: str = ""
    shared_context_policy: str = "explicit_refs_only"
    memory_sharing_policy: str = "isolated_by_default"
    handoff_policy: str = "filtered_handoff"
    conflict_resolution_policy: str = "coordinator_review"
    output_merge_policy: str = "coordinator_final_merge"
    stop_conditions: tuple[str, ...] = ()
    subtask_refs: tuple[str, ...] = ()
    graph_nodes: tuple[dict[str, Any], ...] = ()
    graph_edges: tuple[dict[str, Any], ...] = ()
    communication_modes: tuple[str, ...] = ()
    enabled: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def graph_ref(self) -> str:
        return str(self.graph_id or "").strip()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["graph_id"] = str(self.graph_id or "").strip()
        payload["graph_ref"] = self.graph_ref
        payload["participant_agent_ids"] = list(self.participant_agent_ids)
        payload["stop_conditions"] = list(self.stop_conditions)
        payload["subtask_refs"] = list(self.subtask_refs)
        payload["graph_nodes"] = [dict(item) for item in self.graph_nodes]
        payload["graph_edges"] = [dict(item) for item in self.graph_edges]
        payload["communication_modes"] = list(self.communication_modes)
        return payload


@dataclass(frozen=True, slots=True)
class TaskCommunicationProtocol:
    protocol_id: str
    title: str
    message_types: tuple[str, ...] = ()
    payload_contracts: tuple[str, ...] = ()
    signal_rules: tuple[str, ...] = ()
    handoff_rules: tuple[str, ...] = ()
    ack_policy: str = "explicit_ack"
    timeout_policy: str = "fail_closed"
    error_signal_policy: str = "raise_to_coordinator"
    enabled: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_communication_protocol"

    def __post_init__(self) -> None:
        if self.authority != "task_system.task_communication_protocol":
            raise ValueError("TaskCommunicationProtocol authority must be task_system.task_communication_protocol")
        if not self.protocol_id:
            raise ValueError("TaskCommunicationProtocol requires protocol_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["message_types"] = list(self.message_types)
        payload["payload_contracts"] = list(self.payload_contracts)
        payload["signal_rules"] = list(self.signal_rules)
        payload["handoff_rules"] = list(self.handoff_rules)
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
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["nodes"] = [dict(item) for item in self.nodes]
        payload["edges"] = [dict(item) for item in self.edges]
        payload["handoff_rules"] = [dict(item) for item in self.handoff_rules]
        return payload


@dataclass(frozen=True, slots=True)
class AgentTaskConnectionProfile:
    profile_id: str
    agent_id: str
    agent_profile_id: str
    owner_system: str
    profile_type: str
    lifecycle_state: str
    task_family_refs: tuple[str, ...] = ()
    task_refs: tuple[str, ...] = ()
    flow_refs: tuple[str, ...] = ()
    binding_refs: tuple[str, ...] = ()
    workflow_refs: tuple[str, ...] = ()
    topology_refs: tuple[str, ...] = ()
    default_flow_ref: str = ""
    default_workflow_ref: str = ""
    default_runtime_lane_hint: str = ""
    validation_state: str = "unchecked"
    blocked_reasons: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "task_family_refs",
            "task_refs",
            "flow_refs",
            "binding_refs",
            "workflow_refs",
            "topology_refs",
            "blocked_reasons",
        ):
            payload[key] = list(payload[key])
        return payload
