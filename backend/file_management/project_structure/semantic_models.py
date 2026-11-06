from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SemanticOverlayRecord:
    overlay_id: str
    build_id: str
    overlay_kind: str
    stable_ref: str = ""
    skeleton_node_id: str = ""
    skeleton_edge_id: str = ""
    anchor_ref: str = ""
    status: str = "candidate"
    confidence: str = "derived"
    generation: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    created_by_task_run_id: str = ""
    created_by_agent_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    authority: str = "file_management.project_structure.semantic_overlay"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_refs"] = list(self.evidence_refs)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class SemanticRouteHopRecord:
    hop_id: str
    source_node_id: str = ""
    target_node_id: str = ""
    skeleton_edge_id: str = ""
    stable_ref: str = ""
    relation_label: str = ""
    purpose: str = ""
    review_focus: str = ""
    verification_target: str = ""
    evidence_refs: tuple[str, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_refs"] = list(self.evidence_refs)
        return _drop_empty(payload)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SemanticRouteHopRecord":
        data = dict(payload or {})
        return cls(
            hop_id=str(data.get("hop_id") or ""),
            source_node_id=str(data.get("source_node_id") or data.get("src_node_id") or ""),
            target_node_id=str(data.get("target_node_id") or data.get("dst_node_id") or ""),
            skeleton_edge_id=str(data.get("skeleton_edge_id") or ""),
            stable_ref=str(data.get("stable_ref") or ""),
            relation_label=str(data.get("relation_label") or data.get("edge_kind") or ""),
            purpose=str(data.get("purpose") or ""),
            review_focus=str(data.get("review_focus") or ""),
            verification_target=str(data.get("verification_target") or ""),
            evidence_refs=tuple(_strings(data.get("evidence_refs"))),
            payload=dict(data.get("payload") or {}),
        )


@dataclass(frozen=True, slots=True)
class SemanticRouteOverlayRecord:
    route_id: str
    build_id: str
    route_kind: str
    title: str = ""
    purpose: str = ""
    start_node_id: str = ""
    target_node_id: str = ""
    stable_ref: str = ""
    status: str = "candidate"
    confidence: str = "derived"
    generation: int = 0
    priority: int = 50
    review_focus: str = ""
    verification_target: str = ""
    hops: tuple[SemanticRouteHopRecord, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    created_by_task_run_id: str = ""
    created_by_agent_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    authority: str = "file_management.project_structure.semantic_route_overlay"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["hops"] = [hop.to_dict() for hop in self.hops]
        payload["evidence_refs"] = list(self.evidence_refs)
        return _drop_empty(payload)

    def to_overlay_record(self) -> SemanticOverlayRecord:
        touched_node_ids = tuple(dict.fromkeys(_route_node_ids(self)))
        touched_edge_ids = tuple(dict.fromkeys(_route_edge_ids(self)))
        payload = {
            "schema": "project_structure.semantic_route_overlay.v1",
            "route_kind": self.route_kind,
            "title": self.title,
            "purpose": self.purpose,
            "priority": int(self.priority or 50),
            "review_focus": self.review_focus,
            "verification_target": self.verification_target,
            "start_node_id": self.start_node_id,
            "target_node_id": self.target_node_id,
            "touched_node_ids": list(touched_node_ids),
            "touched_edge_ids": list(touched_edge_ids),
            "hops": [hop.to_dict() for hop in self.hops],
        }
        return SemanticOverlayRecord(
            overlay_id=self.route_id,
            build_id=self.build_id,
            overlay_kind="semantic_route",
            stable_ref=self.stable_ref,
            skeleton_node_id=self.start_node_id,
            skeleton_edge_id=touched_edge_ids[0] if touched_edge_ids else "",
            status=self.status,
            confidence=self.confidence,
            generation=self.generation,
            payload=payload,
            evidence_refs=self.evidence_refs,
            created_by_task_run_id=self.created_by_task_run_id,
            created_by_agent_id=self.created_by_agent_id,
            created_at=self.created_at,
            updated_at=self.updated_at,
            authority=self.authority,
        )

    @classmethod
    def from_overlay_record(cls, overlay: SemanticOverlayRecord) -> "SemanticRouteOverlayRecord":
        payload = dict(overlay.payload or {})
        return cls(
            route_id=overlay.overlay_id,
            build_id=overlay.build_id,
            route_kind=str(payload.get("route_kind") or overlay.overlay_kind or "semantic_route"),
            title=str(payload.get("title") or payload.get("summary") or ""),
            purpose=str(payload.get("purpose") or ""),
            start_node_id=str(payload.get("start_node_id") or overlay.skeleton_node_id or ""),
            target_node_id=str(payload.get("target_node_id") or ""),
            stable_ref=overlay.stable_ref,
            status=overlay.status,
            confidence=overlay.confidence,
            generation=int(overlay.generation or 0),
            priority=max(0, min(int(payload.get("priority") or 50), 100)),
            review_focus=str(payload.get("review_focus") or ""),
            verification_target=str(payload.get("verification_target") or ""),
            hops=tuple(SemanticRouteHopRecord.from_dict(dict(item)) for item in list(payload.get("hops") or []) if isinstance(item, dict)),
            evidence_refs=tuple(overlay.evidence_refs),
            created_by_task_run_id=overlay.created_by_task_run_id,
            created_by_agent_id=overlay.created_by_agent_id,
            created_at=overlay.created_at,
            updated_at=overlay.updated_at,
        )


@dataclass(frozen=True, slots=True)
class SemanticRouteProjection:
    build_id: str
    generation: int
    anchor_node_id: str = ""
    routes: tuple[SemanticRouteOverlayRecord, ...] = ()
    route_hops: tuple[SemanticRouteHopRecord, ...] = ()
    limitations: tuple[str, ...] = ()
    authority: str = "file_management.project_structure.semantic_route_projection"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "build_id": self.build_id,
                "generation": self.generation,
                "anchor_node_id": self.anchor_node_id,
                "routes": [route.to_dict() for route in self.routes],
                "route_hops": [hop.to_dict() for hop in self.route_hops],
                "limitations": list(self.limitations),
                "authority": self.authority,
            }
        )


@dataclass(frozen=True, slots=True)
class NetworkMaintenanceRunRecord:
    maintenance_run_id: str
    build_id: str
    change_set_id: str
    status: str = "planned"
    affected_node_ids: tuple[str, ...] = ()
    affected_edge_ids: tuple[str, ...] = ()
    repair_work_item_ids: tuple[str, ...] = ()
    shared_memory_refs: tuple[str, ...] = ()
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "file_management.project_structure.maintenance_run"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["affected_node_ids"] = list(self.affected_node_ids)
        payload["affected_edge_ids"] = list(self.affected_edge_ids)
        payload["repair_work_item_ids"] = list(self.repair_work_item_ids)
        payload["shared_memory_refs"] = list(self.shared_memory_refs)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class SemanticRepairWorkItemRecord:
    work_item_id: str
    build_id: str
    change_set_id: str
    skeleton_generation: int
    repair_kind: str
    assigned_scope: dict[str, Any] = field(default_factory=dict)
    affected_node_ids: tuple[str, ...] = ()
    affected_edge_ids: tuple[str, ...] = ()
    previous_semantic_refs: tuple[str, ...] = ()
    shared_memory_refs: tuple[str, ...] = ()
    required_evidence_refs: tuple[str, ...] = ()
    priority: int = 50
    status: str = "queued"
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "file_management.project_structure.semantic_repair_work_item"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["affected_node_ids"] = list(self.affected_node_ids)
        payload["affected_edge_ids"] = list(self.affected_edge_ids)
        payload["previous_semantic_refs"] = list(self.previous_semantic_refs)
        payload["shared_memory_refs"] = list(self.shared_memory_refs)
        payload["required_evidence_refs"] = list(self.required_evidence_refs)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class SemanticRepairDecisionRecord:
    decision_id: str
    build_id: str
    change_set_id: str
    work_item_id: str
    decision: str
    affected_node_ids: tuple[str, ...] = ()
    affected_edge_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    shared_memory_refs: tuple[str, ...] = ()
    reason: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "candidate"
    created_at: str = ""
    updated_at: str = ""
    authority: str = "file_management.project_structure.semantic_repair_decision"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["affected_node_ids"] = list(self.affected_node_ids)
        payload["affected_edge_ids"] = list(self.affected_edge_ids)
        payload["evidence_refs"] = list(self.evidence_refs)
        payload["shared_memory_refs"] = list(self.shared_memory_refs)
        return _drop_empty(payload)


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(item).strip() for item in list(value or []) if str(item).strip()]


def _route_node_ids(route: SemanticRouteOverlayRecord) -> list[str]:
    values = [route.start_node_id, route.target_node_id]
    for hop in route.hops:
        values.extend([hop.source_node_id, hop.target_node_id])
    return [item for item in values if item]


def _route_edge_ids(route: SemanticRouteOverlayRecord) -> list[str]:
    return [hop.skeleton_edge_id for hop in route.hops if hop.skeleton_edge_id]
