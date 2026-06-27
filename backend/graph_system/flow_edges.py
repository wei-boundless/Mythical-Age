from __future__ import annotations

from typing import Any

from .flow_packet import edge_delivers_flow_packet
from .models import ExecutableGraphConfig


def build_inbound_flow_edges(graph_config: ExecutableGraphConfig, node_id: str) -> tuple[dict[str, Any], ...]:
    target = str(node_id or "")
    return tuple(
        dict(edge)
        for edge in graph_config.edges
        if str(edge.get("target_node_id") or "") == target
        and edge_delivers_flow_packet(dict(edge), graph_config=graph_config)
    )


def build_outbound_flow_edges(graph_config: ExecutableGraphConfig, node_id: str) -> tuple[dict[str, Any], ...]:
    source = str(node_id or "")
    return tuple(
        dict(edge)
        for edge in graph_config.edges
        if str(edge.get("source_node_id") or "") == source
        and edge_delivers_flow_packet(dict(edge), graph_config=graph_config)
    )
