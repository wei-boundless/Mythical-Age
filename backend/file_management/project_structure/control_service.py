from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from .control_models import (
    ProjectNetworkNavigationProjection,
    ProjectNetworkNavigationSessionRecord,
    ProjectNetworkOpenedRefRecord,
    ProjectNetworkPathCandidateRecord,
    ProjectNetworkPathDecisionRecord,
)
from .repository import ProjectStructureRepository, content_hash, stable_project_structure_id, utc_now_iso
from .skeleton_models import SkeletonEdgeRecord, SkeletonNodeRecord
from .skeleton_normalizer import CODE_LINK_EDGE_KINDS, HIERARCHY_EDGE_KINDS
from .skeleton_refs import REPO_STABLE_REF, file_ref, folder_ref, normalize_rel_path, py_module_ref
from .skeleton_slice_service import ProjectStructureSliceService


class ProjectNetworkControlService:
    authority = "file_management.project_structure.project_network_control_service"

    def __init__(self, repository: ProjectStructureRepository) -> None:
        self.repository = repository

    @classmethod
    def from_backend_dir(cls, base_dir: str | Path) -> "ProjectNetworkControlService":
        return cls(ProjectStructureRepository(base_dir))

    def start_navigation(
        self,
        *,
        build_id: str,
        goal: str,
        anchor_node_ids: tuple[str, ...] | list[str] = (),
        anchor_stable_refs: tuple[str, ...] | list[str] = (),
        anchor_paths: tuple[str, ...] | list[str] = (),
        generation: int | None = None,
        route_depth: int = 3,
        path_limit: int = 80,
        created_by_task_run_id: str = "",
        created_by_agent_id: str = "",
        navigation_session_id: str = "",
        include_local_slice: bool = True,
    ) -> ProjectNetworkNavigationProjection:
        resolved_build_id = str(build_id or "").strip()
        if not resolved_build_id:
            raise ValueError("ProjectNetworkControlService.start_navigation requires build_id")
        resolved_generation = int(generation or 0) or _latest_generation(self.repository, resolved_build_id)
        anchors = self._resolve_anchor_nodes(
            build_id=resolved_build_id,
            generation=resolved_generation,
            anchor_node_ids=tuple(anchor_node_ids or ()),
            anchor_stable_refs=tuple(anchor_stable_refs or ()),
            anchor_paths=tuple(anchor_paths or ()),
        )
        if not anchors:
            raise ValueError("ProjectNetworkControlService.start_navigation could not resolve an anchor node")
        now = utc_now_iso()
        session_id = str(navigation_session_id or "").strip() or stable_project_structure_id(
            "pnnavsess",
            resolved_build_id,
            resolved_generation,
            content_hash(
                {
                    "goal": goal,
                    "anchors": [node.node_id for node in anchors],
                    "created_at": now,
                    "agent": created_by_agent_id,
                    "task_run": created_by_task_run_id,
                }
            ),
        )
        session = self.repository.upsert_navigation_session(
            ProjectNetworkNavigationSessionRecord(
                navigation_session_id=session_id,
                build_id=resolved_build_id,
                generation=resolved_generation,
                goal=str(goal or "").strip(),
                anchor_node_ids=tuple(node.node_id for node in anchors),
                anchor_stable_refs=tuple(node.stable_ref for node in anchors if node.stable_ref),
                focus_node_ids=tuple(node.node_id for node in anchors),
                route_depth=_bounded_depth(route_depth),
                path_limit=_bounded_path_limit(path_limit),
                status="active",
                created_by_task_run_id=str(created_by_task_run_id or "").strip(),
                created_by_agent_id=str(created_by_agent_id or "").strip(),
                metadata={
                    "control_lane": "agent_neural_navigation_control",
                    "path_model": "precomputed_network_paths_not_stepwise_cursor",
                    "semantic_overlay_write_policy": "not_allowed_from_control_service",
                    "physical_skeleton_write_policy": "not_allowed_from_control_service",
                },
            )
        )
        self.repository.upsert_opened_refs(
            tuple(
                ProjectNetworkOpenedRefRecord(
                    opened_ref_id=stable_project_structure_id("pnopened", session.navigation_session_id, "node", node.node_id),
                    navigation_session_id=session.navigation_session_id,
                    build_id=session.build_id,
                    generation=session.generation,
                    ref_kind="node",
                    ref_id=node.node_id,
                    reason="navigation_anchor",
                    payload={"stable_ref": node.stable_ref, "node_kind": node.node_kind},
                )
                for node in anchors
            )
        )
        self._materialize_path_candidates(session, anchors, reason="initial_paths_from_anchor")
        self.repository.upsert_path_decision(
            ProjectNetworkPathDecisionRecord(
                decision_id=_decision_id(session.navigation_session_id, "start_navigation"),
                navigation_session_id=session.navigation_session_id,
                build_id=session.build_id,
                generation=session.generation,
                decision_kind="start_navigation",
                selected_node_id=",".join(node.node_id for node in anchors),
                reason=str(goal or "start project network navigation").strip(),
                created_by_task_run_id=session.created_by_task_run_id,
                created_by_agent_id=session.created_by_agent_id,
                payload={"anchor_stable_refs": [node.stable_ref for node in anchors if node.stable_ref]},
            )
        )
        return self.build_projection(session.navigation_session_id, include_local_slice=include_local_slice)

    def read_paths(
        self,
        *,
        navigation_session_id: str,
        status: str = "available",
        limit: int = 50,
        include_local_slice: bool = True,
    ) -> ProjectNetworkNavigationProjection:
        return self.build_projection(
            navigation_session_id,
            path_status=status or "available",
            path_limit=limit,
            include_local_slice=include_local_slice,
        )

    def select_path(
        self,
        *,
        navigation_session_id: str,
        selected_path_candidate_id: str = "",
        node_id: str = "",
        edge_id: str = "",
        reason: str = "",
        evidence_refs: tuple[str, ...] | list[str] = (),
        refresh_paths: bool = True,
        created_by_task_run_id: str = "",
        created_by_agent_id: str = "",
        include_local_slice: bool = True,
    ) -> ProjectNetworkNavigationProjection:
        session = self._require_session(navigation_session_id)
        candidate = self._path_candidate(session.navigation_session_id, selected_path_candidate_id)
        selected_node_id = str(node_id or "").strip() or (candidate.target_node_id if candidate is not None else "")
        selected_edge_id = str(edge_id or "").strip()
        if candidate is not None and not selected_edge_id and candidate.edge_ids:
            selected_edge_id = candidate.edge_ids[-1]
        if not selected_node_id and selected_edge_id:
            edge = self.repository.get_skeleton_edge(selected_edge_id)
            selected_node_id = edge.dst_node_id if edge is not None else ""
        node = self.repository.get_skeleton_node(selected_node_id) if selected_node_id else None
        if node is None:
            raise ValueError("ProjectNetworkControlService.select_path requires a resolvable target node")
        if candidate is not None:
            self.repository.upsert_path_candidates((replace(candidate, status="selected"),))
            opened = [
                ProjectNetworkOpenedRefRecord(
                    opened_ref_id=stable_project_structure_id("pnopened", session.navigation_session_id, "path", candidate.path_candidate_id),
                    navigation_session_id=session.navigation_session_id,
                    build_id=session.build_id,
                    generation=session.generation,
                    ref_kind="path_candidate",
                    ref_id=candidate.path_candidate_id,
                    reason=str(reason or "agent_selected_path").strip(),
                    payload={"node_ids": list(candidate.node_ids), "edge_ids": list(candidate.edge_ids)},
                )
            ]
            opened.extend(
                ProjectNetworkOpenedRefRecord(
                    opened_ref_id=stable_project_structure_id("pnopened", session.navigation_session_id, "node", item),
                    navigation_session_id=session.navigation_session_id,
                    build_id=session.build_id,
                    generation=session.generation,
                    ref_kind="node",
                    ref_id=item,
                    reason="selected_path_node",
                )
                for item in candidate.node_ids
            )
            opened.extend(
                ProjectNetworkOpenedRefRecord(
                    opened_ref_id=stable_project_structure_id("pnopened", session.navigation_session_id, "edge", item),
                    navigation_session_id=session.navigation_session_id,
                    build_id=session.build_id,
                    generation=session.generation,
                    ref_kind="edge",
                    ref_id=item,
                    reason="selected_path_edge",
                )
                for item in candidate.edge_ids
            )
            self.repository.upsert_opened_refs(tuple(opened))
        else:
            self.repository.upsert_opened_refs(
                (
                    ProjectNetworkOpenedRefRecord(
                        opened_ref_id=stable_project_structure_id("pnopened", session.navigation_session_id, "node", node.node_id),
                        navigation_session_id=session.navigation_session_id,
                        build_id=session.build_id,
                        generation=session.generation,
                        ref_kind="node",
                        ref_id=node.node_id,
                        reason=str(reason or "agent_selected_node").strip(),
                        payload={"stable_ref": node.stable_ref, "node_kind": node.node_kind},
                    ),
                )
            )
        updated_session = self.repository.upsert_navigation_session(replace(session, focus_node_ids=(node.node_id,)))
        self.repository.upsert_path_decision(
            ProjectNetworkPathDecisionRecord(
                decision_id=_decision_id(session.navigation_session_id, "select_path"),
                navigation_session_id=session.navigation_session_id,
                build_id=session.build_id,
                generation=session.generation,
                decision_kind="select_path",
                selected_path_candidate_id=candidate.path_candidate_id if candidate is not None else "",
                selected_node_id=node.node_id,
                selected_edge_id=selected_edge_id,
                reason=str(reason or "agent selected project network path").strip(),
                evidence_refs=tuple(_clean_list(evidence_refs)),
                created_by_task_run_id=str(created_by_task_run_id or session.created_by_task_run_id or "").strip(),
                created_by_agent_id=str(created_by_agent_id or session.created_by_agent_id or "").strip(),
            )
        )
        if refresh_paths:
            self._materialize_path_candidates(updated_session, (node,), reason="paths_from_selected_focus")
        return self.build_projection(updated_session.navigation_session_id, include_local_slice=include_local_slice)

    def record_decision(
        self,
        *,
        navigation_session_id: str,
        decision_kind: str,
        selected_path_candidate_id: str = "",
        selected_node_id: str = "",
        selected_edge_id: str = "",
        reason: str = "",
        evidence_refs: tuple[str, ...] | list[str] = (),
        status: str = "recorded",
        payload: dict[str, Any] | None = None,
        created_by_task_run_id: str = "",
        created_by_agent_id: str = "",
        include_local_slice: bool = True,
    ) -> ProjectNetworkNavigationProjection:
        session = self._require_session(navigation_session_id)
        kind = str(decision_kind or "").strip() or "record_note"
        candidate = self._path_candidate(session.navigation_session_id, selected_path_candidate_id)
        if candidate is not None and kind in {"dismiss_path", "block_path", "defer_path"}:
            item_status = {"block_path": "blocked", "defer_path": "deferred"}.get(kind, "dismissed")
            self.repository.upsert_path_candidates((replace(candidate, status=item_status),))
        if kind in {"complete", "stop", "blocked"}:
            session = self.repository.upsert_navigation_session(replace(session, status=kind))
        self.repository.upsert_path_decision(
            ProjectNetworkPathDecisionRecord(
                decision_id=_decision_id(session.navigation_session_id, kind),
                navigation_session_id=session.navigation_session_id,
                build_id=session.build_id,
                generation=session.generation,
                decision_kind=kind,
                selected_path_candidate_id=str(selected_path_candidate_id or "").strip(),
                selected_node_id=str(selected_node_id or "").strip(),
                selected_edge_id=str(selected_edge_id or "").strip(),
                reason=str(reason or "").strip(),
                status=str(status or "recorded").strip() or "recorded",
                evidence_refs=tuple(_clean_list(evidence_refs)),
                created_by_task_run_id=str(created_by_task_run_id or session.created_by_task_run_id or "").strip(),
                created_by_agent_id=str(created_by_agent_id or session.created_by_agent_id or "").strip(),
                payload=dict(payload or {}),
            )
        )
        return self.build_projection(session.navigation_session_id, include_local_slice=include_local_slice)

    def build_projection(
        self,
        navigation_session_id: str,
        *,
        path_status: str = "available",
        path_limit: int = 50,
        include_local_slice: bool = True,
    ) -> ProjectNetworkNavigationProjection:
        session = self._require_session(navigation_session_id)
        paths = self.repository.list_path_candidates(
            navigation_session_id=session.navigation_session_id,
            status=path_status,
            limit=max(1, min(int(path_limit or 50), 200)),
        )
        opened = self.repository.list_opened_refs(navigation_session_id=session.navigation_session_id, limit=200)
        decisions = self.repository.list_path_decisions(navigation_session_id=session.navigation_session_id, limit=24)
        local_slice = {}
        if include_local_slice and session.focus_node_ids:
            local_slice = ProjectStructureSliceService(self.repository).expand(
                build_id=session.build_id,
                seed_node_ids=session.focus_node_ids,
                generation=session.generation,
                depth=1,
                limit=80,
                include_inbound=True,
                include_semantic_overlay=True,
            ).to_dict()
        return ProjectNetworkNavigationProjection(
            navigation_session=session,
            path_candidates=paths,
            opened_refs=opened,
            recent_decisions=decisions,
            local_slice=local_slice,
            limitations=(
                "navigation_projection_does_not_create_physical_or_semantic_facts",
                "path_scores_are_map_ordering_not_agent_next_action",
                "paths_are_precomputed_navigation_routes_not_stepwise_cursor_state",
            ),
        )

    def _resolve_anchor_nodes(
        self,
        *,
        build_id: str,
        generation: int,
        anchor_node_ids: tuple[str, ...],
        anchor_stable_refs: tuple[str, ...],
        anchor_paths: tuple[str, ...],
    ) -> tuple[SkeletonNodeRecord, ...]:
        nodes: list[SkeletonNodeRecord] = []
        for node_id in _clean_list(anchor_node_ids):
            node = self.repository.get_skeleton_node(node_id)
            if node is not None and node.build_id == build_id and int(node.generation or 0) == generation:
                nodes.append(node)
        for stable_ref in _clean_list(anchor_stable_refs):
            node = self.repository.find_skeleton_node(build_id=build_id, stable_ref=stable_ref, generation=generation)
            if node is not None:
                nodes.append(node)
        for path in _clean_list(anchor_paths):
            node = _resolve_node_by_path(self.repository, build_id=build_id, path=path, generation=generation)
            if node is not None:
                nodes.append(node)
        if not nodes:
            repo_node = self.repository.find_skeleton_node(build_id=build_id, stable_ref=REPO_STABLE_REF, generation=generation)
            if repo_node is not None:
                nodes.append(repo_node)
        return tuple({node.node_id: node for node in nodes}.values())

    def _materialize_path_candidates(
        self,
        session: ProjectNetworkNavigationSessionRecord,
        focus_nodes: tuple[SkeletonNodeRecord, ...] | list[SkeletonNodeRecord],
        *,
        reason: str,
    ) -> tuple[ProjectNetworkPathCandidateRecord, ...]:
        records: list[ProjectNetworkPathCandidateRecord] = []
        max_depth = _bounded_depth(session.route_depth)
        max_paths = _bounded_path_limit(session.path_limit)
        existing_ids = {
            item.path_candidate_id
            for item in self.repository.list_path_candidates(navigation_session_id=session.navigation_session_id, limit=5000)
        }
        for focus_node in focus_nodes:
            queue: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [(focus_node.node_id, (focus_node.node_id,), ())]
            while queue and len(records) < max_paths:
                current_node_id, node_path, edge_path = queue.pop(0)
                if len(edge_path) >= max_depth:
                    continue
                for edge in self._ordered_edges(session, current_node_id):
                    target_node_id = edge.dst_node_id if edge.src_node_id == current_node_id else edge.src_node_id
                    if not target_node_id or target_node_id in node_path:
                        continue
                    target_node = self.repository.get_skeleton_node(target_node_id)
                    if target_node is None:
                        continue
                    next_node_path = (*node_path, target_node_id)
                    next_edge_path = (*edge_path, edge.edge_id)
                    candidate = self._path_candidate_record(
                        session=session,
                        source_node_id=focus_node.node_id,
                        target_node=target_node,
                        node_ids=next_node_path,
                        edge_ids=next_edge_path,
                        reason=reason,
                    )
                    if candidate.path_candidate_id not in existing_ids:
                        records.append(candidate)
                        existing_ids.add(candidate.path_candidate_id)
                    queue.append((target_node_id, next_node_path, next_edge_path))
                    if len(records) >= max_paths:
                        break
        return self.repository.upsert_path_candidates(tuple(records)) if records else ()

    def _ordered_edges(self, session: ProjectNetworkNavigationSessionRecord, node_id: str) -> tuple[SkeletonEdgeRecord, ...]:
        edges = [
            *self.repository.list_skeleton_edges(
                build_id=session.build_id,
                generation=session.generation,
                src_node_id=node_id,
                limit=1000,
            ),
            *self.repository.list_skeleton_edges(
                build_id=session.build_id,
                generation=session.generation,
                dst_node_id=node_id,
                limit=1000,
            ),
        ]
        deduped = {edge.edge_id: edge for edge in edges}.values()
        return tuple(
            sorted(
                deduped,
                key=lambda edge: (
                    -_edge_navigation_score(self.repository, edge, current_node_id=node_id, goal=session.goal),
                    edge.edge_kind,
                    edge.edge_id,
                ),
            )
        )

    def _path_candidate_record(
        self,
        *,
        session: ProjectNetworkNavigationSessionRecord,
        source_node_id: str,
        target_node: SkeletonNodeRecord,
        node_ids: tuple[str, ...],
        edge_ids: tuple[str, ...],
        reason: str,
    ) -> ProjectNetworkPathCandidateRecord:
        edges = tuple(edge for edge_id in edge_ids for edge in (self.repository.get_skeleton_edge(edge_id),) if edge is not None)
        nodes = tuple(node for node_id in node_ids for node in (self.repository.get_skeleton_node(node_id),) if node is not None)
        overlays = tuple(
            overlay
            for node in nodes
            for overlay in self.repository.list_semantic_overlays(build_id=session.build_id, stable_ref=node.stable_ref, limit=4)
        )
        stable_refs = tuple(node.stable_ref for node in nodes if node.stable_ref)
        path_kind = _path_kind(edges)
        label = " -> ".join(node.display_name or node.stable_ref or node.node_id for node in nodes[:5])
        score = _path_score(edges, semantic_overlay_count=len(overlays), target_node=target_node, goal=session.goal)
        return ProjectNetworkPathCandidateRecord(
            path_candidate_id=stable_project_structure_id("pnpath", session.navigation_session_id, edge_ids, node_ids),
            navigation_session_id=session.navigation_session_id,
            build_id=session.build_id,
            generation=session.generation,
            path_kind=path_kind,
            path_label=label,
            source_node_id=source_node_id,
            target_node_id=target_node.node_id,
            node_ids=node_ids,
            edge_ids=edge_ids,
            stable_refs=stable_refs,
            score=score,
            reason=str(reason or "").strip(),
            status="available",
            evidence_refs=tuple(dict.fromkeys(ref for edge in edges for ref in edge.evidence_refs)),
            semantic_overlay_ids=tuple(dict.fromkeys(overlay.overlay_id for overlay in overlays)),
            payload={
                "target_node_kind": target_node.node_kind,
                "target_display_name": target_node.display_name,
                "target_path": target_node.path,
                "edge_kinds": [edge.edge_kind for edge in edges],
                "path_length": len(edge_ids),
                "path_model": "precomputed_network_path",
            },
        )

    def _require_session(self, navigation_session_id: str) -> ProjectNetworkNavigationSessionRecord:
        session = self.repository.get_navigation_session(navigation_session_id)
        if session is None:
            raise KeyError(f"Unknown project network navigation session: {navigation_session_id}")
        return session

    def _path_candidate(self, navigation_session_id: str, path_candidate_id: str) -> ProjectNetworkPathCandidateRecord | None:
        target = str(path_candidate_id or "").strip()
        if not target:
            return None
        for item in self.repository.list_path_candidates(navigation_session_id=navigation_session_id, limit=5000):
            if item.path_candidate_id == target:
                return item
        return None


def _resolve_node_by_path(
    repository: ProjectStructureRepository,
    *,
    build_id: str,
    path: str,
    generation: int,
) -> SkeletonNodeRecord | None:
    rel = normalize_rel_path(path)
    refs = [folder_ref(rel), file_ref(rel), py_module_ref(rel)]
    for stable_ref in refs:
        node = repository.find_skeleton_node(build_id=build_id, stable_ref=stable_ref, generation=generation)
        if node is not None:
            return node
    matches = repository.list_skeleton_nodes(build_id=build_id, generation=generation, path=rel, limit=1)
    return matches[0] if matches else None


def _latest_generation(repository: ProjectStructureRepository, build_id: str) -> int:
    generations = repository.list_skeleton_generations(build_id=build_id, limit=1)
    return int(generations[0].generation or 0) if generations else 0


def _path_kind(edges: tuple[SkeletonEdgeRecord, ...]) -> str:
    kinds = {edge.edge_kind for edge in edges}
    if kinds and kinds.issubset(HIERARCHY_EDGE_KINDS):
        return "hierarchy_path"
    if kinds & CODE_LINK_EDGE_KINDS:
        return "code_relation_path"
    return "mixed_structure_path"


def _path_score(
    edges: tuple[SkeletonEdgeRecord, ...],
    *,
    semantic_overlay_count: int,
    target_node: SkeletonNodeRecord | None = None,
    goal: str = "",
) -> int:
    if not edges:
        return 1
    base = sum(_edge_score(edge) for edge in edges) // max(1, len(edges))
    length_penalty = max(0, len(edges) - 1) * 8
    semantic_bonus = min(12, semantic_overlay_count * 2)
    target_bonus = _target_navigation_bonus(target_node, goal=goal)
    return max(1, min(base - length_penalty + semantic_bonus + target_bonus, 100))


def _target_navigation_bonus(target_node: SkeletonNodeRecord | None, *, goal: str) -> int:
    if target_node is None:
        return 0
    stable_ref = str(target_node.stable_ref or "")
    node_kind = str(target_node.node_kind or "").lower()
    goal_text = str(goal or "").lower()
    architecture_goal = any(
        item in goal_text
        for item in (
            "整体架构",
            "系统架构",
            "项目架构",
            "项目总览",
            "架构总览",
            "architecture",
            "overview",
            "system map",
        )
    )
    if not architecture_goal:
        return 4 if "directory" in node_kind or stable_ref.startswith("folder://") else 0
    depth = _stable_ref_depth(stable_ref)
    if stable_ref.startswith("folder://") and depth == 1:
        preferred = {"AGENT": 6, "CLIENT": 6, "TASK": 5, "MEMORY": 5, "FILE": 5, "README": 2}
        return 10 + preferred.get(_stable_ref_top_segment(stable_ref), 0)
    if stable_ref.startswith("folder://") and depth == 2:
        return 6
    if stable_ref.startswith("file://") and depth <= 1:
        return -8
    return 0


def _edge_score(edge: SkeletonEdgeRecord) -> int:
    base = 50
    if edge.edge_kind in HIERARCHY_EDGE_KINDS:
        base = 82
    elif edge.edge_kind in CODE_LINK_EDGE_KINDS:
        base = 72
    if edge.resolution_status != "resolved":
        base -= 25
    if edge.freshness == "stale":
        base -= 20
    return max(1, min(base, 100))


def _edge_navigation_score(
    repository: ProjectStructureRepository,
    edge: SkeletonEdgeRecord,
    *,
    current_node_id: str,
    goal: str,
) -> int:
    target_node_id = edge.dst_node_id if edge.src_node_id == current_node_id else edge.src_node_id
    target_node = repository.get_skeleton_node(target_node_id) if target_node_id else None
    return max(1, min(_edge_score(edge) + _target_navigation_bonus(target_node, goal=goal), 100))


def _stable_ref_depth(stable_ref: str) -> int:
    target = str(stable_ref or "")
    if "://" in target:
        target = target.split("://", 1)[1]
    target = target.split("#", 1)[0].replace("\\", "/").strip("/")
    if target in {"", "."}:
        return 0
    return len([part for part in target.split("/") if part])


def _stable_ref_top_segment(stable_ref: str) -> str:
    target = str(stable_ref or "")
    if "://" in target:
        target = target.split("://", 1)[1]
    target = target.split("#", 1)[0].replace("\\", "/").strip("/")
    if target in {"", "."}:
        return "."
    return target.split("/", 1)[0]


def _decision_id(navigation_session_id: str, decision_kind: str) -> str:
    return stable_project_structure_id("pndecision", navigation_session_id, decision_kind, utc_now_iso())


def _bounded_depth(value: int) -> int:
    return max(1, min(int(value or 3), 6))


def _bounded_path_limit(value: int) -> int:
    return max(1, min(int(value or 80), 500))


def _clean_list(values: tuple[str, ...] | list[str]) -> list[str]:
    return [str(item or "").strip().replace("\\", "/") for item in list(values or ()) if str(item or "").strip()]
