from __future__ import annotations

from collections import defaultdict
from typing import Any

from tasks.coordination_graph_models import TaskGraphRuntimeEdge, TaskGraphRuntimeNode, TaskGraphRuntimeSpec

from .task_graph_scheduler_models import (
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
    terminal_status: str = "",
    mode: str = "shadow",
) -> TaskGraphSchedulerState:
    statuses = _initial_node_statuses(runtime_spec=runtime_spec, node_statuses=node_statuses)
    incoming, outgoing = _node_adjacency(runtime_spec.edges)
    completed = {node_id for node_id, status in statuses.items() if status in TERMINAL_COMPLETED}
    failed = {node_id for node_id, status in statuses.items() if status in TERMINAL_FAILED}
    running = {node_id for node_id, status in statuses.items() if status in ACTIVE_STATUSES}
    waiting = {node_id for node_id, status in statuses.items() if status in WAITING_STATUSES}
    phase_order = _phase_order(runtime_spec.nodes)
    active_phase_ids = _active_phase_ids(
        nodes=runtime_spec.nodes,
        statuses=statuses,
        phase_order=phase_order,
    )
    active_sequence_by_phase = _active_sequence_by_phase(
        nodes=runtime_spec.nodes,
        statuses=statuses,
        active_phase_ids=active_phase_ids,
    )

    node_states: list[TaskGraphNodeRunState] = []
    ready_node_ids: list[str] = []
    blocked_node_ids: list[str] = []
    running_node_ids: list[str] = []
    completed_node_ids: list[str] = []
    failed_node_ids: list[str] = []

    for node in runtime_spec.nodes:
        status = statuses.get(node.node_id, "pending")
        blocked_reasons: list[str] = []
        if status in {"pending", "ready"}:
            required_sources = tuple(incoming.get(node.node_id, ()))
            timing_allowed, timing_reasons = _node_timing_allowed(
                node=node,
                active_phase_ids=active_phase_ids,
                active_sequence_by_phase=active_sequence_by_phase,
            )
            ready = _node_ready(
                node=node,
                required_sources=required_sources,
                completed=completed,
                failed=failed,
            ) and timing_allowed
            if ready:
                status = "ready"
                ready_node_ids.append(node.node_id)
            else:
                status = "blocked"
                missing_sources = [source for source in required_sources if source not in completed]
                blocked_reasons.extend(f"upstream:{source}" for source in missing_sources)
                blocked_reasons.extend(timing_reasons)
                if node.wait_policy not in {"wait_all_upstream_completed", "wait_required_contracts"}:
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
                },
            )
        )

    edge_states = [
        _edge_state(edge=edge, statuses=statuses)
        for edge in runtime_spec.edges
    ]
    phase_states = _phase_states(runtime_spec.nodes, node_states)
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
            "node_count": len(runtime_spec.nodes),
            "edge_count": len(runtime_spec.edges),
            "phase_count": len(phase_states),
            "active_phase_ids": list(active_phase_ids),
            "active_sequence_by_phase": dict(active_sequence_by_phase),
        },
    )


def _initial_node_statuses(
    *,
    runtime_spec: TaskGraphRuntimeSpec,
    node_statuses: dict[str, str] | None,
) -> dict[str, str]:
    provided = {str(key): str(value) for key, value in dict(node_statuses or {}).items() if str(key)}
    if provided:
        return {
            node.node_id: provided.get(node.node_id, "pending")
            for node in runtime_spec.nodes
        }
    start_ids = set(runtime_spec.start_node_ids or ())
    return {
        node.node_id: "ready" if node.node_id in start_ids else "pending"
        for node in runtime_spec.nodes
    }


def _node_adjacency(edges: tuple[TaskGraphRuntimeEdge, ...]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    incoming: dict[str, list[str]] = defaultdict(list)
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        source = str(edge.source_node_id or "").strip()
        target = str(edge.target_node_id or "").strip()
        if not source or not target:
            continue
        incoming[target].append(source)
        outgoing[source].append(target)
    return dict(incoming), dict(outgoing)


def _node_ready(
    *,
    node: TaskGraphRuntimeNode,
    required_sources: tuple[str, ...],
    completed: set[str],
    failed: set[str],
) -> bool:
    if node.wait_policy == "fire_and_continue":
        return True
    if not required_sources:
        return True
    if failed and node.join_policy in {"allow_partial_with_issues", "coordinator_decides"}:
        terminal_sources = completed | failed
        return all(source in terminal_sources for source in required_sources) and any(source in completed for source in required_sources)
    if node.wait_policy == "wait_any_upstream_completed":
        return any(source in completed for source in required_sources)
    if node.wait_policy in {"wait_all_upstream_completed", "wait_required_contracts"}:
        return all(source in completed for source in required_sources)
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


def _active_phase_ids(
    *,
    nodes: tuple[TaskGraphRuntimeNode, ...],
    statuses: dict[str, str],
    phase_order: tuple[str, ...],
) -> set[str]:
    running_phases = {
        _phase_id(node)
        for node in nodes
        if statuses.get(node.node_id) in ACTIVE_STATUSES
    }
    if running_phases:
        return running_phases
    nodes_by_phase: dict[str, list[TaskGraphRuntimeNode]] = defaultdict(list)
    for node in nodes:
        nodes_by_phase[_phase_id(node)].append(node)
    for phase_id in phase_order:
        phase_nodes = nodes_by_phase.get(phase_id, [])
        if any(statuses.get(node.node_id, "pending") not in TERMINAL_COMPLETED | TERMINAL_FAILED for node in phase_nodes):
            return {phase_id}
    return set(phase_order[:1])


def _active_sequence_by_phase(
    *,
    nodes: tuple[TaskGraphRuntimeNode, ...],
    statuses: dict[str, str],
    active_phase_ids: set[str],
) -> dict[str, int]:
    result: dict[str, int] = {}
    for phase_id in active_phase_ids:
        candidates = [
            node.sequence_index
            for node in nodes
            if _phase_id(node) == phase_id
            and node.sequence_index > 0
            and statuses.get(node.node_id, "pending") not in TERMINAL_COMPLETED | TERMINAL_FAILED
        ]
        if candidates:
            result[phase_id] = min(candidates)
    return result


def _node_timing_allowed(
    *,
    node: TaskGraphRuntimeNode,
    active_phase_ids: set[str],
    active_sequence_by_phase: dict[str, int],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    phase_id = _phase_id(node)
    if active_phase_ids and phase_id not in active_phase_ids:
        reasons.append(f"phase_not_active:{phase_id}")
    active_sequence = active_sequence_by_phase.get(phase_id, 0)
    if active_sequence > 0 and node.sequence_index > active_sequence:
        reasons.append(f"sequence_wait:{active_sequence}")
    return not reasons, reasons


def _edge_state(*, edge: TaskGraphRuntimeEdge, statuses: dict[str, str]) -> TaskGraphEdgeHandoffState:
    source_status = statuses.get(edge.source_node_id, "pending")
    target_status = statuses.get(edge.target_node_id, "pending")
    if source_status == "failed":
        status = "failed"
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
        },
    )


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
