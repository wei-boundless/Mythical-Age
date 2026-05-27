from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskGraphPhaseState:
    phase_id: str
    status: str = "pending"
    node_ids: tuple[str, ...] = ()
    ready_node_ids: tuple[str, ...] = ()
    running_node_ids: tuple[str, ...] = ()
    completed_node_ids: tuple[str, ...] = ()
    blocked_node_ids: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["node_ids"] = list(self.node_ids)
        payload["ready_node_ids"] = list(self.ready_node_ids)
        payload["running_node_ids"] = list(self.running_node_ids)
        payload["completed_node_ids"] = list(self.completed_node_ids)
        payload["blocked_node_ids"] = list(self.blocked_node_ids)
        return payload


@dataclass(frozen=True, slots=True)
class TaskGraphNodeRunState:
    node_id: str
    status: str = "pending"
    phase_id: str = ""
    sequence_index: int = 0
    timeline_group_id: str = ""
    execution_mode: str = "sync"
    wait_policy: str = "wait_all_upstream_completed"
    join_policy: str = "all_success"
    upstream_node_ids: tuple[str, ...] = ()
    downstream_node_ids: tuple[str, ...] = ()
    blocked_reasons: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["upstream_node_ids"] = list(self.upstream_node_ids)
        payload["downstream_node_ids"] = list(self.downstream_node_ids)
        payload["blocked_reasons"] = list(self.blocked_reasons)
        return payload


@dataclass(frozen=True, slots=True)
class TaskGraphEdgeHandoffState:
    edge_id: str
    source_node_id: str
    target_node_id: str
    status: str = "pending"
    ack_required: bool = True
    ack_policy: str = "explicit_ack"
    wait_policy: str = ""
    failure_propagation_policy: str = "fail_downstream"
    result_delivery_policy: str = "contract_payload_and_refs"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskGraphSchedulerState:
    graph_id: str
    mode: str = "shadow"
    phase_states: tuple[TaskGraphPhaseState, ...] = ()
    node_states: tuple[TaskGraphNodeRunState, ...] = ()
    edge_states: tuple[TaskGraphEdgeHandoffState, ...] = ()
    ready_node_ids: tuple[str, ...] = ()
    blocked_node_ids: tuple[str, ...] = ()
    running_node_ids: tuple[str, ...] = ()
    completed_node_ids: tuple[str, ...] = ()
    failed_node_ids: tuple[str, ...] = ()
    terminal_status: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_graph_scheduler_state"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["phase_states"] = [item.to_dict() for item in self.phase_states]
        payload["node_states"] = [item.to_dict() for item in self.node_states]
        payload["edge_states"] = [item.to_dict() for item in self.edge_states]
        payload["ready_node_ids"] = list(self.ready_node_ids)
        payload["blocked_node_ids"] = list(self.blocked_node_ids)
        payload["running_node_ids"] = list(self.running_node_ids)
        payload["completed_node_ids"] = list(self.completed_node_ids)
        payload["failed_node_ids"] = list(self.failed_node_ids)
        return payload


