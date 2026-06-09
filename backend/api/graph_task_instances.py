from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from api.orchestration import (
    GRAPH_TASK_WORKSPACE_VIEW,
    TaskGraphRunStartRequest,
    start_task_graph_harness_run,
)
from sessions import InvalidSessionId
from task_system import TaskFlowRegistry
from task_system.graph_instances import GraphTaskInstanceFileService, GraphTaskInstanceRepository


router = APIRouter()


class GraphTaskInstanceCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphTaskInstancePatchRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, max_length=80)
    metadata: dict[str, Any] | None = None


class GraphTaskInstanceRunStartRequest(BaseModel):
    initial_inputs: dict[str, Any] = Field(default_factory=dict)
    dispatch_ready: bool = True
    run_mode: str = Field(default="auto_run", max_length=32)
    wait_for_completion: bool = False
    runner_budget: dict[str, Any] = Field(default_factory=dict)
    runtime_overrides: dict[str, Any] = Field(default_factory=dict)
    runtime_settings_patch: dict[str, Any] = Field(default_factory=dict)


class GraphTaskInstanceFileWriteRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1000)
    content: str = ""


@router.get("/orchestration/graph-tasks")
async def list_graph_tasks() -> dict[str, Any]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    graphs = []
    for graph in registry.list_task_graphs():
        graphs.append(
            {
                "graph_id": graph.graph_id,
                "title": graph.title,
                "domain_id": graph.domain_id,
                "graph_kind": graph.graph_kind,
                "publish_state": graph.publish_state,
                "enabled": graph.enabled,
                "metadata": dict(graph.metadata or {}),
            }
        )
    return {
        "authority": "api.graph_task_instances.graph_tasks",
        "graph_tasks": graphs,
        "summary": {"graph_task_count": len(graphs)},
    }


@router.get("/orchestration/graph-tasks/{graph_id}/instances")
async def list_graph_task_instances(graph_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.get_task_graph(graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="TaskGraph not found")
    instances = [item.to_dict() for item in GraphTaskInstanceRepository(runtime.base_dir).list_for_graph(graph_id)]
    return {
        "authority": "api.graph_task_instances.list",
        "graph_id": graph_id,
        "instances": instances,
        "summary": {"instance_count": len(instances)},
    }


@router.post("/orchestration/graph-tasks/{graph_id}/instances")
async def create_graph_task_instance(graph_id: str, payload: GraphTaskInstanceCreateRequest) -> dict[str, Any]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.get_task_graph(graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="TaskGraph not found")
    repo = GraphTaskInstanceRepository(runtime.base_dir)
    instance_id = repo.next_id(graph_id)
    scope = _instance_scope(instance_id)
    root_session = runtime.session_manager.create_session(
        title=f"{payload.title} - 图任务项目",
        scope=scope,
        session_id=f"gti-root-{_safe_session_fragment(instance_id)}",
    )
    instance = repo.create(
        graph_id=graph_id,
        title=payload.title,
        description=payload.description,
        root_session_id=str(root_session.get("id") or ""),
        metadata={**dict(payload.metadata or {}), "graph_title": graph.title},
        instance_id=instance_id,
    )
    file_space = GraphTaskInstanceFileService(runtime.base_dir).ensure_space(instance.graph_task_instance_id)
    return {
        "authority": "api.graph_task_instances.create",
        "instance": instance.to_dict(),
        "root_session": root_session,
        "file_space": file_space,
    }


@router.get("/orchestration/graph-task-instances/{instance_id}")
async def get_graph_task_instance(instance_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    instance = _require_instance(runtime, instance_id)
    return _instance_detail(runtime, instance.graph_task_instance_id)


@router.patch("/orchestration/graph-task-instances/{instance_id}")
async def patch_graph_task_instance(instance_id: str, payload: GraphTaskInstancePatchRequest) -> dict[str, Any]:
    runtime = require_runtime()
    patch = {
        key: value
        for key, value in payload.model_dump(exclude_unset=True).items()
        if value is not None
    }
    instance = GraphTaskInstanceRepository(runtime.base_dir).patch(instance_id, patch)
    return {"authority": "api.graph_task_instances.patch", "instance": instance.to_dict()}


@router.post("/orchestration/graph-task-instances/{instance_id}/runs")
async def start_graph_task_instance_run(instance_id: str, payload: GraphTaskInstanceRunStartRequest) -> dict[str, Any]:
    runtime = require_runtime()
    repo = GraphTaskInstanceRepository(runtime.base_dir)
    instance = repo.require(instance_id)
    launch_session_id = instance.root_session_id
    if not launch_session_id:
        root_session = runtime.session_manager.create_session(
            title=f"{instance.title} - 图任务项目",
            scope=_instance_scope(instance.graph_task_instance_id),
            session_id=f"gti-root-{_safe_session_fragment(instance.graph_task_instance_id)}",
        )
        instance = repo.patch(instance.graph_task_instance_id, {"root_session_id": str(root_session.get("id") or "")})
        launch_session_id = instance.root_session_id
    try:
        runtime.session_manager.load_session_record(launch_session_id)
    except (InvalidSessionId, ValueError):
        root_session = runtime.session_manager.create_session(
            title=f"{instance.title} - 图任务项目",
            scope=_instance_scope(instance.graph_task_instance_id),
            session_id=launch_session_id or f"gti-root-{_safe_session_fragment(instance.graph_task_instance_id)}",
        )
        instance = repo.patch(instance.graph_task_instance_id, {"root_session_id": str(root_session.get("id") or "")})
        launch_session_id = instance.root_session_id
    initial_inputs = {
        **dict(payload.initial_inputs or {}),
        "graph_task_instance_id": instance.graph_task_instance_id,
        "runtime_scope": {
            **dict(dict(payload.initial_inputs or {}).get("runtime_scope") or {}),
            **_instance_scope(instance.graph_task_instance_id),
            "graph_task_instance_id": instance.graph_task_instance_id,
            "scope_source": "api.graph_task_instances.instance_run",
        },
    }
    start = await start_task_graph_harness_run(
        instance.graph_id,
        TaskGraphRunStartRequest(
            session_id=launch_session_id,
            session_scope=_instance_scope(instance.graph_task_instance_id),
            initial_inputs=initial_inputs,
            dispatch_ready=payload.dispatch_ready,
            run_mode=payload.run_mode,
            wait_for_completion=payload.wait_for_completion,
            runner_budget=dict(payload.runner_budget or {}),
            runtime_overrides=dict(payload.runtime_overrides or {}),
            runtime_settings_patch=dict(payload.runtime_settings_patch or {}),
        ),
    )
    graph_run_id = str(start.get("graph_run_id") or "")
    updated = repo.record_run(
        instance.graph_task_instance_id,
        graph_run_id=graph_run_id,
        status=_status_from_start(start),
        metadata={
            "latest_task_run_id": str(start.get("task_run_id") or ""),
            "latest_graph_harness_config_id": str(start.get("graph_harness_config_id") or ""),
            "latest_graph_session_id": str(start.get("graph_session_id") or ""),
        },
    )
    return {
        "authority": "api.graph_task_instances.start_run",
        "instance": updated.to_dict(),
        "start": start,
    }


@router.get("/orchestration/graph-task-instances/{instance_id}/monitor")
async def get_graph_task_instance_monitor(
    instance_id: str,
    event_limit: int = Query(default=40, ge=1, le=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    instance = _require_instance(runtime, instance_id)
    registry = TaskFlowRegistry(runtime.base_dir)
    graph_config = registry.get_published_graph_harness_config(instance.graph_id)
    graph_monitor = None
    if instance.active_graph_run_id:
        graph_monitor = runtime.harness_runtime.graph_harness.get_graph_run_monitor(
            instance.active_graph_run_id,
            graph_config=graph_config,
            event_limit=event_limit,
            include_config=False,
        )
    node_sessions = _instance_sessions(runtime, instance.graph_task_instance_id, root_session_id=instance.root_session_id)
    artifacts = GraphTaskInstanceFileService(runtime.base_dir).artifacts(instance.graph_task_instance_id)
    return {
        "authority": "api.graph_task_instances.monitor",
        "instance": instance.to_dict(),
        "graph_monitor": graph_monitor,
        "node_sessions": node_sessions,
        "artifacts": artifacts,
        "summary": _instance_monitor_summary(instance.to_dict(), graph_monitor, node_sessions, artifacts),
    }


@router.get("/orchestration/graph-task-instances/{instance_id}/node-sessions")
async def list_graph_task_instance_node_sessions(instance_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    instance = _require_instance(runtime, instance_id)
    sessions = _instance_sessions(runtime, instance.graph_task_instance_id, root_session_id=instance.root_session_id)
    return {
        "authority": "api.graph_task_instances.node_sessions",
        "graph_task_instance_id": instance.graph_task_instance_id,
        "sessions": sessions,
        "summary": {"session_count": len(sessions)},
    }


@router.get("/orchestration/graph-task-instances/{instance_id}/files/tree")
async def get_graph_task_instance_file_tree(
    instance_id: str,
    path: str = "",
    max_depth: int = Query(default=4, ge=0, le=20),
    max_entries: int = Query(default=500, ge=1, le=10000),
) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return GraphTaskInstanceFileService(runtime.base_dir).tree(instance_id, path, max_depth=max_depth, max_entries=max_entries)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/orchestration/graph-task-instances/{instance_id}/files")
async def read_graph_task_instance_file(instance_id: str, path: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return GraphTaskInstanceFileService(runtime.base_dir).read_file(instance_id, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/orchestration/graph-task-instances/{instance_id}/files")
async def write_graph_task_instance_file(instance_id: str, payload: GraphTaskInstanceFileWriteRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return GraphTaskInstanceFileService(runtime.base_dir).write_file(instance_id, payload.path, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/orchestration/graph-task-instances/{instance_id}/artifacts")
async def list_graph_task_instance_artifacts(instance_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return GraphTaskInstanceFileService(runtime.base_dir).artifacts(instance_id)


def _require_instance(runtime: Any, instance_id: str):
    try:
        return GraphTaskInstanceRepository(runtime.base_dir).require(instance_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _instance_detail(runtime: Any, instance_id: str) -> dict[str, Any]:
    instance = GraphTaskInstanceRepository(runtime.base_dir).require(instance_id)
    file_service = GraphTaskInstanceFileService(runtime.base_dir)
    return {
        "authority": "api.graph_task_instances.detail",
        "instance": instance.to_dict(),
        "repositories": file_service.repositories(instance.graph_task_instance_id),
        "artifacts": file_service.artifacts(instance.graph_task_instance_id),
    }


def _instance_scope(instance_id: str) -> dict[str, str]:
    return {
        "workspace_view": GRAPH_TASK_WORKSPACE_VIEW,
        "task_environment_id": "",
        "project_id": str(instance_id or "").strip(),
    }


def _instance_sessions(runtime: Any, instance_id: str, *, root_session_id: str = "") -> list[dict[str, Any]]:
    sessions = runtime.session_manager.list_sessions(
        workspace_view=GRAPH_TASK_WORKSPACE_VIEW,
        task_environment_id="",
        project_id=instance_id,
    )
    root = str(root_session_id or "").strip()
    return [
        {
            **dict(item),
            "session_role": "root" if str(item.get("id") or "") == root else "node",
        }
        for item in sessions
    ]


def _status_from_start(start: dict[str, Any]) -> str:
    graph_run = dict(start.get("graph_run") or {})
    task_run = dict(start.get("task_run") or {})
    status = str(graph_run.get("status") or task_run.get("status") or "running").strip()
    return status or "running"


def _instance_monitor_summary(
    instance: dict[str, Any],
    graph_monitor: dict[str, Any] | None,
    node_sessions: list[dict[str, Any]],
    artifacts: dict[str, Any],
) -> dict[str, Any]:
    loop_state = dict(dict(graph_monitor or {}).get("graph_loop_state") or {})
    return {
        "graph_task_instance_id": str(instance.get("graph_task_instance_id") or ""),
        "status": str(instance.get("status") or ""),
        "active_graph_run_id": str(instance.get("active_graph_run_id") or ""),
        "ready_count": len(list(loop_state.get("ready_node_ids") or [])),
        "running_count": len(list(loop_state.get("running_node_ids") or [])),
        "completed_count": len(list(loop_state.get("completed_node_ids") or [])),
        "failed_count": len(list(loop_state.get("failed_node_ids") or [])),
        "blocked_count": len(list(loop_state.get("blocked_node_ids") or [])),
        "node_session_count": len(node_sessions),
        "artifact_count": int(dict(artifacts.get("summary") or {}).get("artifact_count") or 0),
        "authority": "api.graph_task_instances.monitor_summary",
    }


def _safe_session_fragment(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in str(value or "").strip())
    return safe.strip(".-") or "graph-task-instance"

