from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .language import validate_harness_edge_config


GRAPH_HARNESS_CONFIG_SCHEMA_VERSION = "graph_harness_config.v1"
GRAPH_HARNESS_CONFIG_AUTHORITY = "harness.graph_harness_config"
GRAPH_STRUCTURE_VERSION = "graph_structure.v1"
GRAPH_EDGE_STATUSES = {"pending", "ready", "skipped", "source_failed", "waiting_human", "blocked"}
GRAPH_TRANSITION_TRIGGER_TYPES = {
    "initialize",
    "node_result",
    "human_gate_decision",
    "human_edge_decision",
    "failure_reset",
    "resume_requeue",
}


def _session_scope_key(*, workspace_view: str, task_environment_id: str, project_id: str) -> str:
    return "|".join(
        [
            str(workspace_view or "").strip() or "chat",
            str(task_environment_id or "").strip(),
            str(project_id or "").strip(),
        ]
    )


@dataclass(frozen=True, slots=True)
class GraphHarnessConfig:
    config_id: str
    graph_id: str
    graph_title: str
    publish_version: str
    config_schema_version: str = GRAPH_HARNESS_CONFIG_SCHEMA_VERSION
    authority: str = GRAPH_HARNESS_CONFIG_AUTHORITY
    status: str = "published"
    content_hash: str = ""
    published_at: float = 0.0
    task_environment_id: str = ""
    root_task_ref: str = ""
    control: dict[str, Any] = field(default_factory=dict)
    nodes: tuple[dict[str, Any], ...] = ()
    edges: tuple[dict[str, Any], ...] = ()
    loop_frames: tuple[dict[str, Any], ...] = ()
    environment: dict[str, Any] = field(default_factory=dict)
    resources: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    permissions: dict[str, Any] = field(default_factory=dict)
    tools: dict[str, Any] = field(default_factory=dict)
    agents: dict[str, Any] = field(default_factory=dict)
    contracts: dict[str, Any] = field(default_factory=dict)
    composition_sources: tuple[dict[str, Any], ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority_map: dict[str, Any] = field(default_factory=dict)
    source_refs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != GRAPH_HARNESS_CONFIG_AUTHORITY:
            raise ValueError("GraphHarnessConfig authority must be harness.graph_harness_config")
        if self.config_schema_version != GRAPH_HARNESS_CONFIG_SCHEMA_VERSION:
            raise ValueError("unsupported GraphHarnessConfig schema version")
        if not self.config_id:
            raise ValueError("GraphHarnessConfig requires config_id")
        if not self.graph_id:
            raise ValueError("GraphHarnessConfig requires graph_id")
        if self.status not in {"published", "archived"}:
            raise ValueError("GraphHarnessConfig status must be published or archived")
        _validate_node_executors(self.nodes)
        _validate_edges(self.nodes, self.edges)

    def content_payload(self) -> dict[str, Any]:
        payload = self.to_dict()
        payload.pop("config_id", None)
        payload.pop("content_hash", None)
        payload.pop("published_at", None)
        return payload

    def expected_content_hash(self) -> str:
        return stable_hash(self.content_payload())

    def structural_payload(self) -> dict[str, Any]:
        return {
            "authority": "harness.graph_structure_identity",
            "structure_version": GRAPH_STRUCTURE_VERSION,
            "graph_id": self.graph_id,
            "root_task_ref": self.root_task_ref,
            "control": _structure_mapping(
                self.control,
                include_keys={
                    "max_active_nodes",
                    "scheduler",
                    "state_machine",
                    "loop_policy",
                    "human_gate_policy",
                    "checkpoint_policy",
                },
            ),
            "nodes": [_structural_node_payload(dict(item)) for item in self.nodes],
            "edges": [_structural_edge_payload(dict(item)) for item in self.edges],
            "loop_frames": [_structure_mapping(dict(item)) for item in self.loop_frames],
            "resources": _structure_mapping(self.resources),
            "memory": _structure_mapping(self.memory),
            "artifacts": _structure_mapping(self.artifacts),
            "environment": _structure_mapping(
                self.environment,
                include_keys={
                    "storage_space",
                    "file_access_tables",
                    "memory_space",
                    "artifact_policy",
                    "file_management",
                },
            ),
            "contracts": _structure_mapping(
                self.contracts,
                include_keys={
                    "node_protocol_index",
                    "node_contract_index",
                    "resource_contract_index",
                    "edge_contract_index",
                    "graph_binding_contract",
                    "maintenance_contract",
                    "output_contract_index",
                    "memory_contract_index",
                    "artifact_contract_index",
                },
            ),
        }

    def expected_structural_hash(self) -> str:
        return stable_hash(self.structural_payload())

    def with_content_identity(self, *, config_id: str = "", published_at: float = 0.0) -> "GraphHarnessConfig":
        payload = self.to_dict()
        payload["content_hash"] = stable_hash(self.content_payload())
        if config_id:
            payload["config_id"] = config_id
        if published_at:
            payload["published_at"] = published_at
        return graph_harness_config_from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["nodes"] = [dict(item) for item in self.nodes]
        payload["edges"] = [dict(item) for item in self.edges]
        payload["loop_frames"] = [dict(item) for item in self.loop_frames]
        payload["composition_sources"] = [dict(item) for item in self.composition_sources]
        return payload


@dataclass(frozen=True, slots=True)
class GraphRuntimeEnvelope:
    envelope_id: str
    graph_run_id: str
    task_run_id: str
    session_id: str
    config_id: str
    config_hash: str
    graph_id: str
    structure_hash: str = ""
    structure_version: str = GRAPH_STRUCTURE_VERSION
    config_snapshot_id: str = ""
    config_snapshot_hash: str = ""
    initial_inputs: dict[str, Any] = field(default_factory=dict)
    static_topology_view: dict[str, Any] = field(default_factory=dict)
    contract_index: dict[str, Any] = field(default_factory=dict)
    state_machine_spec: dict[str, Any] = field(default_factory=dict)
    loop_control_spec: dict[str, Any] = field(default_factory=dict)
    runtime_services_ref: str = ""
    permission_scope: dict[str, Any] = field(default_factory=dict)
    file_scope: dict[str, Any] = field(default_factory=dict)
    memory_scope: dict[str, Any] = field(default_factory=dict)
    sandbox_scope: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    authority: str = "harness.graph_runtime_envelope"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GraphRun:
    graph_run_id: str
    task_run_id: str
    session_id: str
    graph_id: str
    config_id: str
    config_hash: str
    structure_hash: str = ""
    structure_version: str = GRAPH_STRUCTURE_VERSION
    config_snapshot_id: str = ""
    config_snapshot_hash: str = ""
    workspace_view: str = "chat"
    task_environment_id: str = ""
    project_id: str = ""
    session_scope_key: str = ""
    status: str = "running"
    created_at: float = 0.0
    updated_at: float = 0.0
    terminal_reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.graph_run"

    def __post_init__(self) -> None:
        if self.authority != "harness.graph_run":
            raise ValueError("GraphRun authority must be harness.graph_run")
        if not self.graph_run_id:
            raise ValueError("GraphRun requires graph_run_id")
        if not self.task_run_id:
            raise ValueError("GraphRun requires task_run_id")
        if not self.config_id:
            raise ValueError("GraphRun requires config_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if not payload.get("session_scope_key"):
            payload["session_scope_key"] = _session_scope_key(
                workspace_view=self.workspace_view,
                task_environment_id=self.task_environment_id,
                project_id=self.project_id,
            )
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GraphRun":
        return cls(
            graph_run_id=str(payload.get("graph_run_id") or ""),
            task_run_id=str(payload.get("task_run_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            graph_id=str(payload.get("graph_id") or ""),
            config_id=str(payload.get("config_id") or ""),
            config_hash=str(payload.get("config_hash") or ""),
            structure_hash=str(payload.get("structure_hash") or dict(payload.get("diagnostics") or {}).get("graph_structure_hash") or ""),
            structure_version=str(payload.get("structure_version") or dict(payload.get("diagnostics") or {}).get("graph_structure_version") or GRAPH_STRUCTURE_VERSION),
            config_snapshot_id=str(payload.get("config_snapshot_id") or payload.get("config_id") or ""),
            config_snapshot_hash=str(payload.get("config_snapshot_hash") or payload.get("config_hash") or ""),
            workspace_view=str(payload.get("workspace_view") or "chat"),
            task_environment_id=str(payload.get("task_environment_id") or ""),
            project_id=str(payload.get("project_id") or dict(payload.get("diagnostics") or {}).get("project_id") or ""),
            session_scope_key=str(payload.get("session_scope_key") or ""),
            status=str(payload.get("status") or "running"),
            created_at=float(payload.get("created_at") or 0.0),
            updated_at=float(payload.get("updated_at") or 0.0),
            terminal_reason=str(payload.get("terminal_reason") or ""),
            diagnostics=dict(payload.get("diagnostics") or {}),
            authority=str(payload.get("authority") or "harness.graph_run"),
        )


@dataclass(frozen=True, slots=True)
class GraphLoopState:
    state_id: str
    graph_run_id: str
    task_run_id: str
    session_id: str
    config_id: str
    config_hash: str
    graph_id: str
    structure_hash: str = ""
    structure_version: str = GRAPH_STRUCTURE_VERSION
    config_snapshot_id: str = ""
    config_snapshot_hash: str = ""
    status: str = "created"
    node_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    edge_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    ready_node_ids: tuple[str, ...] = ()
    running_node_ids: tuple[str, ...] = ()
    completed_node_ids: tuple[str, ...] = ()
    failed_node_ids: tuple[str, ...] = ()
    blocked_node_ids: tuple[str, ...] = ()
    initial_inputs: dict[str, Any] = field(default_factory=dict)
    active_work_orders: dict[str, str] = field(default_factory=dict)
    work_order_index: dict[str, dict[str, Any]] = field(default_factory=dict)
    result_index: dict[str, dict[str, Any]] = field(default_factory=dict)
    result_history: dict[str, tuple[dict[str, Any], ...]] = field(default_factory=dict)
    loop_state: dict[str, Any] = field(default_factory=dict)
    event_cursor: int = -1
    terminal_reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.graph_loop_state"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ready_node_ids"] = list(self.ready_node_ids)
        payload["running_node_ids"] = list(self.running_node_ids)
        payload["completed_node_ids"] = list(self.completed_node_ids)
        payload["failed_node_ids"] = list(self.failed_node_ids)
        payload["blocked_node_ids"] = list(self.blocked_node_ids)
        payload["result_history"] = {
            key: [dict(item) for item in value]
            for key, value in self.result_history.items()
        }
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GraphLoopState":
        return cls(
            state_id=str(payload.get("state_id") or ""),
            graph_run_id=str(payload.get("graph_run_id") or ""),
            task_run_id=str(payload.get("task_run_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            config_id=str(payload.get("config_id") or ""),
            config_hash=str(payload.get("config_hash") or ""),
            graph_id=str(payload.get("graph_id") or ""),
            structure_hash=str(payload.get("structure_hash") or dict(payload.get("diagnostics") or {}).get("graph_structure_hash") or ""),
            structure_version=str(payload.get("structure_version") or dict(payload.get("diagnostics") or {}).get("graph_structure_version") or GRAPH_STRUCTURE_VERSION),
            config_snapshot_id=str(payload.get("config_snapshot_id") or payload.get("config_id") or ""),
            config_snapshot_hash=str(payload.get("config_snapshot_hash") or payload.get("config_hash") or ""),
            status=str(payload.get("status") or "created"),
            node_states={str(key): dict(value) for key, value in dict(payload.get("node_states") or {}).items()},
            edge_states={str(key): dict(value) for key, value in dict(payload.get("edge_states") or {}).items()},
            ready_node_ids=tuple(str(item) for item in list(payload.get("ready_node_ids") or []) if str(item)),
            running_node_ids=tuple(str(item) for item in list(payload.get("running_node_ids") or []) if str(item)),
            completed_node_ids=tuple(str(item) for item in list(payload.get("completed_node_ids") or []) if str(item)),
            failed_node_ids=tuple(str(item) for item in list(payload.get("failed_node_ids") or []) if str(item)),
            blocked_node_ids=tuple(str(item) for item in list(payload.get("blocked_node_ids") or []) if str(item)),
            initial_inputs=dict(payload.get("initial_inputs") or {}),
            active_work_orders={str(key): str(value) for key, value in dict(payload.get("active_work_orders") or {}).items()},
            work_order_index={str(key): dict(value) for key, value in dict(payload.get("work_order_index") or {}).items()},
            result_index={str(key): dict(value) for key, value in dict(payload.get("result_index") or {}).items()},
            result_history={
                str(key): tuple(dict(item) for item in list(value or []) if isinstance(item, dict))
                for key, value in dict(payload.get("result_history") or {}).items()
            },
            loop_state=dict(payload.get("loop_state") or {}),
            event_cursor=_int_or_default(payload.get("event_cursor"), -1),
            terminal_reason=str(payload.get("terminal_reason") or ""),
            diagnostics=dict(payload.get("diagnostics") or {}),
            authority=str(payload.get("authority") or "harness.graph_loop_state"),
        )


@dataclass(frozen=True, slots=True)
class GraphEdgeStateRecord:
    edge_id: str
    source_node_id: str
    target_node_id: str
    status: str = "pending"
    reason: str = ""
    decision_ref: str = ""
    source_result_ref: str = ""
    human_decision_ref: str = ""
    selected_handle: str = ""
    policy_snapshot: dict[str, Any] = field(default_factory=dict)
    graph_clock_seq: int = 0
    updated_at: float = 0.0
    authority: str = "harness.graph.edge_state"

    def __post_init__(self) -> None:
        if self.status not in GRAPH_EDGE_STATUSES:
            raise ValueError(f"unsupported GraphEdgeState status: {self.status}")
        if not self.edge_id:
            raise ValueError("GraphEdgeState requires edge_id")

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GraphEdgeStateRecord":
        return cls(
            edge_id=str(payload.get("edge_id") or ""),
            source_node_id=str(payload.get("source_node_id") or ""),
            target_node_id=str(payload.get("target_node_id") or ""),
            status=str(payload.get("status") or "pending"),
            reason=str(payload.get("reason") or ""),
            decision_ref=str(payload.get("decision_ref") or ""),
            source_result_ref=str(payload.get("source_result_ref") or ""),
            human_decision_ref=str(payload.get("human_decision_ref") or ""),
            selected_handle=str(payload.get("selected_handle") or ""),
            policy_snapshot=dict(payload.get("policy_snapshot") or {}),
            graph_clock_seq=_int_or_default(payload.get("graph_clock_seq"), 0),
            updated_at=float(payload.get("updated_at") or 0.0),
            authority=str(payload.get("authority") or "harness.graph.edge_state"),
        )


@dataclass(frozen=True, slots=True)
class GraphTransitionInput:
    trigger_type: str
    graph_run_id: str
    config_id: str
    config_hash: str
    graph_clock_seq: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.graph.transition_input"

    def __post_init__(self) -> None:
        if self.trigger_type not in GRAPH_TRANSITION_TRIGGER_TYPES:
            raise ValueError(f"unsupported GraphTransitionInput trigger_type: {self.trigger_type}")
        if not self.graph_run_id:
            raise ValueError("GraphTransitionInput requires graph_run_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GraphTransitionInput":
        return cls(
            trigger_type=str(payload.get("trigger_type") or ""),
            graph_run_id=str(payload.get("graph_run_id") or ""),
            config_id=str(payload.get("config_id") or ""),
            config_hash=str(payload.get("config_hash") or ""),
            graph_clock_seq=_int_or_default(payload.get("graph_clock_seq"), 0),
            payload=dict(payload.get("payload") or {}),
            authority=str(payload.get("authority") or "harness.graph.transition_input"),
        )


@dataclass(frozen=True, slots=True)
class GraphTransitionPlan:
    edge_updates: tuple[dict[str, Any], ...] = ()
    node_updates: tuple[dict[str, Any], ...] = ()
    blocked_reasons: tuple[dict[str, Any], ...] = ()
    events: tuple[dict[str, Any], ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.graph.transition_plan"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["edge_updates"] = [dict(item) for item in self.edge_updates]
        payload["node_updates"] = [dict(item) for item in self.node_updates]
        payload["blocked_reasons"] = [dict(item) for item in self.blocked_reasons]
        payload["events"] = [dict(item) for item in self.events]
        return payload


@dataclass(frozen=True, slots=True)
class GraphReadinessDecision:
    ready_node_ids: tuple[str, ...] = ()
    blocked_node_ids: tuple[str, ...] = ()
    waiting_node_ids: tuple[str, ...] = ()
    skipped_node_ids: tuple[str, ...] = ()
    reasons: dict[str, dict[str, Any]] = field(default_factory=dict)
    authority: str = "harness.graph.readiness_decision"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ready_node_ids"] = list(self.ready_node_ids)
        payload["blocked_node_ids"] = list(self.blocked_node_ids)
        payload["waiting_node_ids"] = list(self.waiting_node_ids)
        payload["skipped_node_ids"] = list(self.skipped_node_ids)
        return payload


@dataclass(frozen=True, slots=True)
class GraphNodeExecutionSlot:
    slot_id: str
    graph_identity: dict[str, Any] = field(default_factory=dict)
    node_contract: dict[str, Any] = field(default_factory=dict)
    edge_contracts: dict[str, Any] = field(default_factory=dict)
    memory_contract: dict[str, Any] = field(default_factory=dict)
    loop_contract: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)
    state_refs: dict[str, Any] = field(default_factory=dict)
    runtime_controls: dict[str, Any] = field(default_factory=dict)
    visibility: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.graph.node_execution_slot"

    def __post_init__(self) -> None:
        if self.authority != "harness.graph.node_execution_slot":
            raise ValueError("GraphNodeExecutionSlot authority must be harness.graph.node_execution_slot")
        if not self.slot_id:
            raise ValueError("GraphNodeExecutionSlot requires slot_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GraphNodeExecutionSlot":
        return cls(
            slot_id=str(payload.get("slot_id") or ""),
            graph_identity=dict(payload.get("graph_identity") or {}),
            node_contract=dict(payload.get("node_contract") or {}),
            edge_contracts=dict(payload.get("edge_contracts") or {}),
            memory_contract=dict(payload.get("memory_contract") or {}),
            loop_contract=dict(payload.get("loop_contract") or {}),
            output_contract=dict(payload.get("output_contract") or {}),
            state_refs=dict(payload.get("state_refs") or {}),
            runtime_controls=dict(payload.get("runtime_controls") or {}),
            visibility=dict(payload.get("visibility") or {}),
            authority=str(payload.get("authority") or "harness.graph.node_execution_slot"),
        )


@dataclass(frozen=True, slots=True)
class GraphNodeWorkOrder:
    work_order_id: str
    work_kind: str
    graph_run_id: str
    task_run_id: str
    node_id: str
    task_ref: str
    config_id: str
    config_hash: str
    structure_hash: str = ""
    structure_version: str = GRAPH_STRUCTURE_VERSION
    config_snapshot_id: str = ""
    config_snapshot_hash: str = ""
    executor_type: str = "agent"
    node_session_id: str = ""
    node_session_policy: dict[str, Any] = field(default_factory=dict)
    agent_id: str = ""
    agent_profile_id: str = ""
    message: str = ""
    explicit_inputs: dict[str, Any] = field(default_factory=dict)
    input_package: dict[str, Any] = field(default_factory=dict)
    graph_slot: dict[str, Any] = field(default_factory=dict)
    graph_state: dict[str, Any] = field(default_factory=dict)
    context_refs: dict[str, Any] = field(default_factory=dict)
    memory_view_request: dict[str, Any] = field(default_factory=dict)
    artifact_view_request: dict[str, Any] = field(default_factory=dict)
    file_view_request: dict[str, Any] = field(default_factory=dict)
    artifact_space_ref: str = ""
    memory_space_ref: str = ""
    file_access_table_refs: tuple[str, ...] = ()
    artifact_repository_targets: tuple[dict[str, Any], ...] = ()
    memory_repository_targets: tuple[dict[str, Any], ...] = ()
    permission_scope: dict[str, Any] = field(default_factory=dict)
    tool_scope: dict[str, Any] = field(default_factory=dict)
    expected_result_contract: dict[str, Any] = field(default_factory=dict)
    async_policy: dict[str, Any] = field(default_factory=dict)
    retry_policy: dict[str, Any] = field(default_factory=dict)
    timeout_policy: dict[str, Any] = field(default_factory=dict)
    dispatch_context: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    authority: str = "harness.graph_node_work_order"

    def __post_init__(self) -> None:
        if self.authority != "harness.graph_node_work_order":
            raise ValueError("GraphNodeWorkOrder authority must be harness.graph_node_work_order")
        if not self.work_order_id:
            raise ValueError("GraphNodeWorkOrder requires work_order_id")
        if self.work_kind not in {"agent", "tool", "human_gate"}:
            raise ValueError("GraphNodeWorkOrder work_kind is not supported")
        if not self.graph_run_id:
            raise ValueError("GraphNodeWorkOrder requires graph_run_id")
        if not self.task_run_id:
            raise ValueError("GraphNodeWorkOrder requires task_run_id")
        if not self.node_id:
            raise ValueError("GraphNodeWorkOrder requires node_id")
        if not self.task_ref:
            raise ValueError("GraphNodeWorkOrder requires task_ref")
        if not self.idempotency_key:
            object.__setattr__(self, "idempotency_key", f"{self.graph_run_id}:{self.node_id}:{stable_hash(self.explicit_inputs)}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["file_access_table_refs"] = list(self.file_access_table_refs)
        payload["artifact_repository_targets"] = [dict(item) for item in self.artifact_repository_targets]
        payload["memory_repository_targets"] = [dict(item) for item in self.memory_repository_targets]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GraphNodeWorkOrder":
        return cls(
            work_order_id=str(payload.get("work_order_id") or ""),
            work_kind=str(payload.get("work_kind") or "agent"),
            graph_run_id=str(payload.get("graph_run_id") or ""),
            task_run_id=str(payload.get("task_run_id") or ""),
            node_id=str(payload.get("node_id") or ""),
            config_id=str(payload.get("config_id") or ""),
            config_hash=str(payload.get("config_hash") or ""),
            structure_hash=str(payload.get("structure_hash") or dict(payload.get("dispatch_context") or {}).get("graph_structure_hash") or ""),
            structure_version=str(payload.get("structure_version") or dict(payload.get("dispatch_context") or {}).get("graph_structure_version") or GRAPH_STRUCTURE_VERSION),
            config_snapshot_id=str(payload.get("config_snapshot_id") or payload.get("config_id") or ""),
            config_snapshot_hash=str(payload.get("config_snapshot_hash") or payload.get("config_hash") or ""),
            task_ref=str(payload.get("task_ref") or ""),
            executor_type=str(payload.get("executor_type") or "agent"),
            node_session_id=str(payload.get("node_session_id") or ""),
            node_session_policy=dict(payload.get("node_session_policy") or {}),
            agent_id=str(payload.get("agent_id") or ""),
            agent_profile_id=str(payload.get("agent_profile_id") or ""),
            message=str(payload.get("message") or ""),
            explicit_inputs=dict(payload.get("explicit_inputs") or {}),
            input_package=dict(payload.get("input_package") or {}),
            graph_slot=dict(payload.get("graph_slot") or {}),
            graph_state=dict(payload.get("graph_state") or {}),
            context_refs=dict(payload.get("context_refs") or {}),
            memory_view_request=dict(payload.get("memory_view_request") or {}),
            artifact_view_request=dict(payload.get("artifact_view_request") or {}),
            file_view_request=dict(payload.get("file_view_request") or {}),
            artifact_space_ref=str(payload.get("artifact_space_ref") or ""),
            memory_space_ref=str(payload.get("memory_space_ref") or ""),
            file_access_table_refs=tuple(str(item) for item in list(payload.get("file_access_table_refs") or []) if str(item)),
            artifact_repository_targets=tuple(dict(item) for item in list(payload.get("artifact_repository_targets") or []) if isinstance(item, dict)),
            memory_repository_targets=tuple(dict(item) for item in list(payload.get("memory_repository_targets") or []) if isinstance(item, dict)),
            permission_scope=dict(payload.get("permission_scope") or {}),
            tool_scope=dict(payload.get("tool_scope") or {}),
            expected_result_contract=dict(payload.get("expected_result_contract") or {}),
            async_policy=dict(payload.get("async_policy") or {}),
            retry_policy=dict(payload.get("retry_policy") or {}),
            timeout_policy=dict(payload.get("timeout_policy") or {}),
            dispatch_context=dict(payload.get("dispatch_context") or {}),
            idempotency_key=str(payload.get("idempotency_key") or ""),
            authority=str(payload.get("authority") or "harness.graph_node_work_order"),
        )


@dataclass(frozen=True, slots=True)
class NodeResultEnvelope:
    result_id: str
    graph_run_id: str
    task_run_id: str
    node_id: str
    work_order_id: str
    executor_type: str = "agent"
    status: str = "completed"
    outputs: dict[str, Any] = field(default_factory=dict)
    decisions: dict[str, Any] = field(default_factory=dict)
    artifact_refs: tuple[str, ...] = ()
    memory_candidates: tuple[dict[str, Any], ...] = ()
    progress_receipts: tuple[dict[str, Any], ...] = ()
    artifact_materialization_receipts: tuple[dict[str, Any], ...] = ()
    memory_commit_receipts: tuple[dict[str, Any], ...] = ()
    handoff_summary: str = ""
    error: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    authority: str = "harness.graph_node_result_envelope"

    def __post_init__(self) -> None:
        if self.authority != "harness.graph_node_result_envelope":
            raise ValueError("NodeResultEnvelope authority must be harness.graph_node_result_envelope")
        if not self.result_id:
            raise ValueError("NodeResultEnvelope requires result_id")
        if not self.graph_run_id:
            raise ValueError("NodeResultEnvelope requires graph_run_id")
        if not self.task_run_id:
            raise ValueError("NodeResultEnvelope requires task_run_id")
        if not self.node_id:
            raise ValueError("NodeResultEnvelope requires node_id")
        if not self.work_order_id:
            raise ValueError("NodeResultEnvelope requires work_order_id")
        if self.status not in {"completed", "failed", "blocked", "waiting_human_gate"}:
            raise ValueError("NodeResultEnvelope status must be completed, failed, blocked, or waiting_human_gate")
        if self.status == "completed" and not (
            self.outputs
            or self.decisions
            or self.artifact_refs
            or self.memory_candidates
            or self.progress_receipts
            or self.artifact_materialization_receipts
            or self.memory_commit_receipts
            or self.handoff_summary
        ):
            raise ValueError("NodeResultEnvelope completed result requires outputs, decisions, refs, receipts, candidates, or handoff_summary")
        if self.status == "failed" and not str(dict(self.error or {}).get("reason") or "").strip():
            raise ValueError("NodeResultEnvelope failed result requires error.reason")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifact_refs"] = list(self.artifact_refs)
        payload["memory_candidates"] = [dict(item) for item in self.memory_candidates]
        payload["progress_receipts"] = [dict(item) for item in self.progress_receipts]
        payload["artifact_materialization_receipts"] = [dict(item) for item in self.artifact_materialization_receipts]
        payload["memory_commit_receipts"] = [dict(item) for item in self.memory_commit_receipts]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NodeResultEnvelope":
        return cls(
            result_id=str(payload.get("result_id") or ""),
            graph_run_id=str(payload.get("graph_run_id") or ""),
            task_run_id=str(payload.get("task_run_id") or ""),
            node_id=str(payload.get("node_id") or ""),
            work_order_id=str(payload.get("work_order_id") or ""),
            executor_type=str(payload.get("executor_type") or "agent"),
            status=str(payload.get("status") or "completed"),
            outputs=dict(payload.get("outputs") or {}),
            decisions=dict(payload.get("decisions") or {}),
            artifact_refs=tuple(str(item) for item in list(payload.get("artifact_refs") or []) if str(item)),
            memory_candidates=tuple(dict(item) for item in list(payload.get("memory_candidates") or []) if isinstance(item, dict)),
            progress_receipts=tuple(
                dict(item)
                for item in list(payload.get("progress_receipts") or [])
                if isinstance(item, dict)
            ),
            artifact_materialization_receipts=tuple(
                dict(item)
                for item in list(payload.get("artifact_materialization_receipts") or [])
                if isinstance(item, dict)
            ),
            memory_commit_receipts=tuple(
                dict(item)
                for item in list(payload.get("memory_commit_receipts") or [])
                if isinstance(item, dict)
            ),
            handoff_summary=str(payload.get("handoff_summary") or ""),
            error=dict(payload.get("error") or {}),
            diagnostics=dict(payload.get("diagnostics") or {}),
            created_at=float(payload.get("created_at") or 0.0),
            authority=str(payload.get("authority") or "harness.graph_node_result_envelope"),
        )


@dataclass(frozen=True, slots=True)
class GraphResultEnvelope:
    result_id: str
    graph_run_id: str
    task_run_id: str
    graph_id: str
    config_id: str
    status: str
    outputs: dict[str, Any] = field(default_factory=dict)
    artifact_refs: tuple[str, ...] = ()
    node_result_refs: tuple[str, ...] = ()
    terminal_reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    authority: str = "harness.graph_result_envelope"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifact_refs"] = list(self.artifact_refs)
        payload["node_result_refs"] = list(self.node_result_refs)
        return payload


def graph_harness_config_from_dict(payload: dict[str, Any]) -> GraphHarnessConfig:
    return GraphHarnessConfig(
        config_id=str(payload.get("config_id") or ""),
        graph_id=str(payload.get("graph_id") or ""),
        graph_title=str(payload.get("graph_title") or payload.get("title") or ""),
        publish_version=str(payload.get("publish_version") or "published"),
        config_schema_version=str(payload.get("config_schema_version") or GRAPH_HARNESS_CONFIG_SCHEMA_VERSION),
        authority=str(payload.get("authority") or GRAPH_HARNESS_CONFIG_AUTHORITY),
        status=str(payload.get("status") or "published"),
        content_hash=str(payload.get("content_hash") or ""),
        published_at=float(payload.get("published_at") or 0.0),
        task_environment_id=str(payload.get("task_environment_id") or ""),
        root_task_ref=str(payload.get("root_task_ref") or ""),
        control=dict(payload.get("control") or {}),
        nodes=tuple(dict(item) for item in list(payload.get("nodes") or []) if isinstance(item, dict)),
        edges=tuple(dict(item) for item in list(payload.get("edges") or []) if isinstance(item, dict)),
        loop_frames=tuple(dict(item) for item in list(payload.get("loop_frames") or []) if isinstance(item, dict)),
        environment=dict(payload.get("environment") or {}),
        resources=dict(payload.get("resources") or {}),
        memory=dict(payload.get("memory") or {}),
        artifacts=dict(payload.get("artifacts") or {}),
        permissions=dict(payload.get("permissions") or {}),
        tools=dict(payload.get("tools") or {}),
        agents=dict(payload.get("agents") or {}),
        contracts=dict(payload.get("contracts") or {}),
        composition_sources=tuple(dict(item) for item in list(payload.get("composition_sources") or []) if isinstance(item, dict)),
        diagnostics=dict(payload.get("diagnostics") or {}),
        authority_map=dict(payload.get("authority_map") or {}),
        source_refs=dict(payload.get("source_refs") or {}),
    )


def _validate_node_executors(nodes: tuple[dict[str, Any], ...]) -> None:
    supported = {"agent", "resource", "human", "human_gate", "review_gate", "tool"}
    for node in nodes:
        node_id = str(dict(node).get("node_id") or "").strip()
        if not node_id:
            raise ValueError("GraphHarnessConfig node requires node_id")
        executor = dict(dict(node).get("executor") or {})
        executor_type = str(executor.get("executor_type") or "agent").strip() or "agent"
        if executor_type not in supported:
            raise ValueError(f"GraphHarnessConfig node executor_type is not supported: {node_id}")


def _validate_edges(nodes: tuple[dict[str, Any], ...], edges: tuple[dict[str, Any], ...]) -> None:
    nodes_by_id = {str(dict(node).get("node_id") or ""): dict(node) for node in nodes if str(dict(node).get("node_id") or "")}
    for edge in edges:
        validate_harness_edge_config(dict(edge), nodes_by_id=nodes_by_id)


def _structural_node_payload(node: dict[str, Any]) -> dict[str, Any]:
    executor = dict(node.get("executor") or {})
    loop = dict(node.get("loop") or {})
    metadata = dict(node.get("metadata") or {})
    runtime_profile = dict(metadata.get("runtime_profile") or metadata.get("runtime") or {})
    runtime_policy = dict(runtime_profile.get("runtime_policy") or runtime_profile.get("execution_policy") or {})
    return _drop_empty(
        {
            "node_id": str(node.get("node_id") or ""),
            "node_type": str(node.get("node_type") or ""),
            "executor": _structure_mapping(
                executor,
                include_keys={"executor_type", "task_ref", "agent_id", "agent_profile_id", "resource_kind"},
            ),
            "loop": _structure_mapping(loop),
            "resource": _structure_mapping(dict(node.get("resource") or {})),
            "memory": _structure_mapping(dict(node.get("memory") or {})),
            "artifacts": _structure_mapping(dict(node.get("artifacts") or {})),
            "tools": _structure_mapping(dict(node.get("tools") or {})),
            "permissions": _structure_mapping(dict(node.get("permissions") or {})),
            "runtime_authorization": _structure_mapping(
                runtime_policy,
                include_keys={
                    "tool_exposure_policy",
                    "subagent_policy",
                    "network_policy",
                    "approval_policy",
                    "permission_policy",
                    "artifact_policy",
                    "memory_policy",
                },
            ),
            "output_contract": _structure_mapping(dict(node.get("output_contract") or {})),
            "input_contract": _structure_mapping(dict(node.get("input_contract") or {})),
        }
    )


def _structural_edge_payload(edge: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(
        {
            "edge_id": str(edge.get("edge_id") or ""),
            "source_node_id": str(edge.get("source_node_id") or ""),
            "target_node_id": str(edge.get("target_node_id") or ""),
            "edge_type": str(edge.get("edge_type") or ""),
            "semantic_role": str(edge.get("semantic_role") or ""),
            "scheduler_role": str(edge.get("scheduler_role") or ""),
            "route": _structure_mapping(dict(edge.get("route") or {})),
            "memory": _structure_mapping(dict(edge.get("memory") or {})),
            "artifact": _structure_mapping(dict(edge.get("artifact") or {})),
            "contract": _structure_mapping(dict(edge.get("contract") or {})),
            "delivery_policy": _structure_mapping(dict(edge.get("delivery_policy") or {})),
        }
    )


def _structure_mapping(value: Any, *, include_keys: set[str] | None = None) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            normalized_key = str(key or "")
            if include_keys is not None and normalized_key not in include_keys:
                continue
            if _runtime_only_structure_key(normalized_key):
                continue
            child = _structure_mapping(item)
            if child in ({}, [], (), "", None):
                continue
            result[normalized_key] = child
        return result
    if isinstance(value, list | tuple):
        return [_structure_mapping(item) for item in value if _structure_mapping(item) not in ({}, [], (), "", None)]
    return value


def _runtime_only_structure_key(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    if normalized in {
        "prompt",
        "prompt_text",
        "system_prompt",
        "developer_prompt",
        "user_prompt",
        "model",
        "model_family",
        "provider",
        "provider_family",
        "credential_ref",
        "api_key",
        "max_output_tokens",
        "preferred_output_tokens",
        "min_output_tokens",
        "timeout_seconds",
        "temperature",
        "reasoning_effort",
        "thinking_mode",
        "response_format",
        "structured_output",
        "cache_policy",
        "prompt_cache",
        "prompt_cache_policy",
    }:
        return True
    return False


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ({}, [], (), "", None)}


def stable_hash(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def safe_id(value: str, *, limit: int = 120) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or "")).strip("_")
    return (safe or "graph")[:limit]


def stable_safe_id(value: str, *, limit: int = 180, hash_chars: int = 16) -> str:
    raw = str(value or "")
    digest = stable_hash(raw)[: max(8, min(64, int(hash_chars or 16)))]
    safe = safe_id(raw, limit=max(1, int(limit) - len(digest) - 1))
    candidate = f"{safe or 'graph'}_{digest}"
    if len(candidate) <= limit:
        return candidate
    if int(limit) <= len(digest):
        return digest[: max(1, int(limit))]
    prefix_limit = max(1, int(limit) - len(digest) - 1)
    return f"{(safe or 'graph')[:prefix_limit].strip('_') or 'graph'}_{digest}"


def _int_or_default(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
