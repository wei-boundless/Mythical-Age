from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ExecutionNodeType = Literal["model", "tool", "mcp", "agent"]
CommitType = Literal["session_message", "session_memory", "durable_memory", "task_result", "artifact_graph", "title"]


@dataclass(slots=True, frozen=True)
class ExecutionNode:
    """Directive-owned execution unit, independent from query planner models."""

    node_id: str
    node_type: ExecutionNodeType
    executor: str
    directive_ref: str
    inputs: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    policy_refs: tuple[str, ...] = ()
    refs: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime_directive"

    def __post_init__(self) -> None:
        if self.authority != "runtime_directive":
            raise ValueError("ExecutionNode authority must come from runtime_directive")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["depends_on"] = list(self.depends_on)
        payload["policy_refs"] = list(self.policy_refs)
        return payload


@dataclass(slots=True, frozen=True)
class ExecutionEdge:
    source: str
    target: str
    edge_type: str = "depends_on"
    refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ExecutionGraph:
    graph_id: str
    task_id: str
    nodes: tuple[ExecutionNode, ...] = ()
    edges: tuple[ExecutionEdge, ...] = ()
    source_plan_id: str = ""
    refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "task_id": self.task_id,
            "nodes": [item.to_dict() for item in self.nodes],
            "edges": [item.to_dict() for item in self.edges],
            "source_plan_id": self.source_plan_id,
            "refs": dict(self.refs),
        }


@dataclass(slots=True, frozen=True)
class CommitCandidate:
    """Writeback request. It is denied until CommitGate explicitly allows it."""

    candidate_id: str
    commit_type: CommitType
    payload: dict[str, Any] = field(default_factory=dict)
    producer: str = ""
    allowed: bool = False
    reason: str = "pending_commit_gate"
    refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
