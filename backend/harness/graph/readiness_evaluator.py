from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import GraphHarnessConfig, GraphReadinessDecision
from .scheduler_view import build_scheduler_view, is_executable_node


@dataclass(frozen=True, slots=True)
class GraphReadinessEvaluator:
    authority: str = "harness.graph.readiness_evaluator"

    def evaluate(
        self,
        *,
        graph_config: GraphHarnessConfig,
        node_states: dict[str, dict[str, Any]],
        edge_states: dict[str, dict[str, Any]],
        loop_state: dict[str, Any] | None = None,
    ) -> GraphReadinessDecision:
        scheduler_view = build_scheduler_view(graph_config)
        executable_ids = set(scheduler_view.executable_node_ids)
        start_ids = set(scheduler_view.start_node_ids)
        gated_exit_ids = _active_loop_exit_node_ids(graph_config=graph_config, loop_state=loop_state)
        closed_scope_ids = _closed_loop_scope_node_ids(graph_config=graph_config, loop_state=loop_state)
        inbound_by_target = _inbound_scheduler_edges_by_target(tuple(scheduler_view.dependency_edges))

        ready: list[str] = []
        blocked: list[str] = []
        waiting: list[str] = []
        skipped: list[str] = []
        reasons: dict[str, dict[str, Any]] = {}

        for raw_node in graph_config.nodes:
            node = dict(raw_node)
            node_id = str(node.get("node_id") or "")
            if not node_id or node_id not in executable_ids or not is_executable_node(node):
                continue
            if node_id in gated_exit_ids or node_id in closed_scope_ids:
                reasons[node_id] = {"status": "loop_scope_closed_or_gated", "authority": self.authority}
                continue

            node_status = str(dict(node_states.get(node_id) or {}).get("status") or "")
            if node_status in {"running", "completed", "failed"}:
                continue
            if node_status == "waiting_human_gate":
                waiting.append(node_id)
                reasons[node_id] = {"status": node_status, "authority": self.authority}
                continue
            if node_status == "blocked":
                blocked.append(node_id)
                reasons[node_id] = {"status": node_status, "authority": self.authority}
                continue
            if node_status == "ready":
                incoming = tuple(inbound_by_target.get(node_id) or ())
                if not incoming:
                    ready.append(node_id)
                    reasons[node_id] = {"status": "ready_start_node", "authority": self.authority}
                    continue
                edge_decision = _edge_readiness_decision(node=node, incoming_edges=incoming, edge_states=edge_states)
                reasons[node_id] = edge_decision
                if edge_decision["decision"] == "ready":
                    ready.append(node_id)
                elif edge_decision["decision"] == "blocked":
                    blocked.append(node_id)
                elif edge_decision["decision"] == "waiting":
                    waiting.append(node_id)
                elif edge_decision["decision"] == "skipped":
                    skipped.append(node_id)
                continue
            if node_status not in {"", "pending"}:
                continue

            incoming = tuple(inbound_by_target.get(node_id) or ())
            if not incoming:
                if node_id in start_ids:
                    ready.append(node_id)
                    reasons[node_id] = {"status": "topology_start_node", "authority": self.authority}
                continue

            edge_decision = _edge_readiness_decision(node=node, incoming_edges=incoming, edge_states=edge_states)
            reasons[node_id] = edge_decision
            if edge_decision["decision"] == "ready":
                ready.append(node_id)
            elif edge_decision["decision"] == "blocked":
                blocked.append(node_id)
            elif edge_decision["decision"] == "waiting":
                waiting.append(node_id)
            elif edge_decision["decision"] == "skipped":
                skipped.append(node_id)

        return GraphReadinessDecision(
            ready_node_ids=tuple(dict.fromkeys(ready)),
            blocked_node_ids=tuple(dict.fromkeys(blocked)),
            waiting_node_ids=tuple(dict.fromkeys(waiting)),
            skipped_node_ids=tuple(dict.fromkeys(skipped)),
            reasons=reasons,
        )


def _inbound_scheduler_edges_by_target(dependency_edges: tuple[dict[str, Any], ...]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for raw_edge in dependency_edges:
        edge = dict(raw_edge)
        target = str(edge.get("target_node_id") or "")
        result.setdefault(target, []).append(edge)
    return result


def _edge_readiness_decision(
    *,
    node: dict[str, Any],
    incoming_edges: tuple[dict[str, Any], ...],
    edge_states: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    wait_policy = str(dict(node.get("execution") or {}).get("wait_policy") or node.get("wait_policy") or "wait_all_upstream_completed").strip() or "wait_all_upstream_completed"
    join_policy = str(dict(node.get("execution") or {}).get("join_policy") or node.get("join_policy") or "all_success").strip() or "all_success"
    statuses = {}
    ignored_conditional_edges: list[str] = []
    for edge in incoming_edges:
        edge_id = str(edge.get("edge_id") or "")
        if not edge_id:
            continue
        status = str(dict(edge_states.get(edge_id) or {}).get("status") or "pending")
        if status == "pending" and _is_inactive_revision_edge(edge):
            ignored_conditional_edges.append(edge_id)
            continue
        statuses[edge_id] = status
    active_statuses = {edge_id: status for edge_id, status in statuses.items() if status != "skipped"}
    ready_count = sum(1 for status in active_statuses.values() if status == "ready")
    pending_count = sum(1 for status in active_statuses.values() if status == "pending")
    waiting_count = sum(1 for status in active_statuses.values() if status == "waiting_human")
    blocked_count = sum(1 for status in active_statuses.values() if status == "blocked")
    failed_count = sum(1 for status in active_statuses.values() if status == "source_failed")

    base = {
        "decision": "waiting",
        "wait_policy": wait_policy,
        "join_policy": join_policy,
        "edge_statuses": statuses,
        **({"ignored_conditional_edges": ignored_conditional_edges} if ignored_conditional_edges else {}),
        "authority": "harness.graph.readiness_evaluator.edge_decision",
    }
    if not active_statuses and statuses:
        return {**base, "decision": "skipped", "reason": "all_incoming_edges_skipped"}
    if blocked_count:
        return {**base, "decision": "blocked", "reason": "incoming_edge_blocked"}
    if waiting_count and wait_policy in {"manual_release", "wait_handoff_ack"}:
        return {**base, "decision": "waiting", "reason": "incoming_edge_waiting_human_or_ack"}
    if failed_count and join_policy in {"all_success", "fail_on_any_error"}:
        return {**base, "decision": "blocked", "reason": "incoming_edge_source_failed"}
    if join_policy == "coordinator_decides":
        return {**base, "decision": "waiting", "reason": "coordinator_decides"}
    if join_policy == "quorum":
        quorum = _quorum_value(node)
        if quorum < 1:
            return {**base, "decision": "blocked", "reason": "quorum_missing"}
        return {**base, "decision": "ready" if ready_count >= quorum else "waiting", "reason": "quorum_reached" if ready_count >= quorum else "quorum_not_reached", "quorum": quorum}
    if wait_policy in {"wait_any_upstream_completed", "fire_and_continue"} or join_policy == "any_success":
        if ready_count >= 1:
            return {**base, "decision": "ready", "reason": "any_incoming_edge_ready"}
        if failed_count and not pending_count:
            return {**base, "decision": "blocked", "reason": "all_available_incoming_edges_failed"}
        return {**base, "decision": "waiting", "reason": "waiting_any_incoming_edge_ready"}
    if join_policy == "allow_partial_with_issues" and ready_count >= 1:
        return {**base, "decision": "ready", "reason": "partial_ready_with_issues"}
    if wait_policy == "manual_release":
        if ready_count == len(active_statuses):
            return {**base, "decision": "ready", "reason": "manual_release_ready"}
        return {**base, "decision": "waiting", "reason": "manual_release_pending"}
    if wait_policy in {"wait_required_contracts", "wait_handoff_ack", "wait_all_upstream_completed", ""}:
        if active_statuses and all(status == "ready" for status in active_statuses.values()):
            return {**base, "decision": "ready", "reason": "all_required_incoming_edges_ready"}
        return {**base, "decision": "waiting", "reason": "waiting_required_incoming_edges", "pending_count": pending_count}
    if active_statuses and all(status == "ready" for status in active_statuses.values()):
        return {**base, "decision": "ready", "reason": "all_incoming_edges_ready"}
    return {**base, "decision": "waiting", "reason": "unsupported_policy_waiting"}


def _is_inactive_revision_edge(edge: dict[str, Any]) -> bool:
    edge_type = str(edge.get("edge_type") or "").strip()
    semantic_role = str(edge.get("semantic_role") or "").strip()
    scheduler_role = str(edge.get("scheduler_role") or "").strip()
    edge_id = str(edge.get("edge_id") or "").strip()
    return bool(
        edge_type == "revision_request"
        or semantic_role == "revision"
        or scheduler_role == "conditional_dependency"
        or ".revision." in edge_id
        or edge_id.startswith("edge.revision.")
    )


def _quorum_value(node: dict[str, Any]) -> int:
    for source in (
        dict(node.get("execution") or {}),
        dict(node.get("runtime_policy") or {}),
        dict(node.get("metadata") or {}),
    ):
        for key in ("quorum", "quorum_count", "required_success_count"):
            try:
                value = int(source.get(key) or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                return value
    return 0


def _active_loop_exit_node_ids(*, graph_config: GraphHarnessConfig, loop_state: dict[str, Any] | None) -> set[str]:
    frames = dict(dict(loop_state or {}).get("frames") or {})
    if not frames:
        return set()
    exit_ids: set[str] = set()
    for raw_frame in graph_config.loop_frames:
        configured = dict(raw_frame or {})
        frame_id = str(configured.get("frame_id") or configured.get("scope_id") or "").strip()
        frame = dict(frames.get(frame_id) or {})
        if str(frame.get("status") or "") != "active":
            continue
        exit_id = str(frame.get("exit_node_id") or configured.get("exit_node_id") or "").strip()
        if exit_id:
            exit_ids.add(exit_id)
    return exit_ids


def _closed_loop_scope_node_ids(*, graph_config: GraphHarnessConfig, loop_state: dict[str, Any] | None) -> set[str]:
    frames = dict(dict(loop_state or {}).get("frames") or {})
    if not frames:
        return set()
    closed_ids: set[str] = set()
    for raw_frame in graph_config.loop_frames:
        configured = dict(raw_frame or {})
        frame_id = str(configured.get("frame_id") or configured.get("scope_id") or "").strip()
        frame = dict(frames.get(frame_id) or {})
        if str(frame.get("status") or "active") == "active":
            continue
        for item in list(frame.get("scope_node_ids") or configured.get("scope_node_ids") or []):
            node_id = str(item or "").strip()
            if node_id:
                closed_ids.add(node_id)
    return closed_ids
