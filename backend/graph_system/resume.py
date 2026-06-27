from __future__ import annotations

from dataclasses import dataclass, replace
import time
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
        recovered = _recover_stale_active_graph_node_executors(
            services=self._services,
            state=state,
            active_work_orders=active,
        )
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


def _recover_stale_active_graph_node_executors(
    *,
    services: Any | None,
    state: GraphLoopState,
    active_work_orders: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    if services is None or not active_work_orders:
        return ()
    state_index = getattr(services, "state_index", None)
    event_log = getattr(services, "event_log", None)
    monitor_projector = getattr(services, "monitor_projector", None)
    if state_index is None or event_log is None:
        return ()
    recovered: list[dict[str, Any]] = []
    for order in active_work_orders:
        work_order_id = str(order.get("work_order_id") or "")
        node_id = str(order.get("node_id") or "")
        if not work_order_id or not node_id:
            continue
        task_run = _find_graph_node_task_run(
            state_index,
            graph_run_id=state.graph_run_id,
            work_order_id=work_order_id,
        )
        if task_run is None or not _is_stale_running_graph_node_task(
            task_run,
            monitor_projector=monitor_projector,
        ):
            continue
        event = event_log.append(
            task_run.task_run_id,
            "graph_node_executor_recovered_after_runtime_restart",
            payload={
                "task_run_id": task_run.task_run_id,
                "graph_run_id": state.graph_run_id,
                "node_id": node_id,
                "work_order_id": work_order_id,
                "previous_status": str(getattr(task_run, "status", "") or ""),
                "previous_executor_status": str(dict(getattr(task_run, "diagnostics", {}) or {}).get("executor_status") or ""),
            },
            refs={
                "task_run_ref": task_run.task_run_id,
                "graph_run_ref": state.graph_run_id,
                "work_order_ref": work_order_id,
                "node_ref": node_id,
            },
        )
        diagnostics = {
            **_strip_terminal_diagnostics(dict(getattr(task_run, "diagnostics", {}) or {})),
            "executor_status": "waiting_executor",
            "latest_step": "graph_node_executor_recovered_after_runtime_restart",
            "latest_step_status": "waiting_executor",
            "latest_step_summary": "连接已恢复，图节点执行器已恢复为可继续状态。",
            "recoverable_error": {
                "error_code": "task_executor_interrupted_by_runtime_restart",
                "retryable": True,
                "user_message": "连接已恢复，图节点可以继续执行。",
            },
            "recovery_action": "rerun_task_executor",
        }
        state_index.upsert_task_run(
            replace(
                task_run,
                status="waiting_executor",
                updated_at=float(getattr(event, "created_at", 0.0) or time.time()),
                latest_event_offset=int(getattr(event, "offset", -1) or -1),
                terminal_reason="waiting_executor",
                diagnostics=diagnostics,
            )
        )
        recovered.append(event.to_dict() if hasattr(event, "to_dict") else dict(event))
    return tuple(recovered)


def _find_graph_node_task_run(
    state_index: Any,
    *,
    graph_run_id: str,
    work_order_id: str,
) -> Any | None:
    for task_run in list(state_index.list_task_runs()):
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
        origin = diagnostics.get("origin") if isinstance(diagnostics.get("origin"), dict) else {}
        origin_kind = str(diagnostics.get("origin_kind") or dict(origin or {}).get("origin_kind") or "").strip()
        if origin_kind != "graph_node_assigned":
            continue
        if str(diagnostics.get("graph_run_id") or dict(origin or {}).get("graph_run_id") or "") != graph_run_id:
            continue
        if str(diagnostics.get("graph_work_order_id") or dict(origin or {}).get("origin_ref") or "") != work_order_id:
            continue
        return task_run
    return None


def _is_stale_running_graph_node_task(task_run: Any, *, monitor_projector: Any) -> bool:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    if str(getattr(task_run, "status", "") or "") != "running":
        return False
    if str(diagnostics.get("executor_status") or "") not in {"scheduled", "running"}:
        return False
    if monitor_projector is None or not hasattr(monitor_projector, "project_task_run"):
        return False
    try:
        monitor = monitor_projector.project_task_run(task_run, now=time.time())
    except Exception:
        return False
    return bool(monitor.get("stale") or monitor.get("lifecycle") == "stale")


def _strip_terminal_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    blocked = {
        "executor_status",
        "active_packet_ref",
        "completion_state",
        "terminal_reason",
        "error",
        "recoverable_error",
        "recovery_action",
    }
    return {key: value for key, value in diagnostics.items() if key not in blocked}


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
        "task_executor_interrupted_by_runtime_restart",
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
        postprocess_reasons = {
            str(item.get("reason") or "")
            for item in list(error.get("postprocess_errors") or [])
            if isinstance(item, dict)
        }
        if recoverable_error and bool(recoverable_error.get("retryable", True)):
            targets.append(node_id)
        elif reason in {"task_run_executor_already_running", "model_call_recovery_required", "quality_gate_failed"}:
            targets.append(node_id)
        elif any(item.startswith("chapter_progress_receipt_") for item in postprocess_reasons):
            targets.append(node_id)
    return tuple(dict.fromkeys(targets))
