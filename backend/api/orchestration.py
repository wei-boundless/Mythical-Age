from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from harness.graph.models import NodeResultEnvelope
from sessions import InvalidSessionId, validate_session_id
from task_system import TaskFlowRegistry

router = APIRouter()


class TaskGraphRunStartRequest(BaseModel):
    session_id: str = Field(default="task_graph_studio", max_length=180)
    task_id: str = Field(default="", max_length=180)
    initial_inputs: dict[str, Any] = Field(default_factory=dict)
    include_trace: bool = True
    dispatch_ready: bool = True


class GraphNodeResultRequest(BaseModel):
    graph_harness_config_id: str = Field(..., min_length=1, max_length=240)
    result: dict[str, Any] = Field(default_factory=dict)


class GraphRunDispatchReadyRequest(BaseModel):
    graph_harness_config_id: str = Field(..., min_length=1, max_length=240)
    max_requests: int = Field(default=1, ge=1, le=32)


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
    graph_harness = runtime.query_runtime.graph_harness
    start = graph_harness.start_run(
        session_id=session_id,
        task_id=payload.task_id.strip(),
        graph_config=graph_config,
        initial_inputs=dict(payload.initial_inputs or {}),
        diagnostics={"source": "harness.task_graph_start_api"},
        dispatch_ready=payload.dispatch_ready,
    )
    node_work_orders = [item.to_dict() for item in tuple(start.node_work_orders or ())]
    trace = graph_harness.get_trace(start.task_run.task_run_id) if payload.include_trace else None
    return {
        "authority": "harness.api.task_graph_run_start",
        "graph_id": graph_config.graph_id,
        "graph_run_id": start.graph_run.graph_run_id,
        "graph_harness_config_id": graph_config.config_id,
        "task_run_id": start.task_run.task_run_id,
        "task_run": start.task_run.to_dict(),
        "graph_run": start.graph_run.to_dict(),
        "checkpoint": dict(start.checkpoint),
        "graph_loop_state": start.loop_state.to_dict(),
        "graph_harness_config": graph_config.to_dict(),
        "node_work_orders": node_work_orders,
        "trace": trace,
        "events": [dict(item) for item in start.events],
    }


@router.get("/orchestration/harness/graph-runs/{graph_run_id}/monitor")
async def get_graph_run_monitor(graph_run_id: str, graph_harness_config_id: str = "") -> dict[str, Any]:
    runtime = require_runtime()
    graph_config = None
    if graph_harness_config_id:
        graph_config = TaskFlowRegistry(runtime.base_dir).get_graph_harness_config(graph_harness_config_id)
        if graph_config is None:
            raise HTTPException(status_code=404, detail="GraphHarnessConfig not found")
    monitor = runtime.query_runtime.graph_harness.get_graph_run_monitor(
        graph_run_id,
        graph_config=graph_config,
    )
    if monitor is None:
        raise HTTPException(status_code=404, detail="GraphRun monitor not found")
    return monitor


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


def _validated_session_id(value: str) -> str:
    raw = str(value or "").strip() or "task_graph_studio"
    try:
        return validate_session_id(raw)
    except InvalidSessionId as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
