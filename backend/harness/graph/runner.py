from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .model_overrides import merge_effective_runtime_overrides
from .loop import assert_graph_config_compatible_with_state
from .models import GraphHarnessConfig, GraphLoopState, GraphNodeWorkOrder
from .runtime_objects import load_work_order


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
    active_node_work_orders: tuple[dict[str, Any], ...] = ()
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
            "active_node_work_orders": [dict(item) for item in self.active_node_work_orders],
            "active_node_work_order_count": len(self.active_node_work_orders),
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
        runtime_overrides: dict[str, Any] | None = None,
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

            active_orders = _active_work_orders_from_state(state, services=self._services)
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
                active_orders = _active_work_orders_from_state(state, services=self._services)
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
                effective_runtime_overrides = merge_effective_runtime_overrides(
                    persistent=dict(dict(state.diagnostics or {}).get("runtime_settings") or {}),
                    temporary=dict(runtime_overrides or {}),
                )
                execution = await self._execute_work_order(
                    graph_config=graph_config,
                    work_order=order,
                    max_steps=max_node_steps,
                    accept_result=True,
                    runtime_overrides=effective_runtime_overrides,
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
        assert_graph_config_compatible_with_state(graph_config=graph_config, state=state)
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
        if not str(work_order.structure_hash or "").strip():
            raise ValueError("GraphRunRunner work_order structure_hash missing")
        if work_order.structure_hash != state.structure_hash:
            raise ValueError("GraphRunRunner work_order structure_hash mismatch")
        if _node_by_id(graph_config, work_order.node_id) is None:
            raise ValueError("GraphRunRunner work_order node_id not found in GraphHarnessConfig")

    def _validate_executor_origin(
        self,
        *,
        graph_run_id: str,
        work_order: GraphNodeWorkOrder,
        execution: dict[str, Any],
    ) -> None:
        task_run = self._executor_task_run_payload(execution)
        if not task_run:
            return
        if _task_run_origin_kind(task_run) != "graph_node_assigned":
            raise ValueError("GraphRunRunner node executor TaskRun origin_kind mismatch")
        if _task_run_graph_run_id(task_run) != graph_run_id:
            raise ValueError("GraphRunRunner node executor TaskRun graph_run_id mismatch")
        if _task_run_work_order_id(task_run) != work_order.work_order_id:
            raise ValueError("GraphRunRunner node executor TaskRun work_order_id mismatch")

    def _executor_task_run_payload(self, execution: dict[str, Any]) -> dict[str, Any]:
        task_run = dict(execution.get("node_executor_task_run") or {})
        if _task_run_origin_kind(task_run) and _task_run_graph_run_id(task_run) and _task_run_work_order_id(task_run):
            return task_run
        task_run_id = str(
            task_run.get("task_run_id")
            or dict(dict(execution.get("node_result") or {}).get("outputs") or {}).get("node_executor_task_run_id")
            or ""
        ).strip()
        if not task_run_id:
            return task_run
        persisted = self._services.state_index.get_task_run(task_run_id)
        persisted_payload = persisted.to_dict() if hasattr(persisted, "to_dict") else (dict(persisted) if isinstance(persisted, dict) else {})
        if not persisted_payload:
            return task_run
        return {
            **persisted_payload,
            **{key: value for key, value in task_run.items() if value not in ("", None, {}, [])},
        }

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
            loop_state=_loop_state_public_view(state),
            graph_result=dict(graph_result or {}),
            active_node_work_orders=_active_work_order_summaries_from_state(state),
            events=tuple(events),
        )


def _active_work_orders_from_state(state: GraphLoopState, *, services: Any) -> tuple[GraphNodeWorkOrder, ...]:
    active = dict(state.active_work_orders or {})
    index = dict(state.work_order_index or {})
    orders: list[GraphNodeWorkOrder] = []
    for node_id, work_order_id in active.items():
        payload = dict(index.get(str(work_order_id)) or {})
        if not payload:
            raise ValueError(f"GraphNodeWorkOrder missing from work_order_index: {node_id}")
        order = load_work_order(services, payload)
        if order is None:
            order = GraphNodeWorkOrder.from_dict(payload)
        if order.node_id != str(node_id):
            raise ValueError("GraphNodeWorkOrder node_id does not match active_work_orders")
        orders.append(order)
    return tuple(orders)


def _active_work_order_summaries_from_state(state: GraphLoopState) -> tuple[dict[str, Any], ...]:
    active = dict(state.active_work_orders or {})
    index = dict(state.work_order_index or {})
    summaries: list[dict[str, Any]] = []
    for node_id, work_order_id in active.items():
        payload = dict(index.get(str(work_order_id)) or {})
        if not payload:
            payload = {"node_id": str(node_id), "work_order_id": str(work_order_id)}
        summaries.append(
            {
                **payload,
                "node_id": str(payload.get("node_id") or node_id),
                "work_order_id": str(payload.get("work_order_id") or work_order_id),
            }
        )
    return tuple(summaries)


def _validate_graph_config_identity(graph_config: GraphHarnessConfig) -> None:
    if graph_config.status != "published":
        raise ValueError("GraphRunRunner requires a published GraphHarnessConfig")
    expected_hash = graph_config.expected_content_hash()
    if graph_config.content_hash != expected_hash:
        raise ValueError("GraphRunRunner GraphHarnessConfig content_hash mismatch")


def _node_by_id(graph_config: GraphHarnessConfig, node_id: str) -> dict[str, Any] | None:
    target = str(node_id or "").strip()
    return next((dict(item) for item in graph_config.nodes if str(dict(item).get("node_id") or "").strip() == target), None)


def _runtime_budget_exhausted(started_at: float, *, max_runtime_seconds: float) -> bool:
    if max_runtime_seconds <= 0:
        return False
    return (time.monotonic() - started_at) >= max_runtime_seconds


def _task_run_diagnostics(task_run: dict[str, Any]) -> dict[str, Any]:
    return dict(task_run.get("diagnostics") or {})


def _task_run_origin(task_run: dict[str, Any]) -> dict[str, Any]:
    return dict(_task_run_diagnostics(task_run).get("origin") or {})


def _task_run_origin_kind(task_run: dict[str, Any]) -> str:
    diagnostics = _task_run_diagnostics(task_run)
    origin = _task_run_origin(task_run)
    return str(task_run.get("origin_kind") or origin.get("origin_kind") or diagnostics.get("origin_kind") or "").strip()


def _task_run_graph_run_id(task_run: dict[str, Any]) -> str:
    diagnostics = _task_run_diagnostics(task_run)
    origin = _task_run_origin(task_run)
    return str(task_run.get("graph_run_id") or diagnostics.get("graph_run_id") or origin.get("graph_run_id") or "").strip()


def _task_run_work_order_id(task_run: dict[str, Any]) -> str:
    diagnostics = _task_run_diagnostics(task_run)
    origin = _task_run_origin(task_run)
    return str(task_run.get("graph_work_order_id") or diagnostics.get("graph_work_order_id") or origin.get("origin_ref") or "").strip()


def _loop_state_public_view(state: GraphLoopState) -> dict[str, Any]:
    payload = state.to_dict()
    return {
        **payload,
        "work_order_index": {key: dict(value) for key, value in dict(payload.get("work_order_index") or {}).items()},
        "result_index": {key: dict(value) for key, value in dict(payload.get("result_index") or {}).items()},
    }
