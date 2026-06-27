from __future__ import annotations

from typing import Any

from graph_system.language import REVISION_EDGE_TYPES
from graph_system.models import ExecutableGraphConfig
from graph_system.scheduler_view import SchedulerView, build_scheduler_view
from graph_system.state_machine import GraphStateMachine


LOOP_PLAN_PREVIEW_AUTHORITY = "task_system.loop_plan_preview"
CONTEXT_EDGE_TYPES = {"memory_read", "memory_handoff", "artifact_read", "artifact_context", "file_read", "file_context"}
COMMIT_EDGE_TYPES = {
    "memory_commit",
    "memory_write",
    "memory_write_candidate",
    "artifact_write",
    "artifact_commit",
    "file_write",
    "file_commit",
}


def build_loop_plan_preview(
    *,
    graph_config: ExecutableGraphConfig,
    layered_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scheduler = build_scheduler_view(graph_config)
    state_machine = GraphStateMachine()
    node_states = state_machine.initial_node_states(graph_config)
    initial_ready_node_ids = state_machine.ready_nodes(graph_config=graph_config, node_states=node_states)
    edges = [dict(item) for item in graph_config.edges]
    dependency_edge_ids = {str(edge.get("edge_id") or "") for edge in scheduler.dependency_edges}
    dependency_edges = [_edge_plan(edge, runtime_role="dependency") for edge in scheduler.dependency_edges]
    context_edges = [
        _edge_plan(edge, runtime_role="context")
        for edge in edges
        if _edge_is_context(edge) and str(edge.get("edge_id") or "") not in dependency_edge_ids
    ]
    commit_edges = [_edge_plan(edge, runtime_role="commit") for edge in edges if _edge_is_commit(edge)]
    revision_edges = [_edge_plan(edge, runtime_role="revision") for edge in edges if _edge_is_revision(edge)]
    loop_frames = [_loop_frame_plan(frame) for frame in graph_config.loop_frames]
    issues = [
        *_structural_issues(
            graph_config=graph_config,
            scheduler=scheduler,
            initial_ready_node_ids=initial_ready_node_ids,
        ),
        *_loop_frame_issues(loop_frames),
    ]
    layered = dict(layered_graph or {})
    return {
        "available": True,
        "authority": LOOP_PLAN_PREVIEW_AUTHORITY,
        "graph_id": graph_config.graph_id,
        "config_id": graph_config.config_id,
        "config_hash": graph_config.content_hash,
        "start_node_ids": list(scheduler.start_node_ids),
        "terminal_node_ids": list(scheduler.terminal_node_ids),
        "executable_node_ids": list(scheduler.executable_node_ids),
        "initial_ready_node_ids": list(initial_ready_node_ids),
        "dependency_edges": dependency_edges,
        "context_edges": context_edges,
        "commit_edges": commit_edges,
        "revision_edges": revision_edges,
        "loop_frames": loop_frames,
        "execution_levels": _execution_levels(
            executable_node_ids=scheduler.executable_node_ids,
            dependency_edges=scheduler.dependency_edges,
        ),
        "summary": {
            "node_count": len(graph_config.nodes),
            "edge_count": len(graph_config.edges),
            "executable_node_count": len(scheduler.executable_node_ids),
            "dependency_edge_count": len(dependency_edges),
            "context_edge_count": len(context_edges),
            "commit_edge_count": len(commit_edges),
            "revision_edge_count": len(revision_edges),
            "loop_frame_count": len(loop_frames),
            "resource_node_count": len(list(dict(graph_config.resources or {}).get("resource_nodes") or [])),
            "layered_issue_count": len(list(layered.get("issues") or [])),
            "issue_count": len(issues),
        },
        "issues": issues,
    }


def unavailable_loop_plan_preview(*, graph_id: str, issues: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> dict[str, Any]:
    normalized_issues = [_issue_from_payload(item, fallback_code="loop_plan_unavailable") for item in issues if isinstance(item, dict)]
    return {
        "available": False,
        "authority": LOOP_PLAN_PREVIEW_AUTHORITY,
        "graph_id": str(graph_id or "").strip(),
        "start_node_ids": [],
        "terminal_node_ids": [],
        "executable_node_ids": [],
        "initial_ready_node_ids": [],
        "dependency_edges": [],
        "context_edges": [],
        "commit_edges": [],
        "revision_edges": [],
        "loop_frames": [],
        "execution_levels": [],
        "summary": {
            "node_count": 0,
            "edge_count": 0,
            "executable_node_count": 0,
            "dependency_edge_count": 0,
            "context_edge_count": 0,
            "commit_edge_count": 0,
            "revision_edge_count": 0,
            "loop_frame_count": 0,
            "resource_node_count": 0,
            "layered_issue_count": 0,
            "issue_count": len(normalized_issues),
        },
        "issues": normalized_issues,
    }


def _edge_plan(edge: dict[str, Any], *, runtime_role: str) -> dict[str, Any]:
    return {
        "edge_id": str(edge.get("edge_id") or ""),
        "source_node_id": str(edge.get("source_node_id") or ""),
        "target_node_id": str(edge.get("target_node_id") or ""),
        "edge_type": str(edge.get("edge_type") or ""),
        "semantic_role": str(edge.get("semantic_role") or ""),
        "scheduler_role": str(edge.get("scheduler_role") or ""),
        "runtime_role": runtime_role,
    }


def _loop_frame_plan(frame: dict[str, Any]) -> dict[str, Any]:
    return {
        "frame_id": str(frame.get("frame_id") or frame.get("loop_frame_id") or frame.get("scope_id") or ""),
        "scope_id": str(frame.get("scope_id") or frame.get("frame_id") or frame.get("loop_frame_id") or ""),
        "parent_scope_id": str(frame.get("parent_scope_id") or ""),
        "kind": str(frame.get("kind") or ""),
        "entry_node_id": str(frame.get("entry_node_id") or ""),
        "router_node_id": str(frame.get("router_node_id") or ""),
        "continue_node_id": str(frame.get("continue_node_id") or ""),
        "exit_node_id": str(frame.get("exit_node_id") or ""),
        "scope_node_ids": [str(item) for item in list(frame.get("scope_node_ids") or []) if str(item)],
        "cursor_key": str(frame.get("cursor_key") or ""),
        "start_key": str(frame.get("start_key") or ""),
        "end_key": str(frame.get("end_key") or ""),
        "step": frame.get("step"),
        "iteration_index_key": str(frame.get("iteration_index_key") or ""),
        "iteration_identity_template": str(frame.get("iteration_identity_template") or ""),
        "preserve_iteration_results": bool(frame.get("preserve_iteration_results")),
        "initial_input_keys": sorted(str(key) for key in dict(frame.get("initial_inputs") or {}).keys()),
        "derived_field_count": len(list(frame.get("derived_fields") or [])),
    }


def _edge_is_context(edge: dict[str, Any]) -> bool:
    edge_type = str(edge.get("edge_type") or "")
    scheduler_role = str(edge.get("scheduler_role") or "")
    return scheduler_role == "context" or edge_type in CONTEXT_EDGE_TYPES


def _edge_is_commit(edge: dict[str, Any]) -> bool:
    edge_type = str(edge.get("edge_type") or "")
    scheduler_role = str(edge.get("scheduler_role") or "")
    return scheduler_role == "commit" or edge_type in COMMIT_EDGE_TYPES


def _edge_is_revision(edge: dict[str, Any]) -> bool:
    edge_type = str(edge.get("edge_type") or "")
    semantic_role = str(edge.get("semantic_role") or "")
    return semantic_role == "revision" or edge_type in REVISION_EDGE_TYPES


def _structural_issues(
    *,
    graph_config: ExecutableGraphConfig,
    scheduler: SchedulerView,
    initial_ready_node_ids: tuple[str, ...],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not graph_config.nodes:
        issues.append(_issue("loop_plan_no_nodes", "当前图没有节点，GraphLoop 无法初始化。", severity="error"))
    if graph_config.nodes and not scheduler.executable_node_ids:
        issues.append(_issue("loop_plan_no_executable_nodes", "当前图没有可执行节点，资源节点不会被 GraphLoop 调度。", severity="error"))
    if scheduler.executable_node_ids and not scheduler.start_node_ids:
        issues.append(_issue("loop_plan_no_start_nodes", "当前图没有可调度起点。", severity="error"))
    if scheduler.executable_node_ids and not initial_ready_node_ids:
        issues.append(_issue("loop_plan_no_initial_ready_nodes", "当前图初始化后没有 ready 节点。", severity="error"))
    return issues


def _loop_frame_issues(loop_frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for frame in loop_frames:
        frame_id = str(frame.get("frame_id") or "")
        if not frame.get("entry_node_id"):
            issues.append(_issue("loop_frame_entry_missing", "循环 frame 缺少入口节点。", severity="warning", frame_id=frame_id))
        if not frame.get("router_node_id"):
            issues.append(_issue("loop_frame_router_missing", "循环 frame 缺少路由节点。", severity="warning", frame_id=frame_id))
        if not frame.get("continue_node_id"):
            issues.append(_issue("loop_frame_continue_missing", "循环 frame 缺少继续节点。", severity="warning", frame_id=frame_id))
        if not frame.get("exit_node_id"):
            issues.append(_issue("loop_frame_exit_missing", "循环 frame 缺少退出节点。", severity="warning", frame_id=frame_id))
        if frame.get("start_key") or frame.get("end_key") or frame.get("step") is not None:
            if not frame.get("cursor_key"):
                issues.append(_issue("loop_frame_cursor_missing", "循环 frame 声明了范围推进但缺少游标字段。", severity="warning", frame_id=frame_id))
    return issues


def _execution_levels(
    *,
    executable_node_ids: tuple[str, ...],
    dependency_edges: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    remaining = set(executable_node_ids)
    completed: set[str] = set()
    levels: list[dict[str, Any]] = []
    while remaining:
        ready = [
            node_id
            for node_id in executable_node_ids
            if node_id in remaining
            and all(str(edge.get("source_node_id") or "") in completed for edge in dependency_edges if str(edge.get("target_node_id") or "") == node_id)
        ]
        if not ready:
            levels.append(
                {
                    "level_index": len(levels) + 1,
                    "node_ids": sorted(remaining),
                    "status": "blocked_or_cyclic",
                }
            )
            break
        levels.append(
            {
                "level_index": len(levels) + 1,
                "node_ids": ready,
                "status": "schedulable",
            }
        )
        completed.update(ready)
        remaining.difference_update(ready)
    return levels


def _issue(
    code: str,
    message: str,
    *,
    severity: str = "error",
    frame_id: str = "",
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "severity": severity,
        "frame_id": frame_id,
        "source": LOOP_PLAN_PREVIEW_AUTHORITY,
    }


def _issue_from_payload(payload: dict[str, Any], *, fallback_code: str) -> dict[str, Any]:
    return {
        "code": str(payload.get("code") or fallback_code),
        "message": str(payload.get("message") or payload.get("detail") or "LoopPlan 编译不可用。"),
        "severity": str(payload.get("severity") or "error"),
        "node_id": str(payload.get("node_id") or ""),
        "edge_id": str(payload.get("edge_id") or ""),
        "source": str(payload.get("source") or LOOP_PLAN_PREVIEW_AUTHORITY),
    }
