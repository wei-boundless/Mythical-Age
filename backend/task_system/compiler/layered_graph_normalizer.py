from __future__ import annotations

from typing import Any

from task_system.graphs.task_graph_models import TaskGraphDefinition, TaskGraphEdgeDefinition, TaskGraphNodeDefinition


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
    loop_frames = [
        *_graph_runtime_loop_frames(graph),
        *[_loop_frame_payload(node) for node in nodes if _is_loop_frame(node)],
    ]
    timeline_blocks = _timeline_blocks(graph=graph, nodes=nodes)
    matrix = _memory_matrix(nodes=nodes, resource_nodes=resource_nodes, memory_edges=memory_edges)
    memory_protocol = _memory_protocol(resource_nodes=resource_nodes, memory_edges=memory_edges)
    issues = _layer_issues(
        graph=graph,
        resource_nodes=resource_nodes,
        temporal_edges=temporal_edges,
        memory_edges=memory_edges,
        artifact_context_edges=artifact_context_edges,
        revision_edges=revision_edges,
        memory_protocol=memory_protocol,
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
        "memory_protocol": memory_protocol,
        "artifact_context_edges": artifact_context_edges,
        "revision_edges": revision_edges,
        "loop_frames": loop_frames,
        "timeline_blocks": timeline_blocks,
        "memory_matrix": matrix,
        "issues": issues,
        "summary": {
            "resource_node_count": len(resource_nodes),
            "temporal_edge_count": len(temporal_edges),
            "memory_edge_count": len(memory_edges),
            "artifact_context_edge_count": len(artifact_context_edges),
            "revision_edge_count": len(revision_edges),
            "loop_frame_count": len(loop_frames),
            "timeline_block_count": len(timeline_blocks),
            "issue_count": len(issues),
        },
    }


def _is_resource_node(node: TaskGraphNodeDefinition) -> bool:
    node_type = str(node.node_type or "").strip()
    node_id = str(node.node_id or "").strip()
    return node_type in RESOURCE_NODE_TYPES or node_id.startswith(("memory.", "artifact.", "thread.", "progress.", "issue."))


def _is_loop_frame(node: TaskGraphNodeDefinition) -> bool:
    return str(node.node_type or "").strip() == "loop_frame"


def _graph_runtime_loop_frames(graph: TaskGraphDefinition) -> list[dict[str, Any]]:
    metadata = dict(graph.metadata or {})
    policy = dict(metadata.get("runtime_loop_policy") or {})
    frames = list(policy.get("frames") or [])
    normalized: list[dict[str, Any]] = []
    for index, raw_frame in enumerate(frames, start=1):
        if not isinstance(raw_frame, dict):
            continue
        frame = dict(raw_frame)
        frame_id = str(frame.get("frame_id") or frame.get("loop_frame_id") or f"runtime_loop_frame_{index}").strip()
        if not frame_id:
            continue
        normalized.append(
            {
                **frame,
                "frame_id": frame_id,
                "loop_frame_id": frame_id,
                "loop_kind": str(frame.get("loop_kind") or frame.get("kind") or "runtime_loop_policy_frame").strip(),
                "entry_stage_id": str(frame.get("entry_stage_id") or "").strip(),
                "router_stage_id": str(frame.get("router_stage_id") or "").strip(),
                "exit_stage_id": str(frame.get("exit_stage_id") or "").strip(),
                "initial_inputs": dict(policy.get("initial_inputs") or {}),
                "derived_fields": list(policy.get("derived_fields") or []),
                "policy": policy,
                "authority": "task_system.runtime_loop_policy",
            }
        )
    return normalized


def _resource_node_payload(node: TaskGraphNodeDefinition) -> dict[str, Any]:
    metadata = dict(node.metadata or {})
    repository_config = dict(metadata.get("memory_repository") or {})
    lifecycle = dict(node.resource_lifecycle_policy or {})
    raw_collections = repository_config.get("collections") if isinstance(repository_config.get("collections"), list) else metadata.get("collections")
    if not isinstance(raw_collections, list):
        raw_collections = []
    collection_specs = _collection_specs(raw_collections)
    return {
        "node_id": node.node_id,
        "title": node.title,
        "resource_type": node.node_type,
        "repository_id": str(repository_config.get("repository_id") or metadata.get("repository_id") or node.node_id),
        "collections": [item["collection_id"] for item in collection_specs],
        "collection_specs": collection_specs,
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
    metadata = dict(graph.metadata or {})
    metadata_edges = [
        dict(item)
        for item in list(metadata.get("temporal_edges") or [])
        if isinstance(item, dict)
    ]
    return [*metadata_edges, *explicit]


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
        "approval_source_node_id": str(metadata.get("approval_source_node_id") or ""),
        "approval_policy": str(metadata.get("approval_policy") or ""),
        "content_requirement": dict(
            metadata.get("content_requirement")
            or metadata.get("memory_content_requirement")
            or selector.get("content_requirement")
            or {}
        ),
        "materialization_policy": dict(
            metadata.get("materialization_policy")
            or metadata.get("candidate_materialization_policy")
            or {}
        ),
        "commit_visibility_policy": dict(
            metadata.get("commit_visibility_policy")
            or metadata.get("visibility_policy")
            or {}
        ),
        "model_visible_label": str(metadata.get("model_visible_label") or metadata.get("visible_label") or ""),
        "usage_instruction": str(metadata.get("usage_instruction") or metadata.get("instructions") or ""),
        "read_contract": dict(metadata.get("read_contract") or {}),
        "write_contract": dict(metadata.get("write_contract") or {}),
        "working_memory_handoff_policy": dict(edge.working_memory_handoff_policy or {}),
        "metadata": metadata,
        "authority": "task_system.memory_edge",
    }


def _collection_specs(raw_collections: list[Any]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_collections):
        if isinstance(raw, str):
            payload = {"collection_id": raw, "title": raw}
        elif isinstance(raw, dict):
            payload = dict(raw)
        else:
            continue
        collection_id = str(
            payload.get("collection_id")
            or payload.get("id")
            or payload.get("name")
            or ("default" if index == 0 else f"collection_{index + 1}")
        ).strip()
        if not collection_id:
            continue
        specs.append(
            {
                "collection_id": collection_id,
                "title": str(payload.get("title") or payload.get("label") or collection_id),
                "schema_id": str(payload.get("schema_id") or payload.get("schema_ref") or ""),
                "record_kinds": _string_list(payload.get("record_kinds") or payload.get("kinds")),
                "key_strategy": str(payload.get("key_strategy") or "stable_key"),
                "default_version_selector": str(payload.get("default_version_selector") or "latest_committed_before_clock"),
                "content_requirement": dict(payload.get("content_requirement") or {}),
                "snapshot_budget": dict(payload.get("snapshot_budget") or {}),
                "retention_policy": dict(payload.get("retention_policy") or {}),
                "authority": "task_system.memory_collection_spec",
            }
        )
    return specs


def _memory_protocol(*, resource_nodes: list[dict[str, Any]], memory_edges: list[dict[str, Any]]) -> dict[str, Any]:
    memory_resources = [item for item in resource_nodes if _resource_is_memory_repository(item)]
    repositories: list[dict[str, Any]] = []
    collections: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    repository_by_any_id: dict[str, dict[str, Any]] = {}
    collection_by_address: dict[tuple[str, str], dict[str, Any]] = {}
    for resource in memory_resources:
        repository = {
            "repository_id": str(resource.get("repository_id") or resource.get("node_id") or ""),
            "repository_node_id": str(resource.get("node_id") or ""),
            "title": str(resource.get("title") or resource.get("repository_id") or resource.get("node_id") or ""),
            "repository_kind": str(resource.get("resource_type") or "memory_repository"),
            "lifecycle_policy": dict(resource.get("lifecycle_policy") or {}),
            "scope_policy": dict(resource.get("lifecycle_policy") or {}),
            "mutable": bool(resource.get("mutable", True)),
            "authority": "task_system.memory_repository_spec",
        }
        repositories.append(repository)
        for key in (repository["repository_id"], repository["repository_node_id"]):
            if key:
                repository_by_any_id[key] = repository
        raw_specs = [dict(item) for item in list(resource.get("collection_specs") or []) if isinstance(item, dict)]
        if not raw_specs:
            raw_specs = [
                {
                    "collection_id": str(item),
                    "title": str(item),
                    "content_requirement": {},
                }
                for item in list(resource.get("collections") or [])
                if str(item).strip()
            ]
        for spec in raw_specs:
            collection_id = str(spec.get("collection_id") or "").strip()
            if not collection_id:
                continue
            collection = {
                **spec,
                "repository_id": repository["repository_id"],
                "repository_node_id": repository["repository_node_id"],
                "collection_id": collection_id,
                "content_requirement": dict(spec.get("content_requirement") or {}),
                "snapshot_budget": dict(spec.get("snapshot_budget") or {}),
                "authority": "task_system.memory_collection_spec",
            }
            collections.append(collection)
            collection_by_address[(repository["repository_id"], collection_id)] = collection
            collection_by_address[(repository["repository_node_id"], collection_id)] = collection
    read_edges: list[dict[str, Any]] = []
    write_edges: list[dict[str, Any]] = []
    commit_edges: list[dict[str, Any]] = []
    for edge in memory_edges:
        operation = _memory_protocol_operation(edge)
        if operation == "handoff":
            continue
        repository_id = _memory_edge_repository_id(edge=edge, repositories=repository_by_any_id)
        collection_id = str(edge.get("collection") or "").strip()
        collection = collection_by_address.get((repository_id, collection_id), {})
        spec = _memory_protocol_edge(edge=edge, operation=operation, repository_id=repository_id, collection_id=collection_id, collection=collection)
        if operation == "read":
            read_edges.append(spec)
        elif operation in {"write", "write_candidate"}:
            write_edges.append(spec)
        elif operation == "commit":
            commit_edges.append(spec)
        issues.extend(_memory_protocol_edge_issues(edge=spec, collection=collection))
    return {
        "authority": "task_system.memory_protocol",
        "repositories": repositories,
        "collections": collections,
        "read_edges": read_edges,
        "write_edges": write_edges,
        "commit_edges": commit_edges,
        "issues": issues,
        "summary": {
            "repository_count": len(repositories),
            "collection_count": len(collections),
            "read_edge_count": len(read_edges),
            "write_edge_count": len(write_edges),
            "commit_edge_count": len(commit_edges),
            "issue_count": len(issues),
        },
    }


def _resource_is_memory_repository(resource: dict[str, Any]) -> bool:
    resource_type = str(resource.get("resource_type") or "").strip()
    if resource_type == "artifact_repository":
        return False
    return resource_type in {"memory", "memory_resource", "memory_repository", "memory_collection", "working_memory_store", "thread_ledger", "progress_ledger", "issue_ledger", "runtime_state_store"}


def _memory_protocol_operation(edge: dict[str, Any]) -> str:
    operation = str(edge.get("memory_edge_type") or "").strip()
    if operation == "write_candidate":
        return "write_candidate"
    return operation


def _memory_edge_repository_id(*, edge: dict[str, Any], repositories: dict[str, dict[str, Any]]) -> str:
    explicit = str(edge.get("repository") or "").strip()
    if explicit:
        return str(repositories.get(explicit, {}).get("repository_id") or explicit)
    source = str(edge.get("source_node_id") or "").strip()
    target = str(edge.get("target_node_id") or "").strip()
    operation = _memory_protocol_operation(edge)
    connected = source if operation == "read" else target
    return str(repositories.get(connected, {}).get("repository_id") or connected)


def _memory_protocol_edge(
    *,
    edge: dict[str, Any],
    operation: str,
    repository_id: str,
    collection_id: str,
    collection: dict[str, Any],
) -> dict[str, Any]:
    selector = dict(edge.get("selector") or {})
    edge_requirement = dict(edge.get("content_requirement") or {})
    collection_requirement = dict(collection.get("content_requirement") or {})
    content_requirement = {**collection_requirement, **edge_requirement}
    return {
        "edge_id": str(edge.get("edge_id") or ""),
        "operation": operation,
        "source_node_id": str(edge.get("source_node_id") or ""),
        "target_node_id": str(edge.get("target_node_id") or ""),
        "repository_id": repository_id,
        "collection_id": collection_id,
        "address": {
            "repository_id": repository_id,
            "collection_id": collection_id,
            "record_key": str(edge.get("record_key") or selector.get("record_key") or ""),
            "record_kind": str(edge.get("record_kind") or selector.get("record_kind") or ""),
            "record_keys": list(edge.get("record_keys") or []),
            "record_kinds": list(edge.get("record_kinds") or []),
        },
        "selector": selector,
        "version_selector": str(edge.get("version_selector") or ""),
        "missing_policy": str(edge.get("on_missing") or ""),
        "source_output_key": str(edge.get("source_output_key") or ""),
        "candidate_ref_key": str(edge.get("candidate_ref_key") or ""),
        "verdict_key": str(edge.get("verdict_key") or ""),
        "required_verdict": str(edge.get("required_verdict") or ""),
        "approval_source_node_id": str(edge.get("approval_source_node_id") or ""),
        "commit_visibility_policy": dict(edge.get("commit_visibility_policy") or {}),
        "content_requirement": content_requirement,
        "materialization_policy": dict(edge.get("materialization_policy") or {}),
        "model_visible_label": str(edge.get("model_visible_label") or ""),
        "usage_instruction": str(edge.get("usage_instruction") or ""),
        "authority": "task_system.memory_protocol_edge",
    }


def _memory_protocol_edge_issues(*, edge: dict[str, Any], collection: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    edge_id = str(edge.get("edge_id") or "")
    operation = str(edge.get("operation") or "")
    repository_id = str(edge.get("repository_id") or "")
    collection_id = str(edge.get("collection_id") or "")
    requirement = dict(edge.get("content_requirement") or {})
    materialization = dict(edge.get("materialization_policy") or {})
    if not repository_id:
        issues.append(_memory_protocol_issue("memory_protocol_repository_missing", "记忆边缺少 repository，无法解析正式记忆地址。", edge_id=edge_id))
    if not collection_id:
        issues.append(_memory_protocol_issue("memory_protocol_collection_missing", "记忆边缺少 collection，无法解析正式记忆地址。", edge_id=edge_id))
    if repository_id and collection_id and not collection:
        issues.append(_memory_protocol_issue("memory_protocol_collection_undeclared", f"{repository_id}.{collection_id} 没有在记忆仓库中声明。", edge_id=edge_id))
    if operation == "read" and str(edge.get("missing_policy") or "") not in {"block", "required", "fail_closed", "warn", "ignore"}:
        issues.append(_memory_protocol_issue("memory_protocol_read_missing_policy_invalid", "memory_read 必须声明 block/fail_closed/warn/ignore 之一。", edge_id=edge_id, severity="warning"))
    if operation == "read" and str(edge.get("missing_policy") or "") not in {"block", "required", "fail_closed"}:
        issues.append(_memory_protocol_issue("memory_protocol_required_read_not_fail_closed", "正式记忆读取默认应 fail closed；除非明确是可选参考，否则不要使用非阻断策略。", edge_id=edge_id, severity="warning"))
    canonical_required = bool(requirement.get("canonical_text_required"))
    refs_only_allowed = bool(requirement.get("artifact_ref_only_allowed"))
    if canonical_required and refs_only_allowed:
        issues.append(_memory_protocol_issue("memory_protocol_refs_only_conflicts_with_canonical", "同一 collection 不能同时要求 canonical_text 又允许 refs-only 满足。", edge_id=edge_id))
    if operation in {"write", "write_candidate", "commit"} and canonical_required:
        canonical_text_mode = str(materialization.get("canonical_text_mode") or materialization.get("mode") or "").strip()
        if canonical_text_mode in {"none", "refs_only"}:
            issues.append(_memory_protocol_issue("memory_protocol_canonical_write_uses_refs_only_materialization", "要求 canonical_text 的写入边不能使用 refs_only materialization。", edge_id=edge_id))
    if operation in {"write", "write_candidate"} and not str(edge.get("source_output_key") or "").strip() and canonical_required and not materialization:
        issues.append(_memory_protocol_issue("memory_protocol_write_source_missing", "写入正式记忆需要 source_output_key 或 materialization_policy。", edge_id=edge_id))
    if operation == "commit":
        address = dict(edge.get("address") or {})
        has_candidate_ref = bool(str(edge.get("candidate_ref_key") or "").strip())
        has_approval = bool(str(edge.get("approval_source_node_id") or "").strip())
        has_record_selector = bool(str(address.get("record_key") or address.get("record_kind") or "").strip() or list(address.get("record_keys") or []) or list(address.get("record_kinds") or []))
        if not (has_candidate_ref or has_approval or has_record_selector):
            issues.append(_memory_protocol_issue("memory_protocol_commit_candidate_source_missing", "memory_commit 必须有 candidate_ref_key、approval_source_node_id 或明确 record selector。", edge_id=edge_id))
    return issues


def _memory_protocol_issue(code: str, message: str, *, edge_id: str = "", severity: str = "error") -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "severity": severity,
        "edge_id": edge_id,
        "authority": "task_system.memory_protocol_issue",
        "source": "task_system.memory_protocol_issue",
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


def _timeline_blocks(*, graph: TaskGraphDefinition, nodes: list[TaskGraphNodeDefinition]) -> list[dict[str, Any]]:
    metadata = dict(graph.metadata or {})
    explicit = [
        dict(item)
        for item in list(metadata.get("timeline_blocks") or [])
        if isinstance(item, dict)
    ]
    if explicit:
        return [_timeline_block_payload(item, index) for index, item in enumerate(explicit)]
    phase_ids = list(dict.fromkeys(str(node.phase_id or "").strip() for node in nodes if str(node.phase_id or "").strip()))
    blocks: list[dict[str, Any]] = []
    for index, phase_id in enumerate(phase_ids):
        phase_nodes = sorted(
            [node for node in nodes if str(node.phase_id or "").strip() == phase_id],
            key=lambda item: (int(item.sequence_index or 0), item.node_id),
        )
        if not phase_nodes:
            continue
        blocks.append(
            {
                "block_id": f"block.{phase_id}",
                "block_type": "phase_graph",
                "title": phase_id.replace("phase.", "") or phase_id,
                "phase_id": phase_id,
                "entry_node_id": phase_nodes[0].node_id,
                "exit_node_id": phase_nodes[-1].node_id,
                "handoff_contract_id": "",
                "visibility_policy": "committed_only",
                "version_ref": "",
                "detach_policy": "preserve_version_anchor",
                "derived": True,
                "authority": "task_system.timeline_block",
            }
        )
    return blocks


def _timeline_block_payload(payload: dict[str, Any], index: int) -> dict[str, Any]:
    block_id = str(payload.get("block_id") or payload.get("id") or f"timeline_block_{index + 1}").strip()
    contract_bindings = dict(payload.get("contract_bindings") or {})
    metadata = dict(payload.get("metadata") or {})
    legacy_handoff_contract_id = str(payload.get("handoff_contract_id") or "").strip()
    if legacy_handoff_contract_id:
        legacy_contract_fields = dict(metadata.get("legacy_contract_fields") or {})
        legacy_contract_fields.setdefault("handoff_contract_id", legacy_handoff_contract_id)
        metadata["legacy_contract_fields"] = legacy_contract_fields
    handoff_contract_id = _timeline_block_handoff_contract_id(payload)
    return {
        "block_id": block_id or f"timeline_block_{index + 1}",
        "block_type": str(payload.get("block_type") or "phase_graph").strip() or "phase_graph",
        "title": str(payload.get("title") or payload.get("name") or block_id or f"图块 {index + 1}").strip(),
        "phase_id": str(payload.get("phase_id") or "").strip(),
        "linked_graph_id": str(payload.get("linked_graph_id") or payload.get("graph_id") or "").strip(),
        "entry_node_id": str(payload.get("entry_node_id") or "").strip(),
        "exit_node_id": str(payload.get("exit_node_id") or "").strip(),
        "handoff_contract_id": handoff_contract_id,
        "visibility_policy": str(payload.get("visibility_policy") or "committed_only").strip() or "committed_only",
        "version_ref": str(payload.get("version_ref") or "").strip(),
        "detach_policy": str(payload.get("detach_policy") or "preserve_version_anchor").strip() or "preserve_version_anchor",
        "contract_bindings": contract_bindings,
        "metadata": metadata,
        "authority": "task_system.timeline_block",
    }


def _timeline_block_handoff_contract_id(payload: dict[str, Any]) -> str:
    contract_bindings = dict(payload.get("contract_bindings") or {})
    handoff_bindings = dict(contract_bindings.get("handoff") or {})
    return str(handoff_bindings.get("handoff_contract_id") or payload.get("handoff_contract_id") or "").strip()


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
    memory_protocol: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if memory_protocol:
        issues.extend(dict(item) for item in list(memory_protocol.get("issues") or []) if isinstance(item, dict))
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
