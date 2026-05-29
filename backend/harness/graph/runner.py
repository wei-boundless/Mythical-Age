from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .models import GraphHarnessConfig, GraphLoopState, GraphNodeWorkOrder


_TERMINAL_STATUSES = {"completed", "failed", "blocked", "waiting_human_gate", "cancelled"}


@dataclass(frozen=True, slots=True)
class GraphRunRunnerResult:
    graph_run_id: str
    status: str
    terminal_reason: str = ""
    executed_work_order_count: int = 0
    accepted_result_count: int = 0
    dispatch_count: int = 0
    blocked_reason: str = ""
    budget_exhausted: bool = False
    loop_state: dict[str, Any] = field(default_factory=dict)
    graph_result: dict[str, Any] = field(default_factory=dict)
    events: tuple[dict[str, Any], ...] = ()
    authority: str = "harness.graph_run_runner"

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "graph_run_id": self.graph_run_id,
            "status": self.status,
            "terminal_reason": self.terminal_reason,
            "executed_work_order_count": self.executed_work_order_count,
            "accepted_result_count": self.accepted_result_count,
            "dispatch_count": self.dispatch_count,
            "blocked_reason": self.blocked_reason,
            "budget_exhausted": self.budget_exhausted,
            "graph_loop_state": dict(self.loop_state),
            "graph_result": dict(self.graph_result),
            "events": [dict(item) for item in self.events],
        }


class GraphRunRunner:
    """Execution pump for a single graph run.

    The runner does not schedule by itself and does not mutate graph state. It
    reconnects the current GraphLoopState, executes active work orders through
    the node executor path, then returns every result to GraphLoop.
    """

    def __init__(
        self,
        *,
        services: Any,
        graph_loop: Any,
        execute_work_order: Callable[..., Awaitable[dict[str, Any]]],
    ) -> None:
        self._services = services
        self._graph_loop = graph_loop
        self._execute_work_order = execute_work_order

    async def run_until_idle(
        self,
        *,
        graph_config: GraphHarnessConfig,
        graph_run_id: str,
        max_node_executions: int = 64,
        max_loop_iterations: int = 128,
        max_node_steps: int = 12,
        max_dispatches: int = 64,
        max_runtime_seconds: float = 0.0,
        max_dispatch_requests: int | None = None,
    ) -> GraphRunRunnerResult:
        graph_run_id = str(graph_run_id or "").strip()
        if not graph_run_id:
            raise ValueError("GraphRunRunner requires graph_run_id")
        _validate_graph_config_identity(graph_config)

        started_at = time.monotonic()
        max_node_executions = max(0, int(max_node_executions))
        max_loop_iterations = max(1, int(max_loop_iterations or 1))
        max_node_steps = max(1, int(max_node_steps or 1))
        max_dispatches = max(0, int(max_dispatches))
        max_runtime_seconds = max(0.0, float(max_runtime_seconds or 0.0))
        executed_count = 0
        accepted_count = 0
        dispatch_count = 0
        events: list[dict[str, Any]] = []
        graph_result: dict[str, Any] = {}

        state = self._load_locked_state(graph_config=graph_config, graph_run_id=graph_run_id)
        events.append(
            self._append_runner_event(
                state,
                "graph_run_runner_started",
                payload={
                    "graph_run_id": graph_run_id,
                    "graph_harness_config_id": graph_config.config_id,
                    "budget": {
                        "max_node_executions": max_node_executions,
                        "max_loop_iterations": max_loop_iterations,
                        "max_node_steps": max_node_steps,
                        "max_dispatches": max_dispatches,
                        "max_runtime_seconds": max_runtime_seconds,
                    },
                },
            )
        )

        for _iteration in range(1, max_loop_iterations + 1):
            state = self._load_locked_state(graph_config=graph_config, graph_run_id=graph_run_id)
            if state.status in _TERMINAL_STATUSES:
                return self._finish(
                    state=state,
                    status=state.status,
                    terminal_reason=state.terminal_reason or state.status,
                    executed_count=executed_count,
                    accepted_count=accepted_count,
                    dispatch_count=dispatch_count,
                    graph_result=graph_result,
                    events=events,
                )
            if executed_count >= max_node_executions:
                return self._finish(
                    state=state,
                    status="budget_exhausted",
                    terminal_reason="max_node_executions_exhausted",
                    executed_count=executed_count,
                    accepted_count=accepted_count,
                    dispatch_count=dispatch_count,
                    blocked_reason="max_node_executions_exhausted",
                    budget_exhausted=True,
                    graph_result=graph_result,
                    events=events,
                )
            if _runtime_budget_exhausted(started_at, max_runtime_seconds=max_runtime_seconds):
                return self._finish(
                    state=state,
                    status="budget_exhausted",
                    terminal_reason="max_runtime_seconds_exhausted",
                    executed_count=executed_count,
                    accepted_count=accepted_count,
                    dispatch_count=dispatch_count,
                    blocked_reason="max_runtime_seconds_exhausted",
                    budget_exhausted=True,
                    graph_result=graph_result,
                    events=events,
                )

            active_orders = _active_work_orders_from_state(state)
            if not active_orders:
                if not state.ready_node_ids:
                    return self._finish(
                        state=state,
                        status="idle",
                        terminal_reason=state.terminal_reason,
                        executed_count=executed_count,
                        accepted_count=accepted_count,
                        dispatch_count=dispatch_count,
                        blocked_reason="no_active_or_ready_work_orders",
                        graph_result=graph_result,
                        events=events,
                    )
                if dispatch_count >= max_dispatches:
                    return self._finish(
                        state=state,
                        status="budget_exhausted",
                        terminal_reason="max_dispatches_exhausted",
                        executed_count=executed_count,
                        accepted_count=accepted_count,
                        dispatch_count=dispatch_count,
                        blocked_reason="max_dispatches_exhausted",
                        budget_exhausted=True,
                        graph_result=graph_result,
                        events=events,
                    )
                dispatch = self._graph_loop.dispatch_ready_and_checkpoint(
                    graph_config=graph_config,
                    graph_run_id=graph_run_id,
                    max_requests=max_dispatch_requests,
                )
                dispatch_count += 1
                events.extend(dict(item) for item in dispatch.events)
                state = dispatch.loop_state
                active_orders = _active_work_orders_from_state(state)
                if not active_orders:
                    return self._finish(
                        state=state,
                        status="blocked",
                        terminal_reason="ready_nodes_not_dispatched",
                        executed_count=executed_count,
                        accepted_count=accepted_count,
                        dispatch_count=dispatch_count,
                        blocked_reason="ready_nodes_not_dispatched",
                        graph_result=graph_result,
                        events=events,
                    )

            progressed = False
            for order in active_orders:
                state = self._load_locked_state(graph_config=graph_config, graph_run_id=graph_run_id)
                if state.status in _TERMINAL_STATUSES:
                    return self._finish(
                        state=state,
                        status=state.status,
                        terminal_reason=state.terminal_reason or state.status,
                        executed_count=executed_count,
                        accepted_count=accepted_count,
                        dispatch_count=dispatch_count,
                        graph_result=graph_result,
                        events=events,
                    )
                if dict(state.active_work_orders or {}).get(order.node_id) != order.work_order_id:
                    continue
                if executed_count >= max_node_executions:
                    return self._finish(
                        state=state,
                        status="budget_exhausted",
                        terminal_reason="max_node_executions_exhausted",
                        executed_count=executed_count,
                        accepted_count=accepted_count,
                        dispatch_count=dispatch_count,
                        blocked_reason="max_node_executions_exhausted",
                        budget_exhausted=True,
                        graph_result=graph_result,
                        events=events,
                    )
                self._validate_work_order(state=state, graph_config=graph_config, work_order=order)
                execution = await self._execute_work_order(
                    graph_config=graph_config,
                    work_order=order,
                    max_steps=max_node_steps,
                    accept_result=True,
                )
                executed_count += 1
                events.extend(dict(item) for item in list(execution.get("events") or []) if isinstance(item, dict))
                self._validate_executor_origin(
                    graph_run_id=graph_run_id,
                    work_order=order,
                    execution=execution,
                )
                if not execution.get("accepted_result"):
                    return self._finish(
                        state=self._load_locked_state(graph_config=graph_config, graph_run_id=graph_run_id),
                        status="blocked",
                        terminal_reason="work_order_result_not_accepted",
                        executed_count=executed_count,
                        accepted_count=accepted_count,
                        dispatch_count=dispatch_count,
                        blocked_reason="work_order_result_not_accepted",
                        graph_result=graph_result,
                        events=events,
                    )
                accepted_count += 1
                progressed = True
                if isinstance(execution.get("graph_result"), dict) and execution.get("graph_result"):
                    graph_result = dict(execution["graph_result"])

            if not progressed:
                state = self._load_locked_state(graph_config=graph_config, graph_run_id=graph_run_id)
                return self._finish(
                    state=state,
                    status="blocked",
                    terminal_reason="active_work_orders_not_executable",
                    executed_count=executed_count,
                    accepted_count=accepted_count,
                    dispatch_count=dispatch_count,
                    blocked_reason="active_work_orders_not_executable",
                    graph_result=graph_result,
                    events=events,
                )

        state = self._load_locked_state(graph_config=graph_config, graph_run_id=graph_run_id)
        return self._finish(
            state=state,
            status="budget_exhausted",
            terminal_reason="max_loop_iterations_exhausted",
            executed_count=executed_count,
            accepted_count=accepted_count,
            dispatch_count=dispatch_count,
            blocked_reason="max_loop_iterations_exhausted",
            budget_exhausted=True,
            graph_result=graph_result,
            events=events,
        )

    def _load_locked_state(self, *, graph_config: GraphHarnessConfig, graph_run_id: str) -> GraphLoopState:
        state = self._graph_loop.get_state(graph_run_id)
        if state is None:
            raise ValueError(f"GraphLoopState not found: {graph_run_id}")
        if state.graph_run_id != graph_run_id:
            raise ValueError("GraphRunRunner graph_run_id mismatch")
        if state.config_id != graph_config.config_id:
            raise ValueError("GraphRunRunner config_id mismatch")
        if state.config_hash != graph_config.content_hash:
            raise ValueError("GraphRunRunner config_hash mismatch")
        return state

    def _validate_work_order(
        self,
        *,
        state: GraphLoopState,
        graph_config: GraphHarnessConfig,
        work_order: GraphNodeWorkOrder,
    ) -> None:
        if work_order.graph_run_id != state.graph_run_id:
            raise ValueError("GraphRunRunner work_order graph_run_id mismatch")
        if work_order.task_run_id != state.task_run_id:
            raise ValueError("GraphRunRunner work_order task_run_id mismatch")
        if work_order.config_id != graph_config.config_id:
            raise ValueError("GraphRunRunner work_order config_id mismatch")
        if work_order.config_hash != graph_config.content_hash:
            raise ValueError("GraphRunRunner work_order config_hash mismatch")

    def _validate_executor_origin(
        self,
        *,
        graph_run_id: str,
        work_order: GraphNodeWorkOrder,
        execution: dict[str, Any],
    ) -> None:
        task_run = dict(execution.get("node_executor_task_run") or {})
        if not task_run:
            return
        diagnostics = dict(task_run.get("diagnostics") or {})
        if str(diagnostics.get("origin_kind") or "") != "graph_node_assigned":
            raise ValueError("GraphRunRunner node executor TaskRun origin_kind mismatch")
        if str(diagnostics.get("graph_run_id") or "") != graph_run_id:
            raise ValueError("GraphRunRunner node executor TaskRun graph_run_id mismatch")
        if str(diagnostics.get("graph_work_order_id") or "") != work_order.work_order_id:
            raise ValueError("GraphRunRunner node executor TaskRun work_order_id mismatch")

    def _append_runner_event(
        self,
        state: GraphLoopState,
        event_type: str,
        *,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._services.event_log.append(
            state.task_run_id,
            event_type,
            payload={**dict(payload or {}), "authority": "harness.graph_run_runner"},
            refs={"graph_run_ref": state.graph_run_id, "graph_harness_config_ref": state.config_id},
        ).to_dict()

    def _finish(
        self,
        *,
        state: GraphLoopState,
        status: str,
        terminal_reason: str,
        executed_count: int,
        accepted_count: int,
        dispatch_count: int,
        events: list[dict[str, Any]],
        blocked_reason: str = "",
        budget_exhausted: bool = False,
        graph_result: dict[str, Any] | None = None,
    ) -> GraphRunRunnerResult:
        events.append(
            self._append_runner_event(
                state,
                "graph_run_runner_stopped",
                payload={
                    "graph_run_id": state.graph_run_id,
                    "status": status,
                    "terminal_reason": terminal_reason,
                    "blocked_reason": blocked_reason,
                    "budget_exhausted": budget_exhausted,
                    "executed_work_order_count": executed_count,
                    "accepted_result_count": accepted_count,
                    "dispatch_count": dispatch_count,
                },
            )
        )
        return GraphRunRunnerResult(
            graph_run_id=state.graph_run_id,
            status=status,
            terminal_reason=terminal_reason,
            executed_work_order_count=executed_count,
            accepted_result_count=accepted_count,
            dispatch_count=dispatch_count,
            blocked_reason=blocked_reason,
            budget_exhausted=budget_exhausted,
            loop_state=state.to_dict(),
            graph_result=dict(graph_result or {}),
            events=tuple(events),
        )


def _active_work_orders_from_state(state: GraphLoopState) -> tuple[GraphNodeWorkOrder, ...]:
    active = dict(state.active_work_orders or {})
    index = dict(state.work_order_index or {})
    orders: list[GraphNodeWorkOrder] = []
    for node_id, work_order_id in active.items():
        payload = dict(index.get(str(work_order_id)) or {})
        if not payload:
            raise ValueError(f"GraphNodeWorkOrder missing from work_order_index: {node_id}")
        order = GraphNodeWorkOrder.from_dict(payload)
        if order.node_id != str(node_id):
            raise ValueError("GraphNodeWorkOrder node_id does not match active_work_orders")
        orders.append(order)
    return tuple(orders)


def _validate_graph_config_identity(graph_config: GraphHarnessConfig) -> None:
    if graph_config.status != "published":
        raise ValueError("GraphRunRunner requires a published GraphHarnessConfig")
    expected_hash = graph_config.expected_content_hash()
    if graph_config.content_hash != expected_hash:
        raise ValueError("GraphRunRunner GraphHarnessConfig content_hash mismatch")


def _runtime_budget_exhausted(started_at: float, *, max_runtime_seconds: float) -> bool:
    if max_runtime_seconds <= 0:
        return False
    return (time.monotonic() - started_at) >= max_runtime_seconds
