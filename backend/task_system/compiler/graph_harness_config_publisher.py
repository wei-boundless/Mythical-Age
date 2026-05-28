from __future__ import annotations

from pathlib import Path
from typing import Any
import time

from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from harness.graph.models import GraphHarnessConfig, safe_id, stable_hash
from runtime.contracts.compiler import compile_coordination_contract_manifest
from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from task_system.registry.contract_registry import TaskContractRegistry
from task_system.registry.flow_registry import TaskFlowRegistry


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
MEMORY_EDGE_TYPES = {"memory_read", "memory_write", "memory_write_candidate", "memory_commit", "memory_handoff"}
ARTIFACT_EDGE_TYPES = {"artifact_read", "artifact_write", "artifact_context", "artifact_commit"}
REVISION_EDGE_TYPES = {"revision_request", "review_feedback", "repair_feedback", "conditional_feedback", "repair_route"}
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


def publish_graph_harness_config_for_graph(
    *,
    base_dir: Path,
    graph_id: str,
    publish_version: str = "published",
    _visited: set[str] | None = None,
) -> Any:
    registry = TaskFlowRegistry(base_dir)
    graph = registry.get_task_graph(graph_id)
    if graph is None:
        raise ValueError(f"TaskGraph not found: {graph_id}")
    visited = set(_visited or set())
    if graph.graph_id in visited:
        raise ValueError(f"cyclic graph module publication detected: {graph.graph_id}")
    visited.add(graph.graph_id)
    specific_tasks = tuple(registry.list_specific_task_records())
    protocol = registry.get_task_communication_protocol(
        str(graph.default_protocol_id or dict(graph.metadata or {}).get("protocol_id") or "")
    )
    runtime_spec = compile_task_graph_definition_runtime_spec(
        graph=graph,
        specific_tasks=specific_tasks,
        communication_protocol=protocol,
    )
    runtime_registry = AgentRuntimeRegistry(base_dir)
    agent_profiles = tuple(
        profile
        for profile in (
            runtime_registry.get_profile(str(node.agent_id or "").strip())
            for node in runtime_spec.nodes
            if str(node.agent_id or "").strip()
        )
        if profile is not None
    )
    manifest = compile_coordination_contract_manifest(
        contract_registry=TaskContractRegistry(base_dir),
        coordination_task=registry.derive_coordination_task_view_from_graph(graph),
        graph_spec=runtime_spec,
        specific_tasks=specific_tasks,
        communication_protocol=protocol,
        agent_profiles=agent_profiles,
    )
    config = build_graph_harness_config_from_runtime_spec(
        graph=graph,
        runtime_spec=runtime_spec,
        contract_manifest=manifest.to_dict(),
        publish_version=publish_version,
        graph_lookup=registry,
        visited_graph_ids=visited,
    )
    return registry.upsert_graph_harness_config(config, publish=True)


def build_graph_harness_config_from_runtime_spec(
    *,
    graph: Any,
    runtime_spec: Any,
    contract_manifest: dict[str, Any] | None = None,
    publish_version: str = "published",
    graph_lookup: Any | None = None,
    visited_graph_ids: set[str] | None = None,
) -> GraphHarnessConfig:
    runtime_payload = runtime_spec.to_dict()
    graph_metadata = dict(getattr(graph, "metadata", {}) or {})
    graph_runtime_policy = dict(getattr(graph, "runtime_policy", {}) or {})
    graph_context_policy = dict(getattr(graph, "context_policy", {}) or {})
    module_plans = _graph_module_plans(runtime_payload)
    raw_module_node_ids = _raw_composition_node_ids(graph)
    module_node_ids = {
        *raw_module_node_ids,
        *{str(item.get("runtime_node_id") or "").strip() for item in module_plans if str(item.get("runtime_node_id") or "").strip()},
    }
    missing_plan_node_ids = sorted(raw_module_node_ids - {str(item.get("runtime_node_id") or "").strip() for item in module_plans})
    if missing_plan_node_ids:
        raise ValueError(f"Graph composition nodes require imported graph binding before publish: {', '.join(missing_plan_node_ids)}")
    if module_plans and graph_lookup is None:
        raise ValueError("GraphHarnessConfig publication requires graph_lookup to expand graph module nodes before runtime")
    base_projection = _base_graph_projection(graph=graph, runtime_payload=runtime_payload, excluded_node_ids=module_node_ids)
    nodes = base_projection["nodes"]
    edges = base_projection["edges"]
    composition = _expand_composition_sources(
        graph=graph,
        runtime_payload=runtime_payload,
        module_plans=module_plans,
        nodes=nodes,
        edges=edges,
        graph_lookup=graph_lookup,
        publish_version=publish_version,
        visited_graph_ids=set(visited_graph_ids or {str(getattr(graph, "graph_id", "") or "")}),
    )
    nodes = composition["nodes"]
    edges = composition["edges"]
    split_plans = [
        dict(item)
        for item in list(dict(getattr(runtime_spec, "diagnostics", {}) or {}).get("split_plans") or [])
        if isinstance(item, dict)
    ]
    control = {
        "start_node_ids": composition["start_node_ids"],
        "terminal_node_ids": composition["terminal_node_ids"],
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
        "graph_loop_policy": _policy_dict(graph_metadata.get("graph_loop_policy")),
        "batch_policy": {
            "enabled": bool(split_plans),
            "split_plans": split_plans,
        },
        "temporal_edges": [dict(item) for item in list(runtime_payload.get("temporal_edges") or []) if isinstance(item, dict)],
        "revision_edges": [dict(item) for item in list(runtime_payload.get("revision_edges") or []) if isinstance(item, dict)],
        "communication_protocol_id": str(getattr(graph, "default_protocol_id", "") or graph_metadata.get("protocol_id") or ""),
        "handoff_policy": str((runtime_payload.get("communication_modes") or ["handoff"])[0] or graph_metadata.get("handoff_policy") or "handoff"),
        "merge_policy": str(graph_runtime_policy.get("merge_policy") or graph_metadata.get("output_merge_policy") or ""),
    }
    contracts = {
        "manifest": dict(contract_manifest or {}),
        "node_contracts": list(dict(contract_manifest or {}).get("node_contracts") or []),
        "edge_contracts": list(dict(contract_manifest or {}).get("edge_handoff_contracts") or []),
        "graph_module_handoff_contracts": list(dict(contract_manifest or {}).get("graph_module_handoff_contracts") or []),
        "runtime_contracts": list(dict(contract_manifest or {}).get("runtime_contracts") or []),
        "acceptance_contracts": list(dict(contract_manifest or {}).get("acceptance_contracts") or []),
    }
    provisional = {
        "graph_id": graph.graph_id,
        "graph_title": graph.title,
        "publish_version": publish_version,
        "task_environment_id": str(graph_runtime_policy.get("task_environment_id") or graph_context_policy.get("task_environment_id") or graph.domain_id or ""),
        "root_task_ref": str(graph.graph_contract_id or graph.graph_id),
        "control": control,
        "nodes": [dict(item) for item in nodes],
        "edges": [dict(item) for item in edges],
        "loop_frames": [
            *[dict(item) for item in list(runtime_payload.get("loop_frames") or []) if isinstance(item, dict)],
            *composition["loop_frames"],
        ],
        "resources": {
            "resource_nodes": [
                *[dict(item) for item in list(runtime_payload.get("resource_nodes") or []) if isinstance(item, dict)],
                *composition["resource_nodes"],
            ],
        },
        "memory": {
            "working_memory_policy_profile_id": graph.working_memory_policy_profile_id,
            "working_memory_policy": dict(graph.working_memory_policy or {}),
            "memory_matrix": dict(runtime_payload.get("memory_matrix") or {}),
            "read_rules": [
                *[dict(item) for item in list(runtime_payload.get("memory_edges") or []) if isinstance(item, dict)],
                *composition["memory_edges"],
            ],
        },
        "artifacts": {
            "context_edges": [
                *[dict(item) for item in list(runtime_payload.get("artifact_context_edges") or []) if isinstance(item, dict)],
                *composition["artifact_context_edges"],
            ],
        },
        "permissions": dict(graph_runtime_policy.get("permissions") or graph_metadata.get("permissions") or {}),
        "tools": dict(graph_runtime_policy.get("tools") or graph_metadata.get("tools") or {}),
        "agents": {
            "coordinator_agent_id": str(runtime_spec.coordinator_agent_id or "agent:0"),
            "agent_group_id": str(runtime_spec.agent_group_id or ""),
        },
        "contracts": contracts,
        "composition_sources": composition["composition_sources"],
        "diagnostics": {
            "source": "task_system.graph_harness_config_publisher",
            "compiler_diagnostics": dict(getattr(runtime_spec, "diagnostics", {}) or {}),
            "runtime_spec_summary": {
                "node_count": len(runtime_payload.get("nodes") or []),
                "edge_count": len(runtime_payload.get("edges") or []),
                "full_graph_node_count": len(nodes),
                "full_graph_edge_count": len(edges),
                "composition_source_count": len(composition["composition_sources"]),
                "issue_count": len(runtime_payload.get("issues") or []),
            },
            "issues": list(runtime_payload.get("issues") or []),
        },
        "authority_map": {
            "compile": "task_system.graph_harness_config_publisher",
            "assemble": "harness.graph.runtime",
            "decide": "harness.graph.loop",
            "execute_agent": "harness.agent_loop",
        },
        "source_refs": {
            "graph_id": graph.graph_id,
            "publish_state": graph.publish_state,
            "graph_contract_id": graph.graph_contract_id,
            "default_protocol_id": graph.default_protocol_id,
            "composition_sources": composition["composition_sources"],
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
    config_id = f"ghcfg:{safe_id(str(graph.graph_id or 'graph'))}:{content_hash[:16]}"
    return GraphHarnessConfig(
        config_id=config_id,
        content_hash=content_hash,
        published_at=time.time(),
        status="published",
        **provisional,
    )


def _node_config(node: dict[str, Any], *, graph_id: str) -> dict[str, Any]:
    metadata = dict(node.get("metadata") or {})
    contract_bindings = dict(metadata.get("contract_bindings") or {})
    prompt_contract = dict(metadata.get("prompt_contract") or {})
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
            "node_contract_id": str(metadata.get("node_contract_id") or ""),
            "input_contract_id": str(metadata.get("input_contract_id") or ""),
            "output_contract_id": str(metadata.get("output_contract_id") or ""),
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
            "human_gate_policy": dict(metadata.get("human_gate_policy") or {}),
        },
        "retry": dict(metadata.get("quality_retry_policy") or {}),
        "permissions": dict(metadata.get("permissions") or {}),
        "tools": dict(metadata.get("tools") or {}),
        "metadata": metadata,
    }


def _graph_node_config(node: Any, *, graph_id: str, runtime_node: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = node.to_dict() if hasattr(node, "to_dict") else dict(node or {})
    base = _node_config(raw, graph_id=graph_id)
    runtime = dict(runtime_node or {})
    if not runtime:
        return base
    merged = {
        **base,
        "agent_id": base.get("agent_id") or runtime.get("agent_id") or "",
        "agent_profile_id": base.get("agent_profile_id") or runtime.get("agent_profile_id") or "",
        "metadata": {
            **dict(runtime.get("metadata") or {}),
            **dict(base.get("metadata") or {}),
        },
    }
    for key in ("executor", "execution", "contracts", "prompt", "context", "memory", "artifacts", "stream", "gates", "retry", "permissions", "tools"):
        current = dict(base.get(key) or {})
        derived = dict(runtime.get(key) or {})
        merged[key] = {**derived, **current}
    return merged


def _edge_config(edge: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(edge.get("metadata") or {})
    edge_type = str(edge.get("mode") or edge.get("edge_type") or "handoff")
    return {
        "edge_id": str(edge.get("edge_id") or ""),
        "source_node_id": str(edge.get("source_node_id") or ""),
        "target_node_id": str(edge.get("target_node_id") or ""),
        "edge_type": edge_type,
        "semantic_role": _semantic_role_for_edge(edge_type=edge_type, metadata=metadata),
        "scheduler_role": _scheduler_role_for_edge(edge_type=edge_type, metadata=metadata),
        "wait_policy": str(edge.get("wait_policy") or ""),
        "ack_policy": str(edge.get("ack_policy") or "explicit_ack"),
        "ack_required": bool(edge.get("ack_required", True)),
        "failure_propagation_policy": str(edge.get("failure_propagation_policy") or "fail_downstream"),
        "result_delivery_policy": str(edge.get("result_delivery_policy") or "contract_payload_and_refs"),
        "payload_contract_id": str(edge.get("payload_contract_id") or ""),
        "context_filter_policy": dict(edge.get("context_filter_policy") or {}),
        "artifact_ref_policy": dict(edge.get("artifact_ref_policy") or {}),
        "working_memory_handoff_policy": dict(edge.get("working_memory_handoff_policy") or {}),
        "temporal_policy": dict(metadata.get("temporal_policy") or {}),
        "revision_policy": dict(metadata.get("revision_policy") or {}),
        "metadata": metadata,
    }


def _graph_edge_config(edge: Any, *, runtime_edge: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = edge.to_dict() if hasattr(edge, "to_dict") else dict(edge or {})
    base = _edge_config(raw)
    runtime = dict(runtime_edge or {})
    if not runtime:
        return base
    return {
        **base,
        "metadata": {
            **dict(runtime.get("metadata") or {}),
            **dict(base.get("metadata") or {}),
        },
    }


def _base_graph_projection(
    *,
    graph: Any,
    runtime_payload: dict[str, Any],
    excluded_node_ids: set[str],
) -> dict[str, tuple[dict[str, Any], ...]]:
    runtime_nodes_by_id = {
        str(node.get("node_id") or ""): _node_config(node, graph_id=str(graph.graph_id or ""))
        for node in runtime_payload.get("nodes") or []
        if str(node.get("node_id") or "") and str(node.get("node_id") or "") not in excluded_node_ids
    }
    graph_node_ids = {
        str(getattr(node, "node_id", "") or "")
        for node in tuple(getattr(graph, "nodes", ()) or ())
        if str(getattr(node, "node_id", "") or "") not in excluded_node_ids
    }
    nodes = tuple(
        _graph_node_config(
            node,
            graph_id=str(graph.graph_id or ""),
            runtime_node=runtime_nodes_by_id.get(str(getattr(node, "node_id", "") or "")),
        )
        for node in tuple(getattr(graph, "nodes", ()) or ())
        if str(getattr(node, "node_id", "") or "") not in excluded_node_ids
    )
    nodes = tuple(
        [
            *nodes,
            *[
                dict(node)
                for node_id, node in runtime_nodes_by_id.items()
                if node_id and node_id not in graph_node_ids
            ],
        ]
    )
    excluded_edge_node_ids = set(excluded_node_ids)
    runtime_edges_by_id = {
        str(edge.get("edge_id") or ""): _edge_config(edge)
        for edge in runtime_payload.get("edges") or []
        if str(edge.get("edge_id") or "") and not _edge_touches_any(edge, excluded_edge_node_ids)
    }
    graph_edge_ids = {
        str(getattr(edge, "edge_id", "") or "")
        for edge in tuple(getattr(graph, "edges", ()) or ())
        if str(getattr(edge, "edge_id", "") or "") and not _edge_touches_any(_edge_payload(edge), excluded_edge_node_ids)
    }
    edges = tuple(
        _graph_edge_config(edge, runtime_edge=runtime_edges_by_id.get(str(getattr(edge, "edge_id", "") or "")))
        for edge in tuple(getattr(graph, "edges", ()) or ())
        if not _edge_touches_any(_edge_payload(edge), excluded_edge_node_ids)
    )
    edges = tuple(
        [
            *edges,
            *[
                dict(edge)
                for edge_id, edge in runtime_edges_by_id.items()
                if edge_id and edge_id not in graph_edge_ids
            ],
        ]
    )
    return {"nodes": nodes, "edges": edges}


def _expand_composition_sources(
    *,
    graph: Any,
    runtime_payload: dict[str, Any],
    module_plans: tuple[dict[str, Any], ...],
    nodes: tuple[dict[str, Any], ...],
    edges: tuple[dict[str, Any], ...],
    graph_lookup: Any | None,
    publish_version: str,
    visited_graph_ids: set[str],
) -> dict[str, Any]:
    if not module_plans:
        return {
            "nodes": nodes,
            "edges": edges,
            "start_node_ids": list(runtime_payload.get("start_node_ids") or []),
            "terminal_node_ids": list(runtime_payload.get("terminal_node_ids") or []),
            "loop_frames": [],
            "resource_nodes": [],
            "memory_edges": [],
            "artifact_context_edges": [],
            "composition_sources": [],
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
    expanded_by_runtime_node_id: dict[str, dict[str, Any]] = {}
    start_ids = [str(item) for item in list(runtime_payload.get("start_node_ids") or []) if str(item)]
    terminal_ids = [str(item) for item in list(runtime_payload.get("terminal_node_ids") or []) if str(item)]
    module_runtime_ids = {str(plan.get("runtime_node_id") or "").strip() for plan in module_plans if str(plan.get("runtime_node_id") or "").strip()}
    start_ids = [item for item in start_ids if item not in module_runtime_ids]
    terminal_ids = [item for item in terminal_ids if item not in module_runtime_ids]

    for plan in module_plans:
        expanded = _expand_module_plan(
            graph=graph,
            plan=plan,
            graph_lookup=graph_lookup,
            publish_version=publish_version,
            visited_graph_ids=visited_graph_ids,
        )
        runtime_node_id = str(plan.get("runtime_node_id") or "").strip()
        expanded_by_runtime_node_id[runtime_node_id] = expanded
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
        expanded_start = list(expanded["start_node_ids"])
        expanded_terminal = list(expanded["terminal_node_ids"])
        if runtime_node_id in [str(item) for item in list(runtime_payload.get("start_node_ids") or [])]:
            start_ids.extend(expanded_start)
        if runtime_node_id in [str(item) for item in list(runtime_payload.get("terminal_node_ids") or [])]:
            terminal_ids.extend(expanded_terminal)
    for edge in _composition_bridge_edges(graph=graph, expanded_by_runtime_node_id=expanded_by_runtime_node_id):
        edge_id = str(edge.get("edge_id") or "")
        if edge_id and edge_id not in edge_ids:
            all_edges.append(edge)
            edge_ids.add(edge_id)
    if not start_ids:
        start_ids = _derive_start_node_ids(all_nodes, all_edges)
    if not terminal_ids:
        terminal_ids = _derive_terminal_node_ids(all_nodes, all_edges)
    return {
        "nodes": tuple(all_nodes),
        "edges": tuple(all_edges),
        "start_node_ids": list(dict.fromkeys(item for item in start_ids if item)),
        "terminal_node_ids": list(dict.fromkeys(item for item in terminal_ids if item)),
        "loop_frames": loop_frames,
        "resource_nodes": resource_nodes,
        "memory_edges": memory_edges,
        "artifact_context_edges": artifact_context_edges,
        "composition_sources": composition_sources,
    }


def _expand_module_plan(
    *,
    graph: Any,
    plan: dict[str, Any],
    graph_lookup: Any | None,
    publish_version: str,
    visited_graph_ids: set[str],
) -> dict[str, Any]:
    linked_graph_id = str(plan.get("linked_graph_id") or "").strip()
    runtime_node_id = str(plan.get("runtime_node_id") or "").strip()
    if not runtime_node_id:
        raise ValueError("Graph composition source requires runtime_node_id")
    if not linked_graph_id:
        raise ValueError(f"Graph composition source requires linked_graph_id: {runtime_node_id}")
    current_graph_id = str(getattr(graph, "graph_id", "") or "").strip()
    if linked_graph_id in visited_graph_ids or linked_graph_id == current_graph_id:
        raise ValueError(f"cyclic graph composition detected: {current_graph_id} -> {linked_graph_id}")
    imported_graph = _lookup_graph(graph_lookup, linked_graph_id)
    if imported_graph is None:
        raise ValueError(f"Graph composition source not found: {linked_graph_id}")
    protocol = None
    if hasattr(graph_lookup, "get_task_communication_protocol"):
        protocol = graph_lookup.get_task_communication_protocol(str(getattr(imported_graph, "default_protocol_id", "") or dict(getattr(imported_graph, "metadata", {}) or {}).get("protocol_id") or ""))
    specific_tasks = tuple(graph_lookup.list_specific_task_records()) if hasattr(graph_lookup, "list_specific_task_records") else ()
    imported_runtime_spec = compile_task_graph_definition_runtime_spec(
        graph=imported_graph,
        specific_tasks=specific_tasks,
        communication_protocol=protocol,
    )
    imported_payload = imported_runtime_spec.to_dict()
    nested_plans = _graph_module_plans(imported_payload)
    nested_module_ids = {
        *_raw_composition_node_ids(imported_graph),
        *{str(item.get("runtime_node_id") or "").strip() for item in nested_plans if str(item.get("runtime_node_id") or "").strip()},
    }
    missing_nested_plan_ids = sorted(_raw_composition_node_ids(imported_graph) - {str(item.get("runtime_node_id") or "").strip() for item in nested_plans})
    if missing_nested_plan_ids:
        raise ValueError(f"Graph composition nodes require imported graph binding before publish: {', '.join(missing_nested_plan_ids)}")
    base_projection = _base_graph_projection(
        graph=imported_graph,
        runtime_payload=imported_payload,
        excluded_node_ids=nested_module_ids,
    )
    nested = _expand_composition_sources(
        graph=imported_graph,
        runtime_payload=imported_payload,
        module_plans=nested_plans,
        nodes=base_projection["nodes"],
        edges=base_projection["edges"],
        graph_lookup=graph_lookup,
        publish_version=publish_version,
        visited_graph_ids={*visited_graph_ids, current_graph_id},
    )
    scope_prefix = _composition_scope_prefix(runtime_node_id)
    scoped_nodes = [_scope_node(node, scope_prefix=scope_prefix, source_graph_id=linked_graph_id, runtime_node_id=runtime_node_id) for node in nested["nodes"]]
    scoped_edges = [_scope_edge(edge, scope_prefix=scope_prefix, source_graph_id=linked_graph_id, runtime_node_id=runtime_node_id) for edge in nested["edges"]]
    scoped_loop_frames = [_scope_generic_payload(item, scope_prefix=scope_prefix, id_keys=("frame_id", "loop_frame_id", "scope_id")) for item in nested["loop_frames"]]
    scoped_resources = [_scope_generic_payload(item, scope_prefix=scope_prefix, id_keys=("node_id", "resource_id", "repository_id")) for item in nested["resource_nodes"]]
    scoped_memory_edges = [_scope_edge_like_payload(item, scope_prefix=scope_prefix) for item in nested["memory_edges"]]
    scoped_artifact_edges = [_scope_edge_like_payload(item, scope_prefix=scope_prefix) for item in nested["artifact_context_edges"]]
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
            "plan_id": str(plan.get("plan_id") or ""),
            "runtime_node_id": runtime_node_id,
            "unit_id": str(plan.get("unit_id") or ""),
            "linked_graph_id": linked_graph_id,
            "scope_prefix": scope_prefix,
            "publish_version": publish_version,
            "entry_node_ids": scoped_start_ids,
            "terminal_node_ids": scoped_terminal_ids,
            "node_count": len(scoped_nodes),
            "edge_count": len(scoped_edges),
            "metadata": {
                "source_authority": "task_system.graph_harness_config_publisher",
                "plan_metadata": dict(plan.get("metadata") or {}),
            },
        },
    }


def _composition_bridge_edges(*, graph: Any, expanded_by_runtime_node_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    bridges: list[dict[str, Any]] = []
    for edge in tuple(getattr(graph, "edges", ()) or ()):
        payload = _edge_payload(edge)
        source = str(payload.get("source_node_id") or "")
        target = str(payload.get("target_node_id") or "")
        source_expansion = expanded_by_runtime_node_id.get(source)
        target_expansion = expanded_by_runtime_node_id.get(target)
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
        role = "composition_to_composition" if source_expansion is not None and target_expansion is not None else (
            "out_of_composition" if source_expansion is not None else "into_composition"
        )
        for source_id in source_ids:
            for target_id in target_ids:
                bridges.append(_bridge_edge(payload, source_node_id=source_id, target_node_id=target_id, bridge_role=role))
    return bridges


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


def _graph_module_plans(runtime_payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    plans: list[dict[str, Any]] = []
    for item in list(runtime_payload.get("graph_module_runtime_plans") or runtime_payload.get("graph_modules") or []):
        if not isinstance(item, dict):
            continue
        plan = dict(item)
        runtime_node_id = str(plan.get("runtime_node_id") or dict(plan.get("metadata") or {}).get("source_node_id") or "").strip()
        if runtime_node_id:
            plan["runtime_node_id"] = runtime_node_id
        plans.append(plan)
    return tuple(plans)


def _raw_composition_node_ids(graph: Any) -> set[str]:
    ids: set[str] = set()
    for node in tuple(getattr(graph, "nodes", ()) or ()):
        node_type = str(getattr(node, "node_type", "") or "").strip()
        metadata = dict(getattr(node, "metadata", {}) or {})
        executor_policy = dict(getattr(node, "executor_policy", {}) or {})
        if node_type == "graph_module" or bool(metadata.get("graph_module")) or str(executor_policy.get("default_executor") or "") in {"graph_module", "imported_graph"}:
            node_id = str(getattr(node, "node_id", "") or "").strip()
            if node_id:
                ids.add(node_id)
    return ids


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


def _scope_node(node: dict[str, Any], *, scope_prefix: str, source_graph_id: str, runtime_node_id: str) -> dict[str, Any]:
    payload = dict(node)
    original_node_id = str(payload.get("node_id") or "")
    payload["node_id"] = _scoped_id(original_node_id, scope_prefix=scope_prefix)
    payload["task_ref"] = _scope_task_ref(str(payload.get("task_ref") or ""), scope_prefix=scope_prefix, source_graph_id=source_graph_id)
    metadata = dict(payload.get("metadata") or {})
    metadata.update(
        {
            "source_graph_id": source_graph_id,
            "source_node_id": original_node_id,
            "composition_runtime_node_id": runtime_node_id,
            "composition_scope_prefix": scope_prefix,
        }
    )
    payload["metadata"] = metadata
    return payload


def _scope_edge(edge: dict[str, Any], *, scope_prefix: str, source_graph_id: str, runtime_node_id: str) -> dict[str, Any]:
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
            "composition_runtime_node_id": runtime_node_id,
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


def _composition_scope_prefix(runtime_node_id: str) -> str:
    return f"{runtime_node_id}::"


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
    node_ids = [str(node.get("node_id") or "") for node in nodes if str(node.get("node_id") or "")]
    targets = {str(edge.get("target_node_id") or "") for edge in edges}
    return [node_id for node_id in node_ids if node_id not in targets]


def _derive_terminal_node_ids(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    node_ids = [str(node.get("node_id") or "") for node in nodes if str(node.get("node_id") or "")]
    sources = {str(edge.get("source_node_id") or "") for edge in edges}
    return [node_id for node_id in node_ids if node_id not in sources]


def _edge_payload(edge: Any) -> dict[str, Any]:
    return edge.to_dict() if hasattr(edge, "to_dict") else dict(edge or {})


def _edge_touches_any(edge: dict[str, Any], node_ids: set[str]) -> bool:
    return str(edge.get("source_node_id") or "") in node_ids or str(edge.get("target_node_id") or "") in node_ids


def _executor_type_for_node(node: dict[str, Any]) -> str:
    node_type = str(node.get("node_type") or "").strip()
    node_id = str(node.get("node_id") or "").strip()
    if _is_resource_node_type(node_type=node_type, node_id=node_id):
        return "resource"
    metadata = dict(node.get("metadata") or {})
    executor_policy = dict(node.get("executor_policy") or metadata.get("executor_policy") or {})
    raw = str(executor_policy.get("default_executor") or executor_policy.get("executor") or "").strip()
    if raw:
        if raw in {"imported_graph", "graph_module"}:
            raise ValueError("graph composition nodes must be expanded before executor selection")
        return raw
    if node_type == "graph_module" or bool(metadata.get("graph_module")):
        raise ValueError("graph composition nodes must be expanded before executor selection")
    if node_type in {"manual_gate", "human_gate"}:
        return "human"
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
    explicit = str(metadata.get("semantic_role") or "").strip()
    if explicit:
        return explicit
    normalized = str(edge_type or "").strip()
    if normalized in MEMORY_EDGE_TYPES:
        return "memory"
    if normalized in ARTIFACT_EDGE_TYPES:
        return "artifact"
    if normalized in REVISION_EDGE_TYPES:
        return "revision"
    if normalized in DEPENDENCY_EDGE_TYPES:
        return "control"
    return "extension"


def _scheduler_role_for_edge(*, edge_type: str, metadata: dict[str, Any]) -> str:
    explicit = str(metadata.get("scheduler_role") or "").strip()
    if explicit:
        return explicit
    normalized = str(edge_type or "").strip()
    if normalized in DEPENDENCY_EDGE_TYPES:
        return "dependency"
    if normalized in REVISION_EDGE_TYPES:
        return "conditional_dependency"
    if normalized == "memory_read" or normalized in {"artifact_read", "artifact_context"}:
        return "context"
    if normalized in {"memory_commit", "memory_write", "memory_write_candidate", "artifact_write", "artifact_commit"}:
        return "commit"
    if normalized == "memory_handoff":
        return "context"
    return "none"


def _policy_dict(value: Any, *, string_key: str = "mode") -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        return {string_key: text} if text else {}
    return {}
