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
