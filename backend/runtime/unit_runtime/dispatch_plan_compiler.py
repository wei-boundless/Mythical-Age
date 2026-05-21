from __future__ import annotations

import time
from typing import Any

from task_system.compiler.coordination_graph_models import TaskGraphRuntimeEdge, TaskGraphRuntimeNode, TaskGraphRuntimeSpec
from task_system.graphs.task_graph_models import TaskGraphDefinition, task_graph_from_dict

from ..shared.models import (
    AgentDispatchPlan,
    AgentDispatchRecord,
    CoordinationBarrierState,
    QueuedAgentNotification,
)


def _compile_agent_dispatch_plan_from_graph_payload(
    *,
    task_run_id: str,
    coordination_run_id: str,
    graph_payload: dict[str, Any],
    topology_template_payload: dict[str, Any],
) -> AgentDispatchPlan:
    nodes = _dispatch_nodes_from_payload(graph_payload, topology_template_payload)
    edges = _dispatch_edges_from_payload(graph_payload, topology_template_payload)
    upstream: dict[str, list[str]] = {}
    downstream: dict[str, list[str]] = {}
    for edge in edges:
        source = str(edge.get("source_node_id") or edge.get("from") or edge.get("source") or "").strip()
        target = str(edge.get("target_node_id") or edge.get("to") or edge.get("target") or "").strip()
        if source and target:
            downstream.setdefault(source, []).append(target)
            upstream.setdefault(target, []).append(source)

    records: list[AgentDispatchRecord] = []
    barriers: list[CoordinationBarrierState] = []
    notifications: list[QueuedAgentNotification] = []
    dispatch_groups: dict[str, list[str]] = {}
    ready_node_ids: list[str] = []
    blocked_node_ids: list[str] = []
    background_node_ids: list[str] = []
    now = time.time()
    for index, node in enumerate(nodes):
        node_id = str(node.get("node_id") or node.get("id") or f"node_{index + 1}").strip()
        if not node_id:
            continue
        mode = str(node.get("execution_mode") or "sync").strip() or "sync"
        dispatch_group = str(node.get("dispatch_group") or "").strip()
        wait_policy = str(node.get("wait_policy") or "wait_all_upstream_completed").strip() or "wait_all_upstream_completed"
        join_policy = str(node.get("join_policy") or "all_success").strip() or "all_success"
        node_metadata = dict(node.get("metadata") or {}) if isinstance(node.get("metadata"), dict) else {}
        background_policy = dict(node.get("background_policy") or node_metadata.get("background_policy") or {})
        notification_policy = dict(node.get("notification_policy") or node_metadata.get("notification_policy") or {})
        lifecycle_policy = dict(node.get("resource_lifecycle_policy") or node_metadata.get("resource_lifecycle_policy") or {})
        node_upstream = tuple(upstream.get(node_id, ()))
        node_downstream = tuple(downstream.get(node_id, ()))
        status = "ready" if not node_upstream or wait_policy == "fire_and_continue" else "blocked"
        if mode == "manual_gate":
            status = "waiting"
        if status == "ready":
            ready_node_ids.append(node_id)
        else:
            blocked_node_ids.append(node_id)
        if mode == "background":
            background_node_ids.append(node_id)
        if dispatch_group:
            dispatch_groups.setdefault(dispatch_group, []).append(node_id)
        record = AgentDispatchRecord(
            dispatch_id=f"dispatch:{coordination_run_id}:{node_id}",
            task_run_id=task_run_id,
            coordination_run_id=coordination_run_id,
            node_id=node_id,
            node_run_id=f"noderun:{coordination_run_id}:{node_id}",
            agent_id=str(node.get("agent_id") or "").strip(),
            execution_mode=mode,
            dispatch_group=dispatch_group,
            wait_policy=wait_policy,
            join_policy=join_policy,
            status=status,
            blocks_downstream=not (mode == "background" and background_policy.get("blocks_downstream") is False),
            background_policy=background_policy,
            notification_policy=notification_policy,
            resource_lifecycle_policy=lifecycle_policy,
            upstream_node_ids=node_upstream,
            downstream_node_ids=node_downstream,
            created_at=now,
            diagnostics={
                "node_type": str(node.get("node_type") or ""),
                "input_contract_id": str(node.get("input_contract_id") or node_metadata.get("input_contract_id") or ""),
                "output_contract_id": str(node.get("output_contract_id") or node.get("node_contract_id") or node_metadata.get("output_contract_id") or node_metadata.get("node_contract_id") or ""),
                "projection_id": str(node.get("projection_id") or node_metadata.get("projection_id") or ""),
            },
        )
        records.append(record)
        if mode == "barrier":
            barriers.append(
                CoordinationBarrierState(
                    barrier_id=f"barrier:{coordination_run_id}:{node_id}",
                    task_run_id=task_run_id,
                    coordination_run_id=coordination_run_id,
                    node_id=node_id,
                    join_policy=join_policy,
                    waiting_for_node_ids=node_upstream,
                    status="waiting",
                )
            )
        if mode == "background":
            notifications.append(
                QueuedAgentNotification(
                    notification_id=f"notify:{coordination_run_id}:{node_id}:completion",
                    task_run_id=task_run_id,
                    coordination_run_id=coordination_run_id,
                    node_id=node_id,
                    event="background_completion_pending",
                    priority=str(notification_policy.get("priority") or "later"),
                    include_result=str(notification_policy.get("include_result") or "summary_and_refs"),
                    status="queued",
                    created_at=now,
                    diagnostics={"state_order": "status_before_notification"},
                )
            )

    return AgentDispatchPlan(
        dispatch_plan_id=f"dispatchplan:{coordination_run_id}",
        task_run_id=task_run_id,
        coordination_run_id=coordination_run_id,
        records=tuple(records),
        barrier_states=tuple(barriers),
        queued_notifications=tuple(notifications),
        ready_node_ids=tuple(ready_node_ids),
        blocked_node_ids=tuple(blocked_node_ids),
        background_node_ids=tuple(background_node_ids),
        dispatch_groups=dispatch_groups,
        diagnostics={
            "node_count": len(records),
            "edge_count": len(edges),
            "ready_count": len(ready_node_ids),
            "blocked_count": len(blocked_node_ids),
            "background_count": len(background_node_ids),
            "barrier_count": len(barriers),
            "notification_count": len(notifications),
            "scheduler_phase": "compiled_plan_only",
        },
    )


def _dispatch_graph_payload_from_task_graph_runtime_spec(
    *,
    graph: TaskGraphDefinition,
    runtime_spec: TaskGraphRuntimeSpec,
) -> dict[str, Any]:
    runtime_nodes = [node.to_dict() for node in runtime_spec.nodes]
    runtime_edges = [
        {
            **edge.to_dict(),
            "edge_type": edge.mode,
        }
        for edge in runtime_spec.edges
    ]
    return {
        "authority": "orchestration.task_graph_dispatch_payload",
        "graph_id": graph.graph_id,
        "task_graph_id": graph.graph_id,
        "title": graph.title,
        "domain_id": graph.domain_id,
        "task_family": graph.task_family,
        "graph_kind": graph.graph_kind,
        "coordinator_agent_id": runtime_spec.coordinator_agent_id,
        "agent_group_id": runtime_spec.agent_group_id,
        "topology_template_id": str(graph.metadata.get("topology_template_id") or ""),
        "handoff_policy": str((runtime_spec.communication_modes or ("handoff",))[0]),
        "conflict_resolution_policy": str(dict(graph.runtime_policy or {}).get("failure_policy") or ""),
        "output_merge_policy": str(dict(graph.runtime_policy or {}).get("merge_policy") or ""),
        "shared_context_policy": str(dict(graph.context_policy or {}).get("shared_context_policy") or ""),
        "memory_sharing_policy": str(dict(graph.working_memory_policy or {}).get("memory_sharing_policy") or ""),
        "graph_nodes": runtime_nodes,
        "graph_edges": runtime_edges,
        "metadata": {
            **dict(graph.metadata or {}),
            "runtime_spec_source": str(dict(runtime_spec.diagnostics or {}).get("source") or ""),
            "start_node_ids": list(runtime_spec.start_node_ids),
            "terminal_node_ids": list(runtime_spec.terminal_node_ids),
            "communication_modes": list(runtime_spec.communication_modes),
        },
    }


def _normalize_runtime_graph_payload(
    *,
    raw_graph_payload: dict[str, Any],
    task_graph_payload: dict[str, Any],
    runtime_spec_payload: dict[str, Any],
) -> dict[str, Any]:
    graph_payload = dict(raw_graph_payload or {})
    task_graph = dict(task_graph_payload or {})
    if not graph_payload and not task_graph:
        return {}
    if graph_payload.get("authority") == "orchestration.task_graph_dispatch_payload":
        return graph_payload
    metadata = dict(task_graph.get("metadata") or graph_payload.get("metadata") or {})
    runtime_policy = dict(task_graph.get("runtime_policy") or graph_payload.get("runtime_policy") or {})
    context_policy = dict(task_graph.get("context_policy") or graph_payload.get("context_policy") or {})
    working_memory_policy = dict(task_graph.get("working_memory_policy") or graph_payload.get("working_memory_policy") or {})
    runtime_spec = _runtime_spec_from_payload(runtime_spec_payload) if runtime_spec_payload else None
    if runtime_spec is not None:
        graph_definition = task_graph_from_dict(task_graph) if task_graph else task_graph_from_dict(graph_payload)
        return _dispatch_graph_payload_from_task_graph_runtime_spec(
            graph=graph_definition,
            runtime_spec=runtime_spec,
        )
    return {
        **graph_payload,
        "authority": "orchestration.task_graph_dispatch_payload",
        "graph_id": str(task_graph.get("graph_id") or graph_payload.get("graph_id") or graph_payload.get("task_graph_id") or ""),
        "task_graph_id": str(task_graph.get("graph_id") or graph_payload.get("task_graph_id") or graph_payload.get("graph_id") or ""),
        "title": str(task_graph.get("title") or graph_payload.get("title") or ""),
        "domain_id": str(task_graph.get("domain_id") or graph_payload.get("domain_id") or ""),
        "task_family": str(task_graph.get("task_family") or graph_payload.get("task_family") or ""),
        "graph_kind": str(task_graph.get("graph_kind") or graph_payload.get("graph_kind") or "coordination"),
        "coordinator_agent_id": str(runtime_policy.get("coordinator_agent_id") or graph_payload.get("coordinator_agent_id") or "agent:0"),
        "agent_group_id": str(runtime_policy.get("agent_group_id") or graph_payload.get("agent_group_id") or ""),
        "topology_template_id": str(metadata.get("topology_template_id") or graph_payload.get("topology_template_id") or ""),
        "handoff_policy": str(metadata.get("handoff_policy") or graph_payload.get("handoff_policy") or "handoff"),
        "conflict_resolution_policy": str(metadata.get("conflict_resolution_policy") or graph_payload.get("conflict_resolution_policy") or "coordinator_review"),
        "output_merge_policy": str(metadata.get("output_merge_policy") or graph_payload.get("output_merge_policy") or "coordinator_final_merge"),
        "shared_context_policy": str(context_policy.get("shared_context_policy") or graph_payload.get("shared_context_policy") or "explicit_refs_only"),
        "memory_sharing_policy": str(context_policy.get("memory_sharing_policy") or working_memory_policy.get("memory_sharing_policy") or graph_payload.get("memory_sharing_policy") or "isolated_by_default"),
        "graph_nodes": list(task_graph.get("graph_nodes") or task_graph.get("nodes") or graph_payload.get("graph_nodes") or graph_payload.get("nodes") or []),
        "graph_edges": list(task_graph.get("graph_edges") or task_graph.get("edges") or graph_payload.get("graph_edges") or graph_payload.get("edges") or []),
        "metadata": {
            **metadata,
            **dict(graph_payload.get("metadata") or {}),
        },
    }


def _runtime_spec_from_payload(payload: dict[str, Any]) -> TaskGraphRuntimeSpec | None:
    if not payload:
        return None
    try:
        return TaskGraphRuntimeSpec(
            graph_id=str(payload.get("graph_id") or ""),
            domain_id=str(payload.get("domain_id") or ""),
            task_family=str(payload.get("task_family") or ""),
            coordinator_agent_id=str(payload.get("coordinator_agent_id") or ""),
            graph_ref=str(payload.get("graph_ref") or payload.get("graph_id") or ""),
            agent_group_id=str(payload.get("agent_group_id") or ""),
            nodes=tuple(
                TaskGraphRuntimeNode(**{key: value for key, value in dict(item).items() if key in TaskGraphRuntimeNode.__dataclass_fields__})
                for item in list(payload.get("nodes") or [])
                if isinstance(item, dict)
            ),
            edges=tuple(
                TaskGraphRuntimeEdge(**{key: value for key, value in dict(item).items() if key in TaskGraphRuntimeEdge.__dataclass_fields__})
                for item in list(payload.get("edges") or [])
                if isinstance(item, dict)
            ),
            subtask_refs=tuple(str(item) for item in list(payload.get("subtask_refs") or []) if str(item)),
            communication_modes=tuple(str(item) for item in list(payload.get("communication_modes") or []) if str(item)),
            start_node_ids=tuple(str(item) for item in list(payload.get("start_node_ids") or []) if str(item)),
            terminal_node_ids=tuple(str(item) for item in list(payload.get("terminal_node_ids") or []) if str(item)),
            resource_nodes=_dict_tuple(payload.get("resource_nodes")),
            temporal_edges=_dict_tuple(payload.get("temporal_edges")),
            memory_edges=_dict_tuple(payload.get("memory_edges")),
            artifact_context_edges=_dict_tuple(payload.get("artifact_context_edges")),
            revision_edges=_dict_tuple(payload.get("revision_edges")),
            loop_frames=_dict_tuple(payload.get("loop_frames")),
            memory_matrix=dict(payload.get("memory_matrix") or {}),
            diagnostics=dict(payload.get("diagnostics") or {}),
        )
    except (TypeError, ValueError):
        return None


def _dispatch_nodes_from_payload(graph_payload: dict[str, Any], topology_template_payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = (
        graph_payload.get("graph_nodes"),
        topology_template_payload.get("nodes"),
        dict(graph_payload.get("metadata") or {}).get("graph_nodes"),
    )
    for value in candidates:
        nodes = [dict(item) for item in list(value or []) if isinstance(item, dict)]
        if nodes:
            return nodes
    return []


def _dict_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    return tuple(dict(item) for item in list(value or []) if isinstance(item, dict))


def _dispatch_edges_from_payload(graph_payload: dict[str, Any], topology_template_payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = (
        graph_payload.get("graph_edges"),
        topology_template_payload.get("edges"),
        dict(graph_payload.get("metadata") or {}).get("graph_edges"),
    )
    for value in candidates:
        edges = [dict(item) for item in list(value or []) if isinstance(item, dict)]
        if edges:
            return edges
    return []