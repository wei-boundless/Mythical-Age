from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ContextContractNode:
    node_id: str
    semantic_kind: str
    semantic_layer: str
    semantic_time: str
    authority: str
    source_ref: str
    scope: str
    ttl: str
    visibility: str
    agent_use_contract: str
    commit_policy: str
    replay_policy: str
    cache_tier: str
    content_mode: str = "full"
    refs: dict[str, Any] = field(default_factory=dict)
    supersedes: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["supersedes"] = list(self.supersedes)
        return payload


@dataclass(frozen=True, slots=True)
class ContextContractEdge:
    source_node_id: str
    target_node_id: str
    edge_kind: str
    authority: str = "harness.runtime.context_contract"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ContextContractManifest:
    packet_id: str
    invocation_kind: str
    nodes: tuple[ContextContractNode, ...] = ()
    edges: tuple[ContextContractEdge, ...] = ()
    agent_visible_order: tuple[str, ...] = ()
    hidden_transport_refs: tuple[str, ...] = ()
    physical_context_refs: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.context_contract"
    schema_version: str = "context_contract_manifest.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "authority": self.authority,
            "packet_id": self.packet_id,
            "invocation_kind": self.invocation_kind,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "agent_visible_order": list(self.agent_visible_order),
            "hidden_transport_refs": list(self.hidden_transport_refs),
            "physical_context_refs": list(self.physical_context_refs),
            "diagnostics": dict(self.diagnostics),
        }
