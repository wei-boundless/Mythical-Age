from __future__ import annotations

from typing import Any

from .task_graph_models import TaskGraphDefinition, TaskGraphEdgeDefinition, TaskGraphNodeDefinition


RESOURCE_NODE_TYPES = {
    "memory",
    "memory_resource",
    "memory_repository",
    "memory_collection",
    "artifact_repository",
    "progress_ledger",
    "issue_ledger",
    "runtime_state_store",
    "working_memory_store",
}
MEMORY_EDGE_TYPES = {"memory_read", "memory_write", "memory_write_candidate", "memory_commit", "memory_handoff"}
ARTIFACT_EDGE_TYPES = {"artifact_read", "artifact_write", "artifact_context"}
REVISION_EDGE_TYPES = {"revision_request", "review_feedback", "repair_feedback", "conditional_feedback", "repair_route"}
TEMPORAL_EDGE_TYPES = {"temporal_dependency", "temporal_after", "phase_dependency", "sequence_dependency"}


def normalize_task_graph_layers(graph: TaskGraphDefinition) -> dict[str, Any]:
    nodes = list(graph.nodes)
    edges = list(graph.edges)
    resource_nodes = [_resource_node_payload(node) for node in nodes if _is_resource_node(node)]
    temporal_edges = _temporal_edges(graph=graph, nodes=nodes, edges=edges)
    memory_edges = [_memory_edge_payload(edge) for edge in edges if _is_memory_edge(edge)]
    artifact_context_edges = [_artifact_context_edge_payload(edge) for edge in edges if _is_artifact_context_edge(edge)]
    revision_edges = [_revision_edge_payload(edge) for edge in edges if _is_revision_edge(edge)]
    loop_frames = [_loop_frame_payload(node) for node in nodes if _is_loop_frame(node)]
    matrix = _memory_matrix(nodes=nodes, resource_nodes=resource_nodes, memory_edges=memory_edges)
    issues = _layer_issues(
        graph=graph,
        resource_nodes=resource_nodes,
        temporal_edges=temporal_edges,
        memory_edges=memory_edges,
        artifact_context_edges=artifact_context_edges,
        revision_edges=revision_edges,
    )
    return {
        "authority": "task_system.layered_graph_normalizer",
        "graph_id": graph.graph_id,
        "layers": {
            "execution": {"enabled": True, "node_count": len(nodes), "edge_count": len(edges)},
            "timeline": {"enabled": True, "edge_count": len(temporal_edges), "loop_frame_count": len(loop_frames)},
            "memory": {"enabled": True, "resource_count": len(resource_nodes), "edge_count": len(memory_edges)},
            "artifact_context": {"enabled": True, "edge_count": len(artifact_context_edges)},
            "revision": {"enabled": True, "edge_count": len(revision_edges)},
        },
        "resource_nodes": resource_nodes,
        "temporal_edges": temporal_edges,
        "memory_edges": memory_edges,
        "artifact_context_edges": artifact_context_edges,
        "revision_edges": revision_edges,
        "loop_frames": loop_frames,
        "memory_matrix": matrix,
        "issues": issues,
        "summary": {
            "resource_node_count": len(resource_nodes),
            "temporal_edge_count": len(temporal_edges),
            "memory_edge_count": len(memory_edges),
            "artifact_context_edge_count": len(artifact_context_edges),
            "revision_edge_count": len(revision_edges),
            "loop_frame_count": len(loop_frames),
            "issue_count": len(issues),
        },
    }


def _is_resource_node(node: TaskGraphNodeDefinition) -> bool:
    node_type = str(node.node_type or "").strip()
    node_id = str(node.node_id or "").strip()
    return node_type in RESOURCE_NODE_TYPES or node_id.startswith(("memory.", "artifact.", "progress.", "issue."))


def _is_loop_frame(node: TaskGraphNodeDefinition) -> bool:
    return str(node.node_type or "").strip() == "loop_frame" or bool(node.loop_policy)


def _resource_node_payload(node: TaskGraphNodeDefinition) -> dict[str, Any]:
    metadata = dict(node.metadata or {})
    lifecycle = dict(node.resource_lifecycle_policy or {})
    collections = metadata.get("collections")
    if not isinstance(collections, list):
        collections = []
    return {
        "node_id": node.node_id,
        "title": node.title,
        "resource_type": node.node_type,
        "repository_id": str(metadata.get("repository_id") or node.node_id),
        "collections": [str(item).strip() for item in collections if str(item).strip()],
        "versioning": str(lifecycle.get("versioning") or metadata.get("versioning") or "append_version"),
        "mutable": bool(lifecycle.get("mutable", True)),
        "write_owner_node_ids": _string_list(lifecycle.get("write_owner_node_ids")),
        "readable_by": _string_list(lifecycle.get("readable_by") or ["*"]),
        "lifecycle_policy": lifecycle,
        "metadata": metadata,
        "authority": "task_system.resource_node",
    }


def _temporal_edges(
    *,
    graph: TaskGraphDefinition,
    nodes: list[TaskGraphNodeDefinition],
    edges: list[TaskGraphEdgeDefinition],
) -> list[dict[str, Any]]:
    explicit = [_temporal_edge_payload(edge) for edge in edges if _is_temporal_edge(edge)]
    derived: list[dict[str, Any]] = []
    nodes_by_phase: dict[str, list[TaskGraphNodeDefinition]] = {}
    for node in nodes:
        phase_id = str(node.phase_id or "").strip()
        if not phase_id:
            continue
        nodes_by_phase.setdefault(phase_id, []).append(node)
    for phase_id, phase_nodes in nodes_by_phase.items():
        ordered = sorted(phase_nodes, key=lambda item: (int(item.sequence_index or 0), item.node_id))
        for previous, current in zip(ordered, ordered[1:]):
            if int(previous.sequence_index or 0) == int(current.sequence_index or 0):
                continue
            derived.append(
                {
                    "edge_id": f"temporal:{phase_id}:{previous.node_id}->{current.node_id}",
                    "source_node_id": previous.node_id,
                    "target_node_id": current.node_id,
                    "temporal_type": "phase_sequence",
                    "phase_id": phase_id,
                    "sequence_policy": "strict_after_source",
                    "blocking": True,
                    "derived": True,
                    "authority": "task_system.temporal_edge",
                }
            )
    metadata = dict(graph.metadata or {})
    metadata_edges = [
        dict(item)
        for item in list(metadata.get("temporal_edges") or [])
        if isinstance(item, dict)
    ]
    return [*metadata_edges, *explicit, *derived]


def _is_temporal_edge(edge: TaskGraphEdgeDefinition) -> bool:
    edge_type = str(edge.edge_type or "").strip()
    metadata = dict(edge.metadata or {})
    dependency_role = str(metadata.get("dependency_role") or "").strip()
    return edge_type in TEMPORAL_EDGE_TYPES or dependency_role.startswith("temporal")


def _temporal_edge_payload(edge: TaskGraphEdgeDefinition) -> dict[str, Any]:
    metadata = dict(edge.metadata or {})
    return {
        "edge_id": edge.edge_id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "temporal_type": str(metadata.get("temporal_type") or edge.edge_type or "after_success"),
        "phase_id": str(metadata.get("phase_id") or ""),
        "sequence_policy": str(metadata.get("sequence_policy") or "strict_after_source"),
        "blocking": metadata.get("blocking", True) is not False,
        "derived": False,
        "metadata": metadata,
        "authority": "task_system.temporal_edge",
    }


def _is_memory_edge(edge: TaskGraphEdgeDefinition) -> bool:
    edge_type = str(edge.edge_type or "").strip()
    if edge_type in MEMORY_EDGE_TYPES:
        return True
    metadata = dict(edge.metadata or {})
    return bool(
        edge.working_memory_handoff_policy
        or metadata.get("memory_edge_type")
        or metadata.get("repository")
        or metadata.get("repository_id")
        or metadata.get("collection")
        or metadata.get("selector")
    )


def _memory_edge_payload(edge: TaskGraphEdgeDefinition) -> dict[str, Any]:
    metadata = dict(edge.metadata or {})
    edge_type = str(edge.edge_type or "").strip()
    if edge_type in MEMORY_EDGE_TYPES:
        memory_edge_type = edge_type.replace("memory_", "")
    elif edge.working_memory_handoff_policy:
        memory_edge_type = "handoff"
    else:
        memory_edge_type = str(metadata.get("memory_edge_type") or "read")
    default_on_missing = "warn" if memory_edge_type == "handoff" else "block"
    selector = dict(metadata.get("selector") or {})
    record_key = str(metadata.get("record_key") or selector.get("record_key") or "").strip()
    record_kind = str(metadata.get("record_kind") or selector.get("record_kind") or "").strip()
    record_keys = _string_list(metadata.get("record_keys") or selector.get("record_keys") or edge.working_memory_handoff_policy.get("carry_kinds"))
    record_kinds = _string_list(metadata.get("record_kinds") or selector.get("record_kinds"))
    if record_key and record_key not in record_keys:
        record_keys.insert(0, record_key)
    if record_kind and record_kind not in record_kinds:
        record_kinds.insert(0, record_kind)
    return {
        "edge_id": edge.edge_id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "memory_edge_type": memory_edge_type,
        "repository": str(metadata.get("repository") or metadata.get("repository_id") or metadata.get("repository_node_id") or ""),
        "collection": str(metadata.get("collection") or selector.get("collection") or ""),
        "selector": selector,
        "record_key": record_key,
        "record_kind": record_kind,
        "record_keys": record_keys,
        "record_kinds": record_kinds,
        "version_selector": str(metadata.get("version_selector") or "latest_committed_before_stage_start"),
        "effective_from": str(metadata.get("effective_from") or "next_stage"),
        "on_missing": str(metadata.get("on_missing") or default_on_missing),
        "source_output_key": str(metadata.get("source_output_key") or selector.get("source_output_key") or ""),
        "candidate_ref_key": str(metadata.get("candidate_ref_key") or ""),
        "verdict_key": str(metadata.get("verdict_key") or ""),
        "required_verdict": str(metadata.get("required_verdict") or ""),
        "receipt_policy": dict(metadata.get("receipt_policy") or {}),
        "model_visible_label": str(metadata.get("model_visible_label") or metadata.get("visible_label") or ""),
        "usage_instruction": str(metadata.get("usage_instruction") or metadata.get("instructions") or ""),
        "read_contract": dict(metadata.get("read_contract") or {}),
        "write_contract": dict(metadata.get("write_contract") or {}),
        "working_memory_handoff_policy": dict(edge.working_memory_handoff_policy or {}),
        "metadata": metadata,
        "authority": "task_system.memory_edge",
    }


def _is_artifact_context_edge(edge: TaskGraphEdgeDefinition) -> bool:
    edge_type = str(edge.edge_type or "").strip()
    metadata = dict(edge.metadata or {})
    return edge_type in ARTIFACT_EDGE_TYPES or bool(edge.artifact_ref_policy) or "artifact" in str(metadata.get("context_mode") or "")


def _artifact_context_edge_payload(edge: TaskGraphEdgeDefinition) -> dict[str, Any]:
    metadata = dict(edge.metadata or {})
    artifact_policy = dict(edge.artifact_ref_policy or {})
    return {
        "edge_id": edge.edge_id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "context_mode": str(metadata.get("context_mode") or artifact_policy.get("context_mode") or edge.result_delivery_policy or "refs_only"),
        "source_output_key": str(artifact_policy.get("source_output_key") or metadata.get("source_output_key") or ""),
        "target_input_key": str(artifact_policy.get("target_input_key") or metadata.get("target_input_key") or ""),
        "max_chars": _int_value(artifact_policy.get("max_chars") or metadata.get("max_chars"), 0),
        "artifact_ref_policy": artifact_policy,
        "metadata": metadata,
        "authority": "task_system.artifact_context_edge",
    }


def _is_revision_edge(edge: TaskGraphEdgeDefinition) -> bool:
    metadata = dict(edge.metadata or {})
    edge_type = str(edge.edge_type or "").strip()
    dependency_role = str(metadata.get("dependency_role") or "").strip()
    verdict = str(metadata.get("verdict") or "").strip()
    return edge_type in REVISION_EDGE_TYPES or dependency_role in {"conditional_feedback", "repair_feedback"} or verdict in {"revise", "repair"}


def _revision_edge_payload(edge: TaskGraphEdgeDefinition) -> dict[str, Any]:
    metadata = dict(edge.metadata or {})
    return {
        "edge_id": edge.edge_id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "trigger": dict(metadata.get("trigger") or {"verdict": metadata.get("verdict") or "revise"}),
        "carry": list(metadata.get("carry") or []),
        "clear_input_keys": _string_list(metadata.get("clear_input_keys")),
        "metadata": metadata,
        "authority": "task_system.revision_edge",
    }


def _loop_frame_payload(node: TaskGraphNodeDefinition) -> dict[str, Any]:
    policy = dict(node.loop_policy or {})
    return {
        "loop_frame_id": str(policy.get("loop_frame_id") or node.node_id),
        "node_id": node.node_id,
        "phase_id": node.phase_id,
        "loop_kind": str(policy.get("loop_kind") or ("loop_frame" if node.node_type == "loop_frame" else "while_target_not_met")),
        "loop_variable": str(policy.get("loop_variable") or "iteration_index"),
        "exit_condition": str(policy.get("exit_condition") or ""),
        "memory_snapshot_policy": str(policy.get("memory_snapshot_policy") or "latest_committed_before_iteration"),
        "policy": policy,
        "authority": "task_system.loop_frame",
    }


def _memory_matrix(
    *,
    nodes: list[TaskGraphNodeDefinition],
    resource_nodes: list[dict[str, Any]],
    memory_edges: list[dict[str, Any]],
) -> dict[str, Any]:
    phase_ids = list(
        dict.fromkeys(
            str(node.phase_id or "phase.unassigned").strip() or "phase.unassigned"
            for node in nodes
        )
    )
    resource_ids = [str(item.get("node_id") or "") for item in resource_nodes if str(item.get("node_id") or "")]
    node_phase = {node.node_id: str(node.phase_id or "phase.unassigned").strip() or "phase.unassigned" for node in nodes}
    cells: list[dict[str, Any]] = []
    for phase_id in phase_ids:
        for resource_id in resource_ids:
            operations = []
            for edge in memory_edges:
                source = str(edge.get("source_node_id") or "")
                target = str(edge.get("target_node_id") or "")
                operation = str(edge.get("memory_edge_type") or "")
                if source == resource_id and node_phase.get(target) == phase_id:
                    operations.append("read" if operation in {"read", "handoff"} else operation)
                if target == resource_id and node_phase.get(source) == phase_id:
                    operations.append("write" if operation in {"write", "write_candidate", "commit"} else operation)
            cells.append(
                {
                    "phase_id": phase_id,
                    "resource_node_id": resource_id,
                    "operations": list(dict.fromkeys(item for item in operations if item)),
                    "state": "active" if operations else "forbidden",
                }
            )
    return {
        "authority": "task_system.timeline_memory_matrix",
        "phase_ids": phase_ids,
        "resource_node_ids": resource_ids,
        "cells": cells,
    }


def _layer_issues(
    *,
    graph: TaskGraphDefinition,
    resource_nodes: list[dict[str, Any]],
    temporal_edges: list[dict[str, Any]],
    memory_edges: list[dict[str, Any]],
    artifact_context_edges: list[dict[str, Any]],
    revision_edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    resource_ids = {str(item.get("node_id") or "") for item in resource_nodes}
    node_ids = {node.node_id for node in graph.nodes}
    for edge in memory_edges:
        source = str(edge.get("source_node_id") or "")
        target = str(edge.get("target_node_id") or "")
        if source not in resource_ids and target not in resource_ids and not str(edge.get("repository") or ""):
            issues.append(_issue("memory_edge_without_repository", "记忆边没有连接资源节点，也没有声明 repository", edge_id=str(edge.get("edge_id") or ""), severity="warning"))
        if (
            str(edge.get("memory_edge_type") or "") != "handoff"
            and str(edge.get("on_missing") or "") == "block"
            and not (str(edge.get("repository") or "") or source in resource_ids or target in resource_ids)
        ):
            issues.append(_issue("blocking_memory_edge_unresolvable", "阻塞型记忆边缺少可解析仓库", edge_id=str(edge.get("edge_id") or "")))
    for edge in artifact_context_edges:
        if str(edge.get("context_mode") or "") == "expand_text_for_model" and not str(edge.get("source_output_key") or ""):
            issues.append(_issue("artifact_context_missing_source_output_key", "产物正文展开边缺少 source_output_key", edge_id=str(edge.get("edge_id") or ""), severity="warning"))
    for edge in revision_edges:
        if not edge.get("carry"):
            issues.append(_issue("revision_edge_missing_carry_contract", "返修边缺少 carry 规则，退稿节点可能拿不到原稿或审核意见", edge_id=str(edge.get("edge_id") or ""), severity="warning"))
        if str(edge.get("target_node_id") or "") not in node_ids:
            issues.append(_issue("revision_edge_missing_target", "返修边目标节点不存在", edge_id=str(edge.get("edge_id") or "")))
    if graph.nodes and not temporal_edges:
        issues.append(_issue("timeline_layer_empty", "任务图没有显式或派生时序边", severity="info"))
    return issues


def _issue(code: str, message: str, *, severity: str = "error", node_id: str = "", edge_id: str = "") -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "severity": severity,
        "node_id": node_id,
        "edge_id": edge_id,
        "authority": "task_system.layered_graph_issue",
    }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.replace("，", ",").replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = []
    return [str(item).strip() for item in values if str(item).strip()]


def _int_value(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
