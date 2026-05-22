from __future__ import annotations

from collections import defaultdict
from typing import Any

from task_system.compiler.coordination_graph_models import TaskGraphRuntimeEdge, TaskGraphRuntimeNode, TaskGraphRuntimeSpec

from .scheduler_models import (
    TaskGraphEdgeHandoffState,
    TaskGraphNodeRunState,
    TaskGraphPhaseState,
    TaskGraphSchedulerState,
)


TERMINAL_COMPLETED = {"completed"}
TERMINAL_FAILED = {"failed"}
ACTIVE_STATUSES = {"running", "background_running"}
WAITING_STATUSES = {"waiting_for_human", "human_gate", "waiting"}


def bootstrap_scheduler_state(
    *,
    runtime_spec: TaskGraphRuntimeSpec,
    node_statuses: dict[str, str] | None = None,
    result_record_index: dict[str, dict[str, Any]] | None = None,
    accepted_result_records_by_scope: dict[str, dict[str, str]] | None = None,
    edge_handoff_index: dict[str, dict[str, Any]] | None = None,
    active_scope_key: str = "",
    terminal_status: str = "",
    mode: str = "shadow",
) -> TaskGraphSchedulerState:
    execution_nodes = _execution_nodes(runtime_spec.nodes)
    raw_statuses = _initial_node_statuses(nodes=execution_nodes, start_node_ids=runtime_spec.start_node_ids, node_statuses=node_statuses)
    statuses, failure_propagation = _apply_failure_propagation(
        nodes=execution_nodes,
        edges=runtime_spec.edges,
        statuses=raw_statuses,
    )
    incoming, outgoing = _node_adjacency(execution_nodes, runtime_spec.edges, runtime_spec.temporal_edges)
    incoming_edges = _incoming_edges_by_target(runtime_spec.edges, runtime_spec.temporal_edges)
    optional_node_ids = _optional_feedback_subgraph_nodes(runtime_spec.nodes, runtime_spec.edges)
    temporal_gate_enabled = bool(result_record_index is not None or accepted_result_records_by_scope is not None)
    record_index = _normalize_result_record_index(result_record_index)
    accepted_by_scope = _normalize_accepted_result_records(accepted_result_records_by_scope)
    handoff_index = _normalize_edge_handoff_index(edge_handoff_index)
    completed = {node_id for node_id, status in statuses.items() if status in TERMINAL_COMPLETED}
    failed = {node_id for node_id, status in statuses.items() if status in TERMINAL_FAILED}
    running = {node_id for node_id, status in statuses.items() if status in ACTIVE_STATUSES}
    waiting = {node_id for node_id, status in statuses.items() if status in WAITING_STATUSES}
    start_node_ids = set(runtime_spec.start_node_ids or ())

    node_states: list[TaskGraphNodeRunState] = []
    ready_node_ids: list[str] = []
    blocked_node_ids: list[str] = []
    running_node_ids: list[str] = []
    completed_node_ids: list[str] = []
    failed_node_ids: list[str] = []

    for node in execution_nodes:
        status = statuses.get(node.node_id, "pending")
        blocked_reasons: list[str] = []
        if status in {"pending", "ready"}:
            required_sources = tuple(incoming.get(node.node_id, ()))
            ready = _node_ready(
                node=node,
                current_status=status,
                start_node_ids=start_node_ids,
                required_sources=required_sources,
                completed=completed,
                failed=failed,
                temporal_gate_enabled=temporal_gate_enabled,
                incoming_edges=tuple(incoming_edges.get(node.node_id, ())),
                result_record_index=record_index,
                accepted_result_records_by_scope=accepted_by_scope,
                edge_handoff_index=handoff_index,
                active_scope_key=active_scope_key,
            )
            if ready:
                status = "ready"
                ready_node_ids.append(node.node_id)
            else:
                status = "blocked"
                for source in required_sources:
                    if source in completed:
                        continue
                    if source in failed:
                        blocked_reasons.append(f"upstream_failed:{source}")
                    else:
                        blocked_reasons.append(f"upstream:{source}")
                blocked_reasons.extend(
                    _timeline_gate_blocked_reasons(
                        node=node,
                        required_sources=required_sources,
                        completed=completed,
                        temporal_gate_enabled=temporal_gate_enabled,
                        incoming_edges=tuple(incoming_edges.get(node.node_id, ())),
                        result_record_index=record_index,
                        accepted_result_records_by_scope=accepted_by_scope,
                        edge_handoff_index=handoff_index,
                        active_scope_key=active_scope_key,
                    )
                )
                if node.wait_policy not in {
                    "wait_all_upstream_completed",
                    "wait_required_contracts",
                    "wait_any_upstream_completed",
                    "wait_handoff_ack",
                    "fire_and_continue",
                    "manual_release",
                }:
                    blocked_reasons.append(f"unsupported_wait_policy:{node.wait_policy}")
                blocked_node_ids.append(node.node_id)
        elif status in ACTIVE_STATUSES:
            running_node_ids.append(node.node_id)
        elif status in TERMINAL_COMPLETED:
            completed_node_ids.append(node.node_id)
        elif status in TERMINAL_FAILED:
            failed_node_ids.append(node.node_id)
        elif status in WAITING_STATUSES:
            blocked_node_ids.append(node.node_id)
            blocked_reasons.append(status)

        node_states.append(
            TaskGraphNodeRunState(
                node_id=node.node_id,
                status=status,
                phase_id=node.phase_id,
                sequence_index=node.sequence_index,
                timeline_group_id=node.timeline_group_id,
                execution_mode=node.execution_mode,
                wait_policy=node.wait_policy,
                join_policy=node.join_policy,
                upstream_node_ids=tuple(incoming.get(node.node_id, ())),
                downstream_node_ids=tuple(outgoing.get(node.node_id, ())),
                blocked_reasons=tuple(blocked_reasons),
                diagnostics={
                    "dispatch_group": node.dispatch_group,
                    "blocks_phase_exit": node.blocks_phase_exit,
                    "node_type": node.node_type,
                    "graph_module": bool(dict(node.metadata or {}).get("graph_module")),
                    "graph_module_runtime_plan_id": str(dict(node.metadata or {}).get("graph_module_runtime_plan_id") or ""),
                    "linked_graph_id": str(dict(node.metadata or {}).get("linked_graph_id") or ""),
                    "raw_status": str(raw_statuses.get(node.node_id, "")),
                    "failure_propagated": bool(
                        raw_statuses.get(node.node_id) != "failed"
                        and statuses.get(node.node_id) == "failed"
                    ),
                },
            )
        )

    edge_states = [
        _edge_state(
            edge=edge,
            statuses=statuses,
            temporal_gate_enabled=temporal_gate_enabled,
            result_record_index=record_index,
            accepted_result_records_by_scope=accepted_by_scope,
            edge_handoff_index=handoff_index,
            active_scope_key=active_scope_key,
        )
        for edge in runtime_spec.edges
    ]
    phase_states = _phase_states(execution_nodes, node_states)
    active_phase_ids = _observed_active_phase_ids(nodes=execution_nodes, node_states=node_states)
    active_sequence_by_phase = _observed_active_sequence_by_phase(
        node_states=node_states,
        active_phase_ids=set(active_phase_ids),
    )
    resolved_terminal = terminal_status or _terminal_status(
        runtime_spec=runtime_spec,
        completed=set(completed_node_ids),
        failed=set(failed_node_ids),
        running=set(running_node_ids),
        ready=set(ready_node_ids),
        blocked=set(blocked_node_ids),
    )
    return TaskGraphSchedulerState(
        graph_id=runtime_spec.graph_id,
        mode=mode or "shadow",
        phase_states=tuple(phase_states),
        node_states=tuple(node_states),
        edge_states=tuple(edge_states),
        ready_node_ids=tuple(ready_node_ids),
        blocked_node_ids=tuple(blocked_node_ids),
        running_node_ids=tuple(running_node_ids),
        completed_node_ids=tuple(completed_node_ids),
        failed_node_ids=tuple(failed_node_ids),
        terminal_status=resolved_terminal,
        diagnostics={
            "runtime_spec_source": str(dict(runtime_spec.diagnostics or {}).get("source") or ""),
            "scheduler_phase": "runtime_bootstrap" if mode == "active" else "shadow_bootstrap",
            "node_count": len(execution_nodes),
            "resource_node_count": len(runtime_spec.nodes) - len(execution_nodes),
            "resource_node_ids_excluded_from_schedule": [
                node.node_id for node in runtime_spec.nodes if not _is_execution_node(node)
            ],
            "edge_count": len(runtime_spec.edges),
            "temporal_edge_count": len(runtime_spec.temporal_edges),
            "blocking_temporal_edge_count": len(_blocking_temporal_edges(runtime_spec.temporal_edges)),
            "phase_count": len(phase_states),
            "scheduling_authority": "explicit_dependency_ready_set",
            "lifecycle_coordinate_authority": "diagnostic_only",
            "legacy_timing_gate_enabled": False,
            "active_phase_ids": list(active_phase_ids),
            "active_sequence_by_phase": dict(active_sequence_by_phase),
            "active_phase_ids_semantics": "observed_ready_running_waiting_only",
            "active_sequence_by_phase_semantics": "observed_ready_running_waiting_only",
            "optional_node_ids": sorted(optional_node_ids),
            "timeline_gate_enabled": temporal_gate_enabled,
            "edge_handoff_gate_enabled": bool(handoff_index),
            "active_scope_key": active_scope_key,
            "input_node_statuses": dict(raw_statuses),
            "effective_node_statuses": dict(statuses),
            "failure_propagation": failure_propagation,
            "failure_propagated_node_ids": sorted(
                {
                    str(item.get("target_node_id") or "")
                    for item in failure_propagation
                    if str(item.get("target_node_id") or "")
                }
            ),
            "graph_module_runtime_plan_count": len(getattr(runtime_spec, "graph_module_runtime_plans", ())),
            "graph_module_node_ids": [
                node.node_id
                for node in runtime_spec.nodes
                if node.node_type == "graph_module" or bool(dict(node.metadata or {}).get("graph_module"))
            ],
        },
    )


def _initial_node_statuses(
    *,
    nodes: tuple[TaskGraphRuntimeNode, ...],
    start_node_ids: tuple[str, ...],
    node_statuses: dict[str, str] | None,
) -> dict[str, str]:
    provided = {str(key): str(value) for key, value in dict(node_statuses or {}).items() if str(key)}
    if provided:
        return {
            node.node_id: provided.get(node.node_id, "pending")
            for node in nodes
        }
    start_ids = set(start_node_ids or ())
    return {
        node.node_id: "ready" if node.node_id in start_ids else "pending"
        for node in nodes
    }


def _execution_nodes(nodes: tuple[TaskGraphRuntimeNode, ...]) -> tuple[TaskGraphRuntimeNode, ...]:
    return tuple(node for node in nodes if _is_execution_node(node))


def _is_execution_node(node: TaskGraphRuntimeNode) -> bool:
    node_type = str(node.node_type or "").strip()
    node_id = str(node.node_id or "").strip()
    if node_type in {
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
    }:
        return False
    return not node_id.startswith(("memory.", "artifact.", "thread.", "progress.", "issue."))


def _apply_failure_propagation(
    *,
    nodes: tuple[TaskGraphRuntimeNode, ...],
    edges: tuple[TaskGraphRuntimeEdge, ...],
    statuses: dict[str, str],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    effective = dict(statuses)
    node_ids = {node.node_id for node in nodes}
    propagation: list[dict[str, Any]] = []
    propagated_keys: set[tuple[str, str, str]] = set()
    changed = True
    while changed:
        changed = False
        for edge in edges:
            source = str(edge.source_node_id or "").strip()
            target = str(edge.target_node_id or "").strip()
            if source not in node_ids or target not in node_ids:
                continue
            if _is_feedback_edge(edge) or _is_conditional_route_edge(edge):
                continue
            if effective.get(source) != "failed":
                continue
            policy = _failure_propagation_policy(edge)
            if policy != "fail_downstream":
                continue
            target_status = str(effective.get(target) or "pending")
            if target_status in TERMINAL_COMPLETED | TERMINAL_FAILED | ACTIVE_STATUSES | WAITING_STATUSES:
                continue
            effective[target] = "failed"
            key = (source, edge.edge_id, target)
            if key not in propagated_keys:
                propagation.append(
                    {
                        "source_node_id": source,
                        "target_node_id": target,
                        "edge_id": edge.edge_id,
                        "failure_propagation_policy": policy,
                        "previous_target_status": target_status,
                    }
                )
                propagated_keys.add(key)
            changed = True
    return effective, propagation


def _failure_propagation_policy(edge: TaskGraphRuntimeEdge | dict[str, Any] | None) -> str:
    if edge is None:
        return "fail_downstream"
    if isinstance(edge, TaskGraphRuntimeEdge):
        value = str(edge.failure_propagation_policy or "fail_downstream").strip()
    else:
        value = str(edge.get("failure_propagation_policy") or "fail_downstream").strip()
    return value or "fail_downstream"


def _node_adjacency(
    nodes: tuple[TaskGraphRuntimeNode, ...],
    edges: tuple[TaskGraphRuntimeEdge, ...],
    temporal_edges: tuple[dict[str, Any], ...] = (),
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    incoming: dict[str, list[str]] = defaultdict(list)
    outgoing: dict[str, list[str]] = defaultdict(list)
    node_order = {node.node_id: index for index, node in enumerate(nodes)}
    for edge in edges:
        source = str(edge.source_node_id or "").strip()
        target = str(edge.target_node_id or "").strip()
        if not source or not target:
            continue
        if (
            _is_feedback_edge(edge)
            or _is_conditional_route_edge(edge)
            or _is_backward_edge(source=source, target=target, node_order=node_order)
        ):
            outgoing[source].append(target)
            continue
        incoming[target].append(source)
        outgoing[source].append(target)
    for edge in _blocking_temporal_edges(temporal_edges):
        source = str(edge.get("source_node_id") or "").strip()
        target = str(edge.get("target_node_id") or "").strip()
        if not source or not target:
            continue
        if _is_backward_edge(source=source, target=target, node_order=node_order):
            outgoing[source].append(target)
            continue
        if source not in incoming[target]:
            incoming[target].append(source)
        if target not in outgoing[source]:
            outgoing[source].append(target)
    return dict(incoming), dict(outgoing)


def _incoming_edges_by_target(
    edges: tuple[TaskGraphRuntimeEdge, ...],
    temporal_edges: tuple[dict[str, Any], ...] = (),
) -> dict[str, list[TaskGraphRuntimeEdge | dict[str, Any]]]:
    incoming: dict[str, list[TaskGraphRuntimeEdge | dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        target = str(edge.target_node_id or "").strip()
        if target:
            incoming[target].append(edge)
    for edge in _blocking_temporal_edges(temporal_edges):
        target = str(edge.get("target_node_id") or "").strip()
        if target:
            incoming[target].append(dict(edge))
    return dict(incoming)


def _blocking_temporal_edges(temporal_edges: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    selected: list[dict[str, Any]] = []
    for edge in temporal_edges:
        item = dict(edge or {})
        if item.get("blocking", True) is False:
            continue
        temporal_type = str(item.get("temporal_type") or "").strip()
        if temporal_type in {"revision_feedback", "conditional_feedback", "repair_feedback"}:
            continue
        selected.append(item)
    return tuple(selected)


def _optional_feedback_subgraph_nodes(
    nodes: tuple[TaskGraphRuntimeNode, ...],
    edges: tuple[TaskGraphRuntimeEdge, ...],
) -> set[str]:
    node_ids = {node.node_id for node in nodes}
    node_order = {node.node_id: index for index, node in enumerate(nodes)}
    forward_outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        source = str(edge.source_node_id or "").strip()
        target = str(edge.target_node_id or "").strip()
        if not source or not target:
            continue
        if (
            _is_feedback_edge(edge)
            or _is_conditional_route_edge(edge)
            or _is_backward_edge(source=source, target=target, node_order=node_order)
        ):
            continue
        forward_outgoing[source].append(target)
    roots = {
        str(edge.target_node_id or "").strip()
        for edge in edges
        if (_is_feedback_edge(edge) or _is_conditional_route_edge(edge))
        and str(edge.target_node_id or "").strip() in node_ids
        and not _is_backward_edge(
            source=str(edge.source_node_id or "").strip(),
            target=str(edge.target_node_id or "").strip(),
            node_order=node_order,
        )
    }
    optional: set[str] = set()
    stack = list(roots)
    while stack:
        node_id = stack.pop()
        if node_id in optional:
            continue
        optional.add(node_id)
        for target in forward_outgoing.get(node_id, ()):
            if target in node_ids and target not in optional:
                stack.append(target)
    return optional


def _node_ready(
    *,
    node: TaskGraphRuntimeNode,
    current_status: str,
    start_node_ids: set[str],
    required_sources: tuple[str, ...],
    completed: set[str],
    failed: set[str],
    temporal_gate_enabled: bool = False,
    incoming_edges: tuple[TaskGraphRuntimeEdge | dict[str, Any], ...] = (),
    result_record_index: dict[str, dict[str, Any]] | None = None,
    accepted_result_records_by_scope: dict[str, dict[str, str]] | None = None,
    edge_handoff_index: dict[str, dict[str, Any]] | None = None,
    active_scope_key: str = "",
) -> bool:
    if node.wait_policy == "fire_and_continue":
        return True
    if not required_sources:
        return current_status == "ready" or node.node_id in start_node_ids
    if failed and node.join_policy in {"allow_partial_with_issues", "coordinator_decides"}:
        allowed_failed_sources = {
            source
            for source in required_sources
            if source in failed
            and _failure_propagation_policy(_edge_for_source(incoming_edges, source)) in {"allow_partial", "coordinator_decides"}
        }
        terminal_sources = completed | allowed_failed_sources
        if not (all(source in terminal_sources for source in required_sources) and any(source in completed for source in required_sources)):
            return False
        return _source_readiness_dependencies_satisfied(
            node=node,
            required_sources=tuple(source for source in required_sources if source in completed),
            temporal_gate_enabled=temporal_gate_enabled,
            incoming_edges=incoming_edges,
            result_record_index=result_record_index or {},
            accepted_result_records_by_scope=accepted_result_records_by_scope or {},
            edge_handoff_index=edge_handoff_index or {},
            active_scope_key=active_scope_key,
        )
    if node.wait_policy == "wait_any_upstream_completed":
        completed_sources = tuple(source for source in required_sources if source in completed)
        return any(completed_sources) and _source_readiness_dependencies_satisfied(
            node=node,
            required_sources=completed_sources,
            temporal_gate_enabled=temporal_gate_enabled,
            incoming_edges=incoming_edges,
            result_record_index=result_record_index or {},
            accepted_result_records_by_scope=accepted_result_records_by_scope or {},
            edge_handoff_index=edge_handoff_index or {},
            active_scope_key=active_scope_key,
            any_source=True,
        )
    if node.wait_policy in {"wait_all_upstream_completed", "wait_required_contracts", "wait_handoff_ack"}:
        return all(source in completed for source in required_sources) and _source_readiness_dependencies_satisfied(
            node=node,
            required_sources=required_sources,
            temporal_gate_enabled=temporal_gate_enabled,
            incoming_edges=incoming_edges,
            result_record_index=result_record_index or {},
            accepted_result_records_by_scope=accepted_result_records_by_scope or {},
            edge_handoff_index=edge_handoff_index or {},
            active_scope_key=active_scope_key,
        )
    if node.wait_policy == "manual_release":
        return False
    return False


def _phase_id(node: TaskGraphRuntimeNode) -> str:
    return str(node.phase_id or "phase.unassigned")


def _phase_order(nodes: tuple[TaskGraphRuntimeNode, ...]) -> tuple[str, ...]:
    phase_first_index: dict[str, int] = {}
    for index, node in enumerate(nodes):
        phase_id = _phase_id(node)
        phase_first_index.setdefault(phase_id, index)
    return tuple(sorted(phase_first_index, key=lambda item: phase_first_index[item]))


def _observed_active_phase_ids(
    *,
    nodes: tuple[TaskGraphRuntimeNode, ...],
    node_states: list[TaskGraphNodeRunState],
) -> tuple[str, ...]:
    phase_order = _phase_order(nodes)
    active_statuses = ACTIVE_STATUSES | WAITING_STATUSES | {"ready"}
    active_by_phase = {
        state.phase_id or "phase.unassigned"
        for state in node_states
        if state.status in active_statuses
    }
    return tuple(phase_id for phase_id in phase_order if phase_id in active_by_phase)


def _observed_active_sequence_by_phase(
    *,
    node_states: list[TaskGraphNodeRunState],
    active_phase_ids: set[str],
) -> dict[str, int]:
    result: dict[str, int] = {}
    for phase_id in active_phase_ids:
        candidates = [
            state.sequence_index
            for state in node_states
            if (state.phase_id or "phase.unassigned") == phase_id
            and state.status in ACTIVE_STATUSES | WAITING_STATUSES | {"ready"}
            and state.sequence_index > 0
        ]
        if candidates:
            result[phase_id] = min(candidates)
    return result


def _source_readiness_dependencies_satisfied(
    *,
    node: TaskGraphRuntimeNode,
    required_sources: tuple[str, ...],
    temporal_gate_enabled: bool,
    incoming_edges: tuple[TaskGraphRuntimeEdge | dict[str, Any], ...],
    result_record_index: dict[str, dict[str, Any]],
    accepted_result_records_by_scope: dict[str, dict[str, str]],
    edge_handoff_index: dict[str, dict[str, Any]],
    active_scope_key: str = "",
    any_source: bool = False,
) -> bool:
    checks = [
        _source_ready_dependency_satisfied(
            node=node,
            source=source,
            edge=_edge_for_source(incoming_edges, source),
            temporal_gate_enabled=temporal_gate_enabled,
            result_record_index=result_record_index,
            accepted_result_records_by_scope=accepted_result_records_by_scope,
            edge_handoff_index=edge_handoff_index,
            active_scope_key=active_scope_key,
        )
        for source in required_sources
    ]
    return any(checks) if any_source else all(checks)


def _timeline_gate_blocked_reasons(
    *,
    node: TaskGraphRuntimeNode,
    required_sources: tuple[str, ...],
    completed: set[str],
    temporal_gate_enabled: bool,
    incoming_edges: tuple[TaskGraphRuntimeEdge | dict[str, Any], ...],
    result_record_index: dict[str, dict[str, Any]],
    accepted_result_records_by_scope: dict[str, dict[str, str]],
    edge_handoff_index: dict[str, dict[str, Any]],
    active_scope_key: str = "",
) -> list[str]:
    reasons: list[str] = []
    for source in required_sources:
        if source not in completed:
            continue
        edge = _edge_for_source(incoming_edges, source)
        if temporal_gate_enabled:
            record = _effective_result_record(
                source=source,
                edge=edge,
                result_record_index=result_record_index,
                accepted_result_records_by_scope=accepted_result_records_by_scope,
                active_scope_key=active_scope_key,
            )
            if not record:
                reasons.append(f"timeline_result_missing:{source}")
                continue
            if record.get("accepted") is not True:
                reasons.append(f"timeline_result_not_accepted:{source}")
            if int(record.get("effective_from_clock_seq") or 0) <= 0:
                reasons.append(f"timeline_result_not_effective:{source}")
            if _edge_requires_artifacts(edge) and not list(record.get("produced_artifact_refs") or []):
                reasons.append(f"timeline_result_missing_artifacts:{source}")
        reasons.extend(
            _edge_handoff_blocked_reasons(
                node=node,
                source=source,
                edge=edge,
                edge_handoff_index=edge_handoff_index,
            )
        )
    return reasons


def _source_ready_dependency_satisfied(
    *,
    node: TaskGraphRuntimeNode,
    source: str,
    edge: TaskGraphRuntimeEdge | dict[str, Any] | None,
    temporal_gate_enabled: bool,
    result_record_index: dict[str, dict[str, Any]],
    accepted_result_records_by_scope: dict[str, dict[str, str]],
    edge_handoff_index: dict[str, dict[str, Any]],
    active_scope_key: str = "",
) -> bool:
    if temporal_gate_enabled and not _source_has_effective_result_record(
        source=source,
        edge=edge,
        result_record_index=result_record_index,
        accepted_result_records_by_scope=accepted_result_records_by_scope,
        active_scope_key=active_scope_key,
    ):
        return False
    return _edge_handoff_satisfied(
        node=node,
        source=source,
        edge=edge,
        edge_handoff_index=edge_handoff_index,
    )


def _source_has_effective_result_record(
    *,
    source: str,
    edge: TaskGraphRuntimeEdge | dict[str, Any] | None,
    result_record_index: dict[str, dict[str, Any]],
    accepted_result_records_by_scope: dict[str, dict[str, str]],
    active_scope_key: str = "",
) -> bool:
    record = _effective_result_record(
        source=source,
        edge=edge,
        result_record_index=result_record_index,
        accepted_result_records_by_scope=accepted_result_records_by_scope,
        active_scope_key=active_scope_key,
    )
    if not record:
        return False
    if record.get("accepted") is not True:
        return False
    if int(record.get("effective_from_clock_seq") or 0) <= 0:
        return False
    if _edge_requires_artifacts(edge) and not list(record.get("produced_artifact_refs") or []):
        return False
    return True


def _effective_result_record(
    *,
    source: str,
    edge: TaskGraphRuntimeEdge | dict[str, Any] | None,
    result_record_index: dict[str, dict[str, Any]],
    accepted_result_records_by_scope: dict[str, dict[str, str]],
    active_scope_key: str = "",
) -> dict[str, Any]:
    scope_candidates = _scope_candidates(edge=edge, active_scope_key=active_scope_key)
    for scope_key in scope_candidates:
        record_id = str(dict(accepted_result_records_by_scope.get(scope_key) or {}).get(source) or "")
        record = dict(result_record_index.get(record_id) or {})
        if record:
            return record
    if scope_candidates and _timeline_dependency_requires_current_scope(edge):
        return {}
    fallback_records: list[dict[str, Any]] = []
    for scope_records in accepted_result_records_by_scope.values():
        record_id = str(dict(scope_records or {}).get(source) or "")
        record = dict(result_record_index.get(record_id) or {})
        if record:
            fallback_records.append(record)
    if fallback_records:
        return sorted(
            fallback_records,
            key=lambda item: int(item.get("effective_from_clock_seq") or item.get("clock_seq") or 0),
            reverse=True,
        )[0]
    for record in result_record_index.values():
        item = dict(record or {})
        if item.get("accepted") is not True:
            continue
        if str(item.get("stage_id") or item.get("node_id") or "") != source:
            continue
        fallback_records.append(item)
    if fallback_records:
        return sorted(
            fallback_records,
            key=lambda item: int(item.get("effective_from_clock_seq") or item.get("clock_seq") or 0),
            reverse=True,
        )[0]
    return {}


def _timeline_dependency_requires_current_scope(edge: TaskGraphRuntimeEdge | dict[str, Any] | None) -> bool:
    policy = _timeline_dependency_policy(edge)
    scope_mode = str(policy.get("scope") or policy.get("scope_mode") or "").strip()
    return policy.get("require_current_scope") is True or scope_mode in {"current", "current_scope", "same_scope"}


def _edge_handoff_satisfied(
    *,
    node: TaskGraphRuntimeNode,
    source: str,
    edge: TaskGraphRuntimeEdge | dict[str, Any] | None,
    edge_handoff_index: dict[str, dict[str, Any]],
) -> bool:
    if not _edge_requires_handoff_ack(node=node, edge=edge):
        return True
    record = _handoff_record_for_edge(edge=edge, source=source, target=node.node_id, edge_handoff_index=edge_handoff_index)
    if not record:
        return False
    return _handoff_ack_satisfied(record)


def _edge_handoff_blocked_reasons(
    *,
    node: TaskGraphRuntimeNode,
    source: str,
    edge: TaskGraphRuntimeEdge | dict[str, Any] | None,
    edge_handoff_index: dict[str, dict[str, Any]],
) -> list[str]:
    if not _edge_requires_handoff_ack(node=node, edge=edge):
        return []
    edge_ref = _edge_id(edge) or f"{source}->{node.node_id}"
    record = _handoff_record_for_edge(edge=edge, source=source, target=node.node_id, edge_handoff_index=edge_handoff_index)
    if not record:
        return [f"handoff_ack_missing:{edge_ref}"]
    if not _handoff_ack_satisfied(record):
        return [f"handoff_ack_waiting:{edge_ref}"]
    return []


def _edge_requires_handoff_ack(
    *,
    node: TaskGraphRuntimeNode,
    edge: TaskGraphRuntimeEdge | dict[str, Any] | None,
) -> bool:
    if edge is None:
        return False
    if _edge_ack_required(edge) is False:
        return False
    metadata = dict(edge.metadata or {}) if isinstance(edge, TaskGraphRuntimeEdge) else dict(edge.get("metadata") or {})
    bindings = dict(metadata.get("contract_bindings") or {})
    handoff_bindings = dict(bindings.get("handoff") or {})
    temporal_bindings = dict(bindings.get("temporal") or {})
    return (
        node.wait_policy == "wait_handoff_ack"
        or _edge_wait_policy(edge) == "wait_handoff_ack"
        or str(handoff_bindings.get("ack_timing") or "").strip() == "before_downstream_ready"
        or str(temporal_bindings.get("dependency_gate") or "").strip() == "handoff_ack"
    )


def _edge_ack_required(edge: TaskGraphRuntimeEdge | dict[str, Any] | None) -> bool:
    if edge is None:
        return False
    if isinstance(edge, TaskGraphRuntimeEdge):
        return bool(edge.ack_required)
    return bool(edge.get("ack_required", True))


def _edge_wait_policy(edge: TaskGraphRuntimeEdge | dict[str, Any] | None) -> str:
    if edge is None:
        return ""
    if isinstance(edge, TaskGraphRuntimeEdge):
        return str(edge.wait_policy or "").strip()
    return str(edge.get("wait_policy") or "").strip()


def _edge_id(edge: TaskGraphRuntimeEdge | dict[str, Any] | None) -> str:
    if edge is None:
        return ""
    if isinstance(edge, TaskGraphRuntimeEdge):
        return str(edge.edge_id or "").strip()
    return str(edge.get("edge_id") or edge.get("id") or "").strip()


def _edge_target(edge: TaskGraphRuntimeEdge | dict[str, Any] | None) -> str:
    if edge is None:
        return ""
    if isinstance(edge, TaskGraphRuntimeEdge):
        return str(edge.target_node_id or "").strip()
    return str(edge.get("target_node_id") or edge.get("to") or edge.get("target") or "").strip()


def _handoff_record_for_edge(
    *,
    edge: TaskGraphRuntimeEdge | dict[str, Any] | None,
    source: str,
    target: str,
    edge_handoff_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    candidates = [
        _edge_id(edge),
        f"{source}->{target}",
        f"{source}:{target}",
    ]
    edge_target = _edge_target(edge)
    if edge_target and edge_target != target:
        candidates.append(f"{source}->{edge_target}")
    for key in candidates:
        record = dict(edge_handoff_index.get(str(key or "").strip()) or {})
        if record:
            return record
    return {}


def _handoff_ack_satisfied(record: dict[str, Any]) -> bool:
    ack_state = str(record.get("ack_state") or record.get("status") or "").strip().lower()
    return ack_state in {
        "acknowledged",
        "acked",
        "accepted",
        "received",
        "delivered",
        "not_required",
        "completed",
        "satisfied",
    }


def _scope_candidates(*, edge: TaskGraphRuntimeEdge | dict[str, Any] | None, active_scope_key: str) -> tuple[str, ...]:
    policy = _timeline_dependency_policy(edge)
    configured = str(policy.get("scope_key") or policy.get("required_scope_key") or "").strip()
    scope_mode = str(policy.get("scope") or policy.get("scope_mode") or "").strip()
    if configured:
        return (configured,)
    if active_scope_key and scope_mode in {"current", "current_scope", "same_scope", ""}:
        return (active_scope_key,)
    if active_scope_key and policy.get("require_current_scope") is True:
        return (active_scope_key,)
    return ()


def _edge_requires_artifacts(edge: TaskGraphRuntimeEdge | dict[str, Any] | None) -> bool:
    if edge is None:
        return False
    policy = _artifact_policy(edge)
    timeline_policy = _timeline_dependency_policy(edge)
    return policy.get("required") is True or timeline_policy.get("require_artifacts") is True


def _edge_for_source(
    incoming_edges: tuple[TaskGraphRuntimeEdge | dict[str, Any], ...],
    source: str,
) -> TaskGraphRuntimeEdge | dict[str, Any] | None:
    for edge in incoming_edges:
        if _edge_source(edge) == source:
            return edge
    return None


def _edge_source(edge: TaskGraphRuntimeEdge | dict[str, Any] | None) -> str:
    if edge is None:
        return ""
    if isinstance(edge, TaskGraphRuntimeEdge):
        return str(edge.source_node_id or "")
    return str(edge.get("source_node_id") or edge.get("from") or edge.get("source") or "")


def _timeline_dependency_policy(edge: TaskGraphRuntimeEdge | dict[str, Any] | None) -> dict[str, Any]:
    if edge is None:
        return {}
    if isinstance(edge, TaskGraphRuntimeEdge):
        metadata = dict(edge.metadata or {})
        return dict(metadata.get("timeline_dependency") or metadata.get("temporal_control") or {})
    metadata = dict(edge.get("metadata") or {})
    return dict(edge.get("timeline_dependency") or metadata.get("timeline_dependency") or metadata.get("temporal_control") or {})


def _artifact_policy(edge: TaskGraphRuntimeEdge | dict[str, Any] | None) -> dict[str, Any]:
    if edge is None:
        return {}
    if isinstance(edge, TaskGraphRuntimeEdge):
        return dict(edge.artifact_ref_policy or {})
    return dict(edge.get("artifact_ref_policy") or {})


def _normalize_result_record_index(value: dict[str, dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    return {str(key): dict(record) for key, record in dict(value or {}).items() if str(key) and isinstance(record, dict)}


def _normalize_accepted_result_records(value: dict[str, dict[str, str]] | None) -> dict[str, dict[str, str]]:
    return {
        str(scope): {str(stage): str(record_id) for stage, record_id in dict(records or {}).items() if str(stage) and str(record_id)}
        for scope, records in dict(value or {}).items()
        if str(scope) and isinstance(records, dict)
    }


def _normalize_edge_handoff_index(value: dict[str, dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for key, raw in dict(value or {}).items():
        if not isinstance(raw, dict):
            continue
        record = dict(raw)
        keys = {str(key or "").strip()}
        diagnostics = dict(record.get("diagnostics") or {})
        edge_id = str(record.get("edge_id") or diagnostics.get("edge_id") or "").strip()
        source = str(record.get("source_node_id") or diagnostics.get("source_node_id") or diagnostics.get("source_stage_id") or "").strip()
        target = str(record.get("target_node_id") or diagnostics.get("target_node_id") or diagnostics.get("target_stage_id") or "").strip()
        keys.update(item for item in (edge_id, f"{source}->{target}" if source and target else "", f"{source}:{target}" if source and target else "") if item)
        for item in keys:
            normalized[item] = record
    return normalized


def _edge_state(
    *,
    edge: TaskGraphRuntimeEdge,
    statuses: dict[str, str],
    temporal_gate_enabled: bool = False,
    result_record_index: dict[str, dict[str, Any]] | None = None,
    accepted_result_records_by_scope: dict[str, dict[str, str]] | None = None,
    edge_handoff_index: dict[str, dict[str, Any]] | None = None,
    active_scope_key: str = "",
) -> TaskGraphEdgeHandoffState:
    source_status = statuses.get(edge.source_node_id, "pending")
    target_status = statuses.get(edge.target_node_id, "pending")
    record = _effective_result_record(
        source=edge.source_node_id,
        edge=edge,
        result_record_index=result_record_index or {},
        accepted_result_records_by_scope=accepted_result_records_by_scope or {},
        active_scope_key=active_scope_key,
    ) if temporal_gate_enabled else {}
    handoff_record = _handoff_record_for_edge(
        edge=edge,
        source=edge.source_node_id,
        target=edge.target_node_id,
        edge_handoff_index=edge_handoff_index or {},
    )
    if source_status == "failed":
        policy = _failure_propagation_policy(edge)
        if policy == "fail_downstream":
            status = "failed"
        elif policy == "isolate_failure":
            status = "failure_isolated"
        elif policy in {"allow_partial", "coordinator_decides"}:
            status = "partial_failure_allowed"
        else:
            status = "failed"
    elif temporal_gate_enabled and source_status == "completed" and not record:
        status = "timeline_waiting"
    elif handoff_record and _handoff_ack_satisfied(handoff_record):
        status = "acknowledged" if edge.ack_required else "delivered"
    elif handoff_record and edge.ack_required:
        status = "ack_waiting"
    elif source_status == "completed" and target_status in {"completed", "running"}:
        status = "acknowledged" if edge.ack_required else "delivered"
    elif source_status == "completed":
        status = "ack_waiting" if edge.ack_required else "payload_ready"
    else:
        status = "pending"
    return TaskGraphEdgeHandoffState(
        edge_id=edge.edge_id,
        source_node_id=edge.source_node_id,
        target_node_id=edge.target_node_id,
        status=status,
        ack_required=edge.ack_required,
        ack_policy=edge.ack_policy,
        wait_policy=edge.wait_policy,
        failure_propagation_policy=edge.failure_propagation_policy,
        result_delivery_policy=edge.result_delivery_policy,
        diagnostics={
            "source_status": source_status,
            "target_status": target_status,
            "timeout_policy": str(dict(edge.metadata or {}).get("timeout_policy") or ""),
            "timeline_gate_enabled": temporal_gate_enabled,
            "result_record_id": str(record.get("result_record_id") or ""),
            "result_scope_key": str(record.get("scope_key") or ""),
            "handoff_id": str(handoff_record.get("handoff_id") or ""),
            "handoff_ack_state": str(handoff_record.get("ack_state") or handoff_record.get("status") or ""),
        },
    )


def _is_feedback_edge(edge: TaskGraphRuntimeEdge) -> bool:
    metadata = dict(edge.metadata or {})
    mode = str(edge.mode or "").strip()
    dependency_role = str(metadata.get("dependency_role") or "").strip()
    loop_role = str(metadata.get("loop_role") or "").strip()
    return mode in {"review_feedback", "repair_feedback", "conditional_feedback"} or dependency_role in {
        "feedback",
        "conditional_feedback",
        "repair_feedback",
        "non_blocking_feedback",
    } or loop_role in {"repair", "feedback"}


def _is_conditional_route_edge(edge: TaskGraphRuntimeEdge) -> bool:
    metadata = dict(edge.metadata or {})
    mode = str(edge.mode or "").strip()
    dependency_role = str(metadata.get("dependency_role") or "").strip()
    verdict = str(metadata.get("verdict") or "").strip()
    return (
        mode
        in {
            "revision_request",
            "repair_route",
            "human_handoff",
            "fail_closed",
            "conditional_route",
        }
        or dependency_role in {"conditional_route", "repair_route", "failure_route", "human_handoff"}
        or verdict in {
            "revise",
            "repair_world",
            "repair_outline",
            "repair_character",
            "human_review_required",
            "fail_closed",
        }
    )


def _is_backward_edge(*, source: str, target: str, node_order: dict[str, int]) -> bool:
    if source not in node_order or target not in node_order:
        return False
    return node_order[source] > node_order[target]


def _phase_states(
    nodes: tuple[TaskGraphRuntimeNode, ...],
    node_states: list[TaskGraphNodeRunState],
) -> list[TaskGraphPhaseState]:
    by_phase: dict[str, list[TaskGraphNodeRunState]] = defaultdict(list)
    for state in node_states:
        phase_id = state.phase_id or "phase.unassigned"
        by_phase[phase_id].append(state)
    phase_states: list[TaskGraphPhaseState] = []
    node_by_id = {node.node_id: node for node in nodes}
    for phase_id, states in by_phase.items():
        ready = tuple(state.node_id for state in states if state.status == "ready")
        running = tuple(state.node_id for state in states if state.status in ACTIVE_STATUSES)
        completed = tuple(state.node_id for state in states if state.status == "completed")
        blocked = tuple(state.node_id for state in states if state.status == "blocked")
        if running or ready:
            status = "active"
        elif blocked:
            status = "blocked"
        elif completed and len(completed) == len(states):
            status = "completed"
        else:
            status = "pending"
        phase_states.append(
            TaskGraphPhaseState(
                phase_id=phase_id,
                status=status,
                node_ids=tuple(state.node_id for state in states),
                ready_node_ids=ready,
                running_node_ids=running,
                completed_node_ids=completed,
                blocked_node_ids=blocked,
                diagnostics={
                    "blocks_phase_exit_node_ids": [
                        state.node_id
                        for state in states
                        if node_by_id.get(state.node_id) is not None and node_by_id[state.node_id].blocks_phase_exit
                    ],
                },
            )
        )
    return phase_states


def _terminal_status(
    *,
    runtime_spec: TaskGraphRuntimeSpec,
    completed: set[str],
    failed: set[str],
    running: set[str],
    ready: set[str],
    blocked: set[str],
) -> str:
    if failed:
        return "failed"
    node_ids = {node.node_id for node in runtime_spec.nodes}
    if node_ids and completed == node_ids:
        return "completed"
    if not running and not ready and blocked:
        return "blocked"
    return ""
