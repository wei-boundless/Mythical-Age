from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .models import GraphHarnessConfig, GraphNodeWorkOrder
from .runtime_objects import load_work_order


ExecuteWorkOrder = Callable[..., Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class GraphRunBackgroundSubmission:
    graph_run_id: str
    graph_harness_config_id: str
    accepted: bool = True
    background_started: bool = False
    already_running: bool = False
    scheduled_work_order_count: int = 0
    already_running_work_order_count: int = 0
    active_work_order_count: int = 0
    background_task_names: tuple[str, ...] = ()
    monitor_url: str = ""
    authority: str = "harness.graph.background_submission"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": "harness.api.graph_run_until_idle_background",
            "accepted": self.accepted,
            "background_started": self.background_started,
            "already_running": self.already_running,
            "graph_run_id": self.graph_run_id,
            "graph_harness_config_id": self.graph_harness_config_id,
            "background_task_name": self.background_task_names[0] if self.background_task_names else "",
            "background_task_names": list(self.background_task_names),
            "scheduled_work_order_count": self.scheduled_work_order_count,
            "already_running_work_order_count": self.already_running_work_order_count,
            "active_work_order_count": self.active_work_order_count,
            "monitor_url": self.monitor_url or f"/api/orchestration/harness/graph-runs/{self.graph_run_id}/monitor",
            "diagnostics": dict(self.diagnostics or {}),
        }


class GraphRunBackgroundSupervisor:
    """Schedules GraphRun work orders outside the HTTP request boundary."""

    def __init__(
        self,
        *,
        services: Any,
        graph_loop: Any,
        resume: Any,
        execute_work_order: ExecuteWorkOrder,
    ) -> None:
        self._services = services
        self._graph_loop = graph_loop
        self._resume = resume
        self._execute_work_order = execute_work_order

    def submit_until_idle(
        self,
        *,
        graph_config: GraphHarnessConfig,
        graph_run_id: str,
        max_node_executions: int = 64,
        max_node_steps: int = 12,
        max_dispatch_requests: int | None = None,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> GraphRunBackgroundSubmission:
        runtime_host = _runtime_host(self._services)
        if runtime_host is None:
            raise ValueError("GraphRun background supervisor requires runtime_host")
        resume_result = self._resume.resume(
            graph_config=graph_config,
            graph_run_id=graph_run_id,
            dispatch_ready=True,
            max_requests=max_dispatch_requests,
        )
        state = resume_result.loop_state or self._graph_loop.get_state(graph_run_id)
        active_orders = _active_work_orders_from_state(state, services=self._services)
        if max_node_executions <= 0:
            active_orders = ()
        else:
            active_orders = active_orders[: max(0, int(max_node_executions))]
        scheduled_names: list[str] = []
        already_running_count = 0
        for order in active_orders:
            task_name = _work_order_task_name(order)
            if _background_task_running(runtime_host, task_name):
                already_running_count += 1
                continue
            runtime_host.spawn_background_task(
                self._execute_order_and_schedule_next(
                    graph_config=graph_config,
                    work_order=order,
                    max_node_steps=max_node_steps,
                    max_node_executions=max(0, int(max_node_executions) - 1),
                    max_dispatch_requests=max_dispatch_requests,
                    runtime_overrides=dict(runtime_overrides or {}),
                ),
                name=task_name,
            )
            scheduled_names.append(task_name)
        _append_submission_event(
            self._services,
            graph_run_id=graph_run_id,
            task_run_id=str(getattr(state, "task_run_id", "") or ""),
            graph_harness_config_id=graph_config.config_id,
            scheduled_names=scheduled_names,
            already_running_count=already_running_count,
            active_order_count=len(active_orders),
        )
        return GraphRunBackgroundSubmission(
            graph_run_id=graph_run_id,
            graph_harness_config_id=graph_config.config_id,
            background_started=bool(scheduled_names),
            already_running=bool(already_running_count and not scheduled_names),
            scheduled_work_order_count=len(scheduled_names),
            already_running_work_order_count=already_running_count,
            active_work_order_count=len(active_orders),
            background_task_names=tuple(scheduled_names),
            diagnostics={
                "resume_reason": str(getattr(resume_result, "reason", "") or ""),
                "max_node_executions": max_node_executions,
                "max_node_steps": max_node_steps,
                "max_dispatch_requests": max_dispatch_requests,
            },
        )

    async def _execute_order_and_schedule_next(
        self,
        *,
        graph_config: GraphHarnessConfig,
        work_order: GraphNodeWorkOrder,
        max_node_steps: int,
        max_node_executions: int,
        max_dispatch_requests: int | None,
        runtime_overrides: dict[str, Any],
    ) -> None:
        try:
            execution = await self._execute_work_order(
                graph_config=graph_config,
                work_order=work_order,
                max_steps=max_node_steps,
                accept_result=True,
                runtime_overrides=runtime_overrides,
            )
            if max_node_executions <= 0:
                return
            if not execution.get("accepted_result"):
                return
            state = self._graph_loop.get_state(work_order.graph_run_id)
            next_orders = _active_work_orders_from_state(state, services=self._services)
            if not next_orders:
                return
            self.submit_until_idle(
                graph_config=graph_config,
                graph_run_id=work_order.graph_run_id,
                max_node_executions=max_node_executions,
                max_node_steps=max_node_steps,
                max_dispatch_requests=max_dispatch_requests,
                runtime_overrides=runtime_overrides,
            )
        except Exception as exc:
            _append_execution_failure_event(
                self._services,
                work_order=work_order,
                error=str(exc) or exc.__class__.__name__,
                error_type=exc.__class__.__name__,
            )


def _active_work_orders_from_state(state: Any | None, *, services: Any) -> tuple[GraphNodeWorkOrder, ...]:
    if state is None:
        return ()
    active = dict(getattr(state, "active_work_orders", {}) or {})
    index = dict(getattr(state, "work_order_index", {}) or {})
    orders: list[GraphNodeWorkOrder] = []
    for node_id, work_order_id in active.items():
        payload = dict(index.get(str(work_order_id)) or {})
        if not payload:
            payload = {"node_id": str(node_id), "work_order_id": str(work_order_id)}
        order = load_work_order(services, payload)
        if order is None:
            order = GraphNodeWorkOrder.from_dict(payload)
        if order.node_id != str(node_id):
            raise ValueError("GraphNodeWorkOrder node_id does not match active_work_orders")
        orders.append(order)
    return tuple(orders)


def _work_order_task_name(order: GraphNodeWorkOrder) -> str:
    return f"graph-work-order:{order.graph_run_id}:{order.work_order_id}"


def _runtime_host(services: Any) -> Any | None:
    return getattr(services, "runtime_host", None)


def _background_task_running(runtime_host: Any, name: str) -> bool:
    tasks_by_name = getattr(runtime_host, "_background_tasks_by_name", {})
    if not isinstance(tasks_by_name, dict):
        return False
    tasks = tasks_by_name.get(name, set())
    return any(not getattr(task, "done", lambda: True)() for task in list(tasks or []))


def _append_submission_event(
    services: Any,
    *,
    graph_run_id: str,
    task_run_id: str,
    graph_harness_config_id: str,
    scheduled_names: list[str],
    already_running_count: int,
    active_order_count: int,
) -> None:
    if not task_run_id:
        return
    services.event_log.append(
        task_run_id,
        "graph_run_background_submitted",
        payload={
            "graph_run_id": graph_run_id,
            "graph_harness_config_id": graph_harness_config_id,
            "scheduled_work_order_count": len(scheduled_names),
            "already_running_work_order_count": already_running_count,
            "active_work_order_count": active_order_count,
            "background_task_names": list(scheduled_names),
        },
        refs={"task_run_ref": task_run_id, "graph_run_ref": graph_run_id},
    )


def _append_execution_failure_event(
    services: Any,
    *,
    work_order: GraphNodeWorkOrder,
    error: str,
    error_type: str,
) -> None:
    services.event_log.append(
        work_order.task_run_id,
        "graph_work_order_background_failed",
        payload={
            "graph_run_id": work_order.graph_run_id,
            "node_id": work_order.node_id,
            "work_order_id": work_order.work_order_id,
            "error": error,
            "error_type": error_type,
        },
        refs={
            "task_run_ref": work_order.task_run_id,
            "graph_run_ref": work_order.graph_run_id,
            "work_order_ref": work_order.work_order_id,
        },
    )
