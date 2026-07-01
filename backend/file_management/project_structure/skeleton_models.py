from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


SkeletonConfidence = Literal["exact", "derived", "unresolved"]
SkeletonFreshness = Literal["fresh", "stale"]
SkeletonNodeStatus = Literal["active", "stale", "removed"]
SkeletonResolutionStatus = Literal["resolved", "unresolved", "ambiguous"]


@dataclass(frozen=True, slots=True)
class SkeletonFactRecord:
    fact_id: str
    build_id: str
    generation: int
    source_kind: str
    subject_ref: str
    predicate: str
    object_ref: str = ""
    object_literal: str = ""
    qualifiers: dict[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    anchor_refs: tuple[str, ...] = ()
    source_snapshot_ref: str = ""
    extractor_id: str = ""
    extractor_version: str = "v1"
    content_hash: str = ""
    confidence: SkeletonConfidence = "exact"
    created_at: str = ""
    authority: str = "file_management.project_structure.skeleton_fact"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_refs"] = list(self.evidence_refs)
        payload["anchor_refs"] = list(self.anchor_refs)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class SkeletonNodeRecord:
    node_id: str
    build_id: str
    generation: int
    node_kind: str
    stable_ref: str
    display_name: str = ""
    path: str = ""
    layer_kind: str = ""
    hierarchy_path: str = ""
    parent_node_ids: tuple[str, ...] = ()
    ancestor_node_ids: tuple[str, ...] = ()
    anchor_ref: str = ""
    file_hash: str = ""
    extractor: str = ""
    confidence: SkeletonConfidence = "exact"
    status: SkeletonNodeStatus = "active"
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    authority: str = "file_management.project_structure.skeleton_node"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["parent_node_ids"] = list(self.parent_node_ids)
        payload["ancestor_node_ids"] = list(self.ancestor_node_ids)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class SkeletonEdgeRecord:
    edge_id: str
    build_id: str
    generation: int
    edge_kind: str
    src_node_id: str
    dst_node_id: str = ""
    dst_candidate_ref: str = ""
    src_anchor_ref: str = ""
    dst_anchor_ref: str = ""
    evidence_refs: tuple[str, ...] = ()
    source_fact_ids: tuple[str, ...] = ()
    extractor: str = ""
    confidence: SkeletonConfidence = "exact"
    resolution_status: SkeletonResolutionStatus = "resolved"
    freshness: SkeletonFreshness = "fresh"
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    authority: str = "file_management.project_structure.skeleton_edge"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_refs"] = list(self.evidence_refs)
        payload["source_fact_ids"] = list(self.source_fact_ids)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class SkeletonGenerationRecord:
    skeleton_generation_id: str
    build_id: str
    generation: int
    status: str = "candidate"
    source_snapshot_ref: str = ""
    fact_count: int = 0
    node_count: int = 0
    edge_count: int = 0
    stale_count: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    authority: str = "file_management.project_structure.skeleton_generation"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class SkeletonExtractionReport:
    build_id: str
    generation: int
    scope_roots: tuple[str, ...] = ()
    fact_count: int = 0
    node_count: int = 0
    edge_count: int = 0
    extractor_counts: dict[str, int] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()
    authority: str = "file_management.project_structure.skeleton_extraction_report"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scope_roots"] = list(self.scope_roots)
        payload["limitations"] = list(self.limitations)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class SkeletonNodeCard:
    node: SkeletonNodeRecord
    inbound_edges: tuple[SkeletonEdgeRecord, ...] = ()
    outbound_edges: tuple[SkeletonEdgeRecord, ...] = ()
    children: tuple[SkeletonNodeRecord, ...] = ()
    ancestors: tuple[SkeletonNodeRecord, ...] = ()
    semantic_overlays: tuple[dict[str, Any], ...] = ()
    authority: str = "file_management.project_structure.skeleton_node_card"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "node": self.node.to_dict(),
                "inbound_edges": [item.to_dict() for item in self.inbound_edges],
                "outbound_edges": [item.to_dict() for item in self.outbound_edges],
                "children": [item.to_dict() for item in self.children],
                "ancestors": [item.to_dict() for item in self.ancestors],
                "semantic_overlays": [dict(item) for item in self.semantic_overlays],
                "authority": self.authority,
            }
        )


@dataclass(frozen=True, slots=True)
class SkeletonEdgeCard:
    edge: SkeletonEdgeRecord
    source_node: SkeletonNodeRecord | None = None
    target_node: SkeletonNodeRecord | None = None
    evidence_facts: tuple[SkeletonFactRecord, ...] = ()
    authority: str = "file_management.project_structure.skeleton_edge_card"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "edge": self.edge.to_dict(),
                "source_node": self.source_node.to_dict() if self.source_node is not None else {},
                "target_node": self.target_node.to_dict() if self.target_node is not None else {},
                "evidence_facts": [item.to_dict() for item in self.evidence_facts],
                "authority": self.authority,
            }
        )


@dataclass(frozen=True, slots=True)
class SkeletonSliceProjection:
    build_id: str
    generation: int
    seed_node_ids: tuple[str, ...] = ()
    nodes: tuple[SkeletonNodeRecord, ...] = ()
    edges: tuple[SkeletonEdgeRecord, ...] = ()
    semantic_overlays: tuple[dict[str, Any], ...] = ()
    limitations: tuple[str, ...] = ()
    authority: str = "file_management.project_structure.skeleton_slice_projection"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "build_id": self.build_id,
                "generation": self.generation,
                "seed_node_ids": list(self.seed_node_ids),
                "nodes": [item.to_dict() for item in self.nodes],
                "edges": [item.to_dict() for item in self.edges],
                "semantic_overlays": [dict(item) for item in self.semantic_overlays],
                "limitations": list(self.limitations),
                "authority": self.authority,
            }
        )


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
