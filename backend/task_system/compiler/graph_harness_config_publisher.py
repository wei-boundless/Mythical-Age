from __future__ import annotations

from pathlib import Path
from typing import Any
import time

from harness.graph.language import (
    ARTIFACT_EDGE_TYPES,
    AUDIT_EDGE_TYPES,
    DEPENDENCY_EDGE_TYPES,
    EVENT_EDGE_TYPES,
    EXECUTABLE_MEMORY_NODE_TYPES,
    FILE_EDGE_TYPES,
    MEMORY_EDGE_TYPES,
    RESOURCE_NODE_TYPES,
    REVISION_EDGE_TYPES,
    harness_edge_scheduler_role,
    harness_edge_semantic_role,
)
from harness.graph.models import GraphHarnessConfig, safe_id, stable_hash
from task_system.compiler.layered_graph_normalizer import normalize_task_graph_layers
from task_system.environments import build_task_environment_catalog, task_environment_registry_from_backend_dir
from task_system.graphs.composable_graph_builder import build_composable_graph_view
from task_system.registry.flow_registry import TaskFlowRegistry


def publish_graph_harness_config_for_graph(
    *,
    base_dir: Path,
    graph_id: str,
    publish_version: str = "published",
    _visited: set[str] | None = None,
) -> GraphHarnessConfig:
    registry = TaskFlowRegistry(base_dir)
    graph = registry.get_task_graph(graph_id)
    if graph is None:
        raise ValueError(f"TaskGraph not found: {graph_id}")
    config = build_graph_harness_config_from_graph(
        graph=graph,
        publish_version=publish_version,
        graph_lookup=registry,
        base_dir=base_dir,
        visited_graph_ids=set(_visited or set()),
    )
    return registry.upsert_graph_harness_config(config, publish=True)


def build_graph_harness_config_from_graph(
    *,
    graph: Any,
    contract_manifest: dict[str, Any] | None = None,
    publish_version: str = "published",
    graph_lookup: Any | None = None,
    base_dir: Path | str | None = None,
    visited_graph_ids: set[str] | None = None,
) -> GraphHarnessConfig:
    graph_id = str(getattr(graph, "graph_id", "") or "").strip()
    if not graph_id:
        raise ValueError("TaskGraphDefinition requires graph_id before GraphHarnessConfig publication")
    visited = set(visited_graph_ids or set())
    if graph_id in visited:
        raise ValueError(f"cyclic graph composition detected: {graph_id}")
    visited.add(graph_id)

    projection = _project_graph_for_harness(
        graph=graph,
        graph_lookup=graph_lookup,
        publish_version=publish_version,
        visited_graph_ids=visited,
    )
    layered = projection["layered_graph"]
    graph_metadata = dict(getattr(graph, "metadata", {}) or {})
    graph_runtime_policy = dict(getattr(graph, "runtime_policy", {}) or {})
    graph_context_policy = dict(getattr(graph, "context_policy", {}) or {})
    task_environment_id = _graph_task_environment_id(
        graph_runtime_policy=graph_runtime_policy,
        graph_context_policy=graph_context_policy,
    )
    environment = _published_environment_payload(
        task_environment_id=task_environment_id,
        base_dir=base_dir,
        graph_lookup=graph_lookup,
    )
    split_plans = _list_dicts(graph_metadata.get("split_plans") or graph_runtime_policy.get("split_plans"))
    manifest = dict(contract_manifest or _contract_manifest_from_projection(graph=graph, projection=projection))
    nodes = [dict(item) for item in projection["nodes"]]
    edges = [dict(item) for item in projection["edges"]]
    composition_sources = [dict(item) for item in projection["composition_sources"]]
    issues = [
        *[dict(item) for item in list(getattr(graph, "to_dict", lambda: {})().get("issues") or []) if isinstance(item, dict)],
        *[dict(item) for item in list(layered.get("issues") or []) if isinstance(item, dict)],
        *[dict(item) for item in list(projection.get("issues") or []) if isinstance(item, dict)],
    ]
    provisional = {
        "graph_id": graph_id,
        "graph_title": str(getattr(graph, "title", "") or graph_id),
        "publish_version": publish_version,
        "task_environment_id": task_environment_id,
        "root_task_ref": str(getattr(graph, "graph_contract_id", "") or graph_id),
        "control": {
            "start_node_ids": list(projection["start_node_ids"]),
            "terminal_node_ids": list(projection["terminal_node_ids"]),
            "scheduling_policy": {
                "mode": str(graph_runtime_policy.get("scheduling_mode") or "topology"),
                "max_active_nodes": int(graph_runtime_policy.get("max_active_nodes") or 1),
            },
            "max_active_nodes": int(graph_runtime_policy.get("max_active_nodes") or 1),
            "completion_policy": _policy_dict(graph_runtime_policy.get("completion_policy")),
            "failure_policy": _policy_dict(graph_runtime_policy.get("failure_policy")),
            "retry_policy": _policy_dict(graph_runtime_policy.get("retry_policy")),
            "checkpoint_policy": _policy_dict(graph_runtime_policy.get("checkpoint_policy")),
            "resume_policy": {"mode": "config_id_locked"},
            "human_gate_policy": _policy_dict(graph_metadata.get("human_gate_policy")),
            "batch_policy": {"enabled": bool(split_plans), "split_plans": split_plans},
            "temporal_edges": _list_dicts(layered.get("temporal_edges")),
            "revision_edges": _list_dicts(layered.get("revision_edges")),
            "communication_protocol_id": str(
                getattr(graph, "default_protocol_id", "") or graph_metadata.get("protocol_id") or ""
            ),
            "handoff_policy": str(graph_metadata.get("handoff_policy") or "handoff"),
            "merge_policy": str(graph_runtime_policy.get("merge_policy") or graph_metadata.get("output_merge_policy") or ""),
        },
        "nodes": nodes,
        "edges": edges,
        "loop_frames": _normalize_loop_frames(_list_dicts(layered.get("loop_frames")) + _list_dicts(projection.get("loop_frames"))),
        "environment": environment,
        "resources": {
            "resource_nodes": _list_dicts(layered.get("resource_nodes")) + _list_dicts(projection.get("resource_nodes")),
        },
        "memory": {
            "working_memory_policy_profile_id": str(getattr(graph, "working_memory_policy_profile_id", "") or ""),
            "working_memory_policy": dict(getattr(graph, "working_memory_policy", {}) or {}),
            "memory_matrix": dict(layered.get("memory_matrix") or {}),
            "memory_protocol": dict(layered.get("memory_protocol") or {}),
            "read_rules": _list_dicts(layered.get("memory_edges")) + _list_dicts(projection.get("memory_edges")),
        },
        "artifacts": {
            "context_edges": _list_dicts(layered.get("artifact_context_edges")) + _list_dicts(projection.get("artifact_context_edges")),
        },
        "permissions": dict(graph_runtime_policy.get("permissions") or graph_metadata.get("permissions") or {}),
        "tools": dict(graph_runtime_policy.get("tools") or graph_metadata.get("tools") or {}),
        "agents": {
            "coordinator_agent_id": str(graph_runtime_policy.get("coordinator_agent_id") or graph_metadata.get("coordinator_agent_id") or "agent:0"),
            "agent_group_id": str(graph_runtime_policy.get("agent_group_id") or graph_metadata.get("agent_group_id") or ""),
        },
        "contracts": {
            "manifest": manifest,
            "node_contracts": list(manifest.get("node_contracts") or []),
            "edge_contracts": list(manifest.get("edge_handoff_contracts") or []),
            "runtime_contracts": list(manifest.get("runtime_contracts") or []),
            "acceptance_contracts": list(manifest.get("acceptance_contracts") or []),
        },
        "composition_sources": composition_sources,
        "diagnostics": {
            "source": "task_system.graph_harness_config_publisher",
            "source_graph_authority": str(getattr(graph, "authority", "") or "task_system.task_graph_definition"),
            "layered_graph": {
                "authority": layered.get("authority"),
                "summary": dict(layered.get("summary") or {}),
                "layers": dict(layered.get("layers") or {}),
            },
            "composable_graph": dict(projection.get("composable_graph_summary") or {}),
            "summary": {
                "node_count": len(nodes),
                "edge_count": len(edges),
                "composition_source_count": len(composition_sources),
                "issue_count": len(issues),
            },
            "issues": issues,
        },
        "authority_map": {
            "observe": "task_system.task_graph_definition",
            "normalize": "task_system.graph_harness_config_publisher",
            "assemble": "harness.graph.runtime",
            "decide": "harness.graph.loop",
            "execute_agent": "harness.agent_loop",
            "record": "harness.graph.loop",
        },
        "source_refs": {
            "graph_id": graph_id,
            "publish_state": str(getattr(graph, "publish_state", "") or ""),
            "graph_contract_id": str(getattr(graph, "graph_contract_id", "") or ""),
            "default_protocol_id": str(getattr(graph, "default_protocol_id", "") or ""),
            "composition_sources": composition_sources,
        },
    }
    content_hash = stable_hash(
        {
            "config_schema_version": "graph_harness_config.v1",
            "authority": "harness.graph_harness_config",
            "status": "published",
            **provisional,
        }
    )
    return GraphHarnessConfig(
        config_id=f"ghcfg:{safe_id(graph_id)}:{content_hash[:16]}",
        content_hash=content_hash,
        published_at=time.time(),
        status="published",
        **provisional,
    )


def _project_graph_for_harness(
    *,
    graph: Any,
    graph_lookup: Any | None,
    publish_version: str,
    visited_graph_ids: set[str],
) -> dict[str, Any]:
    graph_id = str(getattr(graph, "graph_id", "") or "").strip()
    layered = normalize_task_graph_layers(graph)
    composable = build_composable_graph_view(graph=graph, layered_graph=layered)
    composition_plans = _composition_plans(graph)
    composition_node_ids = {item["composition_node_id"] for item in composition_plans}
    base_nodes = [
        _graph_node_config(node, graph_id=graph_id)
        for node in tuple(getattr(graph, "nodes", ()) or ())
        if str(getattr(node, "node_id", "") or "").strip() not in composition_node_ids
    ]
    base_edges = [
        _graph_edge_config(edge)
        for edge in tuple(getattr(graph, "edges", ()) or ())
        if not _edge_touches_any(_edge_payload(edge), composition_node_ids)
    ]
    projection = _expand_composition_sources(
        graph=graph,
        composition_plans=composition_plans,
        nodes=tuple(base_nodes),
        edges=tuple(base_edges),
        graph_lookup=graph_lookup,
        publish_version=publish_version,
        visited_graph_ids=visited_graph_ids,
    )
    if not projection["start_node_ids"]:
        projection["start_node_ids"] = _derive_start_node_ids(list(projection["nodes"]), list(projection["edges"]))
    if not projection["terminal_node_ids"]:
        projection["terminal_node_ids"] = _derive_terminal_node_ids(list(projection["nodes"]), list(projection["edges"]))
    else:
        projection["terminal_node_ids"] = list(
            dict.fromkeys(
                [
                    *[str(item) for item in list(projection["terminal_node_ids"] or []) if str(item)],
                    *_derive_terminal_node_ids(list(projection["nodes"]), list(projection["edges"])),
                ]
            )
        )
    projection["layered_graph"] = layered
    projection["composable_graph_summary"] = {
        "authority": composable.authority,
        "unit_count": len(composable.units),
        "interface_count": len(composable.interfaces),
        "port_edge_count": len(composable.port_edges),
        "composition_plan_count": len(composition_plans),
        "issue_count": len(composable.issues),
    }
    projection["issues"] = [dict(item) for item in composable.issues]
    return projection


def _composition_plans(graph: Any) -> tuple[dict[str, Any], ...]:
    plans: list[dict[str, Any]] = []
    for node in tuple(getattr(graph, "nodes", ()) or ()):
        node_id = str(getattr(node, "node_id", "") or "").strip()
        node_type = str(getattr(node, "node_type", "") or "").strip()
        metadata = dict(getattr(node, "metadata", {}) or {})
        executor_policy = dict(getattr(node, "executor_policy", {}) or {})
        bindings = dict(getattr(node, "contract_bindings", {}) or {})
        runtime_bindings = dict(bindings.get("runtime") or {})
        composition = dict(runtime_bindings.get("graph_composition") or {})
        legacy_module = dict(runtime_bindings.get("graph_module_runtime") or {})
        default_executor = str(executor_policy.get("default_executor") or executor_policy.get("executor") or "").strip()
        is_composition = (
            node_type in {"graph_module", "graph_composition"}
            or bool(metadata.get("graph_module"))
            or bool(metadata.get("graph_composition"))
            or default_executor in {"graph_module", "imported_graph", "graph_composition"}
        )
        if not is_composition:
            continue
        linked_graph_id = str(
            composition.get("linked_graph_id")
            or metadata.get("linked_graph_id")
            or metadata.get("imported_graph_id")
            or executor_policy.get("linked_graph_id")
            or executor_policy.get("imported_graph_id")
            or legacy_module.get("linked_graph_id")
            or ""
        ).strip()
        plans.append(
            {
                "composition_id": f"graph-composition:{safe_id(str(getattr(graph, 'graph_id', '') or 'graph'))}:{safe_id(node_id)}",
                "composition_node_id": node_id,
                "linked_graph_id": linked_graph_id,
                "scope_prefix": f"{node_id}::",
                "version_ref": str(composition.get("version_ref") or metadata.get("version_ref") or publish_version_default()),
                "metadata": {
                    "source_node_title": str(getattr(node, "title", "") or node_id),
                    "source_node_type": node_type,
                },
            }
        )
    return tuple(plans)


def publish_version_default() -> str:
    return "published"


def _expand_composition_sources(
    *,
    graph: Any,
    composition_plans: tuple[dict[str, Any], ...],
    nodes: tuple[dict[str, Any], ...],
    edges: tuple[dict[str, Any], ...],
    graph_lookup: Any | None,
    publish_version: str,
    visited_graph_ids: set[str],
) -> dict[str, Any]:
    if not composition_plans:
        return {
            "nodes": nodes,
            "edges": edges,
            "start_node_ids": _entry_ids_after_expansion(graph=graph, expanded_by_node_id={}),
            "terminal_node_ids": _output_ids_after_expansion(graph=graph, expanded_by_node_id={}),
            "loop_frames": [],
            "resource_nodes": [],
            "memory_edges": [],
            "artifact_context_edges": [],
            "composition_sources": [],
            "issues": [],
        }
    node_ids = {str(node.get("node_id") or "") for node in nodes}
    edge_ids = {str(edge.get("edge_id") or "") for edge in edges}
    all_nodes = [dict(item) for item in nodes]
    all_edges = [dict(item) for item in edges]
    loop_frames: list[dict[str, Any]] = []
    resource_nodes: list[dict[str, Any]] = []
    memory_edges: list[dict[str, Any]] = []
    artifact_context_edges: list[dict[str, Any]] = []
    composition_sources: list[dict[str, Any]] = []
    expanded_by_node_id: dict[str, dict[str, Any]] = {}
    for plan in composition_plans:
        expanded = _expand_composition_plan(
            graph=graph,
            plan=plan,
            graph_lookup=graph_lookup,
            publish_version=publish_version,
            visited_graph_ids=visited_graph_ids,
        )
        composition_node_id = str(plan.get("composition_node_id") or "")
        expanded_by_node_id[composition_node_id] = expanded
        composition_sources.append(expanded["composition_source"])
        for node in expanded["nodes"]:
            node_id = str(node.get("node_id") or "")
            if node_id and node_id not in node_ids:
                all_nodes.append(node)
                node_ids.add(node_id)
        for edge in expanded["edges"]:
            edge_id = str(edge.get("edge_id") or "")
            if edge_id and edge_id not in edge_ids:
                all_edges.append(edge)
                edge_ids.add(edge_id)
        loop_frames.extend(expanded["loop_frames"])
        resource_nodes.extend(expanded["resource_nodes"])
        memory_edges.extend(expanded["memory_edges"])
        artifact_context_edges.extend(expanded["artifact_context_edges"])
    for edge in _composition_bridge_edges(graph=graph, expanded_by_node_id=expanded_by_node_id):
        edge_id = str(edge.get("edge_id") or "")
        if edge_id and edge_id not in edge_ids:
            all_edges.append(edge)
            edge_ids.add(edge_id)
    return {
        "nodes": tuple(all_nodes),
        "edges": tuple(all_edges),
        "start_node_ids": _entry_ids_after_expansion(graph=graph, expanded_by_node_id=expanded_by_node_id),
        "terminal_node_ids": _output_ids_after_expansion(graph=graph, expanded_by_node_id=expanded_by_node_id),
        "loop_frames": loop_frames,
        "resource_nodes": resource_nodes,
        "memory_edges": memory_edges,
        "artifact_context_edges": artifact_context_edges,
        "composition_sources": composition_sources,
    }


def _expand_composition_plan(
    *,
    graph: Any,
    plan: dict[str, Any],
    graph_lookup: Any | None,
    publish_version: str,
    visited_graph_ids: set[str],
) -> dict[str, Any]:
    linked_graph_id = str(plan.get("linked_graph_id") or "").strip()
    composition_node_id = str(plan.get("composition_node_id") or "").strip()
    if not composition_node_id:
        raise ValueError("Graph composition source requires composition_node_id")
    if not linked_graph_id:
        raise ValueError(f"Graph composition source requires linked_graph_id: {composition_node_id}")
    current_graph_id = str(getattr(graph, "graph_id", "") or "").strip()
    if linked_graph_id in visited_graph_ids or linked_graph_id == current_graph_id:
        raise ValueError(f"cyclic graph composition detected: {current_graph_id} -> {linked_graph_id}")
    imported_graph = _lookup_graph(graph_lookup, linked_graph_id)
    if imported_graph is None:
        raise ValueError(f"Graph composition source not found: {linked_graph_id}")
    nested = _project_graph_for_harness(
        graph=imported_graph,
        graph_lookup=graph_lookup,
        publish_version=publish_version,
        visited_graph_ids=visited_graph_ids,
    )
    nested_layered = dict(nested.get("layered_graph") or {})
    scope_prefix = str(plan.get("scope_prefix") or f"{composition_node_id}::")
    nested_node_ids = {str(node.get("node_id") or "") for node in nested["nodes"] if str(node.get("node_id") or "")}
    scoped_nodes = [
        _scope_node(
            node,
            scope_prefix=scope_prefix,
            source_graph_id=linked_graph_id,
            composition_node_id=composition_node_id,
            node_ids=nested_node_ids,
        )
        for node in nested["nodes"]
    ]
    scoped_edges = [
        _scope_edge(edge, scope_prefix=scope_prefix, source_graph_id=linked_graph_id, composition_node_id=composition_node_id)
        for edge in nested["edges"]
    ]
    nested_loop_frames = _list_dicts(nested_layered.get("loop_frames")) + _list_dicts(nested.get("loop_frames"))
    nested_resource_nodes = _list_dicts(nested_layered.get("resource_nodes")) + _list_dicts(nested.get("resource_nodes"))
    nested_memory_edges = _list_dicts(nested_layered.get("memory_edges")) + _list_dicts(nested.get("memory_edges"))
    nested_artifact_edges = _list_dicts(nested_layered.get("artifact_context_edges")) + _list_dicts(nested.get("artifact_context_edges"))
    scoped_loop_frames = [
        _scope_loop_frame_payload(item, scope_prefix=scope_prefix, node_ids=nested_node_ids)
        for item in nested_loop_frames
    ]
    scoped_resources = [_scope_generic_payload(item, scope_prefix=scope_prefix, id_keys=("node_id", "resource_id", "repository_id")) for item in nested_resource_nodes]
    scoped_memory_edges = [_scope_edge_like_payload(item, scope_prefix=scope_prefix) for item in nested_memory_edges]
    scoped_artifact_edges = [_scope_edge_like_payload(item, scope_prefix=scope_prefix) for item in nested_artifact_edges]
    scoped_start_ids = [_scoped_id(item, scope_prefix=scope_prefix) for item in nested["start_node_ids"]]
    scoped_terminal_ids = [_scoped_id(item, scope_prefix=scope_prefix) for item in nested["terminal_node_ids"]]
    return {
        "nodes": tuple(scoped_nodes),
        "edges": tuple(scoped_edges),
        "loop_frames": scoped_loop_frames,
        "resource_nodes": scoped_resources,
        "memory_edges": scoped_memory_edges,
        "artifact_context_edges": scoped_artifact_edges,
        "start_node_ids": scoped_start_ids,
        "terminal_node_ids": scoped_terminal_ids,
        "composition_source": {
            "source_type": "graph_composition",
            "composition_id": str(plan.get("composition_id") or ""),
            "composition_node_id": composition_node_id,
            "linked_graph_id": linked_graph_id,
            "scope_prefix": scope_prefix,
            "publish_version": publish_version,
            "entry_node_ids": scoped_start_ids,
            "terminal_node_ids": scoped_terminal_ids,
            "node_count": len(scoped_nodes),
            "edge_count": len(scoped_edges),
            "metadata": dict(plan.get("metadata") or {}),
        },
    }


def _composition_bridge_edges(*, graph: Any, expanded_by_node_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    bridges: list[dict[str, Any]] = []
    for edge in tuple(getattr(graph, "edges", ()) or ()):
        payload = _edge_payload(edge)
        source = str(payload.get("source_node_id") or "")
        target = str(payload.get("target_node_id") or "")
        source_expansion = expanded_by_node_id.get(source)
        target_expansion = expanded_by_node_id.get(target)
        if source_expansion is None and target_expansion is None:
            continue
        source_ids = (
            [str(item) for item in list(source_expansion.get("terminal_node_ids") or []) if str(item)]
            if source_expansion is not None
            else [source]
        )
        target_ids = (
            [str(item) for item in list(target_expansion.get("start_node_ids") or []) if str(item)]
            if target_expansion is not None
            else [target]
        )
        bridge_role = "composition_to_composition" if source_expansion is not None and target_expansion is not None else (
            "out_of_composition" if source_expansion is not None else "into_composition"
        )
        for source_id in source_ids:
            for target_id in target_ids:
                bridges.append(_bridge_edge(payload, source_node_id=source_id, target_node_id=target_id, bridge_role=bridge_role))
    return bridges


def _entry_ids_after_expansion(*, graph: Any, expanded_by_node_id: dict[str, dict[str, Any]]) -> list[str]:
    explicit = str(getattr(graph, "entry_node_id", "") or "").strip()
    if not explicit:
        return []
    expansion = expanded_by_node_id.get(explicit)
    if expansion is not None:
        return [str(item) for item in list(expansion.get("start_node_ids") or []) if str(item)]
    return [explicit]


def _output_ids_after_expansion(*, graph: Any, expanded_by_node_id: dict[str, dict[str, Any]]) -> list[str]:
    explicit = str(getattr(graph, "output_node_id", "") or "").strip()
    if not explicit:
        return []
    expansion = expanded_by_node_id.get(explicit)
    if expansion is not None:
        return [str(item) for item in list(expansion.get("terminal_node_ids") or []) if str(item)]
    return [explicit]


def _contract_manifest_from_projection(*, graph: Any, projection: dict[str, Any]) -> dict[str, Any]:
    graph_id = str(getattr(graph, "graph_id", "") or "")
    node_contracts = []
    for node in projection["nodes"]:
        contracts = dict(node.get("contracts") or {})
        refs = _contract_refs(
            contracts.get("node_contract_id"),
            contracts.get("input_contract_id"),
            contracts.get("output_contract_id"),
            *list(dict(contracts.get("contract_bindings") or {}).get("contract_refs") or []),
        )
        node_contracts.append(
            {
                "node_id": str(node.get("node_id") or ""),
                "title": str(node.get("title") or ""),
                "node_type": str(node.get("node_type") or ""),
                "task_id": str(node.get("task_ref") or ""),
                "agent_id": str(node.get("agent_id") or ""),
                "input_contract_id": str(contracts.get("input_contract_id") or ""),
                "output_contract_id": str(contracts.get("output_contract_id") or ""),
                "contract_refs": refs,
                "contract_bindings": dict(contracts.get("contract_bindings") or {}),
            }
        )
    edge_contracts = []
    for edge in projection["edges"]:
        edge_contracts.append(
            {
                "edge_id": str(edge.get("edge_id") or ""),
                "source_node_id": str(edge.get("source_node_id") or ""),
                "target_node_id": str(edge.get("target_node_id") or ""),
                "message_type": "message/send",
                "contract_refs": _contract_refs(edge.get("payload_contract_id")),
                "handoff_policy": "structured_packet",
                "schema_bindings": dict(dict(edge.get("contract_bindings") or {}).get("schema") or {}),
                "handoff_bindings": dict(dict(edge.get("contract_bindings") or {}).get("handoff") or {}),
            }
        )
    return {
        "authority": "task_system.contract_manifest",
        "manifest_id": f"contract-manifest:graph:{graph_id}",
        "manifest_kind": "task_graph",
        "graph_id": graph_id,
        "graph_ref": graph_id,
        "node_contracts": node_contracts,
        "edge_handoff_contracts": edge_contracts,
        "runtime_contracts": [],
        "acceptance_contracts": [],
        "issues": [],
        "valid": True,
        "metadata": {"compiler": "graph_harness_config_publisher"},
    }


def _graph_task_environment_id(*, graph_runtime_policy: dict[str, Any], graph_context_policy: dict[str, Any]) -> str:
    return str(
        graph_runtime_policy.get("task_environment_id")
        or graph_runtime_policy.get("environment_id")
        or graph_context_policy.get("task_environment_id")
        or graph_context_policy.get("environment_id")
        or ""
    ).strip()


def _published_environment_payload(
    *,
    task_environment_id: str,
    base_dir: Path | str | None,
    graph_lookup: Any | None,
) -> dict[str, Any]:
    environment_id = str(task_environment_id or "").strip()
    if not environment_id:
        return {}
    registry_base = base_dir or getattr(graph_lookup, "base_dir", None)
    if registry_base is None:
        return {
            "task_environment_id": environment_id,
            "environment_id": environment_id,
            "locked": False,
            "lock_error": "backend_dir_required_for_task_environment_lock",
            "authority": "task_system.graph_harness_config_publisher.environment_lock",
        }
    catalog = build_task_environment_catalog(
        registry=task_environment_registry_from_backend_dir(Path(registry_base)),
    )
    payload = catalog.runtime_environment_payload(environment_id)
    return {
        **dict(payload),
        "task_environment_id": environment_id,
        "environment_id": str(payload.get("environment_id") or environment_id),
        "locked": True,
        "authority": "task_system.graph_harness_config_publisher.environment_lock",
    }


def _node_config(node: dict[str, Any], *, graph_id: str) -> dict[str, Any]:
    raw_metadata = dict(node.get("metadata") or {})
    metadata = _published_node_metadata(raw_metadata)
    contract_bindings = dict(node.get("contract_bindings") or raw_metadata.get("contract_bindings") or {})
    prompt_contract = dict(raw_metadata.get("prompt_contract") or {})
    node_id = str(node.get("node_id") or "").strip()
    node_type = str(node.get("node_type") or "agent").strip() or "agent"
    task_ref = str(node.get("task_id") or metadata.get("task_ref") or f"task_graph.node.{graph_id}.{node_id}").strip()
    return {
        "node_id": node_id,
        "title": str(node.get("title") or node_id),
        "node_type": node_type,
        "node_class": "resource" if _is_resource_node_type(node_type=node_type, node_id=node_id) else "executable",
        "task_ref": task_ref,
        "agent_id": str(node.get("agent_id") or ""),
        "agent_profile_id": str(metadata.get("agent_profile_id") or metadata.get("agent_profile_ref") or ""),
        "executor": {
            "executor_type": _executor_type_for_node(node),
            "executor_policy": dict(node.get("executor_policy") or metadata.get("executor_policy") or {}),
        },
        "execution": {
            "execution_mode": str(node.get("execution_mode") or "sync"),
            "wait_policy": str(node.get("wait_policy") or "wait_all_upstream_completed"),
            "join_policy": str(node.get("join_policy") or "all_success"),
            "dispatch_group": str(node.get("dispatch_group") or ""),
        },
        "contracts": {
            "node_contract_id": str(node.get("node_contract_id") or dict(contract_bindings.get("execution") or {}).get("node_contract_id") or ""),
            "input_contract_id": str(node.get("input_contract_id") or dict(contract_bindings.get("schema") or {}).get("input_contract_id") or ""),
            "output_contract_id": str(node.get("output_contract_id") or dict(contract_bindings.get("schema") or {}).get("output_contract_id") or ""),
            "contract_bindings": contract_bindings,
        },
        "prompt": {
            "role_prompt": str(prompt_contract.get("role_prompt") or metadata.get("role_prompt") or ""),
            "task_instruction": str(prompt_contract.get("task_instruction") or metadata.get("task_instruction") or ""),
            "output_instruction": str(prompt_contract.get("output_instruction") or metadata.get("output_instruction") or ""),
        },
        "context": dict(node.get("context_visibility_policy") or {}),
        "memory": {
            "read_policy": dict(node.get("memory_read_policy") or {}),
            "writeback_policy": dict(node.get("memory_writeback_policy") or {}),
            "dynamic_read_policy": dict(node.get("dynamic_memory_read_policy") or {}),
        },
        "artifacts": dict(node.get("artifact_policy") or {}),
        "stream": dict(node.get("stream_policy") or {}),
        "gates": {
            "review_gate_policy": dict(node.get("review_gate_policy") or {}),
            "human_gate_policy": dict(node.get("human_gate_policy") or metadata.get("human_gate_policy") or {}),
        },
        "retry": dict(node.get("quality_retry_policy") or metadata.get("quality_retry_policy") or {}),
        "loop": _node_loop_contract(node, metadata=raw_metadata),
        "permissions": dict(metadata.get("permissions") or {}),
        "tools": dict(metadata.get("tools") or {}),
        "metadata": metadata,
    }


def _published_node_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return dict(metadata or {})


def _node_loop_contract(node: dict[str, Any], *, metadata: dict[str, Any]) -> dict[str, Any]:
    loop = dict(node.get("loop") or {})
    if not loop:
        return {}
    contract = dict(loop)
    if isinstance(contract.get("route_policy"), dict):
        contract["route_policy"] = _normalize_route_policy(contract.get("route_policy"))
    contract["scope_id"] = str(contract.get("scope_id") or "").strip()
    contract["kind"] = str(contract.get("kind") or "").strip()
    contract["title_template"] = str(contract.get("title_template") or "").strip()
    contract["policy"] = dict(contract.get("policy") or {})
    contract["authority"] = "harness.graph.node_loop_contract"
    return _prune_empty(contract)


def _normalize_route_policy(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    payload = dict(value)
    scope_id = str(payload.get("scope_id") or "").strip()
    continue_node_id = str(payload.get("continue_node_id") or "").strip()
    exit_node_id = str(payload.get("exit_node_id") or "").strip()
    route = {
        "scope_id": scope_id,
        "continue_node_id": continue_node_id,
        "exit_node_id": exit_node_id,
        "mode": str(payload.get("mode") or "metric_target").strip() or "metric_target",
        "metric_key": str(payload.get("metric_key") or "").strip(),
        "diagnostic_metric_key": str(payload.get("diagnostic_metric_key") or "").strip(),
        "fallback_increment_key": str(payload.get("fallback_increment_key") or "").strip(),
        "default_increment": payload.get("default_increment"),
        "current_key": str(payload.get("current_key") or "").strip(),
        "target_key": str(payload.get("target_key") or "").strip(),
        "last_metric_key": str(payload.get("last_metric_key") or "").strip(),
        "secondary_counters": list(payload.get("secondary_counters") or []),
        "patch_rules": list(payload.get("patch_rules") or []),
        "derived_fields": list(payload.get("derived_fields") or []),
        "authority": "harness.graph.route_policy",
    }
    return _prune_empty(route)


def _normalize_loop_frames(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(frames, start=1):
        frame = dict(raw or {})
        frame_id = str(frame.get("frame_id") or frame.get("loop_frame_id") or frame.get("scope_id") or f"loop_frame_{index}").strip()
        if not frame_id:
            continue
        result.append(
            _prune_empty(
                {
                    "frame_id": frame_id,
                    "scope_id": str(frame.get("scope_id") or frame_id).strip(),
                    "title": str(frame.get("title") or "").strip(),
                    "kind": str(frame.get("kind") or "").strip(),
                    "entry_node_id": str(frame.get("entry_node_id") or "").strip(),
                    "router_node_id": str(frame.get("router_node_id") or "").strip(),
                    "continue_node_id": str(frame.get("continue_node_id") or "").strip(),
                    "exit_node_id": str(frame.get("exit_node_id") or "").strip(),
                    "unit_kind": str(frame.get("unit_kind") or "").strip(),
                    "iteration_size_key": str(frame.get("iteration_size_key") or "").strip(),
                    "initial_inputs": dict(frame.get("initial_inputs") or {}),
                    "derived_fields": list(frame.get("derived_fields") or []),
                    "authority": "harness.graph.loop_frame_contract",
                }
            )
        )
    return result


def _graph_node_config(node: Any, *, graph_id: str) -> dict[str, Any]:
    raw = node.to_dict() if hasattr(node, "to_dict") else dict(node or {})
    return _node_config(raw, graph_id=graph_id)


def _edge_config(edge: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(edge.get("metadata") or {})
    contract_bindings = dict(edge.get("contract_bindings") or {})
    schema_bindings = dict(contract_bindings.get("schema") or {})
    edge_type = str(edge.get("mode") or edge.get("edge_type") or "handoff")
    return {
        "edge_id": str(edge.get("edge_id") or ""),
        "source_node_id": str(edge.get("source_node_id") or edge.get("from") or edge.get("source") or ""),
        "target_node_id": str(edge.get("target_node_id") or edge.get("to") or edge.get("target") or ""),
        "edge_type": edge_type,
        "semantic_role": _semantic_role_for_edge(edge_type=edge_type, metadata=metadata),
        "scheduler_role": _scheduler_role_for_edge(edge_type=edge_type, metadata=metadata),
        "wait_policy": str(edge.get("wait_policy") or ""),
        "ack_policy": str(edge.get("ack_policy") or "explicit_ack"),
        "ack_required": bool(edge.get("ack_required", True)),
        "failure_propagation_policy": str(edge.get("failure_propagation_policy") or "fail_downstream"),
        "result_delivery_policy": str(edge.get("result_delivery_policy") or "contract_payload_and_refs"),
        "payload_contract_id": str(edge.get("payload_contract_id") or schema_bindings.get("payload_contract_id") or ""),
        "contract_bindings": contract_bindings,
        "context_filter_policy": dict(edge.get("context_filter_policy") or {}),
        "artifact_ref_policy": dict(edge.get("artifact_ref_policy") or {}),
        "working_memory_handoff_policy": dict(edge.get("working_memory_handoff_policy") or {}),
        "temporal_policy": dict(metadata.get("temporal_policy") or {}),
        "revision_policy": dict(metadata.get("revision_policy") or {}),
        "metadata": metadata,
    }


def _graph_edge_config(edge: Any) -> dict[str, Any]:
    raw = edge.to_dict() if hasattr(edge, "to_dict") else dict(edge or {})
    return _edge_config(raw)


def _bridge_edge(raw_edge: dict[str, Any], *, source_node_id: str, target_node_id: str, bridge_role: str) -> dict[str, Any]:
    payload = _edge_config(raw_edge)
    payload["edge_id"] = f"{raw_edge.get('edge_id')}.{bridge_role}.{safe_id(source_node_id)}.{safe_id(target_node_id)}"
    payload["source_node_id"] = source_node_id
    payload["target_node_id"] = target_node_id
    metadata = dict(payload.get("metadata") or {})
    metadata["composition_bridge_role"] = bridge_role
    metadata["source_edge_id"] = str(raw_edge.get("edge_id") or "")
    payload["metadata"] = metadata
    return payload


def _lookup_graph(graph_lookup: Any | None, graph_id: str) -> Any | None:
    if graph_lookup is None:
        return None
    if hasattr(graph_lookup, "get_task_graph"):
        return graph_lookup.get_task_graph(graph_id)
    if callable(graph_lookup):
        return graph_lookup(graph_id)
    if isinstance(graph_lookup, dict):
        return graph_lookup.get(graph_id)
    return None


def _scope_node(
    node: dict[str, Any],
    *,
    scope_prefix: str,
    source_graph_id: str,
    composition_node_id: str,
    node_ids: set[str],
) -> dict[str, Any]:
    payload = dict(node)
    original_node_id = str(payload.get("node_id") or "")
    payload["node_id"] = _scoped_id(original_node_id, scope_prefix=scope_prefix)
    payload["task_ref"] = _scope_task_ref(str(payload.get("task_ref") or ""), scope_prefix=scope_prefix, source_graph_id=source_graph_id)
    payload["loop"] = _scope_node_loop_contract(dict(payload.get("loop") or {}), scope_prefix=scope_prefix, node_ids=node_ids)
    metadata = dict(payload.get("metadata") or {})
    metadata.update(
        {
            "source_graph_id": source_graph_id,
            "source_node_id": original_node_id,
            "composition_node_id": composition_node_id,
            "composition_scope_prefix": scope_prefix,
        }
    )
    payload["metadata"] = metadata
    return payload


def _scope_edge(edge: dict[str, Any], *, scope_prefix: str, source_graph_id: str, composition_node_id: str) -> dict[str, Any]:
    payload = dict(edge)
    original_edge_id = str(payload.get("edge_id") or "")
    payload["edge_id"] = _scoped_id(original_edge_id, scope_prefix=scope_prefix)
    payload["source_node_id"] = _scoped_id(str(payload.get("source_node_id") or ""), scope_prefix=scope_prefix)
    payload["target_node_id"] = _scoped_id(str(payload.get("target_node_id") or ""), scope_prefix=scope_prefix)
    metadata = dict(payload.get("metadata") or {})
    metadata.update(
        {
            "source_graph_id": source_graph_id,
            "source_edge_id": original_edge_id,
            "composition_node_id": composition_node_id,
            "composition_scope_prefix": scope_prefix,
        }
    )
    payload["metadata"] = metadata
    return payload


def _scope_edge_like_payload(payload: dict[str, Any], *, scope_prefix: str) -> dict[str, Any]:
    scoped = dict(payload)
    for key in ("edge_id", "source_node_id", "target_node_id", "node_id", "owner_node_id", "before_node_id", "after_node_id"):
        if str(scoped.get(key) or ""):
            scoped[key] = _scoped_id(str(scoped.get(key) or ""), scope_prefix=scope_prefix)
    return scoped


def _scope_loop_frame_payload(payload: dict[str, Any], *, scope_prefix: str, node_ids: set[str]) -> dict[str, Any]:
    scoped = _scope_generic_payload(payload, scope_prefix=scope_prefix, id_keys=("frame_id", "loop_frame_id", "scope_id"))
    for key in ("entry_node_id", "router_node_id", "continue_node_id", "exit_node_id"):
        if str(scoped.get(key) or ""):
            scoped[key] = _scope_graph_node_ref(str(scoped.get(key) or ""), scope_prefix=scope_prefix, node_ids=node_ids)
    return scoped


def _scope_node_loop_contract(loop: dict[str, Any], *, scope_prefix: str, node_ids: set[str]) -> dict[str, Any]:
    if not loop:
        return {}
    scoped = dict(loop)
    for key in ("frame_id", "loop_frame_id", "scope_id"):
        if str(scoped.get(key) or ""):
            scoped[key] = _scoped_id(str(scoped.get(key) or ""), scope_prefix=scope_prefix)
    route_policy = scoped.get("route_policy")
    if isinstance(route_policy, dict):
        route = dict(route_policy)
        for key in ("frame_id", "loop_frame_id", "scope_id"):
            if str(route.get(key) or ""):
                route[key] = _scoped_id(str(route.get(key) or ""), scope_prefix=scope_prefix)
        for key in ("entry_node_id", "router_node_id", "continue_node_id", "exit_node_id"):
            if str(route.get(key) or ""):
                route[key] = _scope_graph_node_ref(str(route.get(key) or ""), scope_prefix=scope_prefix, node_ids=node_ids)
        scoped["route_policy"] = route
    return scoped


def _scope_graph_node_ref(value: str, *, scope_prefix: str, node_ids: set[str]) -> str:
    text = str(value or "").strip()
    if not text or text.startswith(scope_prefix):
        return text
    if text.startswith("__") and text.endswith("__"):
        return text
    if text in node_ids:
        return _scoped_id(text, scope_prefix=scope_prefix)
    return _scoped_id(text, scope_prefix=scope_prefix)


def _scope_generic_payload(payload: dict[str, Any], *, scope_prefix: str, id_keys: tuple[str, ...]) -> dict[str, Any]:
    scoped = dict(payload)
    for key in id_keys:
        if str(scoped.get(key) or ""):
            scoped[key] = _scoped_id(str(scoped.get(key) or ""), scope_prefix=scope_prefix)
    for key in ("node_ids", "main_chain_node_ids", "blocking_node_ids", "readable_by", "write_owner_node_ids"):
        values = scoped.get(key)
        if isinstance(values, list):
            scoped[key] = [_scoped_id(str(item), scope_prefix=scope_prefix) for item in values if str(item)]
    return scoped


def _scoped_id(value: str, *, scope_prefix: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith(scope_prefix):
        return text
    return f"{scope_prefix}{text}"


def _scope_task_ref(value: str, *, scope_prefix: str, source_graph_id: str) -> str:
    text = str(value or "").strip()
    if not text:
        return f"task_graph.node.{source_graph_id}.{safe_id(scope_prefix)}"
    return f"{text}@{scope_prefix.rstrip(':')}"


def _derive_start_node_ids(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    executable_nodes = [node for node in nodes if not _is_resource_node_type(node_type=str(node.get("node_type") or ""), node_id=str(node.get("node_id") or ""))]
    node_ids = [str(node.get("node_id") or "") for node in executable_nodes if str(node.get("node_id") or "")]
    targets = {str(edge.get("target_node_id") or "") for edge in edges if _scheduler_role_for_edge(edge_type=str(edge.get("edge_type") or ""), metadata=dict(edge.get("metadata") or {})) == "dependency"}
    return [node_id for node_id in node_ids if node_id not in targets]


def _derive_terminal_node_ids(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    executable_nodes = [node for node in nodes if not _is_resource_node_type(node_type=str(node.get("node_type") or ""), node_id=str(node.get("node_id") or ""))]
    node_ids = [str(node.get("node_id") or "") for node in executable_nodes if str(node.get("node_id") or "")]
    sources = {str(edge.get("source_node_id") or "") for edge in edges if _scheduler_role_for_edge(edge_type=str(edge.get("edge_type") or ""), metadata=dict(edge.get("metadata") or {})) == "dependency"}
    return [node_id for node_id in node_ids if node_id not in sources]


def _edge_payload(edge: Any) -> dict[str, Any]:
    return edge.to_dict() if hasattr(edge, "to_dict") else dict(edge or {})


def _edge_touches_any(edge: dict[str, Any], node_ids: set[str]) -> bool:
    return str(edge.get("source_node_id") or edge.get("from") or edge.get("source") or "") in node_ids or str(edge.get("target_node_id") or edge.get("to") or edge.get("target") or "") in node_ids


def _executor_type_for_node(node: dict[str, Any]) -> str:
    node_type = str(node.get("node_type") or "").strip()
    node_id = str(node.get("node_id") or "").strip()
    if _is_resource_node_type(node_type=node_type, node_id=node_id):
        return "resource"
    metadata = dict(node.get("metadata") or {})
    executor_policy = dict(node.get("executor_policy") or metadata.get("executor_policy") or {})
    raw = str(executor_policy.get("default_executor") or executor_policy.get("executor") or "").strip()
    if raw:
        if raw in {"imported_graph", "graph_module", "graph_composition"}:
            raise ValueError("graph composition nodes must be expanded before executor selection")
        return raw
    if node_type in {"graph_module", "graph_composition"} or bool(metadata.get("graph_module") or metadata.get("graph_composition")):
        raise ValueError("graph composition nodes must be expanded before executor selection")
    if node_type in {"manual_gate", "human_gate"}:
        return "human"
    if node_type == "review_gate":
        return "review_gate"
    if node_type == "tool":
        return "tool"
    return "agent"


def _is_resource_node_type(*, node_type: str, node_id: str = "") -> bool:
    normalized = str(node_type or "").strip()
    normalized_id = str(node_id or "").strip()
    return (
        normalized in RESOURCE_NODE_TYPES
        or normalized.endswith("_repository")
        or normalized.endswith("_ledger")
        or (
            normalized_id.startswith(("memory.", "artifact.", "thread.", "progress.", "issue."))
            and normalized not in EXECUTABLE_MEMORY_NODE_TYPES
        )
    )


def _semantic_role_for_edge(*, edge_type: str, metadata: dict[str, Any]) -> str:
    return harness_edge_semantic_role(edge_type=edge_type, metadata=metadata)


def _scheduler_role_for_edge(*, edge_type: str, metadata: dict[str, Any]) -> str:
    return harness_edge_scheduler_role(edge_type=edge_type, metadata=metadata)


def _policy_dict(value: Any, *, string_key: str = "mode") -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        return {string_key: text} if text else {}
    return {}


def _prune_empty(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if item not in ("", None, [], {})
    }


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)]


def _contract_refs(*values: Any) -> list[str]:
    refs: list[str] = []
    for value in values:
        if isinstance(value, (list, tuple, set)):
            refs.extend(str(item).strip() for item in value if str(item).strip())
        elif str(value or "").strip():
            refs.append(str(value).strip())
    return list(dict.fromkeys(refs))
