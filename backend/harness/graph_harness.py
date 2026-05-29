from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.shared.models import TaskRun

from .graph.loop import GraphLoop, GraphLoopAdvance, GraphLoopStart
from .graph.models import GraphHarnessConfig, GraphNodeWorkOrder, GraphRun, NodeResultEnvelope
from .graph.resume import GraphResumeResult, GraphResumeService
from .graph.runner import GraphRunRunner, GraphRunRunnerResult
from .graph.runtime import GraphRuntime, GraphRuntimeStart
from .graph.work_order_executor import GraphNodeWorkOrderExecutor


@dataclass(frozen=True, slots=True)
class GraphHarnessStart:
    task_run: Any
    graph_run: Any
    envelope: Any
    loop_state: Any
    checkpoint: dict[str, Any]
    node_work_orders: tuple[Any, ...] = ()
    events: tuple[dict[str, Any], ...] = ()

    @property
    def node_work_order(self) -> dict[str, Any]:
        return self.node_work_orders[0].to_dict() if self.node_work_orders else {}

    @property
    def graph_run_id(self) -> str:
        return str(getattr(self.graph_run, "graph_run_id", "") or "")


class GraphHarness:
    """Production facade for graph task control.

    It owns GraphRuntime and GraphLoop composition. Agent node execution remains
    delegated to AgentHarness outside the graph loop.
    """

    def __init__(self, *, services: Any, agent_harness: Any | None = None) -> None:
        self._services = services
        self._agent_harness = agent_harness
        self._runtime = GraphRuntime(services=services)
        self._loop = GraphLoop(services=services)
        self._resume = GraphResumeService(graph_loop=self._loop)
        self._work_order_executor = GraphNodeWorkOrderExecutor(services=services)
        self._runner = GraphRunRunner(
            services=services,
            graph_loop=self._loop,
            execute_work_order=self.execute_work_order,
        )

    @property
    def graph_loop(self) -> GraphLoop:
        return self._loop

    @property
    def state_index(self) -> Any:
        return self._services.state_index

    def start_run(
        self,
        *,
        session_id: str,
        task_id: str,
        graph_config: GraphHarnessConfig,
        initial_inputs: dict[str, Any] | None = None,
        diagnostics: dict[str, Any] | None = None,
        dispatch_ready: bool = True,
    ) -> GraphHarnessStart:
        runtime_start: GraphRuntimeStart = self._runtime.start(
            session_id=session_id,
            task_id=task_id,
            graph_config=graph_config,
            initial_inputs=dict(initial_inputs or {}),
            diagnostics=dict(diagnostics or {}),
        )
        loop_start: GraphLoopStart = self._loop.initialize(
            graph_config=graph_config,
            envelope=runtime_start.envelope,
            dispatch_ready=dispatch_ready,
        )
        task_run = _task_run_from_payload(
            self._services.state_index.get_task_run(runtime_start.task_run.task_run_id),
            fallback=runtime_start.task_run,
        )
        graph_run = _graph_run_from_payload(
            self.get_graph_run(runtime_start.graph_run.graph_run_id),
            fallback=runtime_start.graph_run,
        )
        return GraphHarnessStart(
            task_run=task_run,
            graph_run=graph_run,
            envelope=runtime_start.envelope,
            loop_state=loop_start.loop_state,
            checkpoint=loop_start.checkpoint,
            node_work_orders=loop_start.node_work_orders,
            events=tuple([*runtime_start.events, *loop_start.events]),
        )

    def accept_node_result(
        self,
        *,
        graph_config: GraphHarnessConfig,
        graph_run_id: str,
        result: NodeResultEnvelope | dict[str, Any],
    ) -> GraphLoopAdvance:
        return self._loop.accept_node_result(
            graph_config=graph_config,
            graph_run_id=graph_run_id,
            result=result,
        )

    def resume_run(
        self,
        *,
        graph_config: GraphHarnessConfig,
        graph_run_id: str,
        dispatch_ready: bool = True,
        max_requests: int | None = None,
    ) -> GraphResumeResult:
        return self._resume.resume(
            graph_config=graph_config,
            graph_run_id=graph_run_id,
            dispatch_ready=dispatch_ready,
            max_requests=max_requests,
        )

    async def execute_work_order(
        self,
        *,
        graph_config: GraphHarnessConfig,
        work_order: GraphNodeWorkOrder | dict[str, Any],
        max_steps: int = 12,
        accept_result: bool = True,
    ) -> dict[str, Any]:
        execution = await self._work_order_executor.execute(
            graph_config=graph_config,
            work_order=work_order,
            max_steps=max_steps,
        )
        advance = None
        if accept_result and _result_should_advance_loop(execution.node_result):
            advance = self.accept_node_result(
                graph_config=graph_config,
                graph_run_id=execution.work_order.graph_run_id,
                result=execution.node_result,
            )
        return {
            "authority": "harness.graph_work_order_execution",
            "graph_run_id": execution.work_order.graph_run_id,
            "graph_harness_config_id": graph_config.config_id,
            "work_order": execution.work_order.to_dict(),
            "node_result": execution.node_result.to_dict(),
            "node_executor_task_run": execution.task_run.to_dict() if hasattr(execution.task_run, "to_dict") else execution.task_run,
            "executor_result": dict(execution.executor_result or {}),
            "accepted_result": advance.accepted_result.to_dict() if advance is not None and advance.accepted_result is not None else None,
            "graph_result": advance.graph_result.to_dict() if advance is not None and advance.graph_result is not None else None,
            "graph_loop_state": advance.loop_state.to_dict() if advance is not None else {},
            "checkpoint": dict(advance.checkpoint) if advance is not None else {},
            "node_work_orders": [item.to_dict() for item in advance.node_work_orders] if advance is not None else [],
            "events": [*list(execution.events), *([dict(item) for item in advance.events] if advance is not None else [])],
        }

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
        return await self._runner.run_until_idle(
            graph_config=graph_config,
            graph_run_id=graph_run_id,
            max_node_executions=max_node_executions,
            max_loop_iterations=max_loop_iterations,
            max_node_steps=max_node_steps,
            max_dispatches=max_dispatches,
            max_runtime_seconds=max_runtime_seconds,
            max_dispatch_requests=max_dispatch_requests,
        )

    def get_checkpoint_state(self, graph_run_id: str) -> dict[str, Any]:
        state = self._loop.get_state(graph_run_id)
        return state.to_dict() if state is not None else {}

    def get_latest_checkpoint(self, graph_run_id: str) -> dict[str, Any]:
        checkpoint = self._loop.get_latest_checkpoint(graph_run_id)
        return checkpoint.to_dict() if checkpoint is not None else {}

    def list_checkpoints(self, graph_run_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self._loop.list_checkpoints(graph_run_id, limit=limit)]

    def get_graph_run(self, graph_run_id: str) -> Any | None:
        try:
            payload = self._services.runtime_objects.get_object(f"rtobj:graph_run:{_safe_ref_id(graph_run_id)}")
        except ValueError:
            return None
        if not payload:
            return None
        return payload

    def get_task_run(self, task_run_id: str) -> Any | None:
        return self.state_index.get_task_run(task_run_id)

    def get_graph_run_monitor(self, graph_run_id: str, *, graph_config: GraphHarnessConfig | None = None) -> dict[str, Any] | None:
        state = self._loop.get_state(graph_run_id)
        graph_run = self.get_graph_run(graph_run_id)
        if state is None and graph_run is None:
            return None
        config_payload = graph_config.to_dict() if graph_config is not None else {}
        task_run_id = state.task_run_id if state is not None else str(dict(graph_run or {}).get("task_run_id") or "")
        events = self._services.event_log.list_events(task_run_id) if task_run_id else []
        active_work_orders = _active_work_orders_from_state(state)
        node_runtime_views = _node_runtime_views(
            state=state,
            events=events,
            task_run_lookup=self.get_task_run,
        )
        return {
            "authority": "harness.graph_run_monitor",
            "graph_run_id": graph_run_id,
            "graph_run": graph_run or {},
            "task_run": self.get_task_run(task_run_id).to_dict() if task_run_id and self.get_task_run(task_run_id) is not None else None,
            "graph_harness_config": config_payload,
            "graph_loop_state": state.to_dict() if state is not None else {},
            "active_node_work_orders": active_work_orders,
            "active_node_work_order_count": len(active_work_orders),
            "node_runtime_views": node_runtime_views,
            "events": [item.to_dict() for item in events],
            "event_count": len(events),
        }

    def get_trace(self, task_run_id: str, **kwargs: Any) -> dict[str, Any] | None:
        return self._services.get_trace(task_run_id, **kwargs)

    def event_count(self, task_run_id: str) -> int:
        return self._services.event_count(task_run_id)


def _safe_ref_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))[:180]


def _task_run_from_payload(payload: Any, *, fallback: TaskRun) -> TaskRun:
    if isinstance(payload, TaskRun):
        return payload
    if isinstance(payload, dict):
        return TaskRun(**payload)
    return fallback


def _graph_run_from_payload(payload: Any, *, fallback: GraphRun) -> GraphRun:
    if isinstance(payload, GraphRun):
        return payload
    if isinstance(payload, dict) and payload:
        return GraphRun.from_dict(payload)
    return fallback


def _result_should_advance_loop(result: NodeResultEnvelope) -> bool:
    return result.status in {"completed", "failed", "blocked", "waiting_human_gate"}


def _active_work_orders_from_state(state: Any | None) -> list[dict[str, Any]]:
    if state is None:
        return []
    active = dict(getattr(state, "active_work_orders", {}) or {})
    index = dict(getattr(state, "work_order_index", {}) or {})
    orders: list[dict[str, Any]] = []
    for node_id, work_order_id in active.items():
        payload = dict(index.get(str(work_order_id)) or {})
        if not payload:
            payload = {"node_id": str(node_id), "work_order_id": str(work_order_id)}
        orders.append(payload)
    return orders


def _node_runtime_views(*, state: Any | None, events: list[Any], task_run_lookup: Any) -> list[dict[str, Any]]:
    if state is None:
        return []
    node_states = {key: dict(value) for key, value in dict(getattr(state, "node_states", {}) or {}).items()}
    work_order_index = dict(getattr(state, "work_order_index", {}) or {})
    result_index = dict(getattr(state, "result_index", {}) or {})
    task_run_refs = _node_executor_refs_by_node(events)
    views: list[dict[str, Any]] = []
    for node_id, node_state in node_states.items():
        result = dict(result_index.get(node_id) or {})
        work_order_id = str(node_state.get("work_order_id") or result.get("work_order_id") or "")
        work_order = dict(work_order_index.get(work_order_id) or {}) if work_order_id else {}
        task_run_id = str(
            task_run_refs.get(node_id)
            or dict(result.get("outputs") or {}).get("node_executor_task_run_id")
            or ""
        )
        task_run = task_run_lookup(task_run_id) if task_run_id else None
        task_payload = task_run.to_dict() if hasattr(task_run, "to_dict") else (dict(task_run) if isinstance(task_run, dict) else {})
        diagnostics = dict(task_payload.get("diagnostics") or {})
        views.append(
            {
                "node_id": node_id,
                "status": str(node_state.get("status") or ""),
                "executor_type": str(node_state.get("executor_type") or work_order.get("executor_type") or ""),
                "work_order_id": work_order_id,
                "work_order": work_order,
                "node_executor_task_run_id": task_run_id,
                "node_executor_task_run": task_payload or None,
                "latest_step": diagnostics.get("latest_step") or diagnostics.get("step_summary") or {},
                "artifact_refs": list(result.get("artifact_refs") or []),
                "artifact_materialization_receipts": list(result.get("artifact_materialization_receipts") or []),
                "memory_commit_receipts": list(result.get("memory_commit_receipts") or []),
                "error": dict(result.get("error") or {}),
                "result": result,
            }
        )
    return views


def _node_executor_refs_by_node(events: list[Any]) -> dict[str, str]:
    refs: dict[str, str] = {}
    for event in events:
        payload = dict(getattr(event, "payload", {}) or {})
        node_id = str(payload.get("node_id") or "")
        if not node_id:
            work_order = dict(payload.get("work_order") or {})
            node_id = str(work_order.get("node_id") or "")
        if not node_id:
            continue
        task_run_id = str(payload.get("node_executor_task_run_id") or "")
        if not task_run_id:
            task_run = dict(payload.get("node_executor_task_run") or {})
            task_run_id = str(task_run.get("task_run_id") or "")
        if task_run_id:
            refs[node_id] = task_run_id
    return refs
