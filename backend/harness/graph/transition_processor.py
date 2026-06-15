from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from task_system.runtime_semantics.review_gate_verdict import (
    extract_review_verdict,
    review_verdict_is_rejected,
)

from .edge_contracts import edge_contract_or_projection
from .flow_edges import build_outbound_flow_edges
from .flow_packet import build_flow_packet, edge_delivers_flow_packet
from .language import REVISION_EDGE_TYPES
from .models import (
    GraphHarnessConfig,
    GraphLoopState,
    GraphTransitionInput,
    GraphTransitionPlan,
    NodeResultEnvelope,
)
from .runtime_objects import flow_packet_summary, store_flow_packet
from .scheduler_view import build_scheduler_view


@dataclass(frozen=True, slots=True)
class GraphTransitionProcessor:
    services: Any | None = None
    authority: str = "harness.graph.transition_processor"

    def plan(
        self,
        *,
        graph_config: GraphHarnessConfig,
        state: GraphLoopState,
        trigger: GraphTransitionInput,
    ) -> GraphTransitionPlan:
        if trigger.trigger_type == "node_result":
            return self._plan_node_result(graph_config=graph_config, state=state, trigger=trigger)
        if trigger.trigger_type in {"human_gate_decision", "human_edge_decision"}:
            return self._plan_node_result(graph_config=graph_config, state=state, trigger=trigger)
        return GraphTransitionPlan(
            blocked_reasons=(
                {
                    "code": "unsupported_transition_trigger",
                    "trigger_type": trigger.trigger_type,
                    "authority": self.authority,
                },
            ),
            diagnostics={"authority": self.authority},
        )

    def _plan_node_result(
        self,
        *,
        graph_config: GraphHarnessConfig,
        state: GraphLoopState,
        trigger: GraphTransitionInput,
    ) -> GraphTransitionPlan:
        payload = dict(trigger.payload or {})
        result_payload = dict(payload.get("result") or {})
        result = NodeResultEnvelope.from_dict(result_payload)
        result_ref = str(payload.get("result_ref") or "").strip()
        edge_id_filter = str(payload.get("edge_id") or "").strip()
        if edge_id_filter:
            outgoing_edges = tuple(
                dict(edge)
                for edge in graph_config.edges
                if str(edge.get("edge_id") or "") == edge_id_filter
            )
        else:
            outgoing_edges = _outgoing_state_edges(graph_config, result.node_id)
        now = time.time()
        review_verdict = extract_review_verdict(result.handoff_summary)
        review_rejected = review_verdict_is_rejected(review_verdict)
        review_routes_revision = bool(review_verdict and any(_edge_is_revision(dict(edge)) for edge in outgoing_edges))
        edge_updates: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []

        for edge in outgoing_edges:
            edge_id = str(edge.get("edge_id") or "")
            if not edge_id:
                continue
            current_edge_state = dict(state.edge_states.get(edge_id) or {})
            is_revision_edge = _edge_is_revision(dict(edge))
            selected = result.status == "completed"
            reason = "source_result_completed"
            if selected and review_routes_revision:
                selected = is_revision_edge if review_rejected else not is_revision_edge
                reason = "review_verdict_selected" if selected else "review_verdict_skipped"
            elif result.status != "completed":
                reason = "source_result_failed"

            status = "ready" if selected else ("source_failed" if result.status != "completed" else "skipped")
            packet_summary = self._packet_summary(
                graph_config=graph_config,
                state=state,
                edge=edge,
                result=result,
                result_ref=result_ref,
                edge_state=current_edge_state,
                selected=selected,
                created_at=now,
            )
            edge_update = _edge_update_payload(
                graph_config=graph_config,
                edge=edge,
                result=result,
                result_ref=result_ref,
                trigger=trigger,
                status=status,
                reason=reason,
                packet_summary=packet_summary,
                current_edge_state=current_edge_state,
                review_verdict=review_verdict,
                review_rejected=review_rejected,
                is_revision_edge=is_revision_edge,
                updated_at=now,
            )
            edge_updates.append(edge_update)
            events.append(
                {
                    "event_type": "graph_edge_transition_planned",
                    "edge_id": edge_id,
                    "status": status,
                    "reason": reason,
                    "decision_ref": edge_update.get("decision_ref"),
                    "authority": self.authority,
                }
            )

        return GraphTransitionPlan(
            edge_updates=tuple(edge_updates),
            events=tuple(events),
            diagnostics={
                "authority": self.authority,
                "trigger_type": trigger.trigger_type,
                "result_id": result.result_id,
                "edge_update_count": len(edge_updates),
            },
        )

    def _packet_summary(
        self,
        *,
        graph_config: GraphHarnessConfig,
        state: GraphLoopState,
        edge: dict[str, Any],
        result: NodeResultEnvelope,
        result_ref: str,
        edge_state: dict[str, Any],
        selected: bool,
        created_at: float,
    ) -> dict[str, Any]:
        if not selected or not edge_delivers_flow_packet(edge, graph_config=graph_config):
            return {}
        packet = build_flow_packet(
            graph_config=graph_config,
            state=state,
            edge=edge,
            result=result,
            result_ref=result_ref,
            created_at=created_at,
        )
        packet_ref = store_flow_packet(self.services, packet) if self.services is not None else ""
        packet_summary = flow_packet_summary(packet, packet_ref=packet_ref)
        existing_packets = [
            dict(item)
            for item in list(edge_state.get("packet_refs") or [])
            if isinstance(item, dict) and str(item.get("packet_ref") or "")
        ]
        existing_packets.append(packet_summary)
        return {
            **packet_summary,
            "packet_refs": existing_packets,
        }


def apply_transition_plan_to_edge_states(
    *,
    edge_states: dict[str, dict[str, Any]],
    plan: GraphTransitionPlan,
) -> dict[str, dict[str, Any]]:
    next_states = {key: dict(value) for key, value in edge_states.items()}
    for update in plan.edge_updates:
        edge_id = str(dict(update).get("edge_id") or "")
        if edge_id:
            next_states[edge_id] = dict(update)
    return next_states


def _edge_update_payload(
    *,
    graph_config: GraphHarnessConfig,
    edge: dict[str, Any],
    result: NodeResultEnvelope,
    result_ref: str,
    trigger: GraphTransitionInput,
    status: str,
    reason: str,
    packet_summary: dict[str, Any],
    current_edge_state: dict[str, Any],
    review_verdict: str,
    review_rejected: bool,
    is_revision_edge: bool,
    updated_at: float,
) -> dict[str, Any]:
    edge_id = str(edge.get("edge_id") or "")
    payload = {
        **dict(current_edge_state),
        "edge_id": edge_id,
        "source_node_id": result.node_id,
        "target_node_id": str(edge.get("target_node_id") or ""),
        "status": status,
        "reason": reason,
        "decision_ref": _decision_ref(trigger=trigger, result=result, result_ref=result_ref),
        "source_result_ref": result_ref,
        "packet_persisted": bool(packet_summary),
        "review_verdict_gate": _drop_empty(
            {
                "verdict": review_verdict,
                "routed_to_revision": review_rejected,
                "edge_revision": is_revision_edge,
                "authority": "harness.graph.review_verdict_edge_gate",
            }
        ),
        "policy_snapshot": _policy_snapshot(graph_config=graph_config, edge=edge),
        "graph_clock_seq": trigger.graph_clock_seq,
        "updated_at": updated_at,
        "authority": "harness.graph.edge_state",
    }
    if packet_summary:
        payload["packet_refs"] = list(packet_summary.get("packet_refs") or [])
        payload["latest_packet_id"] = str(packet_summary.get("packet_id") or "")
        payload["latest_packet_ref"] = str(packet_summary.get("packet_ref") or "")
        payload["latest_packet"] = {
            key: value
            for key, value in packet_summary.items()
            if key != "packet_refs"
        }
    else:
        for key in ("packet_refs", "latest_packet_id", "latest_packet_ref", "latest_packet"):
            payload.pop(key, None)
    human_edge_decision = _human_edge_decision_state(dict(result.diagnostics.get("human_edge_decision") or {}))
    if human_edge_decision:
        payload["human_edge_decision"] = human_edge_decision
        payload["human_decision_ref"] = str(human_edge_decision.get("decision_id") or "")
    return payload


def _decision_ref(*, trigger: GraphTransitionInput, result: NodeResultEnvelope, result_ref: str) -> str:
    explicit = str(dict(trigger.payload or {}).get("decision_ref") or "").strip()
    if explicit:
        return explicit
    if result_ref:
        return result_ref
    return f"node_result:{result.result_id}"


def _policy_snapshot(*, graph_config: GraphHarnessConfig, edge: dict[str, Any]) -> dict[str, Any]:
    contract = edge_contract_or_projection(graph_config, edge)
    return _drop_empty(
        {
            "edge_id": str(edge.get("edge_id") or ""),
            "scheduler": dict(contract.get("scheduler") or {}),
            "transition_policy": dict(contract.get("transition_policy") or dict(dict(edge.get("metadata") or {}).get("transition_policy") or {})),
            "readiness_policy": dict(contract.get("readiness_policy") or dict(dict(edge.get("metadata") or {}).get("readiness_policy") or {})),
            "failure": dict(contract.get("failure") or {}),
            "human_control": dict(contract.get("human_control") or {}),
            "authority": "harness.graph.transition_processor.policy_snapshot",
        }
    )


def _outgoing_dependency_edges(graph_config: GraphHarnessConfig, node_id: str) -> tuple[dict[str, Any], ...]:
    source = str(node_id or "")
    return tuple(
        dict(edge)
        for edge in build_scheduler_view(graph_config).dependency_edges
        if str(edge.get("source_node_id") or "") == source
    )


def _outgoing_state_edges(graph_config: GraphHarnessConfig, node_id: str) -> tuple[dict[str, Any], ...]:
    source = str(node_id or "")
    scheduler_edge_ids = {str(edge.get("edge_id") or "") for edge in _outgoing_dependency_edges(graph_config, source)}
    flow_edge_ids = {str(edge.get("edge_id") or "") for edge in build_outbound_flow_edges(graph_config, source)}
    edges: list[dict[str, Any]] = []
    for edge in graph_config.edges:
        payload = dict(edge)
        if str(payload.get("source_node_id") or "") != source:
            continue
        edge_id = str(payload.get("edge_id") or "")
        if edge_id in scheduler_edge_ids or edge_id in flow_edge_ids:
            edges.append(payload)
    return tuple(edges)


def _edge_is_revision(edge: dict[str, Any]) -> bool:
    edge_type = str(edge.get("edge_type") or "").strip()
    semantic_role = str(edge.get("semantic_role") or "").strip()
    return edge_type in REVISION_EDGE_TYPES or semantic_role == "revision"


def _human_edge_decision_state(decision: dict[str, Any]) -> dict[str, Any]:
    if not decision:
        return {}
    return {
        "decision_id": str(decision.get("decision_id") or ""),
        "decision": str(decision.get("decision") or ""),
        "edge_id": str(decision.get("edge_id") or ""),
        "source_node_id": str(decision.get("source_node_id") or ""),
        "target_node_id": str(decision.get("target_node_id") or ""),
        "authority": "harness.graph.human_edge_decision.state_marker",
    }


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}
