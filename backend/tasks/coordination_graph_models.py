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
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskGraphRuntimeEdge:
    edge_id: str
    source_node_id: str
    target_node_id: str
    mode: str
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
    issues: tuple[TaskGraphRuntimeValidationIssue, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["nodes"] = [item.to_dict() for item in self.nodes]
        payload["edges"] = [item.to_dict() for item in self.edges]
        payload["issues"] = [item.to_dict() for item in self.issues]
        payload["graph_ref"] = self.graph_ref or self.graph_id
        payload["valid"] = self.valid
        return payload
