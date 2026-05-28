from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import GraphHarnessConfig


RESOURCE_NODE_TYPES = {
    "memory",
    "memory_resource",
    "memory_repository",
    "memory_collection",
    "artifact_repository",
    "thread_ledger",
    "progress_ledger",
    "issue_ledger",
    "runtime_state_store",
    "working_memory_store",
}

EXECUTABLE_MEMORY_NODE_TYPES = {"memory_commit", "memory_finalize"}
DEPENDENCY_EDGE_TYPES = {
    "handoff",
    "structured_handoff",
    "control",
    "gate",
    "gate_pass",
    "barrier",
    "temporal_dependency",
    "temporal_after",
    "phase_dependency",
    "sequence_dependency",
}


@dataclass(frozen=True, slots=True)
class SchedulerView:
    config_id: str
    config_hash: str
    dependency_edges: tuple[dict[str, Any], ...]
    executable_node_ids: tuple[str, ...]
    start_node_ids: tuple[str, ...]
    terminal_node_ids: tuple[str, ...]
    diagnostics: dict[str, Any]


def build_scheduler_view(graph_config: GraphHarnessConfig) -> SchedulerView:
    executable_ids = executable_node_ids(graph_config)
    executable_set = set(executable_ids)
    nodes_by_id = {str(node.get("node_id") or ""): dict(node) for node in graph_config.nodes}
    dependency_edges = tuple(
        edge
        for edge in (dict(item) for item in graph_config.edges)
        if _edge_is_scheduler_dependency(edge, nodes_by_id=nodes_by_id)
        and str(edge.get("source_node_id") or "") in executable_set
        and str(edge.get("target_node_id") or "") in executable_set
    )
    start_ids = _explicit_or_derived_start_ids(
        graph_config=graph_config,
        executable_ids=executable_ids,
        dependency_edges=dependency_edges,
    )
    terminal_ids = _explicit_or_derived_terminal_ids(
        graph_config=graph_config,
        executable_ids=executable_ids,
        dependency_edges=dependency_edges,
    )
    return SchedulerView(
        config_id=graph_config.config_id,
        config_hash=graph_config.content_hash,
        dependency_edges=dependency_edges,
        executable_node_ids=executable_ids,
        start_node_ids=start_ids,
        terminal_node_ids=terminal_ids,
        diagnostics={
            "authority": "harness.graph.scheduler_view",
            "full_node_count": len(graph_config.nodes),
            "full_edge_count": len(graph_config.edges),
            "executable_node_count": len(executable_ids),
            "dependency_edge_count": len(dependency_edges),
        },
    )


def executable_node_ids(graph_config: GraphHarnessConfig) -> tuple[str, ...]:
    return tuple(
        str(node.get("node_id") or "")
        for node in graph_config.nodes
        if str(node.get("node_id") or "") and is_executable_node(node)
    )


def is_executable_node(node: dict[str, Any]) -> bool:
    node_class = str(node.get("node_class") or "").strip()
    if node_class == "resource":
        return False
    if node_class == "executable":
        return True
    node_type = str(node.get("node_type") or "").strip()
    if node_type in EXECUTABLE_MEMORY_NODE_TYPES:
        return True
    if node_type in RESOURCE_NODE_TYPES:
        return False
    if node_type.endswith("_repository") or node_type.endswith("_ledger"):
        return False
    return True


def upstream_dependency_node_ids(graph_config: GraphHarnessConfig, node_id: str) -> tuple[str, ...]:
    target = str(node_id or "").strip()
    return tuple(
        str(edge.get("source_node_id") or "")
        for edge in build_scheduler_view(graph_config).dependency_edges
        if str(edge.get("target_node_id") or "") == target and str(edge.get("source_node_id") or "")
    )


def start_node_ids(graph_config: GraphHarnessConfig) -> tuple[str, ...]:
    return build_scheduler_view(graph_config).start_node_ids


def terminal_node_ids(graph_config: GraphHarnessConfig) -> tuple[str, ...]:
    return build_scheduler_view(graph_config).terminal_node_ids


def _explicit_or_derived_start_ids(
    *,
    graph_config: GraphHarnessConfig,
    executable_ids: tuple[str, ...],
    dependency_edges: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    executable_set = set(executable_ids)
    explicit = tuple(
        str(item)
        for item in list(dict(graph_config.control or {}).get("start_node_ids") or [])
        if str(item) in executable_set
    )
    if explicit:
        return explicit
    targets = {str(edge.get("target_node_id") or "") for edge in dependency_edges}
    return tuple(node_id for node_id in executable_ids if node_id not in targets)


def _explicit_or_derived_terminal_ids(
    *,
    graph_config: GraphHarnessConfig,
    executable_ids: tuple[str, ...],
    dependency_edges: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    executable_set = set(executable_ids)
    explicit = tuple(
        str(item)
        for item in list(dict(graph_config.control or {}).get("terminal_node_ids") or [])
        if str(item) in executable_set
    )
    if explicit:
        return explicit
    sources = {str(edge.get("source_node_id") or "") for edge in dependency_edges}
    return tuple(node_id for node_id in executable_ids if node_id not in sources)


def _edge_is_scheduler_dependency(edge: dict[str, Any], *, nodes_by_id: dict[str, dict[str, Any]]) -> bool:
    scheduler_role = str(edge.get("scheduler_role") or "").strip()
    if scheduler_role:
        if scheduler_role == "dependency":
            return True
        if scheduler_role == "commit":
            return _commit_edge_targets_commit_executor(edge=edge, nodes_by_id=nodes_by_id)
        return False
    edge_type = str(edge.get("edge_type") or edge.get("mode") or "").strip()
    if edge_type in DEPENDENCY_EDGE_TYPES:
        return True
    if edge_type in {"memory_commit", "memory_write", "memory_write_candidate", "artifact_commit"}:
        return _commit_edge_targets_commit_executor(edge=edge, nodes_by_id=nodes_by_id)
    return False


def _commit_edge_targets_commit_executor(*, edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]]) -> bool:
    target_node = nodes_by_id.get(str(edge.get("target_node_id") or "")) or {}
    target_type = str(target_node.get("node_type") or "").strip()
    return target_type in {"memory_commit", "memory_finalize"}
