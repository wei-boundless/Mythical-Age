from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .loop import assert_graph_config_compatible_with_state
from .models import ExecutableGraphConfig, GraphLoopState, GraphNodeWorkOrder


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
    authority: str = "graph_system_resume_result"

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

    Resume verifies the immutable ExecutableGraphConfig identity and hands state
    progression back to GraphLoop. It does not compile graphs or inspect editor
    drafts.
    """

    def __init__(self, *, graph_loop: Any, services: Any | None = None) -> None:
        self._graph_loop = graph_loop
        self._services = services

    def resume(
        self,
        *,
        graph_config: ExecutableGraphConfig,
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
        assert_graph_config_compatible_with_state(graph_config=graph_config, state=state)
        _assert_canonical_edge_states_present(graph_config=graph_config, state=state)
        active = _active_work_orders_from_state(state)
        recovered: tuple[dict[str, Any], ...] = ()
        if state.status == "failed" and dispatch_ready:
            recoverable_failed = _recoverable_failed_node_ids(state, services=self._services)
            if recoverable_failed:
                replay = self._graph_loop.requeue_recoverable_failed_nodes_and_checkpoint(
                    state=state,
                    node_ids=recoverable_failed,
                )
                dispatch = self._graph_loop.dispatch_ready_and_checkpoint(
                    graph_config=graph_config,
                    graph_run_id=graph_run_id,
                    max_requests=max_requests,
                )
                return GraphResumeResult(
                    graph_run_id=graph_run_id,
                    resumed=True,
                    reason="recoverable_failed_nodes_requeued",
                    loop_state=dispatch.loop_state,
                    checkpoint=dict(dispatch.checkpoint),
                    active_work_orders=_active_work_orders_from_state(dispatch.loop_state),
                    node_work_orders=dispatch.node_work_orders,
                    events=tuple([*recovered, *replay.events, *dispatch.events]),
                )
        if state.status in {"completed", "failed"}:
            return GraphResumeResult(
                graph_run_id=graph_run_id,
                resumed=True,
                reason=f"terminal:{state.status}",
                loop_state=state,
                checkpoint=checkpoint.to_dict(),
                active_work_orders=active,
                events=tuple(recovered),
            )
        if active:
            reset = self._graph_loop.reset_source_failed_edges_for_nodes_and_checkpoint(
                state=state,
                node_ids=tuple(str(item.get("node_id") or "") for item in active),
            )
            state = reset.loop_state
            checkpoint = dict(reset.checkpoint)
            return GraphResumeResult(
                graph_run_id=graph_run_id,
                resumed=True,
                reason="active_work_orders_reconnected",
                loop_state=state,
                checkpoint=checkpoint,
                active_work_orders=active,
                events=tuple([*recovered, *reset.events]),
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
            return GraphResumeResult(
                graph_run_id=graph_run_id,
                resumed=True,
                reason="blocked_not_recoverable",
                loop_state=state,
                checkpoint=checkpoint.to_dict(),
                active_work_orders=active,
                events=tuple(recovered),
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


def _assert_canonical_edge_states_present(*, graph_config: ExecutableGraphConfig, state: GraphLoopState) -> None:
    expected_edge_ids = {
        str(edge.get("edge_id") or "").strip()
        for edge in graph_config.edges
        if str(edge.get("edge_id") or "").strip()
    }
    actual_edge_ids = {
        str(edge_id or "").strip()
        for edge_id in dict(state.edge_states or {})
        if str(edge_id or "").strip()
    }
    missing = sorted(expected_edge_ids - actual_edge_ids)
    if missing:
        raise ValueError(f"canonical_edge_state_missing: {missing}")


def _blocked_replay_node_ids(state: GraphLoopState) -> tuple[str, ...]:
    node_states = dict(state.node_states or {})
    return tuple(
        node_id
        for node_id in state.blocked_node_ids
        if _blocked_node_is_recoverable(dict(node_states.get(node_id) or {}), state=state)
    )


def _blocked_node_is_recoverable(node_state: dict[str, Any], *, state: GraphLoopState) -> bool:
    if str(node_state.get("status") or "") != "blocked":
        return False
    result_ref = str(node_state.get("result_ref") or "").strip()
    result = dict(dict(state.result_index or {}).get(str(node_state.get("node_id") or "")) or {})
    error = dict(result.get("error") or {})
    recoverable_error = dict(error.get("recoverable_error") or {})
    reason = str(error.get("reason") or node_state.get("blocked_reason") or state.terminal_reason or "").strip()
    if recoverable_error:
        return bool(recoverable_error.get("retryable", True))
    if reason == "quality_gate_failed":
        return True
    if reason in {
        "model_call_recovery_required",
        "task_execution_step_budget_exhausted",
        "task_execution_step_budget_exceeded",
        "waiting_executor",
        "task_run_executor_already_running",
        "model_action_protocol_repair_required",
    }:
        return True
    return False


def _recoverable_failed_node_ids(state: GraphLoopState, *, services: Any | None) -> tuple[str, ...]:
    if services is None:
        return ()
    result_loader = getattr(services, "runtime_objects", None)
    if result_loader is None:
        return ()
    targets: list[str] = []
    for node_id in tuple(state.failed_node_ids or ()):
        node_state = dict(dict(state.node_states or {}).get(node_id) or {})
        if str(node_state.get("status") or "") != "failed":
            continue
        result_ref = str(node_state.get("result_ref") or "")
        if not result_ref:
            continue
        payload = result_loader.get_object(result_ref)
        if not isinstance(payload, dict):
            continue
        error = dict(payload.get("error") or {})
        diagnostics = dict(payload.get("diagnostics") or {})
        executor_result = dict(diagnostics.get("executor_result") or {})
        reason = str(error.get("reason") or executor_result.get("error") or "")
        recoverable_error = dict(error.get("recoverable_error") or {})
        if recoverable_error and bool(recoverable_error.get("retryable", True)):
            targets.append(node_id)
        elif reason in {"task_run_executor_already_running", "model_call_recovery_required", "quality_gate_failed"}:
            targets.append(node_id)
        elif any(bool(item.get("resume_retryable") is True) for item in list(error.get("postprocess_errors") or []) if isinstance(item, dict)):
            targets.append(node_id)
    return tuple(dict.fromkeys(targets))
