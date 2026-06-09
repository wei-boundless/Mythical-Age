from __future__ import annotations

from typing import Any
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from harness.graph.lifecycle_manager import GraphTaskLifecycleManager
from harness.graph.models import GraphNodeWorkOrder, NodeResultEnvelope, safe_id
from sessions import InvalidSessionId, SessionTaskBindingConflict, SessionTaskBindingMissing, validate_session_id
from task_system import TaskFlowRegistry
from task_system.repositories.project_instance_repository import ProjectInstanceRepository
from task_system.session_scope import (
    SessionScope,
    assert_session_scope,
    normalize_session_scope,
    session_scope_key,
    session_scope_matches,
)

router = APIRouter()


class TaskGraphRunStartRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=180)
    task_id: str = Field(default="", max_length=180)
    session_scope: dict[str, Any] | None = None
    initial_inputs: dict[str, Any] = Field(default_factory=dict)
    include_trace: bool = True
    include_graph_harness_config: bool = False
    dispatch_ready: bool = True
    run_mode: str = Field(default="dispatch_only", max_length=32)
    runner_budget: dict[str, Any] = Field(default_factory=dict)
    runtime_overrides: dict[str, Any] = Field(default_factory=dict)
    runtime_settings_patch: dict[str, Any] = Field(default_factory=dict)


class GraphNodeResultRequest(BaseModel):
    graph_harness_config_id: str = Field(..., min_length=1, max_length=240)
    session_scope: dict[str, Any] | None = None
    result: dict[str, Any] = Field(default_factory=dict)


class GraphRunDispatchReadyRequest(BaseModel):
    graph_harness_config_id: str = Field(..., min_length=1, max_length=240)
    session_scope: dict[str, Any] | None = None
    max_requests: int = Field(default=1, ge=1, le=32)


class GraphRunResumeRequest(BaseModel):
    graph_harness_config_id: str = Field(..., min_length=1, max_length=240)
    session_scope: dict[str, Any] | None = None
    dispatch_ready: bool = True
    max_requests: int | None = Field(default=None, ge=1, le=32)


class GraphRunRequeueNodesRequest(BaseModel):
    graph_harness_config_id: str = Field(..., min_length=1, max_length=240)
    session_scope: dict[str, Any] | None = None
    start_node_ids: list[str] = Field(default_factory=list)
    runtime_settings_patch: dict[str, Any] = Field(default_factory=dict)
    reset_downstream: bool = True


class GraphWorkOrderExecuteRequest(BaseModel):
    graph_harness_config_id: str = Field(..., min_length=1, max_length=240)
    session_scope: dict[str, Any] | None = None
    work_order: dict[str, Any] = Field(default_factory=dict)
    runtime_overrides: dict[str, Any] = Field(default_factory=dict)
    runtime_settings_patch: dict[str, Any] = Field(default_factory=dict)
    max_steps: int = Field(default=12, ge=1, le=50)
    accept_result: bool = True


class GraphRunUntilIdleRequest(BaseModel):
    graph_harness_config_id: str = Field(..., min_length=1, max_length=240)
    session_scope: dict[str, Any] | None = None
    runtime_overrides: dict[str, Any] = Field(default_factory=dict)
    runtime_settings_patch: dict[str, Any] = Field(default_factory=dict)
    max_node_executions: int = Field(default=64, ge=0, le=512)
    max_loop_iterations: int = Field(default=128, ge=1, le=1024)
    max_node_steps: int = Field(default=12, ge=1, le=50)
    max_dispatches: int = Field(default=64, ge=0, le=512)
    max_runtime_seconds: float = Field(default=0.0, ge=0.0, le=3600.0)
    max_dispatch_requests: int | None = Field(default=None, ge=1, le=32)


class GraphRunDeleteRequest(BaseModel):
    session_scope: dict[str, Any] | None = None
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
    launch_session_id = _validated_session_id(payload.session_id)
    resolved_scope = _validated_graph_request_scope(
        runtime=runtime,
        graph_config=graph_config,
        session_id=launch_session_id,
        session_scope=payload.session_scope,
    )
    run_mode = _validated_graph_start_run_mode(payload.run_mode)
    graph_harness = runtime.harness_runtime.graph_harness
    graph_session_id = _create_graph_run_session(
        runtime=runtime,
        graph_config=graph_config,
        scope=resolved_scope,
    )
    start = None
    try:
        start = graph_harness.start_run(
            session_id=graph_session_id,
            task_id=payload.task_id.strip(),
            graph_config=graph_config,
            initial_inputs=_graph_start_initial_inputs(payload.initial_inputs, resolved_scope),
            diagnostics={
                "source": "harness.task_graph_start_api",
                "launch_session_id": launch_session_id,
                "graph_root_session_id": graph_session_id,
                "session_scope": resolved_scope.to_dict(),
                "session_scope_key": resolved_scope.key,
                "workspace_view": resolved_scope.workspace_view,
                "project_id": resolved_scope.project_id,
                "runtime_scope": resolved_scope.to_dict(),
            },
            dispatch_ready=False,
        )
        runtime.session_manager.bind_session_graph_instance(
            graph_session_id,
            graph_run_id=start.graph_run.graph_run_id,
            task_run_id=start.task_run.task_run_id,
            graph_id=graph_config.graph_id,
            graph_harness_config_id=graph_config.config_id,
            session_scope=resolved_scope.to_dict(),
            task_environment_id="",
            project_id=resolved_scope.project_id,
        )
    except (SessionTaskBindingConflict, SessionTaskBindingMissing) as exc:
        if start is not None:
            GraphTaskLifecycleManager(
                base_dir=runtime.base_dir,
                graph_harness=graph_harness,
            ).delete_graph_run(start.graph_run.graph_run_id)
        _delete_graph_run_session(runtime=runtime, graph_session_id=graph_session_id)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        _delete_graph_run_session(runtime=runtime, graph_session_id=graph_session_id)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    events = [dict(item) for item in start.events]
    node_work_orders = [item.to_dict() for item in tuple(start.node_work_orders or ())]
    response_loop_state = start.loop_state.to_dict()
    response_checkpoint = dict(start.checkpoint)
    if payload.dispatch_ready:
        try:
            dispatch = graph_harness.graph_loop.dispatch_ready_and_checkpoint(
                graph_config=graph_config,
                graph_run_id=start.graph_run.graph_run_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        node_work_orders = [item.to_dict() for item in tuple(dispatch.node_work_orders or ())]
        response_loop_state = dispatch.loop_state.to_dict()
        response_checkpoint = dict(dispatch.checkpoint)
        events.extend(dict(item) for item in dispatch.events)
    if payload.runtime_settings_patch and run_mode != "auto_run":
        try:
            patched = graph_harness.apply_runtime_settings_patch(
                graph_run_id=start.graph_run.graph_run_id,
                runtime_settings_patch=dict(payload.runtime_settings_patch or {}),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        response_loop_state = dict(patched.get("graph_loop_state") or response_loop_state)
        response_checkpoint = dict(patched.get("checkpoint") or response_checkpoint)
        events.extend(dict(item) for item in list(patched.get("events") or []) if isinstance(item, dict))
    runner_result = None
    if run_mode == "auto_run":
        try:
            runner_result = await graph_harness.run_until_idle(
                graph_config=graph_config,
                graph_run_id=start.graph_run.graph_run_id,
                runtime_overrides=dict(payload.runtime_overrides or {}),
                runtime_settings_patch=dict(payload.runtime_settings_patch or {}),
                **_runner_budget_kwargs(payload.runner_budget),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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
        "launch_session_id": launch_session_id,
        "graph_session_id": graph_session_id,
        "task_run_id": start.task_run.task_run_id,
        "task_run": response_task_run,
        "graph_run": response_graph_run,
        "checkpoint": response_checkpoint,
        "graph_loop_state": response_loop_state,
        "graph_harness_config": _graph_config_api_view(graph_config, include_config=payload.include_graph_harness_config),
        "node_work_orders": node_work_orders,
        "runner_result": runner_result.to_dict() if runner_result is not None else None,
        "trace": trace,
        "events": events,
    }


@router.get("/orchestration/harness/task-graphs/{graph_id}/published-config")
async def get_published_task_graph_harness_config(graph_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    graph_config = TaskFlowRegistry(runtime.base_dir).get_published_graph_harness_config(graph_id)
    if graph_config is None:
        raise HTTPException(status_code=404, detail="GraphHarnessConfig not found")
    return _graph_config_api_view(graph_config, include_config=True)


@router.get("/orchestration/harness/graph-runs/{graph_run_id}/monitor")
async def get_graph_run_monitor(
    graph_run_id: str,
    graph_harness_config_id: str = "",
    event_limit: int = 80,
    include_config: bool = False,
    workspace_view: str | None = None,
    task_environment_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    runtime = require_runtime()
    graph_config = None
    if graph_harness_config_id:
        graph_config = TaskFlowRegistry(runtime.base_dir).get_graph_harness_config(graph_harness_config_id)
        if graph_config is None:
            raise HTTPException(status_code=404, detail="GraphHarnessConfig not found")
    _assert_graph_run_scope(
        runtime=runtime,
        graph_run_id=graph_run_id,
        graph_harness_config_id=graph_harness_config_id,
        session_scope=_session_scope_from_query(
            workspace_view=workspace_view,
            task_environment_id=task_environment_id,
            project_id=project_id,
        ),
        graph_config=graph_config,
    )
    monitor = runtime.harness_runtime.graph_harness.get_graph_run_monitor(
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
    request = payload or GraphRunDeleteRequest()
    if not request.dry_run:
        raise HTTPException(
            status_code=409,
            detail="GraphRun deletion is owned by session deletion; delete the bound session instead.",
        )
    _assert_graph_run_scope(
        runtime=runtime,
        graph_run_id=graph_run_id,
        graph_harness_config_id="",
        session_scope=request.session_scope,
    )
    manager = GraphTaskLifecycleManager(
        base_dir=runtime.base_dir,
        graph_harness=runtime.harness_runtime.graph_harness,
    )
    try:
        return manager.preview_delete_graph_run(graph_run_id)
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
    _assert_graph_run_scope(
        runtime=runtime,
        graph_run_id=graph_run_id,
        graph_harness_config_id=graph_config.config_id,
        graph_config=graph_config,
        session_scope=payload.session_scope,
    )
    try:
        result = runtime.harness_runtime.graph_harness.resume_run(
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
    _assert_graph_run_scope(
        runtime=runtime,
        graph_run_id=graph_run_id,
        graph_harness_config_id=graph_config.config_id,
        graph_config=graph_config,
        session_scope=payload.session_scope,
    )
    if runtime.harness_runtime.graph_harness.graph_loop.get_state(graph_run_id) is None:
        raise HTTPException(status_code=404, detail="GraphLoopState not found")
    dispatch = runtime.harness_runtime.graph_harness.graph_loop.dispatch_ready_and_checkpoint(
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


@router.post("/orchestration/harness/graph-runs/{graph_run_id}/requeue-nodes")
async def requeue_graph_run_nodes(
    graph_run_id: str,
    payload: GraphRunRequeueNodesRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    graph_config = TaskFlowRegistry(runtime.base_dir).get_graph_harness_config(payload.graph_harness_config_id)
    if graph_config is None:
        raise HTTPException(status_code=404, detail="GraphHarnessConfig not found")
    _assert_graph_run_scope(
        runtime=runtime,
        graph_run_id=graph_run_id,
        graph_harness_config_id=graph_config.config_id,
        graph_config=graph_config,
        session_scope=payload.session_scope,
    )
    try:
        requeue = runtime.harness_runtime.graph_harness.graph_loop.requeue_nodes_and_checkpoint(
            graph_config=graph_config,
            graph_run_id=graph_run_id,
            start_node_ids=tuple(payload.start_node_ids or ()),
            runtime_settings_patch=dict(payload.runtime_settings_patch or {}),
            reset_downstream=payload.reset_downstream,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "authority": "harness.api.graph_run_requeue_nodes",
        "graph_run_id": graph_run_id,
        "graph_harness_config_id": graph_config.config_id,
        "graph_structure_hash": requeue.loop_state.structure_hash,
        "graph_loop_state": requeue.loop_state.to_dict(),
        "checkpoint": dict(requeue.checkpoint),
        "events": [dict(item) for item in requeue.events],
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
    _assert_graph_run_scope(
        runtime=runtime,
        graph_run_id=graph_run_id,
        graph_harness_config_id=graph_config.config_id,
        graph_config=graph_config,
        session_scope=payload.session_scope,
    )
    result_payload = {
        **dict(payload.result or {}),
        "graph_run_id": str(dict(payload.result or {}).get("graph_run_id") or graph_run_id),
    }
    try:
        advance = runtime.harness_runtime.graph_harness.accept_node_result(
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
    _assert_graph_run_scope(
        runtime=runtime,
        graph_run_id=graph_run_id,
        graph_harness_config_id=graph_config.config_id,
        graph_config=graph_config,
        session_scope=payload.session_scope,
    )
    work_order_payload = {
        **dict(payload.work_order or {}),
        "graph_run_id": str(dict(payload.work_order or {}).get("graph_run_id") or graph_run_id),
    }
    try:
        work_order = GraphNodeWorkOrder.from_dict(work_order_payload)
        if work_order.graph_run_id != graph_run_id:
            raise ValueError("GraphNodeWorkOrder graph_run_id does not match route graph_run_id")
        return await runtime.harness_runtime.graph_harness.execute_work_order(
            graph_config=graph_config,
            work_order=work_order,
            max_steps=payload.max_steps,
            accept_result=payload.accept_result,
            runtime_overrides=dict(payload.runtime_overrides or {}),
            runtime_settings_patch=dict(payload.runtime_settings_patch or {}),
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
    _assert_graph_run_scope(
        runtime=runtime,
        graph_run_id=graph_run_id,
        graph_harness_config_id=graph_config.config_id,
        graph_config=graph_config,
        session_scope=payload.session_scope,
    )
    if runtime.harness_runtime.graph_harness.graph_loop.get_state(graph_run_id) is None:
        raise HTTPException(status_code=404, detail="GraphLoopState not found")
    try:
        result = await runtime.harness_runtime.graph_harness.run_until_idle(
            graph_config=graph_config,
            graph_run_id=graph_run_id,
            max_node_executions=payload.max_node_executions,
            max_loop_iterations=payload.max_loop_iterations,
            max_node_steps=payload.max_node_steps,
            max_dispatches=payload.max_dispatches,
            max_runtime_seconds=payload.max_runtime_seconds,
            max_dispatch_requests=payload.max_dispatch_requests,
            runtime_overrides=dict(payload.runtime_overrides or {}),
            runtime_settings_patch=dict(payload.runtime_settings_patch or {}),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.to_dict()


def _validated_session_id(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="session_id is required")
    try:
        return validate_session_id(raw)
    except InvalidSessionId as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validated_graph_start_run_mode(value: str) -> str:
    mode = str(value or "dispatch_only").strip()
    if mode not in {"dispatch_only", "auto_run"}:
        raise HTTPException(status_code=400, detail="run_mode must be dispatch_only or auto_run")
    return mode


def _validated_graph_request_scope(
    *,
    runtime: Any,
    graph_config: Any,
    session_id: str,
    session_scope: dict[str, Any] | None,
) -> SessionScope:
    launch_scope = _require_launch_session(runtime=runtime, session_id=session_id)
    requested = normalize_session_scope(session_scope) if session_scope is not None else launch_scope
    if requested is not None and requested.workspace_view not in {"project", "task_environment"}:
        raise HTTPException(status_code=400, detail="graph task runs must use project or task_environment scope")
    project_id = requested.project_id
    task_environment_id = requested.task_environment_id
    workspace_view = requested.workspace_view
    if project_id:
        workspace_view = "project"
    elif workspace_view == "project":
        workspace_view = "task_environment"
    resolved = normalize_session_scope(
        {
            "workspace_view": workspace_view or "task_environment",
            "task_environment_id": task_environment_id,
            "project_id": project_id,
        }
    )
    if _graph_config_requires_project(graph_config) and not resolved.project_id:
        raise HTTPException(status_code=400, detail="project_id is required for graph runs with project-scoped resources")
    if resolved.project_id:
        try:
            project = ProjectInstanceRepository(runtime.base_dir).require(resolved.project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not resolved.task_environment_id:
            resolved = normalize_session_scope({**resolved.to_dict(), "task_environment_id": project.environment_id})
        if project.environment_id != resolved.task_environment_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Project does not belong to task environment",
                    "project_id": resolved.project_id,
                    "project_environment_id": project.environment_id,
                    "task_environment_id": resolved.task_environment_id,
                },
            )
    return _graph_instance_scope(resolved)


def _assert_graph_run_scope(
    *,
    runtime: Any,
    graph_run_id: str,
    graph_harness_config_id: str,
    session_scope: dict[str, Any] | None,
    graph_config: Any | None = None,
) -> SessionScope:
    expected = _graph_instance_scope(normalize_session_scope(session_scope)) if session_scope is not None else None
    graph_run_payload = runtime.harness_runtime.graph_harness.get_graph_run(graph_run_id)
    if not graph_run_payload:
        raise HTTPException(status_code=404, detail="GraphRun not found")
    graph_run = dict(graph_run_payload)
    if graph_config is not None:
        if str(graph_run.get("graph_id") or "") != str(graph_config.graph_id or ""):
            raise HTTPException(status_code=409, detail="GraphRun graph_id does not match GraphHarnessConfig")
        run_structure_hash = str(
            graph_run.get("structure_hash")
            or dict(graph_run.get("diagnostics") or {}).get("graph_structure_hash")
            or ""
        ).strip()
        config_structure_hash = graph_config.expected_structural_hash()
        if not run_structure_hash and str(graph_run.get("config_hash") or "") == str(graph_config.content_hash or ""):
            run_structure_hash = config_structure_hash
        if run_structure_hash and run_structure_hash != config_structure_hash:
            raise HTTPException(status_code=409, detail="GraphRun structure_hash does not match GraphHarnessConfig")
    actual_scope = normalize_session_scope(
        {
            "workspace_view": graph_run.get("workspace_view") or dict(graph_run.get("diagnostics") or {}).get("workspace_view") or "task_environment",
            "task_environment_id": graph_run.get("task_environment_id") or dict(graph_run.get("diagnostics") or {}).get("task_environment_id") or "",
            "project_id": graph_run.get("project_id") or dict(graph_run.get("diagnostics") or {}).get("project_id") or "",
        }
    )
    if expected is not None and not session_scope_matches(actual_scope, expected):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "GraphRun scope mismatch",
                "graph_run_id": graph_run_id,
                "actual_scope": actual_scope.to_dict(),
                "expected_scope": expected.to_dict(),
            },
        )
    session_id = str(graph_run.get("session_id") or "")
    if not session_id:
        raise HTTPException(status_code=409, detail="GraphRun is not bound to a session")
    try:
        assert_session_scope(runtime.session_manager, session_id, actual_scope, allow_missing_scope=False)
    except ValueError as exc:
        if str(exc) == "Unknown session_id":
            raise HTTPException(
                status_code=404,
                detail={
                    "message": "GraphRun session is missing",
                    "session_id": session_id,
                    "graph_run_id": graph_run_id,
                },
            ) from exc
        raise
    try:
        runtime.session_manager.assert_session_graph_instance(session_id, graph_run_id)
    except (SessionTaskBindingConflict, SessionTaskBindingMissing, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "GraphRun does not match session task binding",
                "session_id": session_id,
                "graph_run_id": graph_run_id,
                "reason": str(exc),
            },
        ) from exc
    if graph_run.get("session_scope_key") and str(graph_run.get("session_scope_key") or "") != session_scope_key(actual_scope):
        raise HTTPException(status_code=409, detail="GraphRun session scope key mismatch")
    return actual_scope


def _session_scope_from_query(
    *,
    workspace_view: str | None,
    task_environment_id: str | None,
    project_id: str | None,
) -> dict[str, str] | None:
    if workspace_view is None and task_environment_id is None and project_id is None:
        return None
    return {
        "workspace_view": str(workspace_view or "").strip(),
        "task_environment_id": str(task_environment_id or "").strip(),
        "project_id": str(project_id or "").strip(),
    }


def _graph_start_initial_inputs(initial_inputs: dict[str, Any] | None, scope: SessionScope) -> dict[str, Any]:
    payload = dict(initial_inputs or {})
    runtime_scope = {
        **dict(payload.get("runtime_scope") or {}),
        **scope.to_dict(),
        "scope_source": "harness.api.task_graph_run_start.graph_binding_contract",
    }
    payload["runtime_scope"] = runtime_scope
    payload["workspace_view"] = scope.workspace_view
    payload["project_id"] = scope.project_id
    return payload


def _graph_instance_scope(scope: SessionScope) -> SessionScope:
    return normalize_session_scope(
        {
            "workspace_view": scope.workspace_view,
            "task_environment_id": "",
            "project_id": scope.project_id,
        }
    )


def _require_launch_session(*, runtime: Any, session_id: str) -> SessionScope:
    try:
        record = runtime.session_manager.load_session_record(session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={"message": "Launch session not found", "session_id": session_id},
        ) from exc
    return normalize_session_scope(dict(record.get("scope") or {}))


def _create_graph_run_session(*, runtime: Any, graph_config: Any, scope: SessionScope) -> str:
    graph_id = str(getattr(graph_config, "graph_id", "") or "graph")
    graph_session_id = f"graph-session-{safe_id(graph_id)}-{uuid.uuid4().hex[:12]}"
    create = getattr(runtime.session_manager, "create_session", None)
    if callable(create):
        title = str(getattr(graph_config, "graph_title", "") or graph_id)
        create(
            session_id=graph_session_id,
            title=f"Graph run - {title}",
            scope=scope.to_dict(),
        )
    return graph_session_id


def _delete_graph_run_session(*, runtime: Any, graph_session_id: str) -> None:
    delete = getattr(runtime.session_manager, "delete_session", None)
    if not callable(delete):
        return
    try:
        delete(graph_session_id)
    except Exception:
        pass


def _graph_config_requires_project(graph_config: Any) -> bool:
    environment = dict(getattr(graph_config, "environment", {}) or {})
    file_management = dict(environment.get("file_management") or {})
    storage_space = dict(environment.get("storage_space") or {})
    project_policy = str(
        file_management.get("project_file_policy")
        or storage_space.get("workspace_policy")
        or environment.get("project_file_policy")
        or ""
    ).strip().lower()
    if project_policy and project_policy not in {"none", "disabled", "conversation_only"}:
        return True
    return bool(file_management.get("required_repository_kinds") or storage_space.get("required_repository_kinds"))


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
