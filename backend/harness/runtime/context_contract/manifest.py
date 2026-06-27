from __future__ import annotations

from typing import Any

from .authority_rules import classify_context_spec, hidden_transport_node
from .diagnostics import diagnose_context_contract_manifest
from .nodes import ContextContractEdge, ContextContractManifest, ContextContractNode


def build_context_contract_manifest(
    *,
    packet_id: str,
    invocation_kind: str,
    message_specs: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    segment_plan: dict[str, Any] | None = None,
    include_provider_transport: bool = True,
) -> ContextContractManifest:
    nodes: list[ContextContractNode] = []
    for index, raw_spec in enumerate(list(message_specs or ())):
        spec = dict(raw_spec or {})
        classified = classify_context_spec(spec, index=index)
        nodes.append(
            ContextContractNode(
                node_id=classified["node_id"],
                semantic_kind=classified["semantic_kind"],
                semantic_layer=classified["semantic_layer"],
                semantic_time=classified["semantic_time"],
                authority=classified["authority"],
                source_ref=classified["source_ref"],
                scope=classified["scope"],
                ttl=classified["ttl"],
                visibility=classified["visibility"],
                agent_use_contract=classified["agent_use_contract"],
                commit_policy=classified["commit_policy"],
                replay_policy=classified["replay_policy"],
                cache_tier=classified["cache_tier"],
                content_mode=classified["content_mode"],
                refs=_refs_from_spec(spec),
                diagnostics={
                    "role": str(spec.get("role") or ""),
                    "kind": str(spec.get("kind") or ""),
                    "cache_scope": str(spec.get("cache_scope") or ""),
                    "cache_role": str(spec.get("cache_role") or ""),
                },
            )
        )
    if include_provider_transport:
        hidden = hidden_transport_node(packet_id)
        nodes.append(ContextContractNode(**hidden))
    node_payloads = [node.to_dict() for node in nodes]
    diagnostics = diagnose_context_contract_manifest(node_payloads)
    agent_visible_order = tuple(node.node_id for node in nodes if node.visibility == "agent_visible")
    hidden_transport_refs = tuple(node.node_id for node in nodes if node.visibility == "provider_transport")
    physical_context_refs = _physical_context_refs(segment_plan or {})
    edges = tuple(_sequence_edges(agent_visible_order))
    return ContextContractManifest(
        packet_id=packet_id,
        invocation_kind=invocation_kind,
        nodes=tuple(nodes),
        edges=edges,
        agent_visible_order=agent_visible_order,
        hidden_transport_refs=hidden_transport_refs,
        physical_context_refs=physical_context_refs,
        diagnostics=diagnostics,
    )


def _sequence_edges(node_ids: tuple[str, ...]) -> list[ContextContractEdge]:
    edges: list[ContextContractEdge] = []
    for source, target in zip(node_ids, node_ids[1:]):
        edges.append(
            ContextContractEdge(
                source_node_id=source,
                target_node_id=target,
                edge_kind="agent_visible_order",
            )
        )
    return edges


def _refs_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    refs: dict[str, Any] = {}
    for key in ("source_ref", "segment_id", "cache_scope", "cache_role", "compression_role"):
        value = spec.get(key)
        if value not in (None, "", [], {}):
            refs[key] = value
    metadata = spec.get("metadata")
    if isinstance(metadata, dict):
        for key in ("content_source", "authority_class", "cache_impact"):
            value = metadata.get(key)
            if value not in (None, "", [], {}):
                refs[key] = value
    return refs


def _physical_context_refs(segment_plan: dict[str, Any]) -> tuple[str, ...]:
    refs: list[str] = []
    for segment in list(segment_plan.get("segments") or []):
        if not isinstance(segment, dict):
            continue
        ref = str(segment.get("segment_id") or segment.get("source_ref") or "").strip()
        if ref:
            refs.append(ref)
    return tuple(dict.fromkeys(refs))
