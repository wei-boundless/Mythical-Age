from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import GraphHarnessConfig, GraphLoopState, GraphNodeWorkOrder


@dataclass(frozen=True, slots=True)
class GraphResumeResult:
    graph_run_id: str
    resumed: bool
    reason: str
    loop_state: GraphLoopState | None
    checkpoint: dict[str, Any]
    active_work_orders: tuple[dict[str, Any], ...] = ()
    node_work_orders: tuple[GraphNodeWorkOrder, ...] = ()
    events: tuple[dict[str, Any], ...] = ()
    authority: str = "harness.graph_resume_result"

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "graph_run_id": self.graph_run_id,
            "resumed": self.resumed,
            "reason": self.reason,
            "graph_loop_state": self.loop_state.to_dict() if self.loop_state is not None else {},
            "checkpoint": dict(self.checkpoint),
            "active_work_orders": [dict(item) for item in self.active_work_orders],
            "node_work_orders": [item.to_dict() for item in self.node_work_orders],
            "events": [dict(item) for item in self.events],
        }


class GraphResumeService:
    """Resume graph runs from checkpointed GraphLoopState.

    Resume verifies the immutable GraphHarnessConfig identity and delegates state
    progression back to GraphLoop. It does not compile graphs or inspect editor
    drafts.
    """

    def __init__(self, *, graph_loop: Any) -> None:
        self._graph_loop = graph_loop

    def resume(
        self,
        *,
        graph_config: GraphHarnessConfig,
        graph_run_id: str,
        dispatch_ready: bool = True,
        max_requests: int | None = None,
    ) -> GraphResumeResult:
        checkpoint = self._graph_loop.get_latest_checkpoint(graph_run_id)
        if checkpoint is None:
            raise ValueError(f"Graph checkpoint not found: {graph_run_id}")
        state = self._graph_loop.get_state(graph_run_id)
        if state is None:
            raise ValueError(f"GraphLoopState not found: {graph_run_id}")
        if state.config_id != graph_config.config_id:
            raise ValueError("Graph resume config_id mismatch")
        if state.config_hash != graph_config.content_hash:
            raise ValueError("Graph resume config_hash mismatch")
        active = _active_work_orders_from_state(state)
        if state.status in {"completed", "failed"}:
            return GraphResumeResult(
                graph_run_id=graph_run_id,
                resumed=True,
                reason=f"terminal:{state.status}",
                loop_state=state,
                checkpoint=checkpoint.to_dict(),
                active_work_orders=active,
            )
        if active:
            return GraphResumeResult(
                graph_run_id=graph_run_id,
                resumed=True,
                reason="active_work_orders_reconnected",
                loop_state=state,
                checkpoint=checkpoint.to_dict(),
                active_work_orders=active,
            )
        if state.status == "blocked" and dispatch_ready:
            blocked = _blocked_replay_node_ids(state)
            if blocked:
                replay = self._graph_loop.requeue_blocked_nodes_and_checkpoint(
                    state=state,
                    node_ids=blocked,
                )
                dispatch = self._graph_loop.dispatch_ready_and_checkpoint(
                    graph_config=graph_config,
                    graph_run_id=graph_run_id,
                    max_requests=max_requests,
                )
                return GraphResumeResult(
                    graph_run_id=graph_run_id,
                    resumed=True,
                    reason="blocked_nodes_requeued",
                    loop_state=dispatch.loop_state,
                    checkpoint=dict(dispatch.checkpoint),
                    active_work_orders=_active_work_orders_from_state(dispatch.loop_state),
                    node_work_orders=dispatch.node_work_orders,
                    events=tuple([*replay.events, *dispatch.events]),
                )
        if not dispatch_ready:
            return GraphResumeResult(
                graph_run_id=graph_run_id,
                resumed=True,
                reason="checkpoint_loaded",
                loop_state=state,
                checkpoint=checkpoint.to_dict(),
                active_work_orders=active,
            )
        dispatch = self._graph_loop.dispatch_ready_and_checkpoint(
            graph_config=graph_config,
            graph_run_id=graph_run_id,
            max_requests=max_requests,
        )
        return GraphResumeResult(
            graph_run_id=graph_run_id,
            resumed=True,
            reason="ready_nodes_dispatched",
            loop_state=dispatch.loop_state,
            checkpoint=dict(dispatch.checkpoint),
            active_work_orders=_active_work_orders_from_state(dispatch.loop_state),
            node_work_orders=dispatch.node_work_orders,
            events=dispatch.events,
        )


def _active_work_orders_from_state(state: GraphLoopState) -> tuple[dict[str, Any], ...]:
    active = dict(state.active_work_orders or {})
    index = dict(state.work_order_index or {})
    result: list[dict[str, Any]] = []
    for node_id, work_order_id in active.items():
        payload = dict(index.get(str(work_order_id)) or {})
        if not payload:
            payload = {"node_id": str(node_id), "work_order_id": str(work_order_id)}
        result.append(payload)
    return tuple(result)


def _blocked_replay_node_ids(state: GraphLoopState) -> tuple[str, ...]:
    node_states = dict(state.node_states or {})
    return tuple(
        node_id
        for node_id in state.blocked_node_ids
        if str(dict(node_states.get(node_id) or {}).get("status") or "") == "blocked"
    )
