from __future__ import annotations

from dataclasses import dataclass, replace
import time
from typing import Any

from artifact_system.artifact_authority import dedupe_artifact_refs, normalize_artifact_ref
from runtime.shared.models import TaskRun

from .graph.loop import GraphLoop, GraphLoopAdvance, GraphLoopStart
from .graph.models import GraphHarnessConfig, GraphNodeWorkOrder, GraphRun, NodeResultEnvelope
from .graph.model_overrides import merge_effective_runtime_overrides
from .graph.resume import GraphResumeResult, GraphResumeService
from .graph.runner import GraphRunRunner, GraphRunRunnerResult
from .graph.runtime import GraphRuntime, GraphRuntimeStart
from .graph.supervisor import GraphSupervisor
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

    It owns GraphRuntime, GraphLoop, and graph node work-order execution.
    """

    def __init__(self, *, services: Any) -> None:
        self._services = services
        self._runtime = GraphRuntime(services=services)
        self._loop = GraphLoop(services=services)
        self._resume = GraphResumeService(graph_loop=self._loop, services=services)
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

    def apply_human_gate_decision(
        self,
        *,
        graph_config: GraphHarnessConfig,
        graph_run_id: str,
        decision: dict[str, Any],
        max_requests: int | None = None,
    ) -> GraphLoopAdvance:
        return self._loop.apply_human_gate_decision_and_checkpoint(
            graph_config=graph_config,
            graph_run_id=graph_run_id,
            decision=dict(decision or {}),
            max_requests=max_requests,
        )

    async def execute_work_order(
        self,
        *,
        graph_config: GraphHarnessConfig,
        work_order: GraphNodeWorkOrder | dict[str, Any],
        max_steps: int = 12,
        accept_result: bool = True,
        runtime_overrides: dict[str, Any] | None = None,
        runtime_settings_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        order = work_order if isinstance(work_order, GraphNodeWorkOrder) else GraphNodeWorkOrder.from_dict(dict(work_order or {}))
        if runtime_settings_patch:
            self.apply_runtime_settings_patch(
                graph_run_id=order.graph_run_id,
                runtime_settings_patch=dict(runtime_settings_patch or {}),
            )
        effective_runtime_overrides = self._effective_runtime_overrides(
            graph_run_id=order.graph_run_id,
            runtime_overrides=runtime_overrides,
        )
        execution = await self._work_order_executor.execute(
            graph_config=graph_config,
            work_order=order,
            max_steps=max_steps,
            runtime_overrides=effective_runtime_overrides,
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
            "node_executor_task_run": _task_run_summary(execution.task_run),
            "executor_result": _executor_result_summary(execution.executor_result),
            "accepted_result": advance.accepted_result.to_dict() if advance is not None and advance.accepted_result is not None else None,
            "graph_result": advance.graph_result.to_dict() if advance is not None and advance.graph_result is not None else None,
            "graph_loop_state": _loop_state_public_view(advance.loop_state) if advance is not None else {},
            "checkpoint": dict(advance.checkpoint) if advance is not None else {},
            "node_work_orders": [_work_order_public_view(item) for item in advance.node_work_orders] if advance is not None else [],
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
        runtime_overrides: dict[str, Any] | None = None,
        runtime_settings_patch: dict[str, Any] | None = None,
    ) -> GraphRunRunnerResult:
        if runtime_settings_patch:
            self.apply_runtime_settings_patch(
                graph_run_id=graph_run_id,
                runtime_settings_patch=dict(runtime_settings_patch or {}),
            )
        self._resume.resume(
            graph_config=graph_config,
            graph_run_id=graph_run_id,
            dispatch_ready=True,
            max_requests=max_dispatch_requests,
        )
        result = await self._runner.run_until_idle(
            graph_config=graph_config,
            graph_run_id=graph_run_id,
            max_node_executions=max_node_executions,
            max_loop_iterations=max_loop_iterations,
            max_node_steps=max_node_steps,
            max_dispatches=max_dispatches,
            max_runtime_seconds=max_runtime_seconds,
            max_dispatch_requests=max_dispatch_requests,
            runtime_overrides=dict(runtime_overrides or {}),
        )
        self._commit_runner_result(graph_run_id=graph_run_id, result=result)
        return result

    def _commit_runner_result(self, *, graph_run_id: str, result: GraphRunRunnerResult) -> None:
        graph_run = _graph_run_from_payload(self.get_graph_run(graph_run_id), fallback=None)
        task_run_id = graph_run.task_run_id if graph_run is not None else ""
        task_run = self.get_task_run(task_run_id) if task_run_id else None
        now = time.time()
        task_status = _task_status_from_runner_result(result)
        graph_status = _graph_status_from_runner_result(result)
        terminal_reason = result.terminal_reason or result.status
        runner_diagnostics = {
            "runner_status": result.status,
            "runner_terminal_reason": terminal_reason,
            "runner_blocked_reason": result.blocked_reason,
            "runner_budget_exhausted": bool(result.budget_exhausted),
            "runner_executed_work_order_count": result.executed_work_order_count,
            "runner_accepted_result_count": result.accepted_result_count,
            "runner_dispatch_count": result.dispatch_count,
            "active_node_work_order_count": len(result.active_node_work_orders),
        }
        if task_run is not None:
            diagnostics = {
                **dict(getattr(task_run, "diagnostics", {}) or {}),
                **runner_diagnostics,
                "executor_status": "waiting_executor" if task_status == "waiting_executor" else task_status,
                "latest_step": "graph_run_runner_stopped",
                "latest_step_status": task_status,
            }
            self.state_index.upsert_task_run(
                replace(
                    task_run,
                    status=task_status,  # type: ignore[arg-type]
                    updated_at=now,
                    terminal_reason=terminal_reason,  # type: ignore[arg-type]
                    diagnostics=diagnostics,
                )
            )
        if graph_run is not None:
            graph_payload = graph_run.to_dict()
            self._services.runtime_objects.put_object(
                "graph_run",
                _safe_ref_id(graph_run_id),
                {
                    **graph_payload,
                    "status": graph_status,
                    "updated_at": now,
                    "terminal_reason": terminal_reason,
                    "diagnostics": {
                        **dict(graph_payload.get("diagnostics") or {}),
                        **runner_diagnostics,
                    },
                },
            )

    def apply_runtime_settings_patch(self, *, graph_run_id: str, runtime_settings_patch: dict[str, Any] | None) -> dict[str, Any]:
        patched = self._loop.patch_runtime_settings_and_checkpoint(
            graph_run_id=graph_run_id,
            runtime_settings_patch=dict(runtime_settings_patch or {}),
        )
        return {
            "graph_loop_state": patched.loop_state.to_dict(),
            "checkpoint": dict(patched.checkpoint),
            "events": [dict(item) for item in patched.events],
        }

    def _effective_runtime_overrides(self, *, graph_run_id: str, runtime_overrides: dict[str, Any] | None) -> dict[str, Any]:
        state = self._loop.get_state(graph_run_id)
        diagnostics = dict(getattr(state, "diagnostics", {}) or {}) if state is not None else {}
        return merge_effective_runtime_overrides(
            persistent=diagnostics.get("runtime_settings") or {},
            temporary=dict(runtime_overrides or {}),
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

    def get_graph_run_monitor(
        self,
        graph_run_id: str,
        *,
        graph_config: GraphHarnessConfig | None = None,
        event_limit: int = 80,
        include_config: bool = False,
    ) -> dict[str, Any] | None:
        state = self._loop.get_state(graph_run_id)
        graph_run = self.get_graph_run(graph_run_id)
        if state is None and graph_run is None:
            return None
        config_payload = _graph_config_monitor_view(graph_config, include_config=include_config)
        task_run_id = state.task_run_id if state is not None else str(dict(graph_run or {}).get("task_run_id") or "")
        event_limit = max(1, min(int(event_limit or 80), 240))
        events = self._recent_events(task_run_id, limit=event_limit) if task_run_id else []
        event_count = self._estimated_event_count(task_run_id, fallback=len(events)) if task_run_id else 0
        active_work_orders = _active_work_orders_from_state(state)
        task_run = self.get_task_run(task_run_id) if task_run_id else None
        task_run_monitor = self._task_run_monitor(task_run)
        active_node_runtime_views = _active_node_runtime_views(
            state=state,
            events=events,
            task_run_lookup=self.get_task_run,
            task_run_monitor_lookup=self._task_run_monitor_by_id,
        )
        supervisor_observation = (
            GraphSupervisor().observe(graph_config=graph_config, state=state).to_dict()
            if graph_config is not None and state is not None
            else {}
        )
        return {
            "authority": "harness.graph_run_monitor",
            "graph_run_id": graph_run_id,
            "graph_run": graph_run or {},
            "task_run": _task_run_summary(task_run) if task_run_id else None,
            "task_run_monitor": task_run_monitor or None,
            "runtime_monitor": task_run_monitor or None,
            "graph_harness_config": config_payload,
            "graph_loop_state": _loop_state_public_view(state) if state is not None else {},
            "active_node_work_orders": active_work_orders,
            "active_node_work_order_count": len(active_work_orders),
            "active_node_runtime_views": active_node_runtime_views,
            "supervisor_observation": supervisor_observation,
            "event_count": event_count,
            "event_window": {
                "kind": "omitted",
                "limit": event_limit,
                "returned": 0,
            },
        }

    def get_trace(self, task_run_id: str, **kwargs: Any) -> dict[str, Any] | None:
        return self._services.get_trace(task_run_id, **kwargs)

    def event_count(self, task_run_id: str) -> int:
        return self._services.event_count(task_run_id)

    def _recent_events(self, task_run_id: str, *, limit: int) -> list[Any]:
        reader = getattr(self._services.event_log, "list_recent_events", None)
        if callable(reader):
            return list(reader(task_run_id, limit=limit))
        return []

    def _estimated_event_count(self, task_run_id: str, *, fallback: int) -> int:
        counter = getattr(self._services.event_log, "estimated_event_count", None)
        if callable(counter):
            try:
                return int(counter(task_run_id))
            except Exception:
                pass
        counter = getattr(self._services.event_log, "event_count", None)
        if callable(counter):
            try:
                return int(counter(task_run_id))
            except Exception:
                pass
        return int(fallback)

    def _task_run_monitor_by_id(self, task_run_id: str) -> dict[str, Any]:
        task_run = self.get_task_run(task_run_id) if task_run_id else None
        return self._task_run_monitor(task_run)

    def _task_run_monitor(self, task_run: Any | None) -> dict[str, Any]:
        if task_run is None:
            return {}
        projector = getattr(self._services, "monitor_projector", None)
        project = getattr(projector, "project_task_run", None)
        if callable(project):
            try:
                return dict(project(task_run, now=time.time(), include_runtime_details=False, include_graph_runtime=False) or {})
            except Exception:
                return {}
        return {}


def _safe_ref_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))[:180]


def _graph_config_monitor_view(graph_config: GraphHarnessConfig | None, *, include_config: bool = False) -> dict[str, Any]:
    if graph_config is None:
        return {}
    if include_config:
        return graph_config.to_dict()
    return {
        "authority": "harness.graph_harness_config.summary",
        "config_id": graph_config.config_id,
        "graph_id": graph_config.graph_id,
        "graph_title": graph_config.graph_title,
        "publish_version": graph_config.publish_version,
        "status": graph_config.status,
        "content_hash": graph_config.content_hash,
        "published_at": graph_config.published_at,
        "task_environment_id": graph_config.task_environment_id,
        "root_task_ref": graph_config.root_task_ref,
        "node_count": len(graph_config.nodes),
        "edge_count": len(graph_config.edges),
        "loop_frame_count": len(graph_config.loop_frames),
        "composition_source_count": len(graph_config.composition_sources),
    }


def _task_run_from_payload(payload: Any, *, fallback: TaskRun) -> TaskRun:
    if isinstance(payload, TaskRun):
        return payload
    if isinstance(payload, dict):
        return TaskRun(**payload)
    return fallback


def _graph_run_from_payload(payload: Any, *, fallback: GraphRun | None) -> GraphRun | None:
    if isinstance(payload, GraphRun):
        return payload
    if isinstance(payload, dict) and payload:
        return GraphRun.from_dict(payload)
    return fallback


def _task_status_from_runner_result(result: GraphRunRunnerResult) -> str:
    status = str(result.status or "").strip()
    if status == "completed":
        return "completed"
    if status in {"failed"}:
        return "failed"
    if status == "cancelled":
        return "aborted"
    if status in {"blocked", "waiting_human_gate"}:
        return "blocked"
    return "waiting_executor"


def _graph_status_from_runner_result(result: GraphRunRunnerResult) -> str:
    status = str(result.status or "").strip()
    if status in {"completed", "failed", "blocked", "waiting_human_gate", "cancelled", "budget_exhausted", "idle"}:
        return status
    return "waiting_executor"


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
        orders.append(
            {
                **payload,
                "node_id": str(payload.get("node_id") or node_id),
                "work_order_id": str(payload.get("work_order_id") or work_order_id),
            }
        )
    return orders


def _active_node_runtime_views(*, state: Any | None, events: list[Any], task_run_lookup: Any, task_run_monitor_lookup: Any | None = None) -> list[dict[str, Any]]:
    if state is None:
        return []
    node_states = {key: dict(value) for key, value in dict(getattr(state, "node_states", {}) or {}).items()}
    task_run_refs = _node_executor_refs_by_node(events)
    active_work_orders = {
        str(key): str(value)
        for key, value in dict(getattr(state, "active_work_orders", {}) or {}).items()
        if str(key) and str(value)
    }
    active_node_ids = {
        str(item)
        for item in [
            *list(getattr(state, "running_node_ids", ()) or ()),
            *list(active_work_orders.keys()),
        ]
        if str(item)
    }
    views: list[dict[str, Any]] = []
    for node_id, node_state in node_states.items():
        if node_id not in active_node_ids:
            continue
        work_order_id = str(active_work_orders.get(node_id) or node_state.get("work_order_id") or "")
        task_run_id = str(
            task_run_refs.get(node_id)
            or ""
        )
        task_run = task_run_lookup(task_run_id) if task_run_id else None
        task_payload = _task_run_summary(task_run)
        task_monitor = task_run_monitor_lookup(task_run_id) if callable(task_run_monitor_lookup) and task_run_id else {}
        work_order_summary = dict(getattr(state, "work_order_index", {}).get(work_order_id) or {}) if work_order_id else {}
        views.append(
            {
                "node_id": node_id,
                "status": str(node_state.get("status") or ""),
                "executor_type": str(node_state.get("executor_type") or ""),
                "work_order_id": work_order_id,
                "work_order": {},
                "work_order_summary": work_order_summary,
                "node_executor_task_run_id": task_run_id,
                "node_executor_task_run": task_payload or None,
                "node_executor_task_run_monitor": task_monitor or None,
                "latest_step": task_payload.get("latest_step") or {},
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


def _loop_state_public_view(state: Any | None) -> dict[str, Any]:
    if state is None:
        return {}
    payload = state.to_dict() if hasattr(state, "to_dict") else dict(state or {})
    node_states = {
        str(node_id): _node_state_monitor_view(dict(node_state or {}))
        for node_id, node_state in dict(payload.get("node_states") or {}).items()
    }
    return {
        "authority": str(payload.get("authority") or "harness.graph_loop_state"),
        "state_id": str(payload.get("state_id") or ""),
        "graph_run_id": str(payload.get("graph_run_id") or ""),
        "task_run_id": str(payload.get("task_run_id") or ""),
        "session_id": str(payload.get("session_id") or ""),
        "config_id": str(payload.get("config_id") or ""),
        "config_hash": str(payload.get("config_hash") or ""),
        "graph_id": str(payload.get("graph_id") or ""),
        "structure_hash": str(payload.get("structure_hash") or ""),
        "structure_version": str(payload.get("structure_version") or ""),
        "config_snapshot_id": str(payload.get("config_snapshot_id") or ""),
        "config_snapshot_hash": str(payload.get("config_snapshot_hash") or ""),
        "status": str(payload.get("status") or ""),
        "ready_node_ids": list(payload.get("ready_node_ids") or []),
        "running_node_ids": list(payload.get("running_node_ids") or []),
        "completed_node_ids": list(payload.get("completed_node_ids") or []),
        "failed_node_ids": list(payload.get("failed_node_ids") or []),
        "blocked_node_ids": list(payload.get("blocked_node_ids") or []),
        "active_node_ids": list(payload.get("running_node_ids") or []),
        "active_work_order_node_ids": list(dict(payload.get("active_work_orders") or {}).keys()),
        "node_states": node_states,
        "event_cursor": payload.get("event_cursor", -1),
        "terminal_reason": str(payload.get("terminal_reason") or ""),
        "diagnostics": _loop_diagnostics_monitor_view(dict(payload.get("diagnostics") or {})),
    }


def _node_state_monitor_view(node_state: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "node_id",
        "status",
        "executor_type",
        "work_order_id",
        "result_ref",
        "updated_at",
        "created_at",
        "terminal_reason",
    }
    return {
        key: value
        for key, value in node_state.items()
        if key in allowed_keys
    }


def _loop_diagnostics_monitor_view(diagnostics: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "graph_structure_hash",
        "graph_structure_version",
        "runtime_settings_revision",
        "config_runtime_settings_fingerprint",
    }
    return {
        key: value
        for key, value in diagnostics.items()
        if key in allowed_keys
    }


def _task_run_summary(task_run: Any | None) -> dict[str, Any]:
    if task_run is None:
        return {}
    payload = task_run.to_dict() if hasattr(task_run, "to_dict") else (dict(task_run) if isinstance(task_run, dict) else {})
    diagnostics = dict(payload.get("diagnostics") or {})
    origin = dict(diagnostics.get("origin") or {})
    return {
        "task_run_id": str(payload.get("task_run_id") or ""),
        "session_id": str(payload.get("session_id") or ""),
        "task_id": str(payload.get("task_id") or ""),
        "status": str(payload.get("status") or ""),
        "created_at": payload.get("created_at", 0.0),
        "updated_at": payload.get("updated_at", 0.0),
        "terminal_reason": str(payload.get("terminal_reason") or ""),
        "latest_step": diagnostics.get("latest_step") or diagnostics.get("step_summary") or {},
        "latest_step_status": diagnostics.get("latest_step_status") or "",
        "latest_step_summary": diagnostics.get("latest_step_summary") or "",
        "origin_kind": diagnostics.get("origin_kind") or origin.get("origin_kind") or "",
        "graph_run_id": diagnostics.get("graph_run_id") or origin.get("graph_run_id") or "",
        "graph_work_order_id": diagnostics.get("graph_work_order_id") or origin.get("origin_ref") or "",
        "project_id": diagnostics.get("project_id") or "",
        "runtime_scope": dict(diagnostics.get("runtime_scope") or {}),
    }


def _executor_result_summary(result: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(result or {})
    task_run = payload.get("task_run")
    return {
        "ok": bool(payload.get("ok") is True),
        "error": str(payload.get("error") or ""),
        "artifact_refs": dedupe_artifact_refs([normalize_artifact_ref(item) for item in list(payload.get("artifact_refs") or [])]),
        "task_run": _task_run_summary(task_run),
        "event": _event_summary(payload.get("event")),
        "lifecycle": _lifecycle_summary(payload.get("lifecycle")),
    }


def _lifecycle_summary(lifecycle: Any | None) -> dict[str, Any]:
    payload = lifecycle.to_dict() if hasattr(lifecycle, "to_dict") else (dict(lifecycle) if isinstance(lifecycle, dict) else {})
    return {
        "task_run_id": str(payload.get("task_run_id") or ""),
        "contract_ref": str(payload.get("contract_ref") or ""),
        "status": str(payload.get("status") or ""),
        "created_at": payload.get("created_at", 0.0),
        "updated_at": payload.get("updated_at", 0.0),
        "terminal_reason": str(payload.get("terminal_reason") or ""),
        "acceptance_ref_count": len(list(payload.get("acceptance_refs") or [])),
        "observation_ref_count": len(list(payload.get("observation_refs") or [])),
        "authority": str(payload.get("authority") or "harness.loop.task_lifecycle"),
    }


def _event_summary(event: Any | None) -> dict[str, Any]:
    payload = event.to_dict() if hasattr(event, "to_dict") else (dict(event) if isinstance(event, dict) else {})
    return {
        "event_id": str(payload.get("event_id") or ""),
        "event_type": str(payload.get("event_type") or payload.get("type") or ""),
        "task_run_id": str(payload.get("task_run_id") or ""),
        "created_at": payload.get("created_at", 0.0),
        "refs": dict(payload.get("refs") or {}),
        "authority": str(payload.get("authority") or ""),
    }


def _work_order_public_view(order: GraphNodeWorkOrder) -> dict[str, Any]:
    return {
        "authority": "harness.graph_node_work_order_dispatch",
        "work_order_id": order.work_order_id,
        "work_kind": order.work_kind,
        "graph_run_id": order.graph_run_id,
        "task_run_id": order.task_run_id,
        "node_id": order.node_id,
        "config_id": order.config_id,
        "config_hash": order.config_hash,
        "executor_type": order.executor_type,
        "node_session_id": order.node_session_id,
        "node_session_policy": dict(order.node_session_policy or {}),
        "agent_id": order.agent_id,
        "agent_profile_id": order.agent_profile_id,
        "message": order.message,
        "explicit_inputs": dict(order.explicit_inputs or {}),
        "input_package": dict(order.input_package or {}),
        "graph_state": dict(order.graph_state or {}),
        "memory_view_request": dict(order.memory_view_request or {}),
        "artifact_view_request": dict(order.artifact_view_request or {}),
        "file_view_request": dict(order.file_view_request or {}),
        "permission_scope": dict(order.permission_scope or {}),
        "tool_scope": dict(order.tool_scope or {}),
        "expected_result_contract": dict(order.expected_result_contract or {}),
        "dispatch_context": dict(order.dispatch_context or {}),
        "idempotency_key": order.idempotency_key,
    }
