from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from capability_system.tools.base_tool import AsyncCallbackManagerForToolRun, BaseTool, CallbackManagerForToolRun
from capability_system.tools.tool_units.project_structure_tools import (
    ProjectStructureBuildSkeletonTool,
    ProjectStructureCollectGitChangesTool,
    ProjectStructureCreateRepairWorkItemsTool,
    ProjectStructureDirectoryRelationsTool,
    ProjectStructureExpandTool,
    ProjectStructureReadEdgeTool,
    ProjectStructureReadNodeTool,
    ProjectStructureSubmitSemanticOverlayTool,
)
from file_management.project_structure import ProjectNetworkControlService
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


ProjectNetworkAction = Literal[
    "build_skeleton",
    "read_node",
    "read_edge",
    "expand",
    "directory_relations",
    "collect_changes",
    "repair_items",
    "submit_overlay",
    "start_traversal",
    "read_frontier",
    "continue_traversal",
    "record_decision",
]


class ProjectNetworkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ProjectNetworkAction = Field(description="Project network action to execute.")
    build_id: str = Field(default="", description="Project network build id.")
    scope_roots: list[str] = Field(default_factory=list, description="Build scope roots.")
    generation: int = Field(default=0, ge=0, description="Skeleton or semantic generation; 0 means latest/next where supported.")
    include_git_snapshot: bool = Field(default=True, description="Include git snapshot facts when building.")
    node_id: str = Field(default="", description="Skeleton node id.")
    stable_ref: str = Field(default="", description="Stable physical ref such as folder://backend or file://backend/app.py.")
    path: str = Field(default="", description="Workspace path for node resolution.")
    edge_id: str = Field(default="", description="Skeleton edge id.")
    seed_node_ids: list[str] = Field(default_factory=list, description="Seed node ids for expansion.")
    seed_stable_refs: list[str] = Field(default_factory=list, description="Seed stable refs for expansion.")
    seed_paths: list[str] = Field(default_factory=list, description="Seed workspace paths for expansion.")
    edge_kinds: list[str] = Field(default_factory=list, description="Optional edge kinds to keep.")
    depth: int = Field(default=1, ge=0, le=6, description="Expansion depth.")
    limit: int = Field(default=200, ge=1, le=1000, description="Expansion node limit.")
    include_inbound: bool = Field(default=True, description="Include inbound edges in expansion.")
    scope_root: str = Field(default="", description="Directory or file scope for directory_relations.")
    max_nodes: int = Field(default=300, ge=1, le=2000, description="Maximum nodes for directory_relations.")
    max_edges: int = Field(default=500, ge=1, le=5000, description="Maximum edges for directory_relations.")
    include_external: bool = Field(default=True, description="Include boundary relations.")
    include_semantic_overlay: bool = Field(default=True, description="Include semantic overlay records.")
    change_mode: str = Field(default="working_tree", description="Git change collection mode.")
    skeleton_generation: int = Field(default=0, ge=0, description="Skeleton generation for maintenance actions.")
    change_set_id: str = Field(default="", description="Change set id for repair_items.")
    group_by_folder_threshold: int = Field(default=40, ge=1, le=500, description="Grouping threshold for repair work items.")
    overlay_kind: str = Field(default="", description="Semantic overlay kind.")
    skeleton_node_id: str = Field(default="", description="Semantic overlay target skeleton node id.")
    skeleton_edge_id: str = Field(default="", description="Semantic overlay target skeleton edge id.")
    anchor_ref: str = Field(default="", description="Optional code or evidence anchor.")
    status: str = Field(default="candidate", description="Overlay status.")
    confidence: str = Field(default="derived", description="Overlay confidence.")
    payload: dict[str, Any] = Field(default_factory=dict, description="Structured semantic overlay payload.")
    evidence_refs: list[str] = Field(default_factory=list, description="Evidence refs that support this overlay.")
    created_by_task_run_id: str = Field(default="", description="Task run id that produced the overlay.")
    created_by_agent_id: str = Field(default="", description="Agent id that produced the overlay.")
    overlay_id: str = Field(default="", description="Optional overlay id for update.")
    traversal_session_id: str = Field(default="", description="Project network traversal session id.")
    goal: str = Field(default="", description="Traversal goal stated in agent-operable terms.")
    anchor_node_ids: list[str] = Field(default_factory=list, description="Traversal anchor skeleton node ids.")
    anchor_stable_refs: list[str] = Field(default_factory=list, description="Traversal anchor stable physical refs.")
    anchor_paths: list[str] = Field(default_factory=list, description="Traversal anchor workspace paths.")
    crawl_budget: int = Field(default=40, ge=1, le=500, description="Remaining traversal budget for control state.")
    selected_frontier_item_id: str = Field(default="", description="Frontier item chosen or updated by the agent.")
    decision_kind: str = Field(default="", description="Agent control decision kind.")
    reason: str = Field(default="", description="Agent-readable reason for the control decision.")
    decision_status: str = Field(default="recorded", description="Status for record_decision.")
    frontier_status: str = Field(default="queued", description="Frontier status to read.")
    enqueue_neighbors: bool = Field(default=True, description="Whether continue_traversal should enqueue neighbors.")
    include_local_slice: bool = Field(default=True, description="Include local physical/semantic slice in control projection.")


class ProjectNetworkTool(BaseTool):
    name: str = "project_network"
    description: str = (
        "Build, read, traverse, and maintain the project structure network. "
        "Follow physical skeleton nodes and edges first; attach semantic overlays only with evidence refs."
    )
    args_schema: type[BaseModel] = ProjectNetworkInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._root_dir = Path(root_dir).resolve()

    def _run(self, action: str, run_manager: CallbackManagerForToolRun | None = None, **kwargs: Any) -> Any:
        _ = run_manager
        normalized = str(action or "").strip()
        if normalized in {"start_traversal", "read_frontier", "continue_traversal", "record_decision"}:
            return self._run_control_action(normalized, kwargs)
        tool = self._tool_for_action(normalized)
        if tool is None:
            return {"text": f"project_network failed: unsupported action {action!r}", "structured_payload": {"tool_result": {"ok": False}}}
        return tool.invoke(_payload_for_action(normalized, kwargs))

    async def _arun(self, action: str, run_manager: AsyncCallbackManagerForToolRun | None = None, **kwargs: Any) -> Any:
        return await asyncio.to_thread(self._run, action, None, **kwargs)

    def _tool_for_action(self, action: str) -> BaseTool | None:
        mapping = {
            "build_skeleton": ProjectStructureBuildSkeletonTool,
            "read_node": ProjectStructureReadNodeTool,
            "read_edge": ProjectStructureReadEdgeTool,
            "expand": ProjectStructureExpandTool,
            "directory_relations": ProjectStructureDirectoryRelationsTool,
            "collect_changes": ProjectStructureCollectGitChangesTool,
            "repair_items": ProjectStructureCreateRepairWorkItemsTool,
            "submit_overlay": ProjectStructureSubmitSemanticOverlayTool,
        }
        tool_cls = mapping.get(action)
        return tool_cls(root_dir=self._root_dir) if tool_cls is not None else None

    def _run_control_action(self, action: str, values: dict[str, Any]) -> dict[str, Any]:
        service = ProjectNetworkControlService.from_backend_dir(self._root_dir)
        try:
            if action == "start_traversal":
                projection = service.start_traversal(
                    build_id=str(values.get("build_id") or ""),
                    goal=str(values.get("goal") or ""),
                    anchor_node_ids=list(values.get("anchor_node_ids") or []),
                    anchor_stable_refs=list(values.get("anchor_stable_refs") or []),
                    anchor_paths=list(values.get("anchor_paths") or []),
                    generation=int(values.get("generation") or 0) or None,
                    crawl_budget=int(values.get("crawl_budget") or 40),
                    created_by_task_run_id=str(values.get("created_by_task_run_id") or ""),
                    created_by_agent_id=str(values.get("created_by_agent_id") or ""),
                    traversal_session_id=str(values.get("traversal_session_id") or ""),
                    include_local_slice=bool(values.get("include_local_slice") is not False),
                )
            elif action == "read_frontier":
                projection = service.read_frontier(
                    traversal_session_id=str(values.get("traversal_session_id") or ""),
                    status=str(values.get("frontier_status") or "queued"),
                    limit=int(values.get("limit") or 50),
                    include_local_slice=bool(values.get("include_local_slice") is not False),
                )
            elif action == "continue_traversal":
                projection = service.continue_traversal(
                    traversal_session_id=str(values.get("traversal_session_id") or ""),
                    selected_frontier_item_id=str(values.get("selected_frontier_item_id") or ""),
                    node_id=str(values.get("node_id") or ""),
                    edge_id=str(values.get("edge_id") or ""),
                    reason=str(values.get("reason") or ""),
                    evidence_refs=list(values.get("evidence_refs") or []),
                    enqueue_neighbors=bool(values.get("enqueue_neighbors") is not False),
                    created_by_task_run_id=str(values.get("created_by_task_run_id") or ""),
                    created_by_agent_id=str(values.get("created_by_agent_id") or ""),
                    include_local_slice=bool(values.get("include_local_slice") is not False),
                )
            elif action == "record_decision":
                projection = service.record_decision(
                    traversal_session_id=str(values.get("traversal_session_id") or ""),
                    decision_kind=str(values.get("decision_kind") or ""),
                    selected_frontier_item_id=str(values.get("selected_frontier_item_id") or ""),
                    selected_node_id=str(values.get("node_id") or ""),
                    selected_edge_id=str(values.get("edge_id") or ""),
                    reason=str(values.get("reason") or ""),
                    evidence_refs=list(values.get("evidence_refs") or []),
                    status=str(values.get("decision_status") or "recorded"),
                    payload=dict(values.get("payload") or {}),
                    created_by_task_run_id=str(values.get("created_by_task_run_id") or ""),
                    created_by_agent_id=str(values.get("created_by_agent_id") or ""),
                    include_local_slice=bool(values.get("include_local_slice") is not False),
                )
            else:
                return _project_network_result(f"project_network failed: unsupported control action {action!r}", ok=False, payload={"kind": action})
        except Exception as exc:
            return _project_network_result(f"Project network control action failed: {exc}", ok=False, payload={"kind": action})
        payload = projection.to_dict()
        return _project_network_result(_format_control_projection(payload), ok=True, payload=payload)


def _payload_for_action(action: str, values: dict[str, Any]) -> dict[str, Any]:
    if action == "build_skeleton":
        return {
            "build_id": values.get("build_id", ""),
            "scope_roots": list(values.get("scope_roots") or []),
            "generation": values.get("generation", 0),
            "include_git_snapshot": bool(values.get("include_git_snapshot") is not False),
        }
    if action == "read_node":
        return {key: values.get(key, "") for key in ("node_id", "build_id", "stable_ref", "path")} | {
            "generation": values.get("generation", 0),
            "include_semantic_overlay": bool(values.get("include_semantic_overlay") is not False),
        }
    if action == "read_edge":
        return {"edge_id": values.get("edge_id", "")}
    if action == "expand":
        return {
            "build_id": values.get("build_id", ""),
            "seed_node_ids": list(values.get("seed_node_ids") or []),
            "seed_stable_refs": list(values.get("seed_stable_refs") or []),
            "seed_paths": list(values.get("seed_paths") or []),
            "generation": values.get("generation", 0),
            "edge_kinds": list(values.get("edge_kinds") or []),
            "depth": values.get("depth", 1),
            "limit": values.get("limit", 200),
            "include_inbound": bool(values.get("include_inbound") is not False),
            "include_semantic_overlay": bool(values.get("include_semantic_overlay") is not False),
        }
    if action == "directory_relations":
        return {
            "build_id": values.get("build_id", ""),
            "scope_root": values.get("scope_root", ""),
            "generation": values.get("generation", 0),
            "edge_kinds": list(values.get("edge_kinds") or []),
            "max_nodes": values.get("max_nodes", 300),
            "max_edges": values.get("max_edges", 500),
            "include_external": bool(values.get("include_external") is not False),
            "include_semantic_overlay": bool(values.get("include_semantic_overlay") is not False),
        }
    if action == "collect_changes":
        return {
            "build_id": values.get("build_id", ""),
            "change_mode": values.get("change_mode", "working_tree"),
            "skeleton_generation": values.get("skeleton_generation", 0),
        }
    if action == "repair_items":
        return {
            "change_set_id": values.get("change_set_id", ""),
            "skeleton_generation": values.get("skeleton_generation", 0),
            "group_by_folder_threshold": values.get("group_by_folder_threshold", 40),
        }
    if action == "submit_overlay":
        return {
            key: values.get(key, "")
            for key in (
                "build_id",
                "overlay_kind",
                "stable_ref",
                "skeleton_node_id",
                "skeleton_edge_id",
                "anchor_ref",
                "status",
                "confidence",
                "created_by_task_run_id",
                "created_by_agent_id",
                "overlay_id",
            )
        } | {
            "generation": values.get("generation", 0),
            "payload": dict(values.get("payload") or {}),
            "evidence_refs": list(values.get("evidence_refs") or []),
        }
    return {}


def _format_control_projection(payload: dict[str, Any]) -> str:
    session = dict(payload.get("traversal_session") or {})
    frontier = list(payload.get("frontier_items") or [])
    visited = list(payload.get("visited_refs") or [])
    decisions = list(payload.get("recent_decisions") or [])
    lines = [
        f"Project network traversal: {session.get('traversal_session_id')}",
        f"build_id={session.get('build_id')}, generation={session.get('generation')}, status={session.get('status')}, budget={session.get('crawl_budget')}",
        f"goal={session.get('goal') or '<none>'}",
        f"current_nodes={len(session.get('current_node_ids') or [])}, frontier={len(frontier)}, visited={len(visited)}, decisions={len(decisions)}",
    ]
    for item in frontier[:12]:
        lines.append(
            "- frontier "
            f"{item.get('priority')} {item.get('relation_kind')} -> "
            f"{item.get('stable_ref') or item.get('target_node_id')} "
            f"[{item.get('frontier_item_id')}]"
        )
    return "\n".join(lines)


def _project_network_result(text: str, *, ok: bool, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = dict(payload or {})
    body.setdefault("ok", ok)
    return {
        "text": str(text or ""),
        "structured_payload": {
            "tool_result": body,
        },
    }
