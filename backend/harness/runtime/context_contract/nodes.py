from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ContextContractNode:
    node_id: str
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
    agent_domain: str = ""
    agent_role: str = ""
    control_layer: str = ""
    time_scope: str = ""
    control_signal: str = ""
    feedback_route: str = ""
    physical_lane: str = ""
    cache_expectation: str = ""
    connection_contract_ref: str = ""
    provider_payload_segment_ref: str = ""
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
    edge_id: str = ""
    payload_identity: str = ""
    payload_schema: str = ""
    authority: str = "harness.runtime.context_contract"
    transport_or_store: str = ""
    consumer: str = ""
    failure_route: str = ""
    cache_expectation: str = ""
    connection_contract_ref: str = ""
    physical_lane: str = ""
    control_signal: str = ""
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
    schema: str = "context_contract_manifest"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
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


def context_contract_edge_id(edge_kind: str, source_node_id: str, target_node_id: str) -> str:
    return f"edge:{_safe_token(edge_kind)}:{_safe_token(source_node_id)}:{_safe_token(target_node_id)}"


def _safe_token(value: Any) -> str:
    text = str(value or "").strip()
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-", ".", ":"} else "_" for ch in text)
    return safe[:160] or "unknown"
