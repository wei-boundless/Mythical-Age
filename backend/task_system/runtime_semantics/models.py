from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


NodeSemanticRole = Literal[
    "producer",
    "validator",
    "approver",
    "publisher",
    "aggregator",
    "router",
    "resource",
    "monitor",
]

EdgeSemanticRole = Literal[
    "activation",
    "data_input",
    "validation_input",
    "approval_input",
    "publish_input",
    "resource_read",
    "resource_write",
    "reference",
    "retry",
    "failure_route",
]

RuntimeArtifactState = Literal[
    "produced",
    "pending_validation",
    "validated",
    "published",
    "rejected",
    "superseded",
    "quarantined",
]


@dataclass(frozen=True, slots=True)
class NodeRuntimeSemantics:
    node_id: str
    semantic_role: NodeSemanticRole
    produces_states: tuple[RuntimeArtifactState, ...] = ()
    consumes_states: tuple[RuntimeArtifactState, ...] = ()
    lifecycle_coordinate: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["produces_states"] = list(self.produces_states)
        payload["consumes_states"] = list(self.consumes_states)
        payload["evidence"] = list(self.evidence)
        return payload


@dataclass(frozen=True, slots=True)
class EdgeRuntimeSemantics:
    edge_id: str
    source_node_id: str
    target_node_id: str
    semantic_role: EdgeSemanticRole
    required_source_state: RuntimeArtifactState = "produced"
    blocks_activation: bool = True
    carries_data: bool = True
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = list(self.evidence)
        return payload


@dataclass(frozen=True, slots=True)
class RuntimeSemanticsDiagnostic:
    code: str
    message: str
    severity: str = "warning"
    scope: str = "graph"
    ref_id: str = ""
    field: str = ""
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RuntimeSemanticsManifest:
    graph_id: str
    node_semantics: tuple[NodeRuntimeSemantics, ...] = ()
    edge_semantics: tuple[EdgeRuntimeSemantics, ...] = ()
    artifact_lifecycle_states: tuple[RuntimeArtifactState, ...] = (
        "produced",
        "pending_validation",
        "validated",
        "published",
        "rejected",
        "superseded",
        "quarantined",
    )
    step_policy: dict[str, Any] = field(default_factory=dict)
    legacy_fields: tuple[dict[str, Any], ...] = ()
    diagnostics: tuple[RuntimeSemanticsDiagnostic, ...] = ()
    summary: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.runtime_semantics_manifest"

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "graph_id": self.graph_id,
            "node_semantics": [item.to_dict() for item in self.node_semantics],
            "edge_semantics": [item.to_dict() for item in self.edge_semantics],
            "artifact_lifecycle_states": list(self.artifact_lifecycle_states),
            "step_policy": dict(self.step_policy),
            "legacy_fields": [dict(item) for item in self.legacy_fields],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "summary": dict(self.summary),
        }


