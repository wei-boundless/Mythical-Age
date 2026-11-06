from __future__ import annotations

from typing import Any

from .models import ExecutableGraphConfig


def edge_contract_for(
    graph_config: ExecutableGraphConfig,
    edge_id: str,
) -> dict[str, Any]:
    contracts = dict(graph_config.contracts or {})
    index = dict(contracts.get("edge_contract_index") or {})
    return dict(index.get(str(edge_id or "")) or {})


def edge_contract_for_edge(
    graph_config: ExecutableGraphConfig,
    edge: dict[str, Any],
) -> dict[str, Any]:
    edge_id = str(edge.get("edge_id") or "").strip()
    if not edge_id:
        raise ValueError("ExecutableGraphConfig edge requires edge_id before contract lookup")
    contract = edge_contract_for(graph_config, edge_id)
    if contract:
        return contract
    raise ValueError(f"ExecutableGraphConfig missing compiled edge contract: {edge_id}")


def edge_contract_packet_field(
    graph_config: ExecutableGraphConfig,
    edge: dict[str, Any],
    field_name: str,
    default: Any = "",
) -> Any:
    packet = dict(edge_contract_for_edge(graph_config, edge).get("packet") or {})
    value = packet.get(field_name)
    return default if value in (None, "") else value


def edge_contract_reliability(
    graph_config: ExecutableGraphConfig,
    edge: dict[str, Any],
) -> dict[str, Any]:
    return dict(edge_contract_for_edge(graph_config, edge).get("reliability") or {})
