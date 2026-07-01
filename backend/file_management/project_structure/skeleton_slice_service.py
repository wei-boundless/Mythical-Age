from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .repository import ProjectStructureRepository
from .skeleton_models import SkeletonEdgeCard, SkeletonNodeCard, SkeletonNodeRecord, SkeletonSliceProjection
from .skeleton_normalizer import CODE_LINK_EDGE_KINDS, HIERARCHY_EDGE_KINDS


DEFAULT_EXPAND_EDGE_KINDS = tuple(sorted(HIERARCHY_EDGE_KINDS | CODE_LINK_EDGE_KINDS))


class ProjectStructureSliceService:
    authority = "file_management.project_structure.slice_service"

    def __init__(self, repository: ProjectStructureRepository) -> None:
        self.repository = repository

    @classmethod
    def from_backend_dir(cls, base_dir: str | Path) -> "ProjectStructureSliceService":
        return cls(ProjectStructureRepository(base_dir))

    def read_node(self, node_id: str, *, include_semantic_overlay: bool = True) -> SkeletonNodeCard | None:
        node = self.repository.get_skeleton_node(node_id)
        if node is None:
            return None
        outbound = self.repository.list_skeleton_edges(
            build_id=node.build_id,
            generation=node.generation,
            src_node_id=node.node_id,
            limit=1000,
        )
        inbound = self.repository.list_skeleton_edges(
            build_id=node.build_id,
            generation=node.generation,
            dst_node_id=node.node_id,
            limit=1000,
        )
        child_ids = tuple(edge.dst_node_id for edge in outbound if edge.edge_kind in HIERARCHY_EDGE_KINDS and edge.dst_node_id)
        children = tuple(
            child
            for child_id in child_ids
            for child in (self.repository.get_skeleton_node(child_id),)
            if child is not None
        )
        ancestors = tuple(
            ancestor
            for ancestor_id in node.ancestor_node_ids
            for ancestor in (self.repository.get_skeleton_node(ancestor_id),)
            if ancestor is not None
        )
        return SkeletonNodeCard(
            node=node,
            inbound_edges=inbound,
            outbound_edges=outbound,
            children=children,
            ancestors=ancestors,
            semantic_overlays=self.semantic_overlays_for_node(node) if include_semantic_overlay else (),
        )

    def read_edge(self, edge_id: str) -> SkeletonEdgeCard | None:
        edge = self.repository.get_skeleton_edge(edge_id)
        if edge is None:
            return None
        evidence = tuple(
            fact
            for fact_id in edge.source_fact_ids
            for fact in (self.repository.get_skeleton_fact(fact_id),)
            if fact is not None
        )
        return SkeletonEdgeCard(
            edge=edge,
            source_node=self.repository.get_skeleton_node(edge.src_node_id) if edge.src_node_id else None,
            target_node=self.repository.get_skeleton_node(edge.dst_node_id) if edge.dst_node_id else None,
            evidence_facts=evidence,
        )

    def expand(
        self,
        *,
        build_id: str,
        seed_node_ids: Iterable[str],
        generation: int | None = None,
        edge_kinds: tuple[str, ...] | list[str] = DEFAULT_EXPAND_EDGE_KINDS,
        depth: int = 1,
        limit: int = 200,
        include_inbound: bool = True,
        include_semantic_overlay: bool = True,
    ) -> SkeletonSliceProjection:
        resolved_generation = int(generation or 0) or _latest_generation(self.repository, build_id)
        allowed_edge_kinds = set(str(item or "").strip() for item in tuple(edge_kinds or ()) if str(item or "").strip())
        max_nodes = max(1, min(int(limit or 200), 1000))
        max_depth = max(0, min(int(depth or 0), 6))
        node_map: dict[str, SkeletonNodeRecord] = {}
        edge_map = {}
        frontier = [str(item or "").strip() for item in seed_node_ids if str(item or "").strip()]
        seed_ids = tuple(frontier)
        visited: set[str] = set()
        for _ in range(max_depth + 1):
            next_frontier: list[str] = []
            for node_id in frontier:
                if node_id in visited or len(node_map) >= max_nodes:
                    continue
                visited.add(node_id)
                node = self.repository.get_skeleton_node(node_id)
                if node is None or node.build_id != build_id or int(node.generation or 0) != resolved_generation:
                    continue
                node_map[node.node_id] = node
                related = list(
                    self.repository.list_skeleton_edges(
                        build_id=build_id,
                        generation=resolved_generation,
                        src_node_id=node.node_id,
                        limit=1000,
                    )
                )
                if include_inbound:
                    related.extend(
                        self.repository.list_skeleton_edges(
                            build_id=build_id,
                            generation=resolved_generation,
                            dst_node_id=node.node_id,
                            limit=1000,
                        )
                    )
                for edge in related:
                    if allowed_edge_kinds and edge.edge_kind not in allowed_edge_kinds:
                        continue
                    edge_map[edge.edge_id] = edge
                    for neighbor_id in (edge.src_node_id, edge.dst_node_id):
                        if neighbor_id and neighbor_id not in visited and len(node_map) + len(next_frontier) < max_nodes:
                            next_frontier.append(neighbor_id)
            frontier = list(dict.fromkeys(next_frontier))
            if not frontier:
                break
        overlays = tuple(
            overlay
            for node in node_map.values()
            for overlay in (self.semantic_overlays_for_node(node) if include_semantic_overlay else ())
        )
        return SkeletonSliceProjection(
            build_id=build_id,
            generation=resolved_generation,
            seed_node_ids=seed_ids,
            nodes=tuple(sorted(node_map.values(), key=lambda item: (item.hierarchy_path, item.node_kind, item.stable_ref))),
            edges=tuple(sorted(edge_map.values(), key=lambda item: (item.edge_kind, item.src_node_id, item.dst_node_id, item.dst_candidate_ref))),
            semantic_overlays=overlays,
            limitations=("semantic_overlay_uses_candidates_by_stable_ref",) if include_semantic_overlay else (),
        )

    def semantic_overlays_for_node(self, node: SkeletonNodeRecord, *, limit: int = 20) -> tuple[dict[str, object], ...]:
        overlays = self.repository.list_semantic_overlays(
            build_id=node.build_id,
            stable_ref=node.stable_ref,
            limit=max(1, min(int(limit or 20), 100)),
        )
        return tuple(
            {
                "overlay_kind": overlay.overlay_kind,
                "overlay_id": overlay.overlay_id,
                "status": overlay.status,
                "confidence": overlay.confidence,
                "generation": overlay.generation,
                "summary": str(overlay.payload.get("summary") or overlay.payload.get("description") or "")[:600],
                "evidence_refs": list(overlay.evidence_refs),
                "payload": dict(overlay.payload or {}),
            }
            for overlay in overlays
        )


def _latest_generation(repository: ProjectStructureRepository, build_id: str) -> int:
    generations = repository.list_skeleton_generations(build_id=build_id, limit=1)
    return int(generations[0].generation or 0) if generations else 0
