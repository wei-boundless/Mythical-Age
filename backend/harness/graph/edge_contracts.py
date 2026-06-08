from __future__ import annotations

from typing import Any

from .models import GraphHarnessConfig


def edge_contract_for(
    graph_config: GraphHarnessConfig,
    edge_id: str,
) -> dict[str, Any]:
    contracts = dict(graph_config.contracts or {})
    index = dict(contracts.get("edge_contract_index") or {})
    return dict(index.get(str(edge_id or "")) or {})


def edge_contract_or_projection(
    graph_config: GraphHarnessConfig,
    edge: dict[str, Any],
) -> dict[str, Any]:
    contract = edge_contract_for(graph_config, str(edge.get("edge_id") or ""))
    if contract:
        return contract
    protocol_index = dict(dict(graph_config.contracts or {}).get("edge_protocol_index") or {})
    edge_id = str(edge.get("edge_id") or "")
    protocol = dict(protocol_index.get(edge_id) or {})
    return {
        "edge_id": edge_id,
        "source_node_id": str(edge.get("source_node_id") or ""),
        "target_node_id": str(edge.get("target_node_id") or ""),
        "protocol": {
            "kind": str(protocol.get("protocol_kind") or protocol.get("edge_type") or edge.get("edge_type") or ""),
            "legacy_edge_type": str(protocol.get("edge_type") or edge.get("edge_type") or ""),
        },
        "scheduler": {
            "scheduler_role": str(protocol.get("scheduler_role") or edge.get("scheduler_role") or ""),
            "semantic_role": str(protocol.get("semantic_role") or edge.get("semantic_role") or ""),
        },
        "packet": {
            "payload_contract_id": str(protocol.get("payload_contract_id") or edge.get("payload_contract_id") or ""),
            "packet_contract_id": str(protocol.get("packet_contract_id") or edge.get("packet_contract_id") or ""),
            "target_context_key": str(protocol.get("target_context_key") or edge.get("target_context_key") or ""),
            "target_input_slot": str(protocol.get("target_input_slot") or edge.get("target_input_slot") or ""),
            "delivery_policy": str(protocol.get("delivery_policy") or edge.get("result_delivery_policy") or ""),
        },
        "reliability": {
            "ack_required": bool(protocol.get("ack_required", edge.get("ack_required", True))),
            "ack_policy": str(protocol.get("ack_policy") or edge.get("ack_policy") or ""),
        },
        "legacy_protocol_projection": protocol,
        "authority": "harness.graph.edge_contract_projection",
    }


def edge_contract_packet_field(
    graph_config: GraphHarnessConfig,
    edge: dict[str, Any],
    field_name: str,
    default: Any = "",
) -> Any:
    packet = dict(edge_contract_or_projection(graph_config, edge).get("packet") or {})
    value = packet.get(field_name)
    return default if value in (None, "") else value


def edge_contract_reliability(
    graph_config: GraphHarnessConfig,
    edge: dict[str, Any],
) -> dict[str, Any]:
    return dict(edge_contract_or_projection(graph_config, edge).get("reliability") or {})
