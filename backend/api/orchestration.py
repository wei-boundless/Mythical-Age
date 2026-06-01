from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from harness.graph.lifecycle_manager import GraphTaskLifecycleManager
from harness.graph.models import GraphNodeWorkOrder, NodeResultEnvelope
from sessions import InvalidSessionId, validate_session_id
from task_system import TaskFlowRegistry

router = APIRouter()


class TaskGraphRunStartRequest(BaseModel):
    session_id: str = Field(default="task_graph_studio", max_length=180)
    task_id: str = Field(default="", max_length=180)
    initial_inputs: dict[str, Any] = Field(default_factory=dict)
    include_trace: bool = True
    include_graph_harness_config: bool = False
    dispatch_ready: bool = True
    run_mode: str = Field(default="dispatch_only", max_length=32)
    runner_budget: dict[str, Any] = Field(default_factory=dict)


class GraphNodeResultRequest(BaseModel):
    graph_harness_config_id: str = Field(..., min_length=1, max_length=240)
    result: dict[str, Any] = Field(default_factory=dict)


class GraphRunDispatchReadyRequest(BaseModel):
    graph_harness_config_id: str = Field(..., min_length=1, max_length=240)
    max_requests: int = Field(default=1, ge=1, le=32)


class GraphRunResumeRequest(BaseModel):
    graph_harness_config_id: str = Field(..., min_length=1, max_length=240)
    dispatch_ready: bool = True
    max_requests: int | None = Field(default=None, ge=1, le=32)


class GraphWorkOrderExecuteRequest(BaseModel):
    graph_harness_config_id: str = Field(..., min_length=1, max_length=240)
    work_order: dict[str, Any] = Field(default_factory=dict)
    max_steps: int = Field(default=12, ge=1, le=50)
    accept_result: bool = True


class GraphRunUntilIdleRequest(BaseModel):
    graph_harness_config_id: str = Field(..., min_length=1, max_length=240)
    max_node_executions: int = Field(default=64, ge=0, le=512)
    max_loop_iterations: int = Field(default=128, ge=1, le=1024)
    max_node_steps: int = Field(default=12, ge=1, le=50)
    max_dispatches: int = Field(default=64, ge=0, le=512)
    max_runtime_seconds: float = Field(default=0.0, ge=0.0, le=3600.0)
    max_dispatch_requests: int | None = Field(default=None, ge=1, le=32)


class GraphRunDeleteRequest(BaseModel):
    dry_run: bool = False


@router.post("/orchestration/harness/task-graphs/{graph_id}/start")
async def start_task_graph_harness_run(
    graph_id: str,
    payload: TaskGraphRunStartRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    graph_config = registry.get_published_graph_harness_config(graph_id)
    if graph_config is None:
        graph = registry.get_task_graph(graph_id)
        if graph is None:
            raise HTTPException(status_code=404, detail="TaskGraph not found")
        raise HTTPException(
            status_code=409,
            detail={
                "message": "TaskGraph has no published GraphHarnessConfig; publish the graph config before run start.",
                "graph_id": graph_id,
            },
        )
    session_id = _validated_session_id(payload.session_id)
    run_mode = _validated_graph_start_run_mode(payload.run_mode)
    graph_harness = runtime.query_runtime.graph_harness
    try:
        start = graph_harness.start_run(
            session_id=session_id,
            task_id=payload.task_id.strip(),
            graph_config=graph_config,
            initial_inputs=dict(payload.initial_inputs or {}),
            diagnostics={"source": "harness.task_graph_start_api"},
            dispatch_ready=payload.dispatch_ready,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    runner_result = None
    if run_mode == "auto_run":
        try:
            runner_result = await graph_harness.run_until_idle(
                graph_config=graph_config,
                graph_run_id=start.graph_run.graph_run_id,
                **_runner_budget_kwargs(payload.runner_budget),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    node_work_orders = [item.to_dict() for item in tuple(start.node_work_orders or ())]
    response_loop_state = start.loop_state.to_dict()
    response_checkpoint = dict(start.checkpoint)
    response_task_run = start.task_run.to_dict()
    response_graph_run = start.graph_run.to_dict()
    if runner_result is not None:
        response_loop_state = dict(runner_result.loop_state)
        response_checkpoint = graph_harness.get_latest_checkpoint(start.graph_run.graph_run_id)
        latest_task_run = graph_harness.get_task_run(start.task_run.task_run_id)
        if latest_task_run is not None:
            response_task_run = latest_task_run.to_dict() if hasattr(latest_task_run, "to_dict") else dict(latest_task_run)
        latest_graph_run = graph_harness.get_graph_run(start.graph_run.graph_run_id)
        if latest_graph_run:
            response_graph_run = latest_graph_run.to_dict() if hasattr(latest_graph_run, "to_dict") else dict(latest_graph_run)
        monitor = graph_harness.get_graph_run_monitor(start.graph_run.graph_run_id, graph_config=graph_config)
        node_work_orders = [dict(item) for item in list(dict(monitor or {}).get("active_node_work_orders") or [])]
    trace = graph_harness.get_trace(start.task_run.task_run_id) if payload.include_trace else None
    return {
        "authority": "harness.api.task_graph_run_start",
        "graph_id": graph_config.graph_id,
        "graph_run_id": start.graph_run.graph_run_id,
        "graph_harness_config_id": graph_config.config_id,
        "task_run_id": start.task_run.task_run_id,
        "task_run": response_task_run,
        "graph_run": response_graph_run,
        "checkpoint": response_checkpoint,
        "graph_loop_state": response_loop_state,
        "graph_harness_config": _graph_config_api_view(graph_config, include_config=payload.include_graph_harness_config),
        "node_work_orders": node_work_orders,
        "runner_result": runner_result.to_dict() if runner_result is not None else None,
        "trace": trace,
        "events": [dict(item) for item in start.events],
    }


@router.get("/orchestration/harness/graph-runs/{graph_run_id}/monitor")
async def get_graph_run_monitor(
    graph_run_id: str,
    graph_harness_config_id: str = "",
    event_limit: int = 80,
    include_config: bool = False,
) -> dict[str, Any]:
    runtime = require_runtime()
    graph_config = None
    if graph_harness_config_id:
        graph_config = TaskFlowRegistry(runtime.base_dir).get_graph_harness_config(graph_harness_config_id)
        if graph_config is None:
            raise HTTPException(status_code=404, detail="GraphHarnessConfig not found")
    monitor = runtime.query_runtime.graph_harness.get_graph_run_monitor(
        graph_run_id,
        graph_config=graph_config,
        event_limit=max(1, min(int(event_limit or 80), 240)),
        include_config=include_config,
    )
    if monitor is None:
        raise HTTPException(status_code=404, detail="GraphRun monitor not found")
    return monitor


@router.delete("/orchestration/harness/graph-runs/{graph_run_id}")
async def delete_graph_task_run(graph_run_id: str, payload: GraphRunDeleteRequest | None = None) -> dict[str, Any]:
    runtime = require_runtime()
    manager = GraphTaskLifecycleManager(
        base_dir=runtime.base_dir,
        graph_harness=runtime.query_runtime.graph_harness,
    )
    request = payload or GraphRunDeleteRequest()
    try:
        if request.dry_run:
            return manager.preview_delete_graph_run(graph_run_id)
        return manager.delete_graph_run(graph_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/orchestration/harness/graph-runs/{graph_run_id}/resume")
async def resume_graph_run(
    graph_run_id: str,
    payload: GraphRunResumeRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    graph_config = TaskFlowRegistry(runtime.base_dir).get_graph_harness_config(payload.graph_harness_config_id)
    if graph_config is None:
        raise HTTPException(status_code=404, detail="GraphHarnessConfig not found")
    try:
        result = runtime.query_runtime.graph_harness.resume_run(
            graph_config=graph_config,
            graph_run_id=graph_run_id,
            dispatch_ready=payload.dispatch_ready,
            max_requests=payload.max_requests,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.to_dict()


@router.post("/orchestration/harness/graph-runs/{graph_run_id}/dispatch-ready")
async def dispatch_graph_run_ready_nodes(
    graph_run_id: str,
    payload: GraphRunDispatchReadyRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    graph_config = TaskFlowRegistry(runtime.base_dir).get_graph_harness_config(payload.graph_harness_config_id)
    if graph_config is None:
        raise HTTPException(status_code=404, detail="GraphHarnessConfig not found")
    if runtime.query_runtime.graph_harness.graph_loop.get_state(graph_run_id) is None:
        raise HTTPException(status_code=404, detail="GraphLoopState not found")
    dispatch = runtime.query_runtime.graph_harness.graph_loop.dispatch_ready_and_checkpoint(
        graph_config=graph_config,
        graph_run_id=graph_run_id,
        max_requests=payload.max_requests,
    )
    return {
        "authority": "harness.api.graph_run_dispatch_ready",
        "graph_run_id": graph_run_id,
        "graph_harness_config_id": graph_config.config_id,
        "graph_loop_state": dispatch.loop_state.to_dict(),
        "checkpoint": dict(dispatch.checkpoint),
        "node_work_orders": [item.to_dict() for item in dispatch.node_work_orders],
        "work_order_count": len(dispatch.node_work_orders),
        "events": [dict(item) for item in dispatch.events],
    }


@router.post("/orchestration/harness/graph-runs/{graph_run_id}/node-results")
async def accept_graph_node_result(
    graph_run_id: str,
    payload: GraphNodeResultRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    graph_config = TaskFlowRegistry(runtime.base_dir).get_graph_harness_config(payload.graph_harness_config_id)
    if graph_config is None:
        raise HTTPException(status_code=404, detail="GraphHarnessConfig not found")
    result_payload = {
        **dict(payload.result or {}),
        "graph_run_id": str(dict(payload.result or {}).get("graph_run_id") or graph_run_id),
    }
    try:
        advance = runtime.query_runtime.graph_harness.accept_node_result(
            graph_config=graph_config,
            graph_run_id=graph_run_id,
            result=NodeResultEnvelope.from_dict(result_payload),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "authority": "harness.api.graph_node_result_accept",
        "graph_run_id": graph_run_id,
        "graph_harness_config_id": graph_config.config_id,
        "accepted_result": advance.accepted_result.to_dict() if advance.accepted_result is not None else None,
        "graph_result": advance.graph_result.to_dict() if advance.graph_result is not None else None,
        "graph_loop_state": advance.loop_state.to_dict(),
        "checkpoint": dict(advance.checkpoint),
        "node_work_orders": [item.to_dict() for item in advance.node_work_orders],
        "events": [dict(item) for item in advance.events],
    }


@router.post("/orchestration/harness/graph-runs/{graph_run_id}/work-orders/execute")
async def execute_graph_work_order(
    graph_run_id: str,
    payload: GraphWorkOrderExecuteRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    graph_config = TaskFlowRegistry(runtime.base_dir).get_graph_harness_config(payload.graph_harness_config_id)
    if graph_config is None:
        raise HTTPException(status_code=404, detail="GraphHarnessConfig not found")
    work_order_payload = {
        **dict(payload.work_order or {}),
        "graph_run_id": str(dict(payload.work_order or {}).get("graph_run_id") or graph_run_id),
    }
    try:
        work_order = GraphNodeWorkOrder.from_dict(work_order_payload)
        if work_order.graph_run_id != graph_run_id:
            raise ValueError("GraphNodeWorkOrder graph_run_id does not match route graph_run_id")
        return await runtime.query_runtime.graph_harness.execute_work_order(
            graph_config=graph_config,
            work_order=work_order,
            max_steps=payload.max_steps,
            accept_result=payload.accept_result,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/orchestration/harness/graph-runs/{graph_run_id}/run-until-idle")
async def run_graph_run_until_idle(
    graph_run_id: str,
    payload: GraphRunUntilIdleRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    graph_config = TaskFlowRegistry(runtime.base_dir).get_graph_harness_config(payload.graph_harness_config_id)
    if graph_config is None:
        raise HTTPException(status_code=404, detail="GraphHarnessConfig not found")
    if runtime.query_runtime.graph_harness.graph_loop.get_state(graph_run_id) is None:
        raise HTTPException(status_code=404, detail="GraphLoopState not found")
    try:
        result = await runtime.query_runtime.graph_harness.run_until_idle(
            graph_config=graph_config,
            graph_run_id=graph_run_id,
            max_node_executions=payload.max_node_executions,
            max_loop_iterations=payload.max_loop_iterations,
            max_node_steps=payload.max_node_steps,
            max_dispatches=payload.max_dispatches,
            max_runtime_seconds=payload.max_runtime_seconds,
            max_dispatch_requests=payload.max_dispatch_requests,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.to_dict()


def _validated_session_id(value: str) -> str:
    raw = str(value or "").strip() or "task_graph_studio"
    try:
        return validate_session_id(raw)
    except InvalidSessionId as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validated_graph_start_run_mode(value: str) -> str:
    mode = str(value or "dispatch_only").strip()
    if mode not in {"dispatch_only", "auto_run"}:
        raise HTTPException(status_code=400, detail="run_mode must be dispatch_only or auto_run")
    return mode


def _graph_config_api_view(graph_config: Any, *, include_config: bool = False) -> dict[str, Any]:
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


def _runner_budget_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    budget = dict(payload or {})
    return {
        "max_node_executions": _int_budget(budget.get("max_node_executions"), 64, minimum=0, maximum=512),
        "max_loop_iterations": _int_budget(budget.get("max_loop_iterations"), 128, minimum=1, maximum=1024),
        "max_node_steps": _int_budget(budget.get("max_node_steps"), 12, minimum=1, maximum=50),
        "max_dispatches": _int_budget(budget.get("max_dispatches"), 64, minimum=0, maximum=512),
        "max_runtime_seconds": _float_budget(budget.get("max_runtime_seconds"), 0.0, minimum=0.0, maximum=3600.0),
        "max_dispatch_requests": _optional_int_budget(budget.get("max_dispatch_requests"), minimum=1, maximum=32),
    }


def _int_budget(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))


def _optional_int_budget(value: Any, *, minimum: int, maximum: int) -> int | None:
    if value is None or value == "":
        return None
    return _int_budget(value, minimum, minimum=minimum, maximum=maximum)


def _float_budget(value: Any, default: float, *, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))
