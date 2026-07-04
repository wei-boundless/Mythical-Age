from __future__ import annotations

import asyncio
import json
import re
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
from core.project_layout import ProjectLayout
from file_management.project_structure import ProjectNetworkControlService
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr
from project_network_system.service import ProjectNetworkBuildService


ProjectNetworkAction = Literal[
    "build_skeleton",
    "read_node",
    "read_edge",
    "expand",
    "directory_relations",
    "collect_changes",
    "repair_items",
    "submit_overlay",
    "start_navigation",
    "read_paths",
    "select_path",
    "record_decision",
    "locate",
    "jump",
    "trace",
    "summarize_chain",
    "read_audit",
    "queue_repair",
    "queue_audit_repairs",
    "read_repairs",
]


_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("provider", "providers", "supplier", "vendor", "供应商"),
    ("llm", "model", "models", "模型"),
    ("terminate", "stop", "cancel", "kill", "终止", "停止", "结束"),
    ("task", "tasks", "job", "jobs", "任务"),
    ("websocket", "ws", "socket", "长连接"),
    ("register", "registration", "registry", "注册"),
    ("ipc", "channel", "invoke", "通道", "进程间"),
    ("preload", "bridge", "bridged", "桥接", "预加载"),
    ("factory", "builder", "creator", "工厂", "构建"),
    ("node", "nodes", "节点"),
    ("api", "apis", "endpoint", "endpoints", "接口"),
    ("memory", "store", "storage", "记忆", "存储"),
)

_BRIDGE_HINTS = (
    "bridge",
    "bridged",
    "ipc",
    "invoke",
    "preload",
    "api",
    "endpoint",
    "handler",
    "signal",
    "channel",
    "route",
    "call",
    "import",
    "adapter",
    "connector",
    "websocket",
    "ws",
    "桥接",
    "通道",
    "链路",
    "信号",
)


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
    navigation_session_id: str = Field(default="", description="Project network navigation session id.")
    goal: str = Field(default="", description="Navigation goal stated in agent-operable terms.")
    intent: str = Field(default="", description="Semantic intent for locate/trace actions.")
    topic: str = Field(default="", description="Signal-chain topic or keyword filter.")
    direction: str = Field(default="both", description="Jump direction: parent, child, upstream, downstream, related, or both.")
    chain_ref: str = Field(default="", description="Signal chain ref for summarize_chain.")
    signal_ref: str = Field(default="", description="Audit signal subject, route ref, or edge id.")
    subject_ref: str = Field(default="", description="Unified graph subject ref for repair or inspection.")
    signal_source: str = Field(default="", description="Maintenance signal source such as artifact_audit, locate_failure, bridge_gap, or manual_request.")
    signal_code: str = Field(default="", description="Maintenance signal code such as unresolved_route_ref or locate_no_primary_match.")
    requested_layers: list[str] = Field(default_factory=list, description="Requested project-network layers to repair.")
    trigger_signal_id: str = Field(default="", description="Repair queue trigger signal id.")
    repair_status: str = Field(default="", description="Repair queue status filter.")
    anchor_node_ids: list[str] = Field(default_factory=list, description="Navigation anchor skeleton node ids.")
    anchor_stable_refs: list[str] = Field(default_factory=list, description="Navigation anchor stable physical refs.")
    anchor_paths: list[str] = Field(default_factory=list, description="Navigation anchor workspace paths.")
    route_depth: int = Field(default=3, ge=1, le=6, description="Maximum physical edge depth for precomputed path candidates.")
    path_limit: int = Field(default=80, ge=1, le=500, description="Maximum precomputed path candidates to materialize.")
    selected_path_candidate_id: str = Field(default="", description="Path candidate chosen or updated by the agent.")
    decision_kind: str = Field(default="", description="Agent control decision kind.")
    reason: str = Field(default="", description="Agent-readable reason for the control decision.")
    decision_status: str = Field(default="recorded", description="Status for record_decision.")
    path_status: str = Field(default="available", description="Path candidate status to read.")
    refresh_paths: bool = Field(default=True, description="Whether select_path should refresh path candidates around the selected focus.")
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
        if normalized in {"start_navigation", "read_paths", "select_path", "record_decision"}:
            return self._run_control_action(normalized, kwargs)
        if normalized in {"locate", "jump", "trace", "summarize_chain", "read_audit", "queue_repair", "queue_audit_repairs", "read_repairs"}:
            return self._run_artifact_action(normalized, kwargs)
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
            if action == "start_navigation":
                build_id = str(values.get("build_id") or "").strip()
                if not build_id:
                    latest_artifact_root = _artifact_root(self._root_dir, "")
                    latest_bundle = _load_artifact_bundle(latest_artifact_root)
                    build_id = _bundle_build_id(latest_bundle, artifact_root=latest_artifact_root)
                projection = service.start_navigation(
                    build_id=build_id,
                    goal=str(values.get("goal") or ""),
                    anchor_node_ids=list(values.get("anchor_node_ids") or []),
                    anchor_stable_refs=list(values.get("anchor_stable_refs") or []),
                    anchor_paths=list(values.get("anchor_paths") or []),
                    generation=int(values.get("generation") or 0) or None,
                    route_depth=int(values.get("route_depth") or 3),
                    path_limit=int(values.get("path_limit") or 80),
                    created_by_task_run_id=str(values.get("created_by_task_run_id") or ""),
                    created_by_agent_id=str(values.get("created_by_agent_id") or ""),
                    navigation_session_id=str(values.get("navigation_session_id") or ""),
                    include_local_slice=bool(values.get("include_local_slice") is not False),
                )
            elif action == "read_paths":
                projection = service.read_paths(
                    navigation_session_id=str(values.get("navigation_session_id") or ""),
                    status=str(values.get("path_status") or "available"),
                    limit=int(values.get("limit") or 50),
                    include_local_slice=bool(values.get("include_local_slice") is not False),
                )
            elif action == "select_path":
                projection = service.select_path(
                    navigation_session_id=str(values.get("navigation_session_id") or ""),
                    selected_path_candidate_id=str(values.get("selected_path_candidate_id") or ""),
                    node_id=str(values.get("node_id") or ""),
                    edge_id=str(values.get("edge_id") or ""),
                    reason=str(values.get("reason") or ""),
                    evidence_refs=list(values.get("evidence_refs") or []),
                    refresh_paths=bool(values.get("refresh_paths") is not False),
                    created_by_task_run_id=str(values.get("created_by_task_run_id") or ""),
                    created_by_agent_id=str(values.get("created_by_agent_id") or ""),
                    include_local_slice=bool(values.get("include_local_slice") is not False),
                )
            elif action == "record_decision":
                projection = service.record_decision(
                    navigation_session_id=str(values.get("navigation_session_id") or ""),
                    decision_kind=str(values.get("decision_kind") or ""),
                    selected_path_candidate_id=str(values.get("selected_path_candidate_id") or ""),
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

    def _run_artifact_action(self, action: str, values: dict[str, Any]) -> dict[str, Any]:
        try:
            artifact_root = _artifact_root(self._root_dir, str(values.get("build_id") or ""))
            bundle = _load_artifact_bundle(artifact_root)
            build_id = _bundle_build_id(bundle, artifact_root=artifact_root)
            if action == "locate":
                payload = _locate_from_artifacts(
                    bundle,
                    artifact_root=artifact_root,
                    build_id=build_id,
                    intent=str(values.get("intent") or values.get("goal") or values.get("topic") or ""),
                    limit=int(values.get("limit") or 20),
                )
            elif action == "jump":
                payload = _jump_from_artifacts(
                    bundle,
                    artifact_root=artifact_root,
                    build_id=build_id,
                    stable_ref=str(values.get("stable_ref") or values.get("subject_ref") or values.get("path") or ""),
                    direction=str(values.get("direction") or "both"),
                    limit=int(values.get("limit") or 20),
                )
            elif action == "trace":
                payload = _trace_from_artifacts(
                    bundle,
                    artifact_root=artifact_root,
                    build_id=build_id,
                    stable_ref=str(values.get("stable_ref") or values.get("subject_ref") or ""),
                    topic=str(values.get("topic") or values.get("intent") or values.get("goal") or ""),
                    limit=int(values.get("limit") or 20),
                )
            elif action == "summarize_chain":
                payload = _summarize_chain_from_artifacts(
                    bundle,
                    artifact_root=artifact_root,
                    build_id=build_id,
                    chain_ref=str(values.get("chain_ref") or ""),
                    stable_ref=str(values.get("stable_ref") or values.get("subject_ref") or ""),
                    limit=int(values.get("limit") or 12),
                )
            elif action == "read_audit":
                payload = _audit_from_artifacts(
                    bundle,
                    artifact_root=artifact_root,
                    build_id=build_id,
                    signal_ref=str(values.get("signal_ref") or values.get("stable_ref") or values.get("edge_id") or ""),
                    limit=int(values.get("limit") or 40),
                )
            elif action == "queue_repair":
                payload = _queue_repair_from_artifacts(
                    self._root_dir,
                    bundle,
                    artifact_root=artifact_root,
                    build_id=build_id,
                    values=values,
                )
            elif action == "queue_audit_repairs":
                payload = _queue_audit_repairs_from_artifacts(
                    self._root_dir,
                    bundle,
                    artifact_root=artifact_root,
                    build_id=build_id,
                    values=values,
                )
            elif action == "read_repairs":
                payload = _read_repairs_from_store(
                    self._root_dir,
                    bundle,
                    artifact_root=artifact_root,
                    build_id=build_id,
                    values=values,
                )
            else:
                return _project_network_result(f"project_network failed: unsupported artifact action {action!r}", ok=False, payload={"kind": action})
        except Exception as exc:
            return _project_network_result(f"Project network artifact action failed: {exc}", ok=False, payload={"kind": action})
        return _project_network_result(_format_artifact_action(action, payload), ok=True, payload=payload)


def _artifact_root(root_dir: Path, build_id: str) -> Path:
    layout = ProjectLayout.from_backend_dir(root_dir)
    base = layout.tasks_dir / "project_network_artifacts"
    target = str(build_id or "").strip()
    if target:
        path = base / _safe_segment(target)
        if path.exists():
            return path
        raise FileNotFoundError(f"project network artifact build not found: {target}")
    candidates = [item for item in base.iterdir() if item.is_dir()] if base.exists() else []
    if not candidates:
        raise FileNotFoundError("no project network artifacts found")
    return max(candidates, key=lambda item: item.stat().st_mtime)


def _load_artifact_bundle(artifact_root: Path) -> dict[str, Any]:
    manifest = _read_json(artifact_root / "manifest.json")
    coordinates = _read_json(artifact_root / "semantic_coordinates.json")
    route_index = _read_json(artifact_root / "deep_network_route_index.json")
    signal_chain_index = _read_json(artifact_root / "signal_chain_index.json")
    link_audit = _read_json(artifact_root / "link_signal_audit.json")
    unified = _read_json(artifact_root / "unified_control_graph.json")
    if not unified:
        unified = _synthesize_unified_control_graph(
            build_id=str(manifest.get("build_id") or route_index.get("build_id") or coordinates.get("build_id") or artifact_root.name),
            coordinates=coordinates,
            route_index=route_index,
            signal_chain_index=signal_chain_index,
            link_audit=link_audit,
        )
    return {
        "manifest": manifest,
        "semantic_coordinates": coordinates,
        "deep_network_route_index": route_index,
        "signal_chain_index": signal_chain_index,
        "link_signal_audit": link_audit,
        "unified_control_graph": unified,
    }


def _bundle_build_id(bundle: dict[str, Any], *, artifact_root: Path) -> str:
    return str(
        dict(bundle.get("manifest") or {}).get("build_id")
        or dict(bundle.get("unified_control_graph") or {}).get("build_id")
        or dict(bundle.get("deep_network_route_index") or {}).get("build_id")
        or dict(bundle.get("semantic_coordinates") or {}).get("build_id")
        or artifact_root.name
    ).strip()


def _locate_from_artifacts(
    bundle: dict[str, Any],
    *,
    artifact_root: Path,
    build_id: str,
    intent: str,
    limit: int,
) -> dict[str, Any]:
    graph = dict(bundle.get("unified_control_graph") or {})
    route_index = dict(bundle.get("deep_network_route_index") or {})
    chain_index = dict(bundle.get("signal_chain_index") or {})
    query = _query_profile(intent)
    node_lookup = _node_lookup(graph)
    edges_by_ref = _edges_by_ref(graph)
    if _is_architecture_overview_intent(query):
        return _locate_architecture_overview(
            graph,
            artifact_root=artifact_root,
            build_id=build_id,
            intent=intent,
            query=query,
            edges_by_ref=edges_by_ref,
            limit=limit,
        )
    candidates: list[dict[str, Any]] = []
    for node in list(graph.get("nodes") or []):
        if not isinstance(node, dict):
            continue
        stable_ref = _node_ref(node)
        connected_edges = edges_by_ref.get(stable_ref, [])
        score, breakdown, matched_terms = _score_node_candidate(node, connected_edges=connected_edges, query=query)
        if query["base_terms"] and score <= 0:
            continue
        candidates.append(
            {
                "score": score,
                "entry": _node_match_entry(
                    node,
                    connected_edges=connected_edges,
                    score=score,
                    breakdown=breakdown,
                    matched_terms=matched_terms,
                ),
            }
        )

    edge_candidates: list[dict[str, Any]] = []
    for edge in list(graph.get("edges") or []):
        if not isinstance(edge, dict):
            continue
        source = node_lookup.get(str(dict(edge.get("identity") or {}).get("source_ref") or ""))
        target = node_lookup.get(str(dict(edge.get("identity") or {}).get("target_ref") or ""))
        score, breakdown, matched_terms = _score_edge_candidate(edge, source_node=source, target_node=target, query=query)
        if query["base_terms"] and score <= 0:
            continue
        edge_candidates.append(
            {
                "score": score,
                "entry": _edge_match_entry(
                    edge,
                    source_node=source,
                    target_node=target,
                    score=score,
                    breakdown=breakdown,
                    matched_terms=matched_terms,
                ),
            }
        )

    matched_refs = {str(dict(item.get("entry") or {}).get("ref") or "") for item in candidates[: min(len(candidates), 20)]}
    chain_candidates: list[dict[str, Any]] = []
    for chain in list(chain_index.get("chains") or []):
        if not isinstance(chain, dict):
            continue
        score, matched_terms = _score_chain_candidate(chain, query=query, matched_refs=matched_refs)
        if query["base_terms"] and score <= 0:
            continue
        chain_candidates.append({"score": score, "entry": _chain_match_entry(chain, score=score, matched_terms=matched_terms)})

    candidates.sort(key=lambda item: (-float(item.get("score") or 0), str(dict(item.get("entry") or {}).get("label") or "")))
    edge_candidates.sort(key=lambda item: (-float(item.get("score") or 0), str(dict(item.get("entry") or {}).get("edge_kind") or "")))
    chain_candidates.sort(key=lambda item: (-float(item.get("score") or 0), str(dict(item.get("entry") or {}).get("source_label") or "")))

    primary: list[dict[str, Any]] = []
    fallback: list[dict[str, Any]] = []
    for item in candidates:
        entry = dict(item.get("entry") or {})
        if not primary and not query["base_terms"]:
            primary.append(entry)
            continue
        route_status = str(entry.get("route_status") or "")
        if float(item.get("score") or 0) >= 12 and route_status == "resolved":
            primary.append(entry)
        else:
            fallback.append(entry)

    bridge_landings = [dict(item.get("entry") or {}) for item in edge_candidates if dict(item.get("entry") or {}).get("bridge_strength")][: max(1, min(limit, 100))]
    primary_landings = primary[: max(1, min(limit, 100))]
    fallback_candidates = fallback[: max(1, min(limit, 100))]
    chain_anchors = [dict(item.get("entry") or {}) for item in chain_candidates[: max(1, min(limit, 40))]]

    flattened = _dedupe_match_entries([*primary_landings, *bridge_landings, *chain_anchors, *fallback_candidates], limit=max(1, min(limit, 100)))
    return {
        "action": "locate",
        "artifact_root": str(artifact_root),
        "build_id": build_id,
        "intent": intent,
        "query": query,
        "summary": {
            "node_candidate_count": len(candidates),
            "bridge_candidate_count": len(edge_candidates),
            "chain_candidate_count": len(chain_candidates),
            "primary_count": len(primary_landings),
            "fallback_count": len(fallback_candidates),
            "reliable_route_count": len(list(route_index.get("reliable_routes") or [])),
        },
        "primary_landings": primary_landings,
        "bridge_landings": bridge_landings,
        "chain_anchors": chain_anchors,
        "fallback_candidates": fallback_candidates,
        "matches": flattened,
    }


def _locate_architecture_overview(
    graph: dict[str, Any],
    *,
    artifact_root: Path,
    build_id: str,
    intent: str,
    query: dict[str, Any],
    edges_by_ref: dict[str, list[dict[str, Any]]],
    limit: int,
) -> dict[str, Any]:
    nodes = [dict(item) for item in list(graph.get("nodes") or []) if isinstance(item, dict)]
    root_node = _resolve_graph_node(graph, "folder://.")
    top_nodes = _top_level_architecture_nodes(nodes)
    primary: list[dict[str, Any]] = []
    if root_node:
        primary.append(
            _node_match_entry(
                root_node,
                connected_edges=edges_by_ref.get("folder://.", []),
                score=120.0,
                breakdown={"architecture": 120.0},
                matched_terms=query["base_terms"][:16],
            )
        )
    for index, node in enumerate(top_nodes[: max(1, min(limit, 20))], start=1):
        ref = _node_ref(node)
        primary.append(
            _node_match_entry(
                node,
                connected_edges=edges_by_ref.get(ref, []),
                score=max(80.0, 112.0 - index),
                breakdown={"architecture": max(80.0, 112.0 - index)},
                matched_terms=query["base_terms"][:16],
            )
        )
    bridge_landings: list[dict[str, Any]] = []
    node_lookup = _node_lookup(graph)
    for edge in edges_by_ref.get("folder://.", []):
        if not isinstance(edge, dict):
            continue
        identity = dict(edge.get("identity") or {})
        semantic = dict(edge.get("semantic_facets") or {})
        if str(semantic.get("edge_kind") or "") not in {"contains", "contains_directory", "contains_file", "owns", "ownership"}:
            continue
        source = node_lookup.get(str(identity.get("source_ref") or ""))
        target = node_lookup.get(str(identity.get("target_ref") or ""))
        bridge_landings.append(
            _edge_match_entry(
                edge,
                source_node=source,
                target_node=target,
                score=70.0,
                breakdown={"architecture": 70.0},
                matched_terms=query["base_terms"][:16],
            )
        )
    primary_landings = _dedupe_match_entries(primary, limit=max(1, min(limit, 100)))
    bridge_landings = _dedupe_match_entries(bridge_landings, limit=max(1, min(limit, 100)))
    return {
        "action": "locate",
        "artifact_root": str(artifact_root),
        "build_id": build_id,
        "intent": intent,
        "query": query,
        "architecture_overview_report": "PROJECT_ARCHITECTURE_OVERVIEW.md",
        "summary": {
            "intent_kind": "project_architecture_overview",
            "node_candidate_count": len(primary_landings),
            "bridge_candidate_count": len(bridge_landings),
            "chain_candidate_count": 0,
            "primary_count": len(primary_landings),
            "fallback_count": 0,
        },
        "primary_landings": primary_landings,
        "bridge_landings": bridge_landings,
        "chain_anchors": [],
        "fallback_candidates": [],
        "matches": _dedupe_match_entries([*primary_landings, *bridge_landings], limit=max(1, min(limit, 100))),
    }


def _jump_from_artifacts(
    bundle: dict[str, Any],
    *,
    artifact_root: Path,
    build_id: str,
    stable_ref: str,
    direction: str,
    limit: int,
) -> dict[str, Any]:
    graph = dict(bundle.get("unified_control_graph") or {})
    current = _resolve_graph_node(graph, stable_ref)
    target_ref = _node_ref(current) if current else str(stable_ref or "").strip()
    edges_by_ref = _edges_by_ref(graph)
    related = _filter_related_edges(edges_by_ref.get(target_ref, []), stable_ref=target_ref, direction=direction, limit=limit)
    nearby = _nearby_node_matches(graph, stable_ref=target_ref, limit=limit)
    chain_anchors = _top_chain_entries(bundle, stable_ref=target_ref, limit=limit)
    return {
        "action": "jump",
        "artifact_root": str(artifact_root),
        "build_id": build_id,
        "stable_ref": stable_ref,
        "resolved_ref": target_ref,
        "direction": direction,
        "current_node": _node_match_entry(current, connected_edges=edges_by_ref.get(target_ref, []), score=0, breakdown={}, matched_terms=[]) if current else {},
        "nearby_routes": nearby,
        "related_edges": related,
        "chain_anchors": chain_anchors,
    }


def _trace_from_artifacts(
    bundle: dict[str, Any],
    *,
    artifact_root: Path,
    build_id: str,
    stable_ref: str,
    topic: str,
    limit: int,
) -> dict[str, Any]:
    graph = dict(bundle.get("unified_control_graph") or {})
    query = _query_profile(topic)
    target_node = _resolve_graph_node(graph, stable_ref)
    target_ref = _node_ref(target_node) if target_node else str(stable_ref or "").strip()
    node_lookup = _node_lookup(graph)
    related_edges = _edges_by_ref(graph).get(target_ref, []) if target_ref else list(graph.get("edges") or [])
    traced: list[dict[str, Any]] = []
    for edge in related_edges:
        if not isinstance(edge, dict):
            continue
        source = node_lookup.get(str(dict(edge.get("identity") or {}).get("source_ref") or ""))
        target = node_lookup.get(str(dict(edge.get("identity") or {}).get("target_ref") or ""))
        score, breakdown, matched_terms = _score_edge_candidate(edge, source_node=source, target_node=target, query=query)
        if query["base_terms"] and score <= 0:
            continue
        traced.append(
            _edge_match_entry(
                edge,
                source_node=source,
                target_node=target,
                score=score,
                breakdown=breakdown,
                matched_terms=matched_terms,
            )
        )
    traced.sort(key=lambda item: (-float(item.get("score") or 0), str(item.get("edge_kind") or "")))
    return {
        "action": "trace",
        "artifact_root": str(artifact_root),
        "build_id": build_id,
        "stable_ref": stable_ref,
        "resolved_ref": target_ref,
        "topic": topic,
        "accepted_edges": [item for item in traced if str(item.get("status") or "") == "accepted"][: max(1, min(limit, 100))],
        "candidate_edges": [item for item in traced if "candidate" in str(item.get("status") or "")][: max(1, min(limit, 100))],
        "conflict_edges": [item for item in traced if "conflict" in str(item.get("status") or "")][: max(1, min(limit, 100))],
        "chain_anchors": _top_chain_entries(bundle, stable_ref=target_ref, topic=topic, limit=limit),
    }


def _summarize_chain_from_artifacts(
    bundle: dict[str, Any],
    *,
    artifact_root: Path,
    build_id: str,
    chain_ref: str,
    stable_ref: str,
    limit: int,
) -> dict[str, Any]:
    chains = dict(bundle.get("signal_chain_index") or {})
    graph = dict(bundle.get("unified_control_graph") or {})
    node_lookup = _node_lookup(graph)
    selected: list[dict[str, Any]] = []
    for chain in list(chains.get("chains") or []):
        if not isinstance(chain, dict):
            continue
        if chain_ref and str(chain.get("chain_ref") or "") != chain_ref:
            continue
        if stable_ref and stable_ref not in json.dumps(chain, ensure_ascii=False, sort_keys=True):
            continue
        selected.append(chain)
    if not chain_ref and not stable_ref:
        selected = [dict(item) for item in list(chains.get("chains") or []) if isinstance(item, dict)]
    summaries = []
    for chain in selected[: max(1, min(limit, 50))]:
        source_ref = str(chain.get("source_ref") or "")
        source_node = node_lookup.get(source_ref)
        outgoing = list(chain.get("outgoing") or [])
        summaries.append(
            {
                "chain_ref": str(chain.get("chain_ref") or ""),
                "source_ref": source_ref,
                "source_label": _node_label(source_node) if source_node else str(chain.get("source_label") or ""),
                "counts": {
                    "outgoing": int(chain.get("outgoing_count") or 0),
                    "accepted": int(chain.get("accepted_count") or 0),
                    "candidate": int(chain.get("candidate_count") or 0),
                    "conflict": int(chain.get("conflict_count") or 0),
                },
                "top_edges": outgoing[:12],
                "recommended_next_action": "read_source_and_targets_for_evidence" if outgoing else "no_chain_edges_found",
            }
        )
    return {
        "action": "summarize_chain",
        "artifact_root": str(artifact_root),
        "build_id": build_id,
        "chain_ref": chain_ref,
        "stable_ref": stable_ref,
        "summaries": summaries,
    }


def _audit_from_artifacts(
    bundle: dict[str, Any],
    *,
    artifact_root: Path,
    build_id: str,
    signal_ref: str,
    limit: int,
) -> dict[str, Any]:
    audit = dict(bundle.get("link_signal_audit") or {})
    target = str(signal_ref or "").strip()
    graph = dict(bundle.get("unified_control_graph") or {})
    node_lookup = _node_lookup(graph)
    signals = [dict(item) for item in list(audit.get("signals") or []) if isinstance(item, dict)]
    if target:
        signals = [
            item
            for item in signals
            if target in {
                str(item.get("subject_ref") or ""),
                str(item.get("edge_id") or ""),
                str(item.get("ref") or ""),
                str(item.get("code") or ""),
            }
        ]
    projected = []
    for signal in signals[: max(1, min(limit, 200))]:
        projected.append(
            {
                **signal,
                "context_label": _audit_context_label(signal, node_lookup=node_lookup, graph=graph),
            }
        )
    return {
        "action": "read_audit",
        "artifact_root": str(artifact_root),
        "build_id": build_id,
        "summary": dict(audit.get("summary") or {}),
        "signals": projected,
    }


def _queue_repair_from_artifacts(
    root_dir: Path,
    bundle: dict[str, Any],
    *,
    artifact_root: Path,
    build_id: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    service = ProjectNetworkBuildService.from_backend_dir(root_dir)
    graph = dict(bundle.get("unified_control_graph") or {})
    audit = dict(bundle.get("link_signal_audit") or {})

    requested_layers = list(values.get("requested_layers") or [])
    subject_ref = str(values.get("subject_ref") or values.get("stable_ref") or "").strip()
    stable_ref = str(values.get("stable_ref") or values.get("subject_ref") or "").strip()
    signal_source = str(values.get("signal_source") or "").strip()
    signal_code = str(values.get("signal_code") or "").strip()
    signal_ref = str(values.get("signal_ref") or values.get("edge_id") or "").strip()
    anchor_ref = str(values.get("anchor_ref") or "").strip()
    severity = "warning"
    payload = dict(values.get("payload") or {})
    evidence_refs = list(values.get("evidence_refs") or [])
    scope_refs = []

    matched_audit = _find_audit_signal(audit, signal_ref) if signal_ref else None
    if matched_audit:
        signal_source = signal_source or "artifact_audit"
        signal_code = signal_code or str(matched_audit.get("code") or "")
        severity = str(matched_audit.get("severity") or severity)
        subject_ref = subject_ref or _repair_subject_from_audit(matched_audit)
        stable_ref = stable_ref or _repair_stable_ref_from_audit(matched_audit)
        payload.setdefault("audit_signal", matched_audit)
        scope_refs.extend(
            [
                subject_ref,
                stable_ref,
                str(matched_audit.get("ref") or ""),
                str(matched_audit.get("edge_id") or ""),
            ]
        )
        details = dict(matched_audit.get("details") or {})
        if details:
            payload.setdefault("audit_details", details)
    elif signal_ref:
        if signal_ref.startswith("pnedge:"):
            subject_ref = subject_ref or signal_ref
            stable_ref = stable_ref or signal_ref
            scope_refs.append(signal_ref)
        elif signal_ref.startswith(("file://", "folder://", "fn://", "pyast://", "handler://", "function://", "func://", "symbol://")):
            subject_ref = subject_ref or signal_ref
            stable_ref = stable_ref or signal_ref
            scope_refs.append(signal_ref)
        elif not signal_code:
            signal_source = signal_source or "manual_request"
            signal_code = signal_ref

    resolved_node = _resolve_graph_node(graph, subject_ref or stable_ref or signal_ref)
    if resolved_node:
        resolved_ref = _node_ref(resolved_node)
        subject_ref = subject_ref or resolved_ref
        stable_ref = stable_ref or resolved_ref
        scope_refs.append(resolved_ref)
        audit_signals = list(dict(resolved_node.get("control_surface") or {}).get("audit_signals") or [])
        if audit_signals and not signal_code:
            first_signal = dict(audit_signals[0])
            signal_source = signal_source or "artifact_audit"
            signal_code = signal_code or str(first_signal.get("code") or "")
            severity = str(first_signal.get("severity") or severity)
            payload.setdefault("node_audit_signal", first_signal)

    if subject_ref or stable_ref:
        related_edges = _edges_by_ref(graph).get(subject_ref or stable_ref, [])
        if not signal_code and not related_edges:
            signal_source = signal_source or "bridge_gap"
            signal_code = "bridge_gap"
            payload.setdefault("gap_reason", "no_related_edges_for_subject")
        elif not signal_code and related_edges:
            signal_source = signal_source or "manual_request"
            signal_code = "coverage_gap"
            payload.setdefault("gap_reason", "manual_refresh_request")

    locate_probe = {}
    intent = str(values.get("intent") or values.get("goal") or values.get("topic") or "").strip()
    if not signal_code and intent:
        locate_probe = _locate_from_artifacts(
            bundle,
            artifact_root=artifact_root,
            build_id=build_id,
            intent=intent,
            limit=min(int(values.get("limit") or 6), 12),
        )
        primary = list(locate_probe.get("primary_landings") or [])
        fallback = list(locate_probe.get("fallback_candidates") or [])
        if not primary:
            signal_source = signal_source or "locate_failure"
            signal_code = "locate_no_primary_match"
            severity = "warning"
        else:
            top = dict(primary[0] or {})
            subject_ref = subject_ref or str(top.get("ref") or "")
            stable_ref = stable_ref or str(top.get("ref") or "")
            if float(top.get("score") or 0) < 16:
                signal_source = signal_source or "locate_failure"
                signal_code = "locate_weak_match"
                severity = "info"
        if fallback and not subject_ref:
            subject_ref = str(dict(fallback[0]).get("ref") or "")
            stable_ref = stable_ref or subject_ref
        payload.setdefault(
            "locate_probe",
            {
                "intent": intent,
                "primary_count": len(primary),
                "bridge_count": len(list(locate_probe.get("bridge_landings") or [])),
                "fallback_count": len(fallback),
                "top_primary": primary[:3],
                "top_fallback": fallback[:3],
            },
        )

    signal_source = signal_source or "manual_request"
    signal_code = signal_code or "refresh_semantic_control_slice"
    stable_ref = stable_ref or subject_ref
    queue_result = service.queue_repair(
        build_id=build_id,
        signal_source=signal_source,
        signal_code=signal_code,
        severity=severity,
        subject_ref=subject_ref,
        stable_ref=stable_ref,
        edge_id=str(values.get("edge_id") or str(dict(matched_audit or {}).get("edge_id") or "")).strip(),
        anchor_ref=anchor_ref,
        scope_refs=[item for item in _dedupe_strings(scope_refs) if item],
        evidence_refs=[item for item in _dedupe_strings(evidence_refs) if item],
        requested_layers=requested_layers,
        payload=payload,
        metadata={
            "artifact_root": str(artifact_root),
            "trigger_signal_ref": signal_ref,
            "queue_origin": "project_network_tool",
        },
    )
    return {
        "action": "queue_repair",
        "artifact_root": str(artifact_root),
        "build_id": build_id,
        "signal": queue_result.signal.to_dict(),
        "repair_items": [item.to_dict() for item in queue_result.repair_items],
        "locate_probe": payload.get("locate_probe", locate_probe),
    }


def _queue_audit_repairs_from_artifacts(
    root_dir: Path,
    bundle: dict[str, Any],
    *,
    artifact_root: Path,
    build_id: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    audit = dict(bundle.get("link_signal_audit") or {})
    target_ref = str(values.get("signal_ref") or values.get("edge_id") or values.get("subject_ref") or values.get("stable_ref") or "").strip()
    target_code = str(values.get("signal_code") or "").strip()
    limit = max(1, min(int(values.get("limit") or 20), 100))
    selected: list[dict[str, Any]] = []
    for signal in list(audit.get("signals") or []):
        if not isinstance(signal, dict):
            continue
        code = str(signal.get("code") or "")
        severity = str(signal.get("severity") or "")
        refs = {
            str(signal.get("subject_ref") or ""),
            str(signal.get("edge_id") or ""),
            str(signal.get("ref") or ""),
            code,
        }
        if target_ref and target_ref not in refs:
            continue
        if target_code and target_code != code:
            continue
        if not target_ref and not target_code and severity not in {"error", "warning"}:
            continue
        selected.append(dict(signal))
        if len(selected) >= limit:
            break

    queued_signals: list[dict[str, Any]] = []
    queued_items: list[dict[str, Any]] = []
    seen_items: set[str] = set()
    for signal in selected:
        queue_payload = _queue_repair_from_artifacts(
            root_dir,
            bundle,
            artifact_root=artifact_root,
            build_id=build_id,
            values={
                **values,
                "signal_source": "artifact_audit",
                "signal_ref": str(signal.get("edge_id") or signal.get("subject_ref") or signal.get("ref") or signal.get("code") or ""),
                "signal_code": str(signal.get("code") or ""),
                "subject_ref": _repair_subject_from_audit(signal),
                "stable_ref": _repair_stable_ref_from_audit(signal),
                "payload": {
                    **dict(values.get("payload") or {}),
                    "audit_signal": signal,
                },
            },
        )
        queued_signals.append(dict(queue_payload.get("signal") or {}))
        for item in list(queue_payload.get("repair_items") or []):
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("repair_item_id") or "")
            if item_id and item_id in seen_items:
                continue
            if item_id:
                seen_items.add(item_id)
            queued_items.append(dict(item))

    return {
        "action": "queue_audit_repairs",
        "artifact_root": str(artifact_root),
        "build_id": build_id,
        "selected_audit_signal_count": len(selected),
        "queued_signal_count": len(queued_signals),
        "queued_repair_count": len(queued_items),
        "signals": queued_signals,
        "repair_items": queued_items,
        "summary": {
            "audit_signal_count": len(list(audit.get("signals") or [])),
            "selected_audit_signal_count": len(selected),
            "queued_repair_count": len(queued_items),
        },
    }


def _read_repairs_from_store(
    root_dir: Path,
    bundle: dict[str, Any],
    *,
    artifact_root: Path,
    build_id: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    service = ProjectNetworkBuildService.from_backend_dir(root_dir)
    stable_ref = str(values.get("stable_ref") or "").strip()
    subject_ref = str(values.get("subject_ref") or "").strip()
    trigger_signal_id = str(values.get("trigger_signal_id") or "").strip()
    status = str(values.get("repair_status") or values.get("status") or "").strip()
    projection = service.read_repairs(
        build_id=build_id,
        stable_ref=stable_ref,
        subject_ref=subject_ref,
        trigger_signal_id=trigger_signal_id,
        status=status,
        limit=int(values.get("limit") or 200),
    )
    projection["action"] = "read_repairs"
    projection["artifact_root"] = str(artifact_root)
    projection["build_id"] = build_id
    return projection


def _synthesize_unified_control_graph(
    *,
    build_id: str,
    coordinates: dict[str, Any],
    route_index: dict[str, Any],
    signal_chain_index: dict[str, Any],
    link_audit: dict[str, Any],
) -> dict[str, Any]:
    coordinate_by_ref = {
        str(item.get("physical_ref") or item.get("coordinate_ref") or ""): dict(item)
        for item in list(coordinates.get("coordinates") or [])
        if isinstance(item, dict) and str(item.get("physical_ref") or item.get("coordinate_ref") or "")
    }
    route_by_ref = {
        str(item.get("route_ref") or ""): dict(item)
        for item in [*list(route_index.get("reliable_routes") or []), *list(route_index.get("unresolved_routes") or [])]
        if isinstance(item, dict) and str(item.get("route_ref") or "")
    }
    node_signal_map: dict[str, list[dict[str, Any]]] = {}
    edge_signal_map: dict[str, list[dict[str, Any]]] = {}
    for signal in list(link_audit.get("signals") or []):
        if not isinstance(signal, dict):
            continue
        edge_id = str(signal.get("edge_id") or "")
        if edge_id:
            edge_signal_map.setdefault(edge_id, []).append(dict(signal))
        for ref in _dedupe_strings([str(signal.get("subject_ref") or ""), str(signal.get("ref") or "")]):
            if ref.startswith("route:"):
                ref = ref[len("route:") :]
            if ref and not ref.startswith("pnedge:"):
                node_signal_map.setdefault(ref, []).append(dict(signal))

    refs = set(coordinate_by_ref) | set(route_by_ref)
    for edge in [*list(signal_chain_index.get("accepted_edges") or []), *list(signal_chain_index.get("candidate_edges") or []), *list(signal_chain_index.get("conflict_edges") or [])]:
        if not isinstance(edge, dict):
            continue
        refs.add(str(edge.get("source_ref") or ""))
        refs.add(str(edge.get("target_ref") or ""))
    nodes = []
    for ref in sorted(item for item in refs if item):
        coordinate = dict(coordinate_by_ref.get(ref) or {})
        route = dict(route_by_ref.get(ref) or {})
        nodes.append(
            {
                "stable_ref": ref,
                "node_id": ref,
                "identity": {
                    "stable_ref": ref,
                    "physical_ref": str(route.get("route_ref") or coordinate.get("physical_ref") or ref),
                    "node_kind": str(route.get("node_kind") or coordinate.get("node_kind") or coordinate.get("layer") or ""),
                },
                "physical_facts": {
                    "physical_validation": dict(route.get("physical_validation") or {}),
                    "evidence_refs": _strings(route.get("evidence_refs")),
                    "anchor_refs": _strings(route.get("anchor_refs")),
                },
                "semantic_facets": {
                    "layer": str(coordinate.get("layer") or coordinate.get("node_kind") or route.get("node_kind") or ""),
                    "label": str(coordinate.get("label") or ref),
                    "summary": str(coordinate.get("summary") or ""),
                    "tags": _strings(coordinate.get("tags")),
                    "control_role": str(coordinate.get("control_role") or ""),
                    "confidence": str(coordinate.get("confidence") or route.get("confidence") or "derived"),
                },
                "control_surface": {
                    "recommended_next_action": str(route.get("recommended_next_action") or ""),
                    "audit_signals": [dict(item) for item in list(node_signal_map.get(ref) or [])],
                },
                "authority": "project_network_system.unified_control_graph.node.synthetic",
            }
        )

    edges = []
    for key, status in (("accepted_edges", "accepted"), ("candidate_edges", "candidate"), ("conflict_edges", "conflict")):
        for edge in list(signal_chain_index.get(key) or []):
            if not isinstance(edge, dict):
                continue
            edge_id = str(edge.get("edge_id") or "")
            edges.append(
                {
                    "edge_id": edge_id,
                    "identity": {
                        "edge_id": edge_id,
                        "source_ref": str(edge.get("source_ref") or ""),
                        "target_ref": str(edge.get("target_ref") or ""),
                    },
                    "physical_facts": {
                        "evidence_refs": _strings(edge.get("evidence_refs")),
                        "anchor_refs": _strings(edge.get("anchor_refs")),
                    },
                    "semantic_facets": {
                        "edge_kind": str(edge.get("edge_kind") or ""),
                        "summary": str(edge.get("summary") or ""),
                        "status": str(edge.get("status") or status),
                        "confidence": str(edge.get("confidence") or ""),
                    },
                    "control_surface": {
                        "trace_priority": 90 if status == "accepted" else 60 if status == "candidate" else 40,
                        "audit_signals": [dict(item) for item in list(edge_signal_map.get(edge_id) or [])],
                    },
                    "authority": "project_network_system.unified_control_graph.edge.synthetic",
                }
            )

    return {
        "authority": "project_network_system.unified_control_graph.synthetic",
        "control_plane": "unified_control_graph",
        "purpose": "single entity space for physical facts, semantic facets, and agent control surface",
        "build_id": build_id,
        "generated_at": str(
            route_index.get("generated_at")
            or coordinates.get("generated_at")
            or signal_chain_index.get("generated_at")
            or ""
        ),
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "accepted_edge_count": len(list(signal_chain_index.get("accepted_edges") or [])),
            "candidate_edge_count": len(list(signal_chain_index.get("candidate_edges") or [])),
            "audit_signal_count": len(list(link_audit.get("signals") or [])),
        },
        "nodes": nodes,
        "edges": edges,
    }


def _score_node_candidate(node: dict[str, Any], *, connected_edges: list[dict[str, Any]], query: dict[str, Any]) -> tuple[float, dict[str, float], list[str]]:
    identity = dict(node.get("identity") or {})
    physical = dict(node.get("physical_facts") or {})
    semantic = dict(node.get("semantic_facets") or {})
    control = dict(node.get("control_surface") or {})
    label = str(semantic.get("label") or "")
    summary = str(semantic.get("summary") or "")
    tags = _strings(semantic.get("tags"))
    route_validation = dict(physical.get("physical_validation") or {})
    signal_text = _search_blob(*list(control.get("audit_signals") or []))
    label_score, label_hits = _score_blob(label, base_terms=query["base_terms"], alias_terms=query["alias_terms"], primary_weight=9.0, alias_weight=4.0)
    semantic_score, semantic_hits = _score_blob(
        _search_blob(summary, tags, semantic.get("control_role")),
        base_terms=query["base_terms"],
        alias_terms=query["alias_terms"],
        primary_weight=5.0,
        alias_weight=2.5,
    )
    physical_score, physical_hits = _score_blob(
        _search_blob(
            identity.get("stable_ref"),
            identity.get("physical_ref"),
            route_validation.get("path"),
            route_validation.get("basis"),
            physical.get("evidence_refs"),
            physical.get("anchor_refs"),
        ),
        base_terms=query["base_terms"],
        alias_terms=query["alias_terms"],
        primary_weight=4.5,
        alias_weight=2.0,
    )
    chain_score, chain_hits = _score_blob(
        _search_blob([dict(edge.get("semantic_facets") or {}) for edge in connected_edges]),
        base_terms=query["base_terms"],
        alias_terms=query["alias_terms"],
        primary_weight=3.0,
        alias_weight=1.5,
    )
    bridge_score, bridge_hits = _score_blob(
        _search_blob(control.get("recommended_next_action"), signal_text),
        base_terms=query["base_terms"],
        alias_terms=query["alias_terms"],
        primary_weight=2.5,
        alias_weight=1.5,
    )
    score = label_score + semantic_score + physical_score + chain_score + bridge_score
    if route_validation.get("status") == "resolved":
        score += 1.5
    if label_score and physical_score:
        score += 2.0
    if not query["base_terms"]:
        score += 1.0
    matched_terms = _dedupe_strings([*label_hits, *semantic_hits, *physical_hits, *chain_hits, *bridge_hits])
    return score, {
        "label": round(label_score, 2),
        "semantic": round(semantic_score, 2),
        "physical": round(physical_score, 2),
        "chain": round(chain_score, 2),
        "bridge": round(bridge_score, 2),
    }, matched_terms


def _score_edge_candidate(
    edge: dict[str, Any],
    *,
    source_node: dict[str, Any] | None,
    target_node: dict[str, Any] | None,
    query: dict[str, Any],
) -> tuple[float, dict[str, float], list[str]]:
    identity = dict(edge.get("identity") or {})
    semantic = dict(edge.get("semantic_facets") or {})
    control = dict(edge.get("control_surface") or {})
    edge_text = _search_blob(
        identity.get("source_ref"),
        identity.get("target_ref"),
        semantic.get("edge_kind"),
        semantic.get("summary"),
        dict(source_node.get("semantic_facets") or {}) if source_node else {},
        dict(target_node.get("semantic_facets") or {}) if target_node else {},
    )
    core_score, core_hits = _score_blob(edge_text, base_terms=query["base_terms"], alias_terms=query["alias_terms"], primary_weight=4.5, alias_weight=2.0)
    bridge_bonus = _bridge_bonus(edge, source_node=source_node, target_node=target_node)
    signal_score, signal_hits = _score_blob(
        _search_blob(control.get("audit_signals")),
        base_terms=query["base_terms"],
        alias_terms=query["alias_terms"],
        primary_weight=2.0,
        alias_weight=1.0,
    )
    score = core_score + signal_score + bridge_bonus
    status = str(semantic.get("status") or "")
    if status == "accepted":
        score += 2.0
    elif "candidate" in status:
        score += 1.0
    matched_terms = _dedupe_strings([*core_hits, *signal_hits])
    return score, {
        "core": round(core_score, 2),
        "bridge": round(bridge_bonus, 2),
        "signal": round(signal_score, 2),
    }, matched_terms


def _score_chain_candidate(chain: dict[str, Any], *, query: dict[str, Any], matched_refs: set[str]) -> tuple[float, list[str]]:
    score, hits = _score_blob(
        _search_blob(chain.get("source_ref"), chain.get("source_label"), chain.get("outgoing")),
        base_terms=query["base_terms"],
        alias_terms=query["alias_terms"],
        primary_weight=4.0,
        alias_weight=2.0,
    )
    source_ref = str(chain.get("source_ref") or "")
    if source_ref and source_ref in matched_refs:
        score += 4.0
    return score, hits


def _node_match_entry(
    node: dict[str, Any] | None,
    *,
    connected_edges: list[dict[str, Any]],
    score: float,
    breakdown: dict[str, Any],
    matched_terms: list[str],
) -> dict[str, Any]:
    if not node:
        return {}
    identity = dict(node.get("identity") or {})
    physical = dict(node.get("physical_facts") or {})
    semantic = dict(node.get("semantic_facets") or {})
    control = dict(node.get("control_surface") or {})
    validation = dict(physical.get("physical_validation") or {})
    return _drop_empty(
        {
            "match_kind": "node",
            "ref": _node_ref(node),
            "physical_ref": str(identity.get("physical_ref") or ""),
            "node_kind": str(identity.get("node_kind") or ""),
            "layer": str(semantic.get("layer") or ""),
            "label": str(semantic.get("label") or _node_ref(node)),
            "summary": str(semantic.get("summary") or ""),
            "tags": _strings(semantic.get("tags")),
            "control_role": str(semantic.get("control_role") or ""),
            "route_status": str(validation.get("status") or ""),
            "path": str(validation.get("path") or ""),
            "recommended_next_action": str(control.get("recommended_next_action") or ""),
            "connected_edge_count": len(connected_edges),
            "audit_codes": _signal_codes(control.get("audit_signals")),
            "score": round(score, 2),
            "score_breakdown": breakdown,
            "matched_terms": matched_terms[:16],
        }
    )


def _edge_match_entry(
    edge: dict[str, Any],
    *,
    source_node: dict[str, Any] | None,
    target_node: dict[str, Any] | None,
    score: float,
    breakdown: dict[str, Any],
    matched_terms: list[str],
) -> dict[str, Any]:
    identity = dict(edge.get("identity") or {})
    semantic = dict(edge.get("semantic_facets") or {})
    return _drop_empty(
        {
            "match_kind": "edge_bridge",
            "edge_id": str(edge.get("edge_id") or ""),
            "source_ref": str(identity.get("source_ref") or ""),
            "source_label": _node_label(source_node),
            "target_ref": str(identity.get("target_ref") or ""),
            "target_label": _node_label(target_node),
            "edge_kind": str(semantic.get("edge_kind") or ""),
            "summary": str(semantic.get("summary") or ""),
            "status": str(semantic.get("status") or ""),
            "bridge_strength": round(_bridge_bonus(edge, source_node=source_node, target_node=target_node), 2),
            "score": round(score, 2),
            "score_breakdown": breakdown,
            "matched_terms": matched_terms[:16],
            "audit_codes": _signal_codes(dict(edge.get("control_surface") or {}).get("audit_signals")),
        }
    )


def _chain_match_entry(chain: dict[str, Any], *, score: float, matched_terms: list[str]) -> dict[str, Any]:
    return _drop_empty(
        {
            "match_kind": "chain_anchor",
            "chain_ref": str(chain.get("chain_ref") or ""),
            "source_ref": str(chain.get("source_ref") or ""),
            "source_label": str(chain.get("source_label") or ""),
            "accepted_count": int(chain.get("accepted_count") or 0),
            "candidate_count": int(chain.get("candidate_count") or 0),
            "conflict_count": int(chain.get("conflict_count") or 0),
            "outgoing_count": int(chain.get("outgoing_count") or 0),
            "score": round(score, 2),
            "matched_terms": matched_terms[:16],
            "recommended_next_action": "follow_outgoing_edges" if int(chain.get("outgoing_count") or 0) else "no_chain_edges_found",
        }
    )


def _resolve_graph_node(graph: dict[str, Any], ref: str) -> dict[str, Any] | None:
    target = str(ref or "").strip()
    if not target:
        return None
    lookup = _node_lookup(graph)
    if target in lookup:
        return lookup[target]
    suffix_target = target.replace("\\", "/").strip("/")
    for node in list(graph.get("nodes") or []):
        if not isinstance(node, dict):
            continue
        node_ref = _node_ref(node)
        validation = dict(dict(node.get("physical_facts") or {}).get("physical_validation") or {})
        path = str(validation.get("path") or "").replace("\\", "/")
        if node_ref.endswith(suffix_target) or path.endswith(suffix_target):
            return node
    return None


def _find_audit_signal(audit: dict[str, Any], signal_ref: str) -> dict[str, Any] | None:
    target = str(signal_ref or "").strip()
    if not target:
        return None
    for signal in list(audit.get("signals") or []):
        if not isinstance(signal, dict):
            continue
        if target in {
            str(signal.get("subject_ref") or ""),
            str(signal.get("edge_id") or ""),
            str(signal.get("ref") or ""),
            str(signal.get("code") or ""),
        }:
            return dict(signal)
    return None


def _repair_subject_from_audit(signal: dict[str, Any]) -> str:
    subject = str(signal.get("subject_ref") or "").strip()
    if subject.startswith("route:"):
        subject = subject[len("route:") :]
    if subject and not subject.startswith("pnedge:"):
        return subject
    ref = str(signal.get("ref") or "").strip()
    return ref or subject


def _repair_stable_ref_from_audit(signal: dict[str, Any]) -> str:
    ref = str(signal.get("ref") or "").strip()
    if ref:
        return ref
    return _repair_subject_from_audit(signal)


def _node_lookup(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for node in list(graph.get("nodes") or []):
        if not isinstance(node, dict):
            continue
        ref = _node_ref(node)
        if ref:
            result[ref] = node
    return result


def _edges_by_ref(graph: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for edge in list(graph.get("edges") or []):
        if not isinstance(edge, dict):
            continue
        identity = dict(edge.get("identity") or {})
        for ref in (str(identity.get("source_ref") or ""), str(identity.get("target_ref") or "")):
            if ref:
                result.setdefault(ref, []).append(edge)
    return result


def _filter_related_edges(edges: list[dict[str, Any]], *, stable_ref: str, direction: str, limit: int) -> list[dict[str, Any]]:
    lowered = str(direction or "both").lower()
    result = []
    for edge in edges:
        identity = dict(edge.get("identity") or {})
        source_ref = str(identity.get("source_ref") or "")
        target_ref = str(identity.get("target_ref") or "")
        source_match = source_ref == stable_ref
        target_match = target_ref == stable_ref
        if lowered in {"downstream", "child"} and not source_match:
            continue
        if lowered in {"upstream", "parent"} and not target_match:
            continue
        if lowered in {"both", "related"} and not (source_match or target_match):
            continue
        result.append(
            {
                "edge_id": str(edge.get("edge_id") or ""),
                "source_ref": source_ref,
                "target_ref": target_ref,
                "edge_kind": str(dict(edge.get("semantic_facets") or {}).get("edge_kind") or ""),
                "summary": str(dict(edge.get("semantic_facets") or {}).get("summary") or ""),
                "status": str(dict(edge.get("semantic_facets") or {}).get("status") or ""),
                "audit_codes": _signal_codes(dict(edge.get("control_surface") or {}).get("audit_signals")),
            }
        )
        if len(result) >= max(1, min(limit, 100)):
            break
    return result


def _nearby_node_matches(graph: dict[str, Any], *, stable_ref: str, limit: int) -> list[dict[str, Any]]:
    target_prefix = _path_prefix(stable_ref)
    target_root = _ref_root_segment(stable_ref)
    result = []
    for node in list(graph.get("nodes") or []):
        if not isinstance(node, dict):
            continue
        ref = _node_ref(node)
        if not ref or ref == stable_ref:
            continue
        prefix = _path_prefix(ref)
        if target_prefix and prefix.startswith(target_prefix):
            result.append(_node_match_entry(node, connected_edges=[], score=0, breakdown={}, matched_terms=[]))
        elif target_root and _ref_root_segment(ref) == target_root:
            result.append(_node_match_entry(node, connected_edges=[], score=0, breakdown={}, matched_terms=[]))
        if len(result) >= max(1, min(limit, 100)):
            break
    return result


def _top_chain_entries(bundle: dict[str, Any], *, stable_ref: str = "", topic: str = "", limit: int) -> list[dict[str, Any]]:
    chains = dict(bundle.get("signal_chain_index") or {})
    query = _query_profile(topic)
    matched_refs = {stable_ref} if stable_ref else set()
    ranked = []
    for chain in list(chains.get("chains") or []):
        if not isinstance(chain, dict):
            continue
        if stable_ref and stable_ref not in json.dumps(chain, ensure_ascii=False, sort_keys=True):
            continue
        score, matched_terms = _score_chain_candidate(chain, query=query, matched_refs=matched_refs)
        if topic and score <= 0:
            continue
        ranked.append({"score": score, "entry": _chain_match_entry(chain, score=score, matched_terms=matched_terms)})
    ranked.sort(key=lambda item: (-float(item.get("score") or 0), str(dict(item.get("entry") or {}).get("source_label") or "")))
    return [dict(item.get("entry") or {}) for item in ranked[: max(1, min(limit, 50))]]


def _audit_context_label(signal: dict[str, Any], *, node_lookup: dict[str, dict[str, Any]], graph: dict[str, Any]) -> str:
    subject_ref = _repair_subject_from_audit(signal)
    if subject_ref in node_lookup:
        return _node_label(node_lookup[subject_ref])
    edge_id = str(signal.get("edge_id") or "")
    if edge_id:
        for edge in list(graph.get("edges") or []):
            if isinstance(edge, dict) and str(edge.get("edge_id") or "") == edge_id:
                identity = dict(edge.get("identity") or {})
                return f"{identity.get('source_ref') or ''} -> {identity.get('target_ref') or ''}".strip()
    return subject_ref or str(signal.get("ref") or "")


def _query_profile(value: str) -> dict[str, Any]:
    text = str(value or "").strip()
    base_terms = _extract_terms(text)
    alias_terms = _expand_alias_terms(text, base_terms)
    return {
        "text": text,
        "base_terms": base_terms,
        "alias_terms": alias_terms,
    }


def _is_architecture_overview_intent(query: dict[str, Any]) -> bool:
    text = str(query.get("text") or "").strip().lower()
    terms = set(str(item).lower() for item in list(query.get("base_terms") or []))
    exact_phrases = {
        "整体架构",
        "系统架构",
        "项目架构",
        "项目总览",
        "整体总览",
        "架构总览",
        "架构图",
        "architecture overview",
        "project overview",
        "system overview",
        "system map",
        "project map",
    }
    if any(phrase in text for phrase in exact_phrases):
        return True
    if "架构" in terms and not (terms & {"文件系统", "操作系统"}):
        return True
    if "总览" in terms or "overview" in terms:
        return True
    return False


def _top_level_architecture_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for node in nodes:
        ref = _node_ref(node)
        if not ref.startswith("folder://") or ref == "folder://.":
            continue
        raw = ref[len("folder://") :].replace("\\", "/").strip("/")
        if raw and "/" not in raw:
            result.append(node)
    preferred = {"AGENT": 0, "CLIENT": 1, "TASK": 2, "MEMORY": 3, "FILE": 4, "README": 5}
    return sorted(result, key=lambda item: (preferred.get(_ref_root_segment(_node_ref(item)), 50), _node_ref(item)))


def _extract_terms(value: str) -> list[str]:
    text = str(value or "")
    results: list[str] = []
    seen: set[str] = set()

    def push(term: str) -> None:
        item = str(term or "").strip().lower()
        if not item:
            return
        if len(item) == 1 and item.isascii():
            return
        if item in seen:
            return
        seen.add(item)
        results.append(item)

    push(text.strip())
    for token in re.findall(r"[A-Za-z0-9_./:-]+", text):
        push(token)
        for chunk in re.split(r"[\\/_:.\-]+", token):
            for part in _camel_parts(chunk):
                push(part)
    for segment in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        push(segment)
        max_size = min(max(len(segment), 2), 4)
        for size in range(max_size, 1, -1):
            for index in range(0, len(segment) - size + 1):
                push(segment[index : index + size])
    return results[:48]


def _expand_alias_terms(text: str, base_terms: list[str]) -> list[str]:
    lowered = str(text or "").lower()
    base = set(base_terms)
    result: list[str] = []
    seen: set[str] = set()
    for group in _ALIAS_GROUPS:
        lowered_group = tuple(item.lower() for item in group)
        if not any(item in lowered for item in lowered_group) and not any(item in base for item in lowered_group):
            continue
        for item in lowered_group:
            if item and item not in base and item not in seen:
                seen.add(item)
                result.append(item)
    return result[:48]


def _camel_parts(value: str) -> list[str]:
    token = str(value or "").strip()
    if not token:
        return []
    parts = re.findall(r"[A-Z]+(?=[A-Z][a-z]|[0-9]|$)|[A-Z]?[a-z]+|[0-9]+", token)
    return [part.lower() for part in parts if part.strip()] or [token.lower()]


def _score_blob(blob: str, *, base_terms: list[str], alias_terms: list[str], primary_weight: float, alias_weight: float) -> tuple[float, list[str]]:
    haystack = _normalized_blob(blob)
    total = 0.0
    matched: list[str] = []
    for term in base_terms:
        if term and term in haystack:
            total += primary_weight + _term_bonus(term)
            matched.append(term)
    for term in alias_terms:
        if term and term in haystack:
            total += alias_weight + (_term_bonus(term) * 0.5)
            matched.append(term)
    return total, _dedupe_strings(matched)


def _normalized_blob(value: Any) -> str:
    return " ".join(_extract_terms(_search_blob(value)))


def _search_blob(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if value in ("", None, [], {}, ()):
            continue
        if isinstance(value, (dict, list, tuple, set)):
            parts.append(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))
        else:
            parts.append(str(value))
    return " ".join(parts)


def _term_bonus(term: str) -> float:
    lowered = str(term or "").strip().lower()
    if not lowered:
        return 0.0
    if any("\u4e00" <= char <= "\u9fff" for char in lowered):
        return 1.0 if len(lowered) >= 3 else 0.5
    if len(lowered) >= 8 or "/" in lowered or ":" in lowered or "." in lowered:
        return 1.2
    if len(lowered) >= 4:
        return 0.6
    return 0.0


def _bridge_bonus(edge: dict[str, Any], *, source_node: dict[str, Any] | None, target_node: dict[str, Any] | None) -> float:
    identity = dict(edge.get("identity") or {})
    semantic = dict(edge.get("semantic_facets") or {})
    edge_text = _search_blob(
        semantic.get("edge_kind"),
        semantic.get("summary"),
        identity.get("source_ref"),
        identity.get("target_ref"),
        _node_label(source_node),
        _node_label(target_node),
    ).lower()
    bonus = 0.0
    if any(hint in edge_text for hint in _BRIDGE_HINTS):
        bonus += 4.0
    if _ref_root_segment(str(identity.get("source_ref") or "")) and _ref_root_segment(str(identity.get("source_ref") or "")) != _ref_root_segment(str(identity.get("target_ref") or "")):
        bonus += 3.0
    if _path_prefix(str(identity.get("source_ref") or "")) != _path_prefix(str(identity.get("target_ref") or "")):
        bonus += 2.0
    return bonus


def _dedupe_match_entries(entries: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        key = str(entry.get("edge_id") or entry.get("chain_ref") or entry.get("ref") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(entry)
        if len(result) >= limit:
            break
    return result


def _signal_codes(value: Any) -> list[str]:
    return _dedupe_strings([str(dict(item).get("code") or "") for item in list(value or []) if isinstance(item, dict)])


def _node_ref(node: dict[str, Any] | None) -> str:
    if not node:
        return ""
    return str(dict(node.get("identity") or {}).get("stable_ref") or node.get("stable_ref") or node.get("node_id") or "")


def _node_label(node: dict[str, Any] | None) -> str:
    if not node:
        return ""
    return str(dict(node.get("semantic_facets") or {}).get("label") or _node_ref(node))


def _format_node_line(prefix: str, item: dict[str, Any]) -> str:
    return f"- {prefix} {item.get('score')} `{item.get('ref')}` [{item.get('layer') or item.get('node_kind') or '-'}] {item.get('label') or ''}"


def _format_edge_line(prefix: str, item: dict[str, Any]) -> str:
    audit_codes = ",".join(_strings(item.get("audit_codes")))
    audit_text = f" audit={audit_codes}" if audit_codes else ""
    status = str(item.get("status") or "")
    return (
        f"- {prefix} {item.get('score', '')} `{item.get('source_ref')}` -> `{item.get('target_ref')}` "
        f"via `{item.get('edge_kind') or ''}` [{status}]{audit_text}"
    )


def _format_chain_line(prefix: str, item: dict[str, Any]) -> str:
    return (
        f"- {prefix} `{item.get('source_ref')}` accepted={item.get('accepted_count', 0)} "
        f"candidate={item.get('candidate_count', 0)} outgoing={item.get('outgoing_count', 0)}"
    )


def _format_artifact_action(action: str, payload: dict[str, Any]) -> str:
    if action == "locate":
        primary = list(payload.get("primary_landings") or [])
        bridges = list(payload.get("bridge_landings") or [])
        chains = list(payload.get("chain_anchors") or [])
        fallback = list(payload.get("fallback_candidates") or [])
        lines = [
            f"Project network locate: primary={len(primary)}, bridge={len(bridges)}, chain={len(chains)}, fallback={len(fallback)}",
        ]
        if payload.get("architecture_overview_report"):
            lines.append(f"recommended_report=`{payload.get('architecture_overview_report')}`")
        for item in primary[:8]:
            lines.append(_format_node_line("node", item))
        for item in bridges[:4]:
            lines.append(_format_edge_line("edge", item))
        for item in chains[:4]:
            lines.append(_format_chain_line("chain", item))
        if not primary and fallback:
            for item in fallback[:4]:
                lines.append(_format_node_line("fallback", item))
        return "\n".join(lines)
    if action == "jump":
        related = list(payload.get("related_edges") or [])
        nearby = list(payload.get("nearby_routes") or [])
        chains = list(payload.get("chain_anchors") or [])
        lines = [
            f"Project network jump: nearby={len(list(payload.get('nearby_routes') or []))}, "
            f"related_edges={len(list(payload.get('related_edges') or []))}, chains={len(list(payload.get('chain_anchors') or []))}"
        ]
        for item in related[:8]:
            lines.append(_format_edge_line("edge", item))
        for item in nearby[:4]:
            lines.append(_format_node_line("nearby", item))
        for item in chains[:4]:
            lines.append(_format_chain_line("chain", item))
        return "\n".join(lines)
    if action == "trace":
        accepted_edges = list(payload.get("accepted_edges") or [])
        candidate_edges = list(payload.get("candidate_edges") or [])
        conflict_edges = list(payload.get("conflict_edges") or [])
        chains = list(payload.get("chain_anchors") or [])
        lines = [
            f"Project network trace: accepted={len(accepted_edges)}, candidate={len(candidate_edges)}, conflict={len(conflict_edges)}",
        ]
        for item in accepted_edges[:8]:
            lines.append(_format_edge_line("accepted", item))
        for item in candidate_edges[:8]:
            lines.append(_format_edge_line("candidate", item))
        for item in conflict_edges[:4]:
            lines.append(_format_edge_line("conflict", item))
        for item in chains[:4]:
            lines.append(_format_chain_line("chain", item))
        return "\n".join(lines)
    if action == "summarize_chain":
        return f"Project network chain summaries: {len(list(payload.get('summaries') or []))}"
    if action == "read_audit":
        summary = dict(payload.get("summary") or {})
        return f"Project network audit: signals={len(list(payload.get('signals') or []))}, warnings={summary.get('warning_count', 0)}, errors={summary.get('error_count', 0)}"
    if action == "queue_repair":
        items = list(payload.get("repair_items") or [])
        signal = dict(payload.get("signal") or {})
        return f"Project network repair queued: signal={signal.get('signal_code') or ''}, repairs={len(items)}"
    if action == "queue_audit_repairs":
        summary = dict(payload.get("summary") or {})
        return (
            "Project network audit repairs queued: "
            f"selected={summary.get('selected_audit_signal_count', 0)}, "
            f"repairs={summary.get('queued_repair_count', 0)}"
        )
    if action == "read_repairs":
        summary = dict(payload.get("summary") or {})
        return f"Project network repairs: signals={summary.get('signal_count', 0)}, queued_repairs={summary.get('queued_repair_count', 0)}"
    return f"Project network artifact action: {action}"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _path_prefix(ref: str) -> str:
    value = str(ref or "")
    if "://" in value:
        value = value.split("://", 1)[1]
    value = value.split("#", 1)[0].strip("/")
    parts = [part for part in value.split("/") if part]
    return "/".join(parts[:-1]) if len(parts) > 1 else value


def _ref_root_segment(ref: str) -> str:
    value = str(ref or "")
    if "://" in value:
        value = value.split("://", 1)[1]
    value = value.split("#", 1)[0].replace("\\", "/").strip("/")
    return value.split("/", 1)[0] if value else ""


def _safe_segment(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._")
    return safe[:180] or "project_network_artifact"


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
    session = dict(payload.get("navigation_session") or {})
    paths = list(payload.get("path_candidates") or [])
    opened = list(payload.get("opened_refs") or [])
    decisions = list(payload.get("recent_decisions") or [])
    lines = [
        f"Project network navigation: {session.get('navigation_session_id')}",
        f"build_id={session.get('build_id')}, generation={session.get('generation')}, status={session.get('status')}, route_depth={session.get('route_depth')}, path_limit={session.get('path_limit')}",
        f"goal={session.get('goal') or '<none>'}",
        f"focus_nodes={len(session.get('focus_node_ids') or [])}, paths={len(paths)}, opened_refs={len(opened)}, decisions={len(decisions)}",
    ]
    for item in paths[:12]:
        lines.append(
            "- path "
            f"{item.get('score')} {item.get('path_kind')} -> "
            f"{item.get('path_label') or item.get('target_node_id')} "
            f"[{item.get('path_candidate_id')}]"
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


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.replace(",", "\n").splitlines() if item.strip()]
    return [str(item).strip() for item in list(value or []) if str(item).strip()]


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
