from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from api.graph_system import (
    GRAPH_TASK_WORKSPACE_VIEW,
    TaskGraphRunStartRequest,
    start_task_graph_system_run,
)
from sessions import InvalidSessionId
from task_system import TaskFlowRegistry
from task_system.graph_instances import GraphTaskInstanceFileService, GraphTaskInstanceRepository
from task_system.graph_instances.edge_control_service import HumanEdgeDecisionService
from task_system.writing_graphs import WritingGraphDeskProjectionService


router = APIRouter()


class GraphTaskInstanceCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    initial_inputs: dict[str, Any] = Field(default_factory=dict)
    run_config: dict[str, Any] = Field(default_factory=dict)
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


class HumanEdgeDecisionSubmitRequest(BaseModel):
    graph_run_id: str = Field(default="", max_length=240)
    edge_id: str = Field(..., min_length=1, max_length=240)
    decision: str = Field(..., min_length=1, max_length=32)
    instruction: str = Field(default="", max_length=20000)
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    content_submission: dict[str, Any] | None = None
    apply_now: bool = True
    idempotency_key: str = Field(default="", max_length=400)
    operator: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WritingChapterActionRequest(BaseModel):
    chapter_id: str = Field(default="", max_length=240)
    action: str = Field(..., min_length=1, max_length=80)
    instruction: str = Field(default="", max_length=20000)
    content: str = ""
    target_path: str = Field(default="", max_length=1000)
    control_id: str = Field(default="", max_length=400)
    apply_now: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


WRITING_CHAPTER_ACTION_DECISIONS = {
    "approve": "pass",
    "request_revision": "revise",
    "replace_with_user_text": "replace",
}


@router.get("/graph-system/graph-tasks")
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


@router.get("/graph-system/graph-tasks/{graph_id}/instances")
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


@router.post("/graph-system/graph-tasks/{graph_id}/instances")
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
    metadata = _instance_create_metadata(
        graph_title=graph.title,
        title=payload.title,
        description=payload.description,
        initial_inputs=payload.initial_inputs,
        run_config=payload.run_config,
        metadata=payload.metadata,
    )
    instance = repo.create(
        graph_id=graph_id,
        title=payload.title,
        description=payload.description,
        root_session_id=str(root_session.get("id") or ""),
        metadata=metadata,
        instance_id=instance_id,
    )
    file_space = GraphTaskInstanceFileService(runtime.base_dir).ensure_space(instance.graph_task_instance_id)
    return {
        "authority": "api.graph_task_instances.create",
        "instance": instance.to_dict(),
        "root_session": root_session,
        "file_space": file_space,
    }


@router.get("/graph-system/graph-task-instances/{instance_id}")
async def get_graph_task_instance(instance_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    instance = _require_instance(runtime, instance_id)
    return _instance_detail(runtime, instance.graph_task_instance_id)


@router.patch("/graph-system/graph-task-instances/{instance_id}")
async def patch_graph_task_instance(instance_id: str, payload: GraphTaskInstancePatchRequest) -> dict[str, Any]:
    runtime = require_runtime()
    patch = {
        key: value
        for key, value in payload.model_dump(exclude_unset=True).items()
        if value is not None
    }
    instance = GraphTaskInstanceRepository(runtime.base_dir).patch(instance_id, patch)
    return {"authority": "api.graph_task_instances.patch", "instance": instance.to_dict()}


@router.post("/graph-system/graph-task-instances/{instance_id}/runs")
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
        **_instance_config_initial_inputs(instance),
        **dict(payload.initial_inputs or {}),
        "graph_task_instance_id": instance.graph_task_instance_id,
        "runtime_scope": {
            **dict(dict(payload.initial_inputs or {}).get("runtime_scope") or {}),
            **_instance_scope(instance.graph_task_instance_id),
            "graph_task_instance_id": instance.graph_task_instance_id,
            "scope_source": "api.graph_task_instances.instance_run",
        },
    }
    _validate_instance_run_inputs(instance, initial_inputs)
    start = await start_task_graph_system_run(
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
            "latest_graph_config_id": str(start.get("graph_config_id") or ""),
            "latest_graph_session_id": str(start.get("graph_session_id") or ""),
        },
    )
    return {
        "authority": "api.graph_task_instances.start_run",
        "instance": updated.to_dict(),
        "start": start,
    }


@router.get("/graph-system/graph-task-instances/{instance_id}/monitor")
async def get_graph_task_instance_monitor(
    instance_id: str,
    event_limit: int = Query(default=40, ge=1, le=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    instance = _require_instance(runtime, instance_id)
    event_limit_value = _query_int(event_limit, default=40)
    payload = _instance_monitor_payload(runtime, instance, event_limit=event_limit_value)
    return {
        "authority": "api.graph_task_instances.monitor",
        "instance": instance.to_dict(),
        "graph_monitor": payload["graph_monitor"],
        "node_sessions": payload["node_sessions"],
        "artifacts": payload["artifacts"],
        "human_controls": payload["human_controls"],
        "summary": _instance_monitor_summary(instance.to_dict(), payload["graph_monitor"], payload["node_sessions"], payload["artifacts"]),
    }


@router.get("/graph-system/writing-graph-instances/{instance_id}/desk")
async def get_writing_graph_instance_desk(
    instance_id: str,
    event_limit: int = Query(default=80, ge=1, le=240),
    include_runtime: bool = Query(default=True),
    include_file_tree: bool = Query(default=True),
) -> dict[str, Any]:
    runtime = require_runtime()
    instance = _require_instance(runtime, instance_id)
    event_limit_value = _query_int(event_limit, default=80)
    desk = _writing_desk_payload(
        runtime,
        instance,
        event_limit=event_limit_value,
        include_runtime=include_runtime,
        include_file_tree=include_file_tree,
    )
    projection_authority = str(desk.get("authority") or "")
    return {
        **desk,
        "authority": "api.graph_task_instances.writing_desk",
        "projection_authority": projection_authority,
    }


@router.post("/graph-system/writing-graph-instances/{instance_id}/chapter-actions")
async def submit_writing_graph_chapter_action(
    instance_id: str,
    payload: WritingChapterActionRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    action = str(payload.action or "").strip()
    if action not in WRITING_CHAPTER_ACTION_DECISIONS:
        raise HTTPException(status_code=400, detail=f"Writing chapter action is not supported: {action}")
    instance = _require_instance(runtime, instance_id)
    try:
        desk = _writing_desk_payload(runtime, instance, event_limit=80)
        chapter_action, control = _resolve_writing_chapter_action(desk, payload)
        decision_payload = _writing_chapter_action_decision_payload(
            desk=desk,
            chapter_action=chapter_action,
            control=control,
            payload=payload,
        )
        result = HumanEdgeDecisionService(runtime.base_dir).submit(
            runtime=runtime,
            instance_id=instance.graph_task_instance_id,
            payload=decision_payload,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "authority": "api.graph_task_instances.writing_chapter_action",
        "graph_task_instance_id": instance.graph_task_instance_id,
        "chapter_action": chapter_action,
        "control": control,
        "decision_result": result,
        "summary": {
            "action": str(chapter_action.get("action") or ""),
            "decision": str(decision_payload.get("decision") or ""),
            "edge_id": str(decision_payload.get("edge_id") or ""),
            "applied": dict(result.get("decision") or {}).get("status") == "applied",
            "authority": "api.graph_task_instances.writing_chapter_action_summary",
        },
    }


@router.get("/graph-system/graph-task-instances/{instance_id}/node-sessions")
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


@router.get("/graph-system/graph-task-instances/{instance_id}/files/tree")
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


@router.get("/graph-system/graph-task-instances/{instance_id}/files")
async def read_graph_task_instance_file(instance_id: str, path: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return GraphTaskInstanceFileService(runtime.base_dir).read_file(instance_id, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/graph-system/graph-task-instances/{instance_id}/files")
async def write_graph_task_instance_file(instance_id: str, payload: GraphTaskInstanceFileWriteRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return GraphTaskInstanceFileService(runtime.base_dir).write_file(instance_id, payload.path, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/graph-system/graph-task-instances/{instance_id}/artifacts")
async def list_graph_task_instance_artifacts(instance_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return GraphTaskInstanceFileService(runtime.base_dir).artifacts(instance_id)


@router.get("/graph-system/graph-task-instances/{instance_id}/human-edge-decisions")
async def list_graph_task_instance_human_edge_decisions(
    instance_id: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return HumanEdgeDecisionService(runtime.base_dir).list(instance_id, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/graph-system/graph-task-instances/{instance_id}/human-edge-decisions")
async def submit_graph_task_instance_human_edge_decision(
    instance_id: str,
    payload: HumanEdgeDecisionSubmitRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return HumanEdgeDecisionService(runtime.base_dir).submit(
            runtime=runtime,
            instance_id=instance_id,
            payload=payload.model_dump(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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


def _instance_create_metadata(
    *,
    graph_title: str,
    title: str,
    description: str,
    initial_inputs: dict[str, Any] | None,
    run_config: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(metadata or {})
    payload["graph_title"] = str(graph_title or "").strip()
    configured_inputs = dict(initial_inputs or {})
    run_config_payload = dict(run_config or {})
    run_config_inputs = dict(run_config_payload.get("initial_inputs") or {})
    if configured_inputs or run_config_payload:
        run_config_payload["initial_inputs"] = {**run_config_inputs, **configured_inputs}
        payload["run_config"] = {**dict(payload.get("run_config") or {}), **run_config_payload}
    writing_project = dict(payload.get("writing_project") or {})
    if configured_inputs:
        writing_project = {**writing_project, **_writing_project_fields_from_inputs(configured_inputs)}
    if str(description or "").strip() and not str(writing_project.get("project_brief") or "").strip():
        writing_project["project_brief"] = str(description or "").strip()
    if str(title or "").strip() and not str(writing_project.get("project_title") or "").strip():
        writing_project["project_title"] = str(title or "").strip()
    if writing_project:
        payload["writing_project"] = writing_project
    return payload


def _instance_config_initial_inputs(instance: Any) -> dict[str, Any]:
    metadata = dict(getattr(instance, "metadata", None) or {})
    payload: dict[str, Any] = {}
    run_config = dict(metadata.get("run_config") or {})
    payload.update(dict(run_config.get("initial_inputs") or {}))
    payload.update(dict(metadata.get("initial_inputs") or {}))
    if _is_modular_novel_graph(getattr(instance, "graph_id", "")):
        writing_project = dict(metadata.get("writing_project") or {})
        payload.update(_writing_project_fields_from_inputs(writing_project))
        title = str(getattr(instance, "title", "") or "").strip()
        description = str(getattr(instance, "description", "") or "").strip()
        payload.setdefault("project_title", title)
        payload.setdefault("title", title)
        if description and not str(payload.get("project_brief") or "").strip():
            payload["project_brief"] = description
        if payload:
            payload.setdefault("source", "graph_task_instance_config")
    return payload


def _writing_project_fields_from_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "project_brief",
        "project_title",
        "title",
        "reference_works",
        "hard_constraints",
        "creative_constraints",
        "genre",
        "style",
        "target_audience",
    }
    return {
        key: value
        for key, value in dict(inputs or {}).items()
        if key in allowed and str(value or "").strip()
    }


def _validate_instance_run_inputs(instance: Any, initial_inputs: dict[str, Any]) -> None:
    if not _is_modular_novel_graph(getattr(instance, "graph_id", "")):
        return
    if str(initial_inputs.get("project_brief") or "").strip():
        return
    raise HTTPException(
        status_code=409,
        detail={
            "message": "写作图任务实例缺少项目启动包，请先在项目配置中填写 project_brief。",
            "graph_task_instance_id": getattr(instance, "graph_task_instance_id", ""),
            "required_input": "project_brief",
        },
    )


def _is_modular_novel_graph(graph_id: str) -> bool:
    return str(graph_id or "").strip().startswith("graph.writing.modular_novel.")


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


def _instance_monitor_payload(runtime: Any, instance: Any, *, event_limit: int = 40) -> dict[str, Any]:
    registry = TaskFlowRegistry(runtime.base_dir)
    graph_config = registry.get_published_graph_config(instance.graph_id)
    graph_monitor = None
    if instance.active_graph_run_id:
        graph_monitor = runtime.harness_runtime.graph_system.get_graph_run_monitor(
            instance.active_graph_run_id,
            graph_config=graph_config,
            event_limit=event_limit,
            include_config=False,
        )
    node_sessions = _instance_sessions(runtime, instance.graph_task_instance_id, root_session_id=instance.root_session_id)
    artifacts = GraphTaskInstanceFileService(runtime.base_dir).artifacts(instance.graph_task_instance_id)
    human_controls = HumanEdgeDecisionService(runtime.base_dir).human_controls(
        instance_id=instance.graph_task_instance_id,
        graph_config=graph_config,
        state=runtime.harness_runtime.graph_system.graph_loop.get_state(instance.active_graph_run_id) if instance.active_graph_run_id else None,
    )
    return {
        "authority": "api.graph_task_instances.monitor_payload",
        "graph_monitor": graph_monitor,
        "node_sessions": node_sessions,
        "artifacts": artifacts,
        "human_controls": human_controls,
    }


def _writing_desk_payload(
    runtime: Any,
    instance: Any,
    *,
    event_limit: int = 80,
    include_runtime: bool = True,
    include_file_tree: bool = True,
) -> dict[str, Any]:
    file_service = GraphTaskInstanceFileService(runtime.base_dir)
    if include_runtime:
        monitor_payload = _instance_monitor_payload(runtime, instance, event_limit=event_limit)
    else:
        monitor_payload = {
            "graph_monitor": None,
            "node_sessions": [],
            "artifacts": file_service.artifacts(instance.graph_task_instance_id),
            "human_controls": _empty_human_controls(),
        }
    flat_files = None
    if include_file_tree:
        file_tree = file_service.tree(instance.graph_task_instance_id, max_depth=8, max_entries=2000)
    else:
        flat_files = _artifact_flat_files(monitor_payload["artifacts"])
        file_tree = {
            "authority": "task_system.graph_task_instance_file_tree",
            "graph_task_instance_id": instance.graph_task_instance_id,
            "repository_id": "instance",
            "path": "",
            "total_entries": len(flat_files),
            "truncated": False,
            "tree": {},
        }
    return WritingGraphDeskProjectionService(runtime.base_dir).build(
        instance=instance,
        file_tree=file_tree,
        artifacts=monitor_payload["artifacts"],
        node_sessions=monitor_payload["node_sessions"],
        human_controls=monitor_payload["human_controls"],
        graph_monitor=monitor_payload["graph_monitor"],
        flat_files=flat_files,
        include_file_tree=include_file_tree,
    )


def _artifact_flat_files(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    files = []
    for artifact in list(artifacts.get("artifacts") or []):
        if not isinstance(artifact, dict):
            continue
        path = str(artifact.get("path") or "").replace("\\", "/").strip().strip("/")
        if not path:
            continue
        files.append(
            {
                "kind": "file",
                "path": path,
                "name": str(artifact.get("name") or path.rsplit("/", 1)[-1]),
            }
        )
    return files


def _empty_human_controls() -> dict[str, Any]:
    return {
        "authority": "graph_system.human_controls",
        "pending": [],
        "available": [],
        "history": [],
        "summary": {"pending_count": 0, "available_count": 0, "decision_count": 0},
    }


def _resolve_writing_chapter_action(
    desk: dict[str, Any],
    payload: WritingChapterActionRequest,
) -> tuple[dict[str, Any], dict[str, Any]]:
    action = str(payload.action or "").strip()
    decision = WRITING_CHAPTER_ACTION_DECISIONS[action]
    requested_control_id = str(payload.control_id or "").strip()
    requested_chapter_id = str(payload.chapter_id or "").strip()
    current_chapter_id = str(dict(desk.get("current_chapter") or {}).get("chapter_id") or "").strip()
    if requested_chapter_id and current_chapter_id and requested_chapter_id != current_chapter_id:
        raise ValueError(
            f"Writing chapter action targets chapter {requested_chapter_id}, current chapter is {current_chapter_id}"
        )

    actions = [
        dict(item)
        for item in list(desk.get("chapter_actions") or [])
        if isinstance(item, dict)
    ]
    matches = [
        item
        for item in actions
        if str(item.get("action") or "").strip() == action
        and str(item.get("decision") or "").strip() == decision
        and bool(item.get("enabled", True))
    ]
    if requested_control_id:
        matches = [item for item in matches if str(item.get("control_id") or "").strip() == requested_control_id]
    if not matches:
        suffix = f" for control {requested_control_id}" if requested_control_id else ""
        raise ValueError(f"Writing chapter action is not available: {action}{suffix}")

    chapter_action = matches[0]
    control_id = str(chapter_action.get("control_id") or "").strip()
    controls = _writing_human_controls(desk)
    control = next((item for item in controls if str(item.get("control_id") or "").strip() == control_id), None)
    if control is None:
        raise ValueError(f"Writing chapter action control is no longer available: {control_id}")
    allowed_decisions = {str(item).strip() for item in list(control.get("allowed_decisions") or []) if str(item).strip()}
    if decision not in allowed_decisions:
        raise ValueError(f"Writing chapter action decision is not allowed by control {control_id}: {decision}")
    return chapter_action, control


def _writing_chapter_action_decision_payload(
    *,
    desk: dict[str, Any],
    chapter_action: dict[str, Any],
    control: dict[str, Any],
    payload: WritingChapterActionRequest,
) -> dict[str, Any]:
    decision = WRITING_CHAPTER_ACTION_DECISIONS[str(chapter_action.get("action") or "").strip()]
    target_path = _writing_action_target_path(desk, payload)
    content_submission = None
    artifact_refs = [dict(item) for item in list(control.get("artifact_refs") or []) if isinstance(item, dict)]
    if decision == "replace":
        content = str(payload.content or "")
        if not target_path:
            raise ValueError("Writing chapter replace action requires target_path or current reader path")
        if not content.strip():
            raise ValueError("Writing chapter replace action requires content")
        content_submission = {
            "path": target_path,
            "content": content,
            "content_kind": "chapter" if _looks_like_chapter_path(target_path) else "document",
            "commit_policy": "project_file",
        }
    return {
        "graph_run_id": str(control.get("graph_run_id") or ""),
        "edge_id": str(control.get("edge_id") or ""),
        "decision": decision,
        "instruction": str(payload.instruction or "").strip(),
        "artifact_refs": artifact_refs,
        "content_submission": content_submission,
        "apply_now": bool(payload.apply_now),
        "metadata": {
            **dict(payload.metadata or {}),
            "submitted_from": "writing_chapter_action_api",
            "writing_action": str(chapter_action.get("action") or ""),
            "chapter_id": str(payload.chapter_id or dict(desk.get("current_chapter") or {}).get("chapter_id") or ""),
            "control_id": str(chapter_action.get("control_id") or ""),
        },
    }


def _writing_human_controls(desk: dict[str, Any]) -> list[dict[str, Any]]:
    human_controls = dict(desk.get("human_controls") or {})
    controls: list[dict[str, Any]] = []
    for bucket in ("pending", "available"):
        controls.extend(
            dict(item)
            for item in list(human_controls.get(bucket) or [])
            if isinstance(item, dict)
        )
    return controls


def _writing_action_target_path(desk: dict[str, Any], payload: WritingChapterActionRequest) -> str:
    requested = str(payload.target_path or "").replace("\\", "/").strip().strip("/")
    if requested:
        return requested
    reader_path = str(dict(desk.get("reader") or {}).get("path") or "").replace("\\", "/").strip().strip("/")
    if reader_path:
        return reader_path
    return str(dict(desk.get("current_chapter") or {}).get("path") or "").replace("\\", "/").strip().strip("/")


def _looks_like_chapter_path(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").strip().strip("/")
    name = normalized.rsplit("/", 1)[-1]
    return normalized.lower().startswith("chapters/") or name.lower().startswith("chapter")


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


def _query_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
