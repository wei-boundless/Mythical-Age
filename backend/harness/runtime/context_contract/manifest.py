from __future__ import annotations

from typing import Any

from .authority_rules import classify_context_spec, hidden_transport_node
from .diagnostics import diagnose_context_contract_manifest
from .nodes import ContextContractEdge, ContextContractManifest, ContextContractNode, context_contract_edge_id


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
                agent_domain=classified["agent_domain"],
                agent_role=classified["agent_role"],
                control_layer=classified["control_layer"],
                time_scope=classified["time_scope"],
                control_signal=classified["control_signal"],
                feedback_route=classified["feedback_route"],
                physical_lane=classified["physical_lane"],
                cache_expectation=classified["cache_expectation"],
                connection_contract_ref=classified["connection_contract_ref"],
                provider_payload_segment_ref=classified["provider_payload_segment_ref"],
                refs=_refs_from_spec(spec),
                diagnostics={
                    **dict(classified.get("diagnostics") or {}),
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
    agent_visible_order = tuple(node.node_id for node in nodes if node.visibility == "agent_visible")
    hidden_transport_refs = tuple(node.node_id for node in nodes if node.visibility == "provider_transport")
    physical_context_refs = _physical_context_refs(segment_plan or {})
    edges = tuple(_connection_edges(nodes=tuple(nodes), agent_visible_order=agent_visible_order, hidden_transport_refs=hidden_transport_refs))
    node_payloads = [node.to_dict() for node in nodes]
    edge_payloads = [edge.to_dict() for edge in edges]
    diagnostics = diagnose_context_contract_manifest(node_payloads, edge_payloads)
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


def _connection_edges(
    *,
    nodes: tuple[ContextContractNode, ...],
    agent_visible_order: tuple[str, ...],
    hidden_transport_refs: tuple[str, ...],
) -> list[ContextContractEdge]:
    by_id = {node.node_id: node for node in nodes}
    edges: list[ContextContractEdge] = []
    edges.extend(_sequence_edges(agent_visible_order, by_id=by_id))
    hidden_transport_ref = hidden_transport_refs[0] if hidden_transport_refs else ""
    for node in nodes:
        if node.visibility != "agent_visible":
            continue
        edges.append(_physical_lane_edge(node))
        if hidden_transport_ref:
            edges.append(_provider_payload_edge(node, target_node_id=hidden_transport_ref))
            if node.cache_expectation:
                edges.append(_cache_health_edge(node, target_node_id=hidden_transport_ref))
    return edges


def _sequence_edges(node_ids: tuple[str, ...], *, by_id: dict[str, ContextContractNode]) -> list[ContextContractEdge]:
    edges: list[ContextContractEdge] = []
    for source, target in zip(node_ids, node_ids[1:]):
        target_node = by_id.get(target)
        edges.append(
            ContextContractEdge(
                edge_id=context_contract_edge_id("agent_visible_order", source, target),
                source_node_id=source,
                target_node_id=target,
                edge_kind="agent_visible_order",
                payload_identity=f"{source}->{target}",
                payload_schema="ordered agent-visible context message boundary",
                authority="harness.runtime.context_contract.manifest",
                transport_or_store="model_message_order",
                consumer="harness.runtime.compiler",
                failure_route="missing adjacent context node -> diagnostics, no reorder fallback",
                cache_expectation=str(getattr(target_node, "cache_expectation", "") or ""),
                connection_contract_ref=str(getattr(target_node, "connection_contract_ref", "") or ""),
                physical_lane=str(getattr(target_node, "physical_lane", "") or ""),
                control_signal=str(getattr(target_node, "control_signal", "") or ""),
            )
        )
    return edges


def _physical_lane_edge(node: ContextContractNode) -> ContextContractEdge:
    return ContextContractEdge(
        edge_id=context_contract_edge_id("physical_lane_projection", node.node_id, node.node_id),
        source_node_id=node.node_id,
        target_node_id=node.node_id,
        edge_kind="physical_lane_projection",
        payload_identity=_first_text(node.provider_payload_segment_ref, node.source_ref, node.node_id),
        payload_schema="context node -> physical lane assignment",
        authority="runtime.context_management.physical_context_assembler",
        transport_or_store="message_spec.metadata.physical_prefix_lane + message_spec.metadata.context_physical_assembly_index",
        consumer="harness.runtime.context_contract.manifest",
        failure_route="missing assembler lane/index -> missing_physical_assembly_metadata diagnostic",
        cache_expectation=node.cache_expectation,
        connection_contract_ref=node.connection_contract_ref,
        physical_lane=node.physical_lane,
        control_signal=node.control_signal,
        diagnostics={
            "agent_domain": node.agent_domain,
            "time_scope": node.time_scope,
            "control_layer": node.control_layer,
        },
    )


def _provider_payload_edge(node: ContextContractNode, *, target_node_id: str) -> ContextContractEdge:
    return ContextContractEdge(
        edge_id=context_contract_edge_id("provider_payload_binding", node.node_id, target_node_id),
        source_node_id=node.node_id,
        target_node_id=target_node_id,
        edge_kind="provider_payload_binding",
        payload_identity=_first_text(node.provider_payload_segment_ref, node.source_ref, node.node_id),
        payload_schema="context contract node metadata -> ProviderPayloadSegment identity",
        authority="runtime.model_gateway.provider_payload",
        transport_or_store="ProviderPayloadManifest.physical_cache_spine",
        consumer="runtime.model_gateway.provider_payload",
        failure_route="provider segment missing contract ref -> cache anomaly diagnostic",
        cache_expectation=node.cache_expectation,
        connection_contract_ref=node.connection_contract_ref,
        physical_lane=node.physical_lane,
        control_signal=node.control_signal,
        diagnostics={
            "agent_domain": node.agent_domain,
            "provider_payload_segment_ref": node.provider_payload_segment_ref,
        },
    )


def _cache_health_edge(node: ContextContractNode, *, target_node_id: str) -> ContextContractEdge:
    return ContextContractEdge(
        edge_id=context_contract_edge_id("cache_health_binding", node.node_id, target_node_id),
        source_node_id=node.node_id,
        target_node_id=target_node_id,
        edge_kind="cache_health_binding",
        payload_identity=_first_text(node.provider_payload_segment_ref, node.source_ref, node.node_id),
        payload_schema="ProviderPayloadSegment identity -> PrefixCacheHealth boundary",
        authority="runtime.prompt_accounting.prefix_cache_health",
        transport_or_store="ProviderCacheBusRecord.physical_cache_spine_*",
        consumer="runtime.prompt_accounting.provider_cache_bus",
        failure_route="expected prefix under-read -> first_missing_expected_prefix_identity",
        cache_expectation=node.cache_expectation,
        connection_contract_ref=node.connection_contract_ref,
        physical_lane=node.physical_lane,
        control_signal=node.control_signal,
        diagnostics={
            "agent_domain": node.agent_domain,
            "cache_tier": node.cache_tier,
        },
    )


def _refs_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    refs: dict[str, Any] = {}
    for key in (
        "source_ref",
        "segment_id",
        "cache_scope",
        "cache_role",
        "compression_role",
        "prefix_tier",
        "provider_payload_segment_ref",
    ):
        value = spec.get(key)
        if value not in (None, "", [], {}):
            refs[key] = value
    metadata = spec.get("metadata")
    if isinstance(metadata, dict):
        for key in (
            "content_source",
            "cache_impact",
            "context_cache_section",
            "context_semantic_slot",
            "context_contract_slot",
            "context_contract_ref",
            "context_candidate_ref",
            "context_candidate_source_identity",
            "context_candidate_content_identity",
            "context_candidate_source_route",
            "context_candidate_identity_authority",
            "context_message_producer_id",
            "context_message_producer_authority",
            "context_line_id",
            "system_asset_line_id",
            "context_input_envelope_ref",
            "context_input_envelope_line_id",
            "context_input_envelope_source_identity",
            "context_input_envelope_content_identity",
            "context_candidate_gateway_authority",
            "context_line_activation_authority",
            "physical_prefix_lane",
            "context_prefix_identity",
            "logical_segment_ref",
            "prefix_segment_ref",
            "physical_context_plan_ref",
            "cache_spine_hash",
            "provider_visible_append_item_key",
            "physical_prefix_frame_id",
            "physical_prefix_frame_source_request_id",
            "physical_prefix_frame_segment_id",
            "physical_prefix_frame_segment_ordinal",
        ):
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


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
