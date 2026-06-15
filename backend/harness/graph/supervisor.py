from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .models import GraphHarnessConfig, GraphLoopState
from .state_machine import GraphStateMachine


@dataclass(frozen=True, slots=True)
class SupervisorObservation:
    observation_id: str
    graph_run_id: str
    graph_id: str
    status: str
    health_status: dict[str, Any]
    risk_alerts: tuple[dict[str, Any], ...] = ()
    maintenance_action_candidates: tuple[dict[str, Any], ...] = ()
    created_at: float = 0.0
    authority: str = "harness.graph.supervisor_observation"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["risk_alerts"] = [dict(item) for item in self.risk_alerts]
        payload["maintenance_action_candidates"] = [dict(item) for item in self.maintenance_action_candidates]
        return payload


class GraphSupervisor:
    authority = "__supervisor__"

    def observe(self, *, graph_config: GraphHarnessConfig, state: GraphLoopState) -> SupervisorObservation:
        snapshot = GraphStateMachine().status_snapshot(
            graph_config=graph_config,
            node_states=dict(state.node_states or {}),
            edge_states=dict(state.edge_states or {}),
            active_work_orders=dict(state.active_work_orders or {}),
            loop_state=dict(state.loop_state or {}),
            graph_result_already_terminal=state.status in {"completed", "failed"},
        )
        risks = _risk_alerts(graph_config=graph_config, state=state, snapshot=snapshot)
        candidates = _maintenance_candidates(graph_config=graph_config, state=state, risks=risks)
        now = time.time()
        return SupervisorObservation(
            observation_id=f"gsup:{state.graph_run_id}:{int(now * 1000)}",
            graph_run_id=state.graph_run_id,
            graph_id=graph_config.graph_id,
            status=snapshot.status,
            health_status={
                "status": snapshot.status,
                "terminal_reason": snapshot.terminal_reason,
                "ready_node_ids": list(snapshot.ready_node_ids),
                "running_node_ids": list(snapshot.running_node_ids),
                "completed_node_ids": list(snapshot.completed_node_ids),
                "failed_node_ids": list(snapshot.failed_node_ids),
                "blocked_node_ids": list(snapshot.blocked_node_ids),
                "waiting_human_node_ids": list(snapshot.waiting_human_node_ids),
                "edge_count": len(graph_config.edges),
                "node_count": len(graph_config.nodes),
                "authority": "harness.graph.supervisor_health_status",
            },
            risk_alerts=tuple(risks),
            maintenance_action_candidates=tuple(candidates),
            created_at=now,
        )


def _risk_alerts(*, graph_config: GraphHarnessConfig, state: GraphLoopState, snapshot: Any) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for node_id in snapshot.blocked_node_ids:
        alerts.append(
            {
                "code": "node_blocked",
                "severity": "warning",
                "node_id": node_id,
                "message": f"节点阻塞：{node_id}",
                "authority": "harness.graph.supervisor_risk_alert",
            }
        )
    for node_id in snapshot.failed_node_ids:
        alerts.append(
            {
                "code": "node_failed",
                "severity": "error",
                "node_id": node_id,
                "message": f"节点失败：{node_id}",
                "authority": "harness.graph.supervisor_risk_alert",
            }
        )
    for edge in graph_config.edges:
        edge_id = str(edge.get("edge_id") or "")
        if not edge_id:
            continue
        edge_state = dict(state.edge_states.get(edge_id) or {})
        if str(edge_state.get("status") or "") == "accepted" and bool(edge_state.get("ack_required")) and not str(edge_state.get("ack_at") or ""):
            alerts.append(
                {
                    "code": "edge_ack_pending",
                    "severity": "info",
                    "edge_id": edge_id,
                    "message": f"边等待 ack：{edge_id}",
                    "authority": "harness.graph.supervisor_risk_alert",
                }
            )
    return alerts


def _maintenance_candidates(*, graph_config: GraphHarnessConfig, state: GraphLoopState, risks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    maintenance_contract = dict(dict(graph_config.contracts or {}).get("maintenance_contract") or {})
    auto_actions = {str(item) for item in list(maintenance_contract.get("auto_actions") or [])}
    candidates: list[dict[str, Any]] = []
    for risk in risks:
        code = str(risk.get("code") or "")
        if code == "node_blocked" and "mark_recoverable_blocked_node" in auto_actions:
            candidates.append(
                {
                    "action": "mark_recoverable_blocked_node",
                    "node_id": str(risk.get("node_id") or ""),
                    "risk_code": code,
                    "requires_human_approval": False,
                    "authority": "harness.graph.maintenance_action_candidate",
                }
            )
        elif code == "node_failed":
            candidates.append(
                {
                    "action": "requeue_failed_node",
                    "node_id": str(risk.get("node_id") or ""),
                    "risk_code": code,
                    "requires_human_approval": True,
                    "authority": "harness.graph.maintenance_action_candidate",
                }
            )
    return candidates
