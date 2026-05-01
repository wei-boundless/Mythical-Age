from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


SearchSourceClass = Literal[
    "rag",
    "local_files",
    "web",
    "document",
    "data",
    "system_execution",
    "general",
]


@dataclass(frozen=True, slots=True)
class AgentCapability:
    agent_id: str
    name: str
    kind: str
    description: str
    bound_tools: list[str] = field(default_factory=list)
    protocol_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WorkerCapability:
    worker_id: str
    route: str
    name: str
    description: str
    operation_id: str
    agent_id: str
    transport: str
    model_visibility: str
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CapabilityBindingEdge:
    from_id: str
    from_label: str
    to_id: str
    to_label: str
    relation: str

    def to_operation_edge(self) -> dict[str, str]:
        return {
            "from": self.from_id,
            "from_label": self.from_label,
            "to": self.to_id,
            "to_label": self.to_label,
            "relation": self.relation,
        }


@dataclass(frozen=True, slots=True)
class CapabilityBindingGraph:
    agent_nodes: list[AgentCapability] = field(default_factory=list)
    worker_nodes: list[WorkerCapability] = field(default_factory=list)
    skill_tool_edges: list[CapabilityBindingEdge] = field(default_factory=list)
    agent_tool_edges: list[CapabilityBindingEdge] = field(default_factory=list)
    worker_operation_edges: list[CapabilityBindingEdge] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_operation_payload(self) -> dict[str, Any]:
        return {
            "agent_nodes": [node.to_dict() for node in self.agent_nodes],
            "worker_nodes": [node.to_dict() for node in self.worker_nodes],
            "skill_tool_edges": [edge.to_operation_edge() for edge in self.skill_tool_edges],
            "agent_tool_edges": [edge.to_operation_edge() for edge in self.agent_tool_edges],
            "worker_operation_edges": [edge.to_operation_edge() for edge in self.worker_operation_edges],
            "recommendations": list(self.recommendations),
        }


@dataclass(frozen=True, slots=True)
class CapabilityValidationIssue:
    severity: str
    code: str
    message: str
    subject: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)
