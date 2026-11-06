from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Type

from capability_system.tools.base_tool import AsyncCallbackManagerForToolRun, BaseTool, CallbackManagerForToolRun
from file_management.project_structure import (
    ProjectStructureIndexService,
    ProjectStructureMaintenanceService,
    ProjectStructureRepository,
    ProjectStructureSliceService,
    SemanticOverlayRecord,
    content_hash,
    file_ref,
    folder_ref,
    py_module_ref,
    stable_project_structure_id,
)
from file_management.project_structure.skeleton_refs import normalize_rel_path
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class ProjectStructureToolResult(dict):
    def __str__(self) -> str:
        return str(self.get("text") or "")


class ProjectStructureBuildSkeletonInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    build_id: str = Field(..., min_length=1, description="Stable project network build id")
    scope_roots: list[str] = Field(default_factory=list, description="Optional workspace directory roots to index")
    generation: int = Field(default=0, ge=0, description="Optional explicit skeleton generation; 0 means next generation")
    include_git_snapshot: bool = Field(default=True, description="Include read-only git snapshot facts")


class ProjectStructureReadNodeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(default="", description="Exact skeleton node id")
    build_id: str = Field(default="", description="Build id, required when resolving by stable_ref or path")
    stable_ref: str = Field(default="", description="Stable physical ref such as folder://backend or file://backend/app.py")
    path: str = Field(default="", description="Workspace path to resolve as folder/file/module node")
    generation: int = Field(default=0, ge=0, description="Skeleton generation; 0 means latest for build_id")
    include_semantic_overlay: bool = Field(default=True, description="Include attached semantic overlay records")


class ProjectStructureReadEdgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str = Field(..., min_length=1, description="Exact skeleton edge id")


class ProjectStructureExpandInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    build_id: str = Field(..., min_length=1, description="Project network build id")
    seed_node_ids: list[str] = Field(default_factory=list, description="Seed skeleton node ids")
    seed_stable_refs: list[str] = Field(default_factory=list, description="Optional seed stable refs")
    seed_paths: list[str] = Field(default_factory=list, description="Optional workspace paths to resolve as seed nodes")
    generation: int = Field(default=0, ge=0, description="Skeleton generation; 0 means latest")
    edge_kinds: list[str] = Field(default_factory=list, description="Optional edge kind filter")
    depth: int = Field(default=1, ge=0, le=6, description="Expansion depth")
    limit: int = Field(default=200, ge=1, le=1000, description="Maximum nodes returned")
    include_inbound: bool = Field(default=True, description="Include inbound edges while expanding")
    include_semantic_overlay: bool = Field(default=True, description="Include semantic overlays")


class ProjectStructureDirectoryRelationsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    build_id: str = Field(..., min_length=1, description="Project network build id")
    scope_root: str = Field(..., min_length=1, description="Workspace directory or file path")
    generation: int = Field(default=0, ge=0, description="Skeleton generation; 0 means latest")
    edge_kinds: list[str] = Field(default_factory=list, description="Optional relation kinds to keep")
    max_nodes: int = Field(default=300, ge=1, le=2000, description="Maximum in-scope nodes returned")
    max_edges: int = Field(default=500, ge=1, le=5000, description="Maximum relation edges returned")
    include_external: bool = Field(default=True, description="Include inbound/outbound boundary relations")
    include_semantic_overlay: bool = Field(default=True, description="Include semantic overlay summaries for in-scope nodes")


class ProjectStructureCollectGitChangesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    build_id: str = Field(..., min_length=1, description="Project network build id")
    change_mode: str = Field(default="working_tree", description="Change collection mode")
    skeleton_generation: int = Field(default=0, ge=0, description="Skeleton generation; 0 means latest")


class ProjectStructureCreateRepairWorkItemsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_set_id: str = Field(..., min_length=1, description="Git change set id from project_structure_collect_git_changes")
    skeleton_generation: int = Field(default=0, ge=0, description="Skeleton generation; 0 means latest")
    group_by_folder_threshold: int = Field(default=40, ge=1, le=500, description="Group repair items above this node count")


class ProjectStructureSubmitSemanticOverlayInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    build_id: str = Field(..., min_length=1, description="Project network build id")
    overlay_kind: str = Field(..., min_length=1, description="Semantic overlay kind, such as module_summary or system_ownership")
    stable_ref: str = Field(default="", description="Attached stable physical ref")
    skeleton_node_id: str = Field(default="", description="Attached skeleton node id")
    skeleton_edge_id: str = Field(default="", description="Attached skeleton edge id")
    anchor_ref: str = Field(default="", description="Optional code or evidence anchor")
    status: str = Field(default="candidate", description="candidate, accepted, rejected, stale, or needs_human_review")
    confidence: str = Field(default="derived", description="exact, derived, unresolved, low, medium, high")
    generation: int = Field(default=0, ge=0, description="Semantic overlay generation")
    payload: dict[str, Any] = Field(default_factory=dict, description="Structured semantic payload")
    evidence_refs: list[str] = Field(default_factory=list, description="Evidence refs that support this overlay")
    created_by_task_run_id: str = Field(default="", description="Task run id that produced the overlay")
    created_by_agent_id: str = Field(default="", description="Agent id that produced the overlay")
    overlay_id: str = Field(default="", description="Optional explicit overlay id for updates")


class _ProjectStructureTool(BaseTool):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._root_dir = Path(root_dir).resolve()

    def _repository(self) -> ProjectStructureRepository:
        return ProjectStructureRepository(self._root_dir)

    def _slice_service(self) -> ProjectStructureSliceService:
        return ProjectStructureSliceService(self._repository())

    def _index_service(self) -> ProjectStructureIndexService:
        return ProjectStructureIndexService.from_backend_dir(self._root_dir)

    def _maintenance_service(self) -> ProjectStructureMaintenanceService:
        return ProjectStructureMaintenanceService.from_backend_dir(self._root_dir, with_working_memory=False)


class ProjectStructureBuildSkeletonTool(_ProjectStructureTool):
    name: str = "project_structure_build_skeleton"
    description: str = (
        "Build a deterministic project structure skeleton graph from file tree, deep AST, and optional git snapshot facts. "
        "Use this before task graph semantic review so every semantic decision can attach to physical nodes and edges."
    )
    args_schema: Type[BaseModel] = ProjectStructureBuildSkeletonInput

    def _run(
        self,
        build_id: str,
        scope_roots: list[str] | None = None,
        generation: int = 0,
        include_git_snapshot: bool = True,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> ProjectStructureToolResult:
        _ = run_manager
        try:
            report = self._index_service().build_skeleton_generation(
                build_id=build_id,
                scope_roots=tuple(_clean_list(scope_roots)),
                generation=int(generation or 0) or None,
                include_git_snapshot=bool(include_git_snapshot),
            )
        except Exception as exc:
            return _tool_result(f"Project structure skeleton build failed: {exc}", ok=False, kind=self.name)
        payload = report.to_dict()
        text = (
            f"Project structure skeleton built: build_id={report.build_id}, generation={report.generation}\n"
            f"nodes={report.node_count}, edges={report.edge_count}, facts={report.fact_count}\n"
            f"scope_roots={', '.join(report.scope_roots) or '<workspace defaults>'}"
        )
        return _tool_result(text, ok=True, kind=self.name, payload=payload)

    async def _arun(
        self,
        build_id: str,
        scope_roots: list[str] | None = None,
        generation: int = 0,
        include_git_snapshot: bool = True,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> ProjectStructureToolResult:
        return await asyncio.to_thread(self._run, build_id, scope_roots, generation, include_git_snapshot, None)


class ProjectStructureReadNodeTool(_ProjectStructureTool):
    name: str = "project_structure_read_node"
    description: str = (
        "Read one project structure skeleton node card with ancestors, children, inbound/outbound relations, "
        "and attached semantic overlays. Resolve by node_id, stable_ref, or workspace path."
    )
    args_schema: Type[BaseModel] = ProjectStructureReadNodeInput

    def _run(
        self,
        node_id: str = "",
        build_id: str = "",
        stable_ref: str = "",
        path: str = "",
        generation: int = 0,
        include_semantic_overlay: bool = True,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> ProjectStructureToolResult:
        _ = run_manager
        repo = self._repository()
        node = _resolve_node(repo, node_id=node_id, build_id=build_id, stable_ref=stable_ref, path=path, generation=generation)
        if node is None:
            return _tool_result("Project structure node not found. Provide node_id or build_id plus stable_ref/path.", ok=False, kind=self.name)
        card = ProjectStructureSliceService(repo).read_node(node.node_id, include_semantic_overlay=include_semantic_overlay)
        if card is None:
            return _tool_result(f"Project structure node disappeared: {node.node_id}", ok=False, kind=self.name)
        payload = card.to_dict()
        text = _format_node_card(payload)
        return _tool_result(text, ok=True, kind=self.name, payload=payload)

    async def _arun(
        self,
        node_id: str = "",
        build_id: str = "",
        stable_ref: str = "",
        path: str = "",
        generation: int = 0,
        include_semantic_overlay: bool = True,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> ProjectStructureToolResult:
        return await asyncio.to_thread(self._run, node_id, build_id, stable_ref, path, generation, include_semantic_overlay, None)


class ProjectStructureReadEdgeTool(_ProjectStructureTool):
    name: str = "project_structure_read_edge"
    description: str = "Read one project structure relation edge card with source/target node cards and evidence facts."
    args_schema: Type[BaseModel] = ProjectStructureReadEdgeInput

    def _run(self, edge_id: str, run_manager: CallbackManagerForToolRun | None = None) -> ProjectStructureToolResult:
        _ = run_manager
        card = self._slice_service().read_edge(edge_id)
        if card is None:
            return _tool_result(f"Project structure edge not found: {edge_id}", ok=False, kind=self.name)
        payload = card.to_dict()
        edge = payload.get("edge") or {}
        src = payload.get("source_node") or {}
        dst = payload.get("target_node") or {}
        text = "\n".join(
            [
                f"Project structure edge: {edge.get('edge_kind')} {edge.get('edge_id')}",
                f"source: {_node_label(src)}",
                f"target: {_node_label(dst) if dst else edge.get('dst_candidate_ref') or '<unresolved>'}",
                f"confidence={edge.get('confidence') or ''}, resolution={edge.get('resolution_status') or ''}, evidence_facts={len(payload.get('evidence_facts') or [])}",
            ]
        )
        return _tool_result(text, ok=True, kind=self.name, payload=payload)

    async def _arun(self, edge_id: str, run_manager: AsyncCallbackManagerForToolRun | None = None) -> ProjectStructureToolResult:
        return await asyncio.to_thread(self._run, edge_id, None)


class ProjectStructureExpandTool(_ProjectStructureTool):
    name: str = "project_structure_expand"
    description: str = (
        "Expand from project structure seed nodes through hierarchy, import, and call relations. "
        "Use this for multi-hop network navigation after a seed is known."
    )
    args_schema: Type[BaseModel] = ProjectStructureExpandInput

    def _run(
        self,
        build_id: str,
        seed_node_ids: list[str] | None = None,
        seed_stable_refs: list[str] | None = None,
        seed_paths: list[str] | None = None,
        generation: int = 0,
        edge_kinds: list[str] | None = None,
        depth: int = 1,
        limit: int = 200,
        include_inbound: bool = True,
        include_semantic_overlay: bool = True,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> ProjectStructureToolResult:
        _ = run_manager
        repo = self._repository()
        resolved_generation = int(generation or 0) or _latest_generation(repo, build_id)
        seeds = _resolve_seed_node_ids(
            repo,
            build_id=build_id,
            generation=resolved_generation,
            seed_node_ids=seed_node_ids,
            seed_stable_refs=seed_stable_refs,
            seed_paths=seed_paths,
        )
        if not seeds:
            return _tool_result("Project structure expand failed: no seed nodes resolved.", ok=False, kind=self.name)
        projection = ProjectStructureSliceService(repo).expand(
            build_id=build_id,
            seed_node_ids=seeds,
            generation=resolved_generation,
            edge_kinds=tuple(_clean_list(edge_kinds)),
            depth=depth,
            limit=limit,
            include_inbound=include_inbound,
            include_semantic_overlay=include_semantic_overlay,
        )
        payload = projection.to_dict()
        text = _format_slice_projection(payload)
        return _tool_result(text, ok=True, kind=self.name, payload=payload)

    async def _arun(
        self,
        build_id: str,
        seed_node_ids: list[str] | None = None,
        seed_stable_refs: list[str] | None = None,
        seed_paths: list[str] | None = None,
        generation: int = 0,
        edge_kinds: list[str] | None = None,
        depth: int = 1,
        limit: int = 200,
        include_inbound: bool = True,
        include_semantic_overlay: bool = True,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> ProjectStructureToolResult:
        return await asyncio.to_thread(
            self._run,
            build_id,
            seed_node_ids,
            seed_stable_refs,
            seed_paths,
            generation,
            edge_kinds,
            depth,
            limit,
            include_inbound,
            include_semantic_overlay,
            None,
        )


class ProjectStructureDirectoryRelationsTool(_ProjectStructureTool):
    name: str = "project_structure_directory_relations"
    description: str = (
        "Read project structure relations for a directory or file scope. Returns in-scope nodes, internal relations, "
        "inbound boundary relations, outbound boundary relations, and next node ids for traversal."
    )
    args_schema: Type[BaseModel] = ProjectStructureDirectoryRelationsInput

    def _run(
        self,
        build_id: str,
        scope_root: str,
        generation: int = 0,
        edge_kinds: list[str] | None = None,
        max_nodes: int = 300,
        max_edges: int = 500,
        include_external: bool = True,
        include_semantic_overlay: bool = True,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> ProjectStructureToolResult:
        _ = run_manager
        repo = self._repository()
        resolved_generation = int(generation or 0) or _latest_generation(repo, build_id)
        projection = _directory_relations_projection(
            repo,
            build_id=build_id,
            scope_root=scope_root,
            generation=resolved_generation,
            edge_kinds=tuple(_clean_list(edge_kinds)),
            max_nodes=max_nodes,
            max_edges=max_edges,
            include_external=include_external,
            include_semantic_overlay=include_semantic_overlay,
        )
        if not projection.get("scope_found"):
            return _tool_result(
                f"Project structure directory relations found no skeleton scope for: {scope_root}",
                ok=False,
                kind=self.name,
                payload=projection,
            )
        text = _format_directory_projection(projection)
        return _tool_result(text, ok=True, kind=self.name, payload=projection)

    async def _arun(
        self,
        build_id: str,
        scope_root: str,
        generation: int = 0,
        edge_kinds: list[str] | None = None,
        max_nodes: int = 300,
        max_edges: int = 500,
        include_external: bool = True,
        include_semantic_overlay: bool = True,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> ProjectStructureToolResult:
        return await asyncio.to_thread(
            self._run,
            build_id,
            scope_root,
            generation,
            edge_kinds,
            max_nodes,
            max_edges,
            include_external,
            include_semantic_overlay,
            None,
        )


class ProjectStructureCollectGitChangesTool(_ProjectStructureTool):
    name: str = "project_structure_collect_git_changes"
    description: str = (
        "Collect the current git working-tree change set and map changed files to project structure skeleton nodes and edges. "
        "Use this before creating semantic repair work items."
    )
    args_schema: Type[BaseModel] = ProjectStructureCollectGitChangesInput

    def _run(
        self,
        build_id: str,
        change_mode: str = "working_tree",
        skeleton_generation: int = 0,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> ProjectStructureToolResult:
        _ = run_manager
        try:
            record = self._maintenance_service().collect_git_change_set(
                build_id=build_id,
                change_mode=change_mode,
                skeleton_generation=int(skeleton_generation or 0) or None,
            )
        except Exception as exc:
            return _tool_result(f"Project structure git change collection failed: {exc}", ok=False, kind=self.name)
        payload = record.to_dict()
        text = (
            f"Project structure git change set: {record.change_set_id}\n"
            f"changed_files={len(record.changed_files)}, touched_nodes={len(record.touched_skeleton_node_ids)}, "
            f"touched_edges={len(record.touched_skeleton_edge_ids)}, stale_semantic_refs={len(record.semantic_refs_to_mark_stale)}"
        )
        return _tool_result(text, ok=True, kind=self.name, payload=payload)

    async def _arun(
        self,
        build_id: str,
        change_mode: str = "working_tree",
        skeleton_generation: int = 0,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> ProjectStructureToolResult:
        return await asyncio.to_thread(self._run, build_id, change_mode, skeleton_generation, None)


class ProjectStructureCreateRepairWorkItemsTool(_ProjectStructureTool):
    name: str = "project_structure_create_repair_work_items"
    description: str = "Create semantic repair work items from a collected project structure git change set."
    args_schema: Type[BaseModel] = ProjectStructureCreateRepairWorkItemsInput

    def _run(
        self,
        change_set_id: str,
        skeleton_generation: int = 0,
        group_by_folder_threshold: int = 40,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> ProjectStructureToolResult:
        _ = run_manager
        try:
            records = self._maintenance_service().create_repair_work_items(
                change_set_id=change_set_id,
                skeleton_generation=int(skeleton_generation or 0) or None,
                group_by_folder_threshold=group_by_folder_threshold,
            )
        except Exception as exc:
            return _tool_result(f"Project structure repair work item creation failed: {exc}", ok=False, kind=self.name)
        payload = {"work_items": [record.to_dict() for record in records], "work_item_count": len(records)}
        text = f"Project structure repair work items created: {len(records)} for change_set_id={change_set_id}"
        return _tool_result(text, ok=True, kind=self.name, payload=payload)

    async def _arun(
        self,
        change_set_id: str,
        skeleton_generation: int = 0,
        group_by_folder_threshold: int = 40,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> ProjectStructureToolResult:
        return await asyncio.to_thread(self._run, change_set_id, skeleton_generation, group_by_folder_threshold, None)


class ProjectStructureSubmitSemanticOverlayTool(_ProjectStructureTool):
    name: str = "project_structure_submit_semantic_overlay"
    description: str = (
        "Submit an agent-reviewed semantic overlay candidate attached to an existing project structure node, edge, stable ref, or anchor. "
        "Accepted overlays must include evidence_refs."
    )
    args_schema: Type[BaseModel] = ProjectStructureSubmitSemanticOverlayInput

    def _run(
        self,
        build_id: str,
        overlay_kind: str,
        stable_ref: str = "",
        skeleton_node_id: str = "",
        skeleton_edge_id: str = "",
        anchor_ref: str = "",
        status: str = "candidate",
        confidence: str = "derived",
        generation: int = 0,
        payload: dict[str, Any] | None = None,
        evidence_refs: list[str] | None = None,
        created_by_task_run_id: str = "",
        created_by_agent_id: str = "",
        overlay_id: str = "",
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> ProjectStructureToolResult:
        _ = run_manager
        repo = self._repository()
        evidence = tuple(_clean_list(evidence_refs))
        normalized_status = str(status or "candidate").strip() or "candidate"
        if normalized_status == "accepted" and not evidence:
            return _tool_result("Project structure semantic overlay failed: accepted overlays require evidence_refs.", ok=False, kind=self.name)
        node = repo.get_skeleton_node(skeleton_node_id) if skeleton_node_id else None
        edge = repo.get_skeleton_edge(skeleton_edge_id) if skeleton_edge_id else None
        resolved_stable_ref = str(stable_ref or "").strip()
        if node is not None:
            resolved_stable_ref = resolved_stable_ref or node.stable_ref
        if edge is not None and not resolved_stable_ref:
            source_node = repo.get_skeleton_node(edge.src_node_id) if edge.src_node_id else None
            resolved_stable_ref = source_node.stable_ref if source_node is not None else ""
        if not any((resolved_stable_ref, skeleton_node_id, skeleton_edge_id, anchor_ref)):
            return _tool_result(
                "Project structure semantic overlay failed: attach to stable_ref, skeleton_node_id, skeleton_edge_id, or anchor_ref.",
                ok=False,
                kind=self.name,
            )
        if skeleton_node_id and node is None:
            return _tool_result(f"Project structure semantic overlay failed: unknown skeleton_node_id {skeleton_node_id}", ok=False, kind=self.name)
        if skeleton_edge_id and edge is None:
            return _tool_result(f"Project structure semantic overlay failed: unknown skeleton_edge_id {skeleton_edge_id}", ok=False, kind=self.name)
        body = dict(payload or {})
        resolved_overlay_id = str(overlay_id or "").strip() or stable_project_structure_id(
            "pnsemovr",
            build_id,
            overlay_kind,
            resolved_stable_ref,
            skeleton_node_id,
            skeleton_edge_id,
            anchor_ref,
            int(generation or 0),
            content_hash({"payload": body, "evidence_refs": evidence, "status": normalized_status}),
        )
        record = repo.upsert_semantic_overlay(
            SemanticOverlayRecord(
                overlay_id=resolved_overlay_id,
                build_id=build_id,
                overlay_kind=overlay_kind,
                stable_ref=resolved_stable_ref,
                skeleton_node_id=str(skeleton_node_id or "").strip(),
                skeleton_edge_id=str(skeleton_edge_id or "").strip(),
                anchor_ref=str(anchor_ref or "").strip(),
                status=normalized_status,
                confidence=str(confidence or "derived").strip() or "derived",
                generation=int(generation or 0),
                payload=body,
                evidence_refs=evidence,
                created_by_task_run_id=str(created_by_task_run_id or "").strip(),
                created_by_agent_id=str(created_by_agent_id or "").strip(),
            )
        )
        payload_dict = record.to_dict()
        text = (
            f"Project structure semantic overlay submitted: {record.overlay_id}\n"
            f"kind={record.overlay_kind}, status={record.status}, stable_ref={record.stable_ref or '<none>'}, "
            f"evidence_refs={len(record.evidence_refs)}"
        )
        return _tool_result(text, ok=True, kind=self.name, payload=payload_dict)

    async def _arun(
        self,
        build_id: str,
        overlay_kind: str,
        stable_ref: str = "",
        skeleton_node_id: str = "",
        skeleton_edge_id: str = "",
        anchor_ref: str = "",
        status: str = "candidate",
        confidence: str = "derived",
        generation: int = 0,
        payload: dict[str, Any] | None = None,
        evidence_refs: list[str] | None = None,
        created_by_task_run_id: str = "",
        created_by_agent_id: str = "",
        overlay_id: str = "",
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> ProjectStructureToolResult:
        return await asyncio.to_thread(
            self._run,
            build_id,
            overlay_kind,
            stable_ref,
            skeleton_node_id,
            skeleton_edge_id,
            anchor_ref,
            status,
            confidence,
            generation,
            payload,
            evidence_refs,
            created_by_task_run_id,
            created_by_agent_id,
            overlay_id,
            None,
        )


def _resolve_node(
    repo: ProjectStructureRepository,
    *,
    node_id: str = "",
    build_id: str = "",
    stable_ref: str = "",
    path: str = "",
    generation: int = 0,
):
    if str(node_id or "").strip():
        return repo.get_skeleton_node(str(node_id).strip())
    resolved_build_id = str(build_id or "").strip()
    if not resolved_build_id:
        return None
    resolved_generation = int(generation or 0) or _latest_generation(repo, resolved_build_id)
    refs = []
    if str(stable_ref or "").strip():
        refs.append(str(stable_ref).strip())
    rel_path = normalize_rel_path(path)
    if rel_path or str(path or "").strip() in {".", "./"}:
        refs.extend([folder_ref(rel_path), file_ref(rel_path), py_module_ref(rel_path)])
    for ref in refs:
        node = repo.find_skeleton_node(build_id=resolved_build_id, stable_ref=ref, generation=resolved_generation)
        if node is not None:
            return node
    if rel_path:
        matches = repo.list_skeleton_nodes(build_id=resolved_build_id, generation=resolved_generation, path=rel_path, limit=1)
        if matches:
            return matches[0]
    return None


def _resolve_seed_node_ids(
    repo: ProjectStructureRepository,
    *,
    build_id: str,
    generation: int,
    seed_node_ids: list[str] | None,
    seed_stable_refs: list[str] | None,
    seed_paths: list[str] | None,
) -> tuple[str, ...]:
    ids = _clean_list(seed_node_ids)
    for stable_ref in _clean_list(seed_stable_refs):
        node = repo.find_skeleton_node(build_id=build_id, stable_ref=stable_ref, generation=generation)
        if node is not None:
            ids.append(node.node_id)
    for path in _clean_list(seed_paths):
        node = _resolve_node(repo, build_id=build_id, path=path, generation=generation)
        if node is not None:
            ids.append(node.node_id)
    return tuple(dict.fromkeys(ids))


def _directory_relations_projection(
    repo: ProjectStructureRepository,
    *,
    build_id: str,
    scope_root: str,
    generation: int,
    edge_kinds: tuple[str, ...],
    max_nodes: int,
    max_edges: int,
    include_external: bool,
    include_semantic_overlay: bool,
) -> dict[str, Any]:
    rel = normalize_rel_path(scope_root)
    folder_node = repo.find_skeleton_node(build_id=build_id, stable_ref=folder_ref(rel), generation=generation)
    file_node = repo.find_skeleton_node(build_id=build_id, stable_ref=file_ref(rel), generation=generation)
    anchor_node = folder_node or file_node
    scan_limit = min(10000, max(int(max_nodes or 300) * 4, int(max_nodes or 300), 1000))
    all_nodes = repo.list_skeleton_nodes(build_id=build_id, generation=generation, limit=scan_limit)
    if anchor_node is not None and anchor_node.node_kind == "folder":
        in_scope = [
            node
            for node in all_nodes
            if node.node_id == anchor_node.node_id or anchor_node.node_id in node.ancestor_node_ids
        ]
        scope_basis = "skeleton_folder_ancestor"
    elif anchor_node is not None:
        in_scope = [node for node in all_nodes if node.node_id == anchor_node.node_id]
        scope_basis = "skeleton_file_node"
    else:
        prefix = "" if rel in {"", "."} else f"{rel.rstrip('/')}/"
        in_scope = [
            node
            for node in all_nodes
            if rel in {"", "."}
            or node.path == rel
            or node.path.startswith(prefix)
            or node.stable_ref in {folder_ref(rel), file_ref(rel), py_module_ref(rel)}
        ]
        scope_basis = "path_prefix_fallback"
    node_limit = max(1, min(int(max_nodes or 300), 2000))
    limited_nodes = tuple(sorted(in_scope, key=lambda item: (item.hierarchy_path, item.node_kind, item.stable_ref))[:node_limit])
    node_ids = {node.node_id for node in limited_nodes}
    allowed_edge_kinds = {item for item in edge_kinds if item}
    edges = repo.list_skeleton_edges(build_id=build_id, generation=generation, limit=min(20000, max(int(max_edges or 500) * 6, 2000)))
    internal = []
    inbound = []
    outbound = []
    unresolved = []
    for edge in edges:
        if allowed_edge_kinds and edge.edge_kind not in allowed_edge_kinds:
            continue
        src_in = edge.src_node_id in node_ids
        dst_in = edge.dst_node_id in node_ids
        if src_in and dst_in:
            internal.append(edge)
        elif include_external and src_in and not dst_in:
            outbound.append(edge)
            if not edge.dst_node_id:
                unresolved.append(edge)
        elif include_external and dst_in and not src_in:
            inbound.append(edge)
    edge_limit = max(1, min(int(max_edges or 500), 5000))
    overlays = []
    if include_semantic_overlay:
        for node in limited_nodes[:100]:
            overlays.extend(ProjectStructureSliceService(repo).semantic_overlays_for_node(node, limit=10))
    next_node_ids = tuple(
        dict.fromkeys(
            edge.dst_node_id
            for edge in (*outbound, *internal)
            if edge.dst_node_id and edge.dst_node_id not in node_ids
        )
    )
    payload = {
        "kind": "project_structure_directory_relations",
        "authority": "file_management.project_structure.directory_relations_projection",
        "build_id": build_id,
        "generation": generation,
        "scope_root": rel or ".",
        "scope_found": bool(limited_nodes),
        "scope_basis": scope_basis,
        "anchor_node": anchor_node.to_dict() if anchor_node is not None else {},
        "node_count": len(in_scope),
        "nodes": [node.to_dict() for node in limited_nodes],
        "internal_edges": [edge.to_dict() for edge in internal[:edge_limit]],
        "inbound_edges": [edge.to_dict() for edge in inbound[:edge_limit]],
        "outbound_edges": [edge.to_dict() for edge in outbound[:edge_limit]],
        "unresolved_outbound_edges": [edge.to_dict() for edge in unresolved[:edge_limit]],
        "semantic_overlays": overlays,
        "next_node_ids": list(next_node_ids[:200]),
        "truncated": {
            "nodes": len(in_scope) > len(limited_nodes),
            "internal_edges": len(internal) > edge_limit,
            "inbound_edges": len(inbound) > edge_limit,
            "outbound_edges": len(outbound) > edge_limit,
            "unresolved_outbound_edges": len(unresolved) > edge_limit,
        },
    }
    return payload


def _latest_generation(repo: ProjectStructureRepository, build_id: str) -> int:
    generations = repo.list_skeleton_generations(build_id=build_id, limit=1)
    return int(generations[0].generation or 0) if generations else 0


def _clean_list(values: list[str] | tuple[str, ...] | None) -> list[str]:
    return [str(item or "").strip().replace("\\", "/") for item in list(values or []) if str(item or "").strip()]


def _format_node_card(payload: dict[str, Any]) -> str:
    node = dict(payload.get("node") or {})
    lines = [
        f"Project structure node: {_node_label(node)}",
        f"stable_ref={node.get('stable_ref') or ''}",
        f"path={node.get('path') or ''}, layer={node.get('layer_kind') or ''}, confidence={node.get('confidence') or ''}",
        f"children={len(payload.get('children') or [])}, inbound={len(payload.get('inbound_edges') or [])}, outbound={len(payload.get('outbound_edges') or [])}, overlays={len(payload.get('semantic_overlays') or [])}",
    ]
    for child in list(payload.get("children") or [])[:12]:
        lines.append(f"- child {_node_label(child)}")
    for edge in list(payload.get("outbound_edges") or [])[:12]:
        lines.append(f"- out {edge.get('edge_kind')} -> {edge.get('dst_node_id') or edge.get('dst_candidate_ref') or '<unresolved>'}")
    return "\n".join(lines)


def _format_slice_projection(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Project structure expansion: build_id={payload.get('build_id')}, generation={payload.get('generation')}",
            f"seed_nodes={len(payload.get('seed_node_ids') or [])}, nodes={len(payload.get('nodes') or [])}, edges={len(payload.get('edges') or [])}, overlays={len(payload.get('semantic_overlays') or [])}",
            *[f"- {_node_label(node)}" for node in list(payload.get("nodes") or [])[:20]],
        ]
    )


def _format_directory_projection(payload: dict[str, Any]) -> str:
    truncated = dict(payload.get("truncated") or {})
    lines = [
        f"Project structure directory relations: {payload.get('scope_root')} (basis={payload.get('scope_basis')})",
        f"nodes={payload.get('node_count')}, internal_edges={len(payload.get('internal_edges') or [])}, inbound_edges={len(payload.get('inbound_edges') or [])}, outbound_edges={len(payload.get('outbound_edges') or [])}, unresolved_outbound={len(payload.get('unresolved_outbound_edges') or [])}",
        f"next_node_ids={len(payload.get('next_node_ids') or [])}, overlays={len(payload.get('semantic_overlays') or [])}",
    ]
    if any(truncated.values()):
        lines.append(f"truncated={truncated}")
    lines.append("top nodes:")
    for node in list(payload.get("nodes") or [])[:20]:
        lines.append(f"- {_node_label(node)}")
    lines.append("sample relations:")
    for edge in [*list(payload.get("internal_edges") or [])[:8], *list(payload.get("outbound_edges") or [])[:8], *list(payload.get("inbound_edges") or [])[:8]]:
        lines.append(f"- {edge.get('edge_kind')} {edge.get('src_node_id')} -> {edge.get('dst_node_id') or edge.get('dst_candidate_ref') or '<unresolved>'}")
    return "\n".join(lines)


def _node_label(node: dict[str, Any]) -> str:
    if not node:
        return "<none>"
    return f"{node.get('node_kind') or 'node'} {node.get('display_name') or node.get('stable_ref') or node.get('node_id')} [{node.get('node_id') or ''}]"


def _tool_result(text: str, *, ok: bool, kind: str, payload: dict[str, Any] | None = None) -> ProjectStructureToolResult:
    body = dict(payload or {"kind": kind})
    body.setdefault("kind", kind)
    body.setdefault("ok", ok)
    return ProjectStructureToolResult(
        {
            "text": str(text or ""),
            "structured_payload": {
                "tool_result": body,
            },
        }
    )
