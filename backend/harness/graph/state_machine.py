from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .models import GraphHarnessConfig, GraphLoopState
from .scheduler_view import build_scheduler_view, is_executable_node


@dataclass(frozen=True, slots=True)
class GraphStatusSnapshot:
    status: str
    terminal_reason: str
    ready_node_ids: tuple[str, ...]
    running_node_ids: tuple[str, ...]
    completed_node_ids: tuple[str, ...]
    failed_node_ids: tuple[str, ...]
    blocked_node_ids: tuple[str, ...]
    waiting_human_node_ids: tuple[str, ...]
    terminal_result_status: str = ""
    authority: str = "harness.graph.state_machine.status_snapshot"


class GraphStateMachine:
    """Owns graph state classification and topology-derived readiness."""

    authority = "harness.graph.state_machine"

    def initial_node_states(self, graph_config: GraphHarnessConfig) -> dict[str, dict[str, Any]]:
        start_ids = set(self.start_node_ids(graph_config))
        now = time.time()
        return {
            str(node.get("node_id") or ""): {
                "node_id": str(node.get("node_id") or ""),
                "status": self.initial_node_status(node, start_ids=start_ids),
                "executor_type": str(dict(node.get("executor") or {}).get("executor_type") or "agent"),
                "created_at": now,
                "updated_at": now,
            }
            for node in graph_config.nodes
            if str(node.get("node_id") or "")
        }

    def initial_edge_states(self, graph_config: GraphHarnessConfig) -> dict[str, dict[str, Any]]:
        edge_protocol_index = dict(dict(graph_config.contracts or {}).get("edge_protocol_index") or {})
        edge_contract_index = dict(dict(graph_config.contracts or {}).get("edge_contract_index") or {})
        return {
            str(edge.get("edge_id") or ""): _initial_edge_state(
                edge=edge,
                edge_protocol_index=edge_protocol_index,
                edge_contract_index=edge_contract_index,
            )
            for edge in graph_config.edges
            if str(edge.get("edge_id") or "")
        }

    def initial_node_status(self, node: dict[str, Any], *, start_ids: set[str]) -> str:
        node_id = str(node.get("node_id") or "")
        if not is_executable_node(node):
            return "resource"
        return "ready" if node_id in start_ids else "pending"

    def ready_nodes(
        self,
        *,
        graph_config: GraphHarnessConfig,
        node_states: dict[str, dict[str, Any]],
        loop_state: dict[str, Any] | None = None,
    ) -> tuple[str, ...]:
        ready: list[str] = []
        scheduler_view = build_scheduler_view(graph_config)
        executable_ids = set(scheduler_view.executable_node_ids)
        gated_exit_ids = _active_loop_exit_node_ids(graph_config=graph_config, loop_state=loop_state)
        for node in graph_config.nodes:
            node_id = str(node.get("node_id") or "")
            if node_id not in executable_ids:
                continue
            if node_id in gated_exit_ids:
                continue
            status = str(dict(node_states.get(node_id) or {}).get("status") or "")
            if status == "ready":
                ready.append(node_id)
                continue
            if status not in {"pending", "blocked"}:
                continue
            upstream = self.upstream_node_ids(graph_config, node_id)
            if upstream and all(str(dict(node_states.get(item) or {}).get("status") or "") == "completed" for item in upstream):
                ready.append(node_id)
        return tuple(dict.fromkeys(item for item in ready if item))

    def blocked_nodes(
        self,
        *,
        graph_config: GraphHarnessConfig,
        node_states: dict[str, dict[str, Any]],
        loop_state: dict[str, Any] | None = None,
    ) -> tuple[str, ...]:
        return tuple(
            node_id
            for node_id, payload in node_states.items()
            if str(payload.get("status") or "") in {"blocked", "waiting_human_gate"}
        )

    def status_snapshot(
        self,
        *,
        graph_config: GraphHarnessConfig,
        node_states: dict[str, dict[str, Any]],
        active_work_orders: dict[str, str] | None = None,
        loop_state: dict[str, Any] | None = None,
        graph_result_already_terminal: bool = False,
    ) -> GraphStatusSnapshot:
        ready = () if graph_result_already_terminal else self.ready_nodes(graph_config=graph_config, node_states=node_states, loop_state=loop_state)
        running = tuple(
            dict.fromkeys(
                [
                    *_nodes_with_status(node_states, "running"),
                    *(str(node_id) for node_id in dict(active_work_orders or {}) if str(node_id)),
                ]
            )
        )
        completed = _nodes_with_status(node_states, "completed")
        failed = _nodes_with_status(node_states, "failed")
        waiting_human = _nodes_with_status(node_states, "waiting_human_gate")
        blocked = tuple(
            dict.fromkeys(
                [
                    *self.blocked_nodes(graph_config=graph_config, node_states=node_states, loop_state=loop_state),
                ]
            )
        )
        terminal_ids = set(self.terminal_node_ids(graph_config))
        executable_ids = tuple(build_scheduler_view(graph_config).executable_node_ids)
        if waiting_human:
            if running:
                return GraphStatusSnapshot("running", f"waiting_human_gate_pending_active:{waiting_human[0]}", (), running, completed, failed, blocked, waiting_human)
            return GraphStatusSnapshot("waiting_human_gate", f"waiting_human_gate:{waiting_human[0]}", ready, running, completed, failed, blocked, waiting_human)
        if _nodes_with_status(node_states, "blocked"):
            first = _nodes_with_status(node_states, "blocked")[0]
            if running:
                return GraphStatusSnapshot("running", f"node_blocked_pending_active:{first}", (), running, completed, failed, blocked, waiting_human)
            return GraphStatusSnapshot("blocked", f"node_blocked:{first}", ready, running, completed, failed, blocked, waiting_human)
        if failed:
            if running:
                return GraphStatusSnapshot("running", f"node_failed_pending_active:{failed[0]}", (), running, completed, failed, blocked, waiting_human)
            return GraphStatusSnapshot("failed", f"node_failed:{failed[0]}", (), running, completed, failed, blocked, waiting_human, terminal_result_status="failed")
        if terminal_ids and terminal_ids.issubset(set(completed)):
            if running:
                return GraphStatusSnapshot("running", "terminal_nodes_completed_pending_active", (), running, completed, failed, blocked, waiting_human)
            return GraphStatusSnapshot("completed", "terminal_nodes_completed", (), running, completed, failed, blocked, waiting_human, terminal_result_status="completed")
        if executable_ids and len(completed) == len(executable_ids):
            if running:
                return GraphStatusSnapshot("running", "all_executable_nodes_completed_pending_active", (), running, completed, failed, blocked, waiting_human)
            return GraphStatusSnapshot("completed", "all_executable_nodes_completed", (), running, completed, failed, blocked, waiting_human, terminal_result_status="completed")
        return GraphStatusSnapshot("running", "", ready, running, completed, failed, blocked, waiting_human)

    def validate(self, state: GraphLoopState) -> None:
        active = dict(state.active_work_orders or {})
        if state.status in {"blocked", "waiting_human_gate", "completed", "failed"} and active:
            raise ValueError(f"GraphLoopState invariant violated: {state.status} state cannot keep active work orders")

    def start_node_ids(self, graph_config: GraphHarnessConfig) -> tuple[str, ...]:
        return build_scheduler_view(graph_config).start_node_ids

    def terminal_node_ids(self, graph_config: GraphHarnessConfig) -> tuple[str, ...]:
        return build_scheduler_view(graph_config).terminal_node_ids

    def upstream_node_ids(self, graph_config: GraphHarnessConfig, node_id: str) -> tuple[str, ...]:
        return tuple(
            str(edge.get("source_node_id") or "")
            for edge in build_scheduler_view(graph_config).dependency_edges
            if str(edge.get("target_node_id") or "") == node_id and str(edge.get("source_node_id") or "")
        )


def _nodes_with_status(node_states: dict[str, dict[str, Any]], status: str) -> tuple[str, ...]:
    return tuple(node_id for node_id, payload in node_states.items() if str(payload.get("status") or "") == status)


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


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


def _initial_edge_state(
    *,
    edge: dict[str, Any],
    edge_protocol_index: dict[str, Any],
    edge_contract_index: dict[str, Any],
) -> dict[str, Any]:
    edge_id = str(edge.get("edge_id") or "")
    contract = dict(edge_contract_index.get(edge_id) or {})
    reliability = dict(contract.get("reliability") or {})
    protocol = dict(contract.get("protocol") or {})
    legacy_projection = dict(contract.get("legacy_protocol_projection") or edge_protocol_index.get(edge_id) or edge)
    return _drop_empty(
        {
            "edge_id": edge_id,
            "source_node_id": str(edge.get("source_node_id") or ""),
            "target_node_id": str(edge.get("target_node_id") or ""),
            "status": "pending",
            "ack_required": bool(reliability.get("ack_required", legacy_projection.get("ack_required", True))),
            "ack_policy": str(reliability.get("ack_policy") or legacy_projection.get("ack_policy") or ""),
            "protocol_kind": str(protocol.get("kind") or ""),
            "protocol_ref": str(contract.get("contract_id") or edge_id)
            if contract or edge_id in edge_protocol_index
            else "",
            "contract_authority": str(contract.get("authority") or ""),
        }
    )
