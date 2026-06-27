from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable

from .models import ExecutableGraphConfig, GraphNodeWorkOrder
from .runtime_objects import load_work_order


ExecuteWorkOrder = Callable[..., Awaitable[dict[str, Any]]]

_RUNTIME_CONTROL_KEY = "runtime_control"
_PAUSE_CONTROL_STATES = {"pause_requested", "paused"}
_STOP_CONTROL_STATES = {"stop_requested", "stopped"}


@dataclass(frozen=True, slots=True)
class GraphRunBackgroundSubmission:
    graph_run_id: str
    graph_config_id: str
    accepted: bool = True
    background_started: bool = False
    already_running: bool = False
    scheduled_work_order_count: int = 0
    already_running_work_order_count: int = 0
    active_work_order_count: int = 0
    background_task_names: tuple[str, ...] = ()
    monitor_url: str = ""
    authority: str = "graph_system.background_submission"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": "graph_system.api.graph_run_until_idle_background",
            "accepted": self.accepted,
            "background_started": self.background_started,
            "already_running": self.already_running,
            "graph_run_id": self.graph_run_id,
            "graph_config_id": self.graph_config_id,
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
        graph_config: ExecutableGraphConfig,
        graph_run_id: str,
        max_node_executions: int = 64,
        max_node_steps: int = 12,
        max_dispatch_requests: int | None = None,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> GraphRunBackgroundSubmission:
        runtime_host = _runtime_host(self._services)
        if runtime_host is None:
            raise ValueError("GraphRun background supervisor requires runtime_host")
        state = self._graph_loop.get_state(graph_run_id)
        control_boundary = _root_control_boundary(self._services, state)
        if control_boundary:
            _mark_root_graph_run_paused(self._services, state, boundary="submit_until_idle", control_boundary=control_boundary)
            return GraphRunBackgroundSubmission(
                graph_run_id=graph_run_id,
                graph_config_id=graph_config.config_id,
                background_started=False,
                scheduled_work_order_count=0,
                active_work_order_count=len(_active_work_orders_from_state(state, services=self._services)),
                diagnostics={
                    "blocked_by_runtime_control": True,
                    "control_state": str(control_boundary.get("control_state") or ""),
                    "boundary": "submit_until_idle",
                    "max_node_executions": max_node_executions,
                    "max_node_steps": max_node_steps,
                    "max_dispatch_requests": max_dispatch_requests,
                },
            )
        resume_result = self._resume.resume(
            graph_config=graph_config,
            graph_run_id=graph_run_id,
            dispatch_ready=True,
            max_requests=max_dispatch_requests,
        )
        state = resume_result.loop_state or self._graph_loop.get_state(graph_run_id)
        control_boundary = _root_control_boundary(self._services, state)
        if control_boundary:
            _mark_root_graph_run_paused(self._services, state, boundary="after_resume", control_boundary=control_boundary)
            return GraphRunBackgroundSubmission(
                graph_run_id=graph_run_id,
                graph_config_id=graph_config.config_id,
                background_started=False,
                scheduled_work_order_count=0,
                active_work_order_count=len(_active_work_orders_from_state(state, services=self._services)),
                diagnostics={
                    "resume_reason": str(getattr(resume_result, "reason", "") or ""),
                    "blocked_by_runtime_control": True,
                    "control_state": str(control_boundary.get("control_state") or ""),
                    "boundary": "after_resume",
                    "max_node_executions": max_node_executions,
                    "max_node_steps": max_node_steps,
                    "max_dispatch_requests": max_dispatch_requests,
                },
            )
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
            graph_config_id=graph_config.config_id,
            scheduled_names=scheduled_names,
            already_running_count=already_running_count,
            active_order_count=len(active_orders),
        )
        return GraphRunBackgroundSubmission(
            graph_run_id=graph_run_id,
            graph_config_id=graph_config.config_id,
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
        graph_config: ExecutableGraphConfig,
        work_order: GraphNodeWorkOrder,
        max_node_steps: int,
        max_node_executions: int,
        max_dispatch_requests: int | None,
        runtime_overrides: dict[str, Any],
    ) -> None:
        try:
            state = self._graph_loop.get_state(work_order.graph_run_id)
            control_boundary = _root_control_boundary(self._services, state)
            if control_boundary:
                _mark_root_graph_run_paused(self._services, state, boundary="before_work_order_execution", control_boundary=control_boundary)
                return
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
            control_boundary = _root_control_boundary(self._services, state)
            if control_boundary:
                _mark_root_graph_run_paused(self._services, state, boundary="before_followup_submit", control_boundary=control_boundary)
                return
            if not _state_needs_followup_submit(state):
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


def _state_needs_followup_submit(state: Any | None) -> bool:
    if state is None:
        return False
    if dict(getattr(state, "active_work_orders", {}) or {}):
        return True
    if tuple(getattr(state, "ready_node_ids", ()) or ()):
        return True
    if str(getattr(state, "status", "") or "") in {"blocked", "failed"}:
        return bool(tuple(getattr(state, "blocked_node_ids", ()) or ()) or tuple(getattr(state, "failed_node_ids", ()) or ()))
    return False


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


def _root_control_boundary(services: Any, state: Any | None) -> dict[str, Any]:
    if state is None:
        return {}
    task_run_id = str(getattr(state, "task_run_id", "") or "").strip()
    if not task_run_id:
        return {}
    task_run = services.state_index.get_task_run(task_run_id)
    if task_run is None:
        return {}
    control = _runtime_control_payload(task_run)
    control_state = str(control.get("state") or "").strip()
    if control_state in _PAUSE_CONTROL_STATES | _STOP_CONTROL_STATES:
        return {
            "task_run_id": task_run_id,
            "control_state": control_state,
            "control": control,
        }
    return {}


def _runtime_control_payload(task_run: Any) -> dict[str, Any]:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    control = diagnostics.get(_RUNTIME_CONTROL_KEY)
    if not isinstance(control, dict):
        return {}
    return {
        "state": str(control.get("state") or "").strip(),
        "requested_by": str(control.get("requested_by") or ""),
        "requested_at": float(control.get("requested_at") or 0.0),
        "reason": str(control.get("reason") or ""),
        "authority": str(control.get("authority") or "orchestration.graph_run_control"),
    }


def _mark_root_graph_run_paused(
    services: Any,
    state: Any | None,
    *,
    boundary: str,
    control_boundary: dict[str, Any],
) -> None:
    if state is None:
        return
    control_state = str(control_boundary.get("control_state") or "").strip()
    if control_state in _STOP_CONTROL_STATES:
        return
    task_run_id = str(control_boundary.get("task_run_id") or getattr(state, "task_run_id", "") or "").strip()
    if not task_run_id:
        return
    task_run = services.state_index.get_task_run(task_run_id)
    if task_run is None:
        return
    current_control = _runtime_control_payload(task_run)
    if str(current_control.get("state") or "") == "paused" and str(getattr(task_run, "status", "") or "") == "waiting_executor":
        return
    now = time.time()
    event = services.event_log.append(
        task_run_id,
        "graph_run_paused_at_control_boundary",
        payload={
            "task_run_id": task_run_id,
            "graph_run_id": str(getattr(state, "graph_run_id", "") or ""),
            "boundary": boundary,
            "previous_control_state": control_state,
        },
        refs={"task_run_ref": task_run_id, "graph_run_ref": str(getattr(state, "graph_run_id", "") or "")},
    )
    services.state_index.upsert_task_run(
        replace(
            task_run,
            status="waiting_executor",
            updated_at=float(getattr(event, "created_at", 0.0) or now),
            latest_event_offset=int(getattr(event, "offset", -1) or -1),
            terminal_reason="waiting_executor",
            diagnostics={
                **dict(getattr(task_run, "diagnostics", {}) or {}),
                _RUNTIME_CONTROL_KEY: {
                    **dict(current_control or {}),
                    "state": "paused",
                    "requested_by": str(current_control.get("requested_by") or "user"),
                    "requested_at": float(current_control.get("requested_at") or getattr(event, "created_at", 0.0) or now),
                    "reason": str(current_control.get("reason") or "graph_run_pause"),
                    "authority": "orchestration.graph_run_control",
                },
                "executor_status": "waiting_executor",
                "latest_step": "graph_run_paused_at_control_boundary",
                "latest_step_status": "waiting_executor",
                "latest_step_summary": "图任务已在安全边界暂停，后续可以从当前图状态续跑。",
            },
        )
    )


def _append_submission_event(
    services: Any,
    *,
    graph_run_id: str,
    task_run_id: str,
    graph_config_id: str,
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
            "graph_config_id": graph_config_id,
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
