from __future__ import annotations

from typing import Any

from task_system.graphs.task_graph_models import (
    NODE_JOIN_POLICIES,
    task_graph_from_dict,
)


WRITING_GRAPH_IDS = {
    "graph.writing.modular_novel.master",
    "graph.writing.modular_novel.design_init",
    "graph.writing.modular_novel.chapter_cycle",
    "graph.writing.modular_novel.finalize",
}
WRITING_GRAPH_MIGRATION_VERSION = "writing_graph_transition_migration.v1"
REVISION_EDGE_TYPES = {"revision_request", "review_feedback", "repair_feedback", "conditional_feedback", "repair_route"}
CHAPTER_CYCLE_REQUIRED_NODE_IDS = {"chapter_unit_router", "chapter_progress_router"}
CHAPTER_CYCLE_REQUIRED_LOOP_FRAME_IDS = {"loop.chapter_unit", "loop.chapter_batch", "loop.volume"}


def normalize_writing_graph_for_transition_runtime(graph: Any) -> Any:
    graph_id = str(getattr(graph, "graph_id", "") or "").strip()
    if graph_id not in WRITING_GRAPH_IDS:
        return graph

    payload = _graph_payload(graph)
    _validate_writing_graph_payload(payload)
    migrated = _migrated_graph_payload(payload)
    _validate_writing_graph_payload(migrated)
    return task_graph_from_dict(migrated)


def _graph_payload(graph: Any) -> dict[str, Any]:
    if hasattr(graph, "to_dict"):
        return dict(graph.to_dict())
    return dict(graph or {})


def _migrated_graph_payload(payload: dict[str, Any]) -> dict[str, Any]:
    graph_id = str(payload.get("graph_id") or "").strip()
    metadata = dict(payload.get("metadata") or {})
    metadata["migration"] = {
        **dict(metadata.get("migration") or {}),
        "authority": "task_system.compiler.writing_graph_config_migrator",
        "version": WRITING_GRAPH_MIGRATION_VERSION,
        "source_graph_id": graph_id,
        "node_id_preserved": True,
        "edge_id_preserved": True,
    }
    metadata["transition_runtime"] = {
        **dict(metadata.get("transition_runtime") or {}),
        "canonical": True,
        "edge_state_authority": "harness.graph.transition_processor",
        "readiness_authority": "harness.graph.readiness_evaluator",
        "migration_version": WRITING_GRAPH_MIGRATION_VERSION,
    }

    nodes = [_migrated_node_payload(node) for node in _list_dicts(payload.get("nodes") or payload.get("graph_nodes"))]
    edges = [_migrated_edge_payload(edge) for edge in _list_dicts(payload.get("edges") or payload.get("graph_edges"))]
    loop_frames = [_migrated_loop_frame_payload(frame) for frame in _list_dicts(payload.get("loop_frames"))]
    return {
        **payload,
        "nodes": nodes,
        "graph_nodes": nodes,
        "edges": edges,
        "graph_edges": edges,
        "loop_frames": loop_frames,
        "metadata": metadata,
    }


def _migrated_node_payload(node: dict[str, Any]) -> dict[str, Any]:
    payload = dict(node)
    metadata = dict(payload.get("metadata") or {})
    transition_policy = dict(metadata.get("transition_policy") or {})
    review_gate_policy = dict(payload.get("review_gate_policy") or _nested(payload, "contract_bindings.acceptance.review_gate_policy") or {})
    if review_gate_policy:
        transition_policy["review_gate"] = {
            **review_gate_policy,
            "authority": "task_system.compiler.writing_graph_config_migrator.review_gate_policy",
        }
    progress_commit_policy = dict(payload.get("progress_commit_policy") or metadata.get("progress_commit_policy") or {})
    if progress_commit_policy:
        transition_policy["progress_commit"] = {
            **progress_commit_policy,
            "authority": "task_system.compiler.writing_graph_config_migrator.progress_commit_policy",
        }
    quality_retry_policy = dict(payload.get("quality_retry_policy") or metadata.get("quality_retry_policy") or {})
    if quality_retry_policy:
        transition_policy["quality_retry"] = {
            **quality_retry_policy,
            "authority": "task_system.compiler.writing_graph_config_migrator.quality_retry_policy",
        }
    loop_policy = dict(payload.get("loop") or metadata.get("loop") or {})
    if loop_policy:
        transition_policy["loop_frames"] = {
            **loop_policy,
            "authority": "task_system.compiler.writing_graph_config_migrator.loop_policy",
        }
    metadata["transition_policy"] = _compact_nested(transition_policy)
    metadata["readiness_policy"] = _compact_nested(
        {
            **dict(metadata.get("readiness_policy") or {}),
            "wait_policy": str(payload.get("wait_policy") or "wait_all_upstream_completed"),
            "join_policy": str(payload.get("join_policy") or "all_success"),
            "authority": "task_system.compiler.writing_graph_config_migrator.node_readiness_policy",
        }
    )
    payload["metadata"] = metadata
    return payload


def _migrated_edge_payload(edge: dict[str, Any]) -> dict[str, Any]:
    payload = dict(edge)
    edge_id = str(payload.get("edge_id") or "").strip()
    edge_type = str(payload.get("edge_type") or "handoff").strip() or "handoff"
    metadata = dict(payload.get("metadata") or {})
    transition_policy = dict(metadata.get("transition_policy") or {})
    transition_policy["edge_status"] = _compact_nested(
        {
            "initial": "pending",
            "on_source_success": "ready",
            "on_source_failed": "source_failed",
            "decision_ref_required": True,
            "authority": "task_system.compiler.writing_graph_config_migrator.edge_status_policy",
        }
    )
    trigger = dict(metadata.get("trigger") or {})
    if edge_type in REVISION_EDGE_TYPES:
        transition_policy["revision"] = _compact_nested(
            {
                "edge_id": edge_id,
                "source_node_id": str(payload.get("source_node_id") or ""),
                "target_node_id": str(payload.get("target_node_id") or ""),
                "trigger": trigger,
                "selected_status": "ready",
                "unselected_status": "skipped",
                "carry": list(metadata.get("carry") or []),
                "authority": "task_system.compiler.writing_graph_config_migrator.revision_edge_policy",
            }
        )
    if edge_type in {"memory_commit", "memory_write_candidate"}:
        transition_policy["memory"] = _compact_nested(
            {
                "operation": edge_type.replace("memory_", ""),
                "approval_policy": str(metadata.get("approval_policy") or ""),
                "commit_visibility_policy": dict(metadata.get("commit_visibility_policy") or {}),
                "authority": "task_system.compiler.writing_graph_config_migrator.memory_edge_policy",
            }
        )
    metadata["transition_policy"] = _compact_nested(transition_policy)
    metadata["readiness_policy"] = _compact_nested(
        {
            **dict(metadata.get("readiness_policy") or {}),
            "wait_policy": str(payload.get("wait_policy") or ""),
            "ack_required": bool(payload.get("ack_required", True)),
            "ack_policy": str(payload.get("ack_policy") or ""),
            "failure_propagation_policy": str(payload.get("failure_propagation_policy") or "fail_downstream"),
            "result_delivery_policy": str(payload.get("result_delivery_policy") or "contract_payload_and_refs"),
            "authority": "task_system.compiler.writing_graph_config_migrator.edge_readiness_policy",
        }
    )
    payload["metadata"] = metadata
    return payload


def _migrated_loop_frame_payload(frame: dict[str, Any]) -> dict[str, Any]:
    payload = dict(frame)
    transition_policy = {
        **dict(payload.get("transition_policy") or {}),
        "canonical": True,
        "authority": "task_system.compiler.writing_graph_config_migrator.loop_frame_policy",
    }
    payload["transition_policy"] = _compact_nested(transition_policy)
    return payload


def _validate_writing_graph_payload(payload: dict[str, Any]) -> None:
    graph_id = str(payload.get("graph_id") or "").strip()
    node_ids = {str(node.get("node_id") or "").strip() for node in _list_dicts(payload.get("nodes") or payload.get("graph_nodes"))}
    edges = _list_dicts(payload.get("edges") or payload.get("graph_edges"))
    loop_frames = _list_dicts(payload.get("loop_frames"))

    for node in _list_dicts(payload.get("nodes") or payload.get("graph_nodes")):
        _validate_review_gate_revision_edge(node=node, node_ids=node_ids, edges=edges)
        _validate_quorum_policy(node)

    for edge in edges:
        if bool(edge.get("ack_required", True)) and not str(edge.get("ack_policy") or "").strip():
            raise ValueError(f"writing graph edge ack_required=true requires ack_policy: {edge.get('edge_id')}")

    if graph_id == "graph.writing.modular_novel.chapter_cycle":
        missing_nodes = sorted(CHAPTER_CYCLE_REQUIRED_NODE_IDS - node_ids)
        if missing_nodes:
            raise ValueError(f"writing chapter_cycle graph missing required nodes: {missing_nodes}")
        frame_ids = {
            str(frame.get("frame_id") or frame.get("loop_frame_id") or frame.get("scope_id") or "").strip()
            for frame in loop_frames
        }
        missing_frames = sorted(CHAPTER_CYCLE_REQUIRED_LOOP_FRAME_IDS - frame_ids)
        if missing_frames:
            raise ValueError(f"writing chapter_cycle graph missing required loop frames: {missing_frames}")
        if not any(str(frame.get("progress_receipt_key") or "").strip() for frame in loop_frames):
            raise ValueError("writing chapter_cycle graph requires progress_receipt_key")


def _validate_review_gate_revision_edge(
    *,
    node: dict[str, Any],
    node_ids: set[str],
    edges: list[dict[str, Any]],
) -> None:
    node_id = str(node.get("node_id") or "").strip()
    review_gate_policy = dict(node.get("review_gate_policy") or _nested(node, "contract_bindings.acceptance.review_gate_policy") or {})
    revision_stage_id = str(review_gate_policy.get("revision_stage_id") or "").strip()
    if not revision_stage_id:
        return
    if revision_stage_id not in node_ids:
        raise ValueError(f"writing review gate revision_stage_id target not found: {node_id}->{revision_stage_id}")
    for edge in edges:
        if (
            str(edge.get("source_node_id") or "").strip() == node_id
            and str(edge.get("target_node_id") or "").strip() == revision_stage_id
            and str(edge.get("edge_type") or "").strip() in REVISION_EDGE_TYPES
        ):
            return
    raise ValueError(f"writing review gate revision edge not found: {node_id}->{revision_stage_id}")


def _validate_quorum_policy(node: dict[str, Any]) -> None:
    if str(node.get("join_policy") or "").strip() != "quorum":
        return
    metadata = dict(node.get("metadata") or {})
    execution = dict(metadata.get("execution") or {})
    quorum = node.get("quorum") or metadata.get("quorum") or execution.get("quorum") or execution.get("required_success_count")
    try:
        value = int(quorum or 0)
    except (TypeError, ValueError):
        value = 0
    if value < 1:
        raise ValueError(f"writing graph quorum join policy requires quorum count: {node.get('node_id')}")
    if str(node.get("join_policy") or "") not in NODE_JOIN_POLICIES:
        raise ValueError(f"unsupported join_policy: {node.get('join_policy')}")


def _nested(payload: dict[str, Any], dotted_key: str) -> Any:
    current: Any = payload
    for key in [item for item in dotted_key.split(".") if item]:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)]


def _compact_nested(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            compacted = _compact_nested(value)
            if compacted:
                result[key] = compacted
        elif isinstance(value, list):
            cleaned = [item for item in value if item not in ("", None, [], {})]
            if cleaned:
                result[key] = cleaned
        elif value not in ("", None, [], {}):
            result[key] = value
    return result
