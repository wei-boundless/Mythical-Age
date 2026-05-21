from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskGraphRuntimeNode:
    node_id: str
    title: str
    node_type: str
    role: str
    agent_id: str = ""
    runtime_lane: str = ""
    projection_id: str = ""
    task_id: str = ""
    task_family: str = ""
    executor_policy: dict[str, Any] = field(default_factory=dict)
    execution_mode: str = "sync"
    wait_policy: str = "wait_all_upstream_completed"
    join_policy: str = "all_success"
    dispatch_group: str = ""
    phase_id: str = ""
    sequence_index: int = 0
    timeline_group_id: str = ""
    blocks_phase_exit: bool = True
    context_visibility_policy: dict[str, Any] = field(default_factory=dict)
    memory_read_policy: dict[str, Any] = field(default_factory=dict)
    memory_writeback_policy: dict[str, Any] = field(default_factory=dict)
    dynamic_memory_read_policy: dict[str, Any] = field(default_factory=dict)
    artifact_policy: dict[str, Any] = field(default_factory=dict)
    stream_policy: dict[str, Any] = field(default_factory=dict)
    review_gate_policy: dict[str, Any] = field(default_factory=dict)
    loop_policy: dict[str, Any] = field(default_factory=dict)
    monitor_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskGraphRuntimeEdge:
    edge_id: str
    source_node_id: str
    target_node_id: str
    mode: str
    payload_contract_id: str = ""
    a2a_message_type: str = "message/send"
    ack_required: bool = True
    ack_policy: str = "explicit_ack"
    wait_policy: str = ""
    failure_propagation_policy: str = "fail_downstream"
    result_delivery_policy: str = "contract_payload_and_refs"
    context_filter_policy: dict[str, Any] = field(default_factory=dict)
    artifact_ref_policy: dict[str, Any] = field(default_factory=dict)
    working_memory_handoff_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskGraphModuleRuntimePlan:
    plan_id: str
    importing_graph_id: str
    unit_id: str
    runtime_node_id: str
    linked_graph_id: str
    version_ref: str = ""
    handoff_contract_id: str = ""
    input_port_id: str = "input.default"
    output_port_id: str = "output.default"
    isolation_policy: str = "isolated_per_graph_module_run"
    visibility_policy: str = "committed_only"
    detach_policy: str = "preserve_version_anchor"
    phase_id: str = ""
    sequence_index: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskGraphRuntimeValidationIssue:
    code: str
    message: str
    severity: str = "error"
    node_id: str = ""
    edge_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskGraphRuntimeSpec:
    graph_id: str
    domain_id: str
    task_family: str
    coordinator_agent_id: str
    graph_ref: str = ""
    agent_group_id: str = ""
    nodes: tuple[TaskGraphRuntimeNode, ...] = ()
    edges: tuple[TaskGraphRuntimeEdge, ...] = ()
    subtask_refs: tuple[str, ...] = ()
    communication_modes: tuple[str, ...] = ()
    start_node_ids: tuple[str, ...] = ()
    terminal_node_ids: tuple[str, ...] = ()
    resource_nodes: tuple[dict[str, Any], ...] = ()
    temporal_edges: tuple[dict[str, Any], ...] = ()
    memory_edges: tuple[dict[str, Any], ...] = ()
    artifact_context_edges: tuple[dict[str, Any], ...] = ()
    revision_edges: tuple[dict[str, Any], ...] = ()
    loop_frames: tuple[dict[str, Any], ...] = ()
    graph_module_runtime_plans: tuple[TaskGraphModuleRuntimePlan, ...] = ()
    memory_matrix: dict[str, Any] = field(default_factory=dict)
    issues: tuple[TaskGraphRuntimeValidationIssue, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["nodes"] = [item.to_dict() for item in self.nodes]
        payload["edges"] = [item.to_dict() for item in self.edges]
        payload["resource_nodes"] = [dict(item) for item in self.resource_nodes]
        payload["temporal_edges"] = [dict(item) for item in self.temporal_edges]
        payload["memory_edges"] = [dict(item) for item in self.memory_edges]
        payload["artifact_context_edges"] = [dict(item) for item in self.artifact_context_edges]
        payload["revision_edges"] = [dict(item) for item in self.revision_edges]
        payload["loop_frames"] = [dict(item) for item in self.loop_frames]
        payload["graph_module_runtime_plans"] = [item.to_dict() for item in self.graph_module_runtime_plans]
        payload["graph_modules"] = payload["graph_module_runtime_plans"]
        payload["memory_matrix"] = dict(self.memory_matrix)
        payload["issues"] = [item.to_dict() for item in self.issues]
        payload["graph_ref"] = self.graph_ref or self.graph_id
        payload["valid"] = self.valid
        return payload
