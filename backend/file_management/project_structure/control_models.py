from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ProjectNetworkNavigationSessionRecord:
    navigation_session_id: str
    build_id: str
    generation: int
    goal: str
    anchor_node_ids: tuple[str, ...] = ()
    anchor_stable_refs: tuple[str, ...] = ()
    focus_node_ids: tuple[str, ...] = ()
    route_depth: int = 3
    path_limit: int = 80
    status: str = "active"
    created_by_task_run_id: str = ""
    created_by_agent_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "file_management.project_structure.project_network_navigation_session"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["anchor_node_ids"] = list(self.anchor_node_ids)
        payload["anchor_stable_refs"] = list(self.anchor_stable_refs)
        payload["focus_node_ids"] = list(self.focus_node_ids)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class ProjectNetworkPathCandidateRecord:
    path_candidate_id: str
    navigation_session_id: str
    build_id: str
    generation: int
    path_kind: str = ""
    path_label: str = ""
    source_node_id: str = ""
    target_node_id: str = ""
    node_ids: tuple[str, ...] = ()
    edge_ids: tuple[str, ...] = ()
    stable_refs: tuple[str, ...] = ()
    score: int = 50
    reason: str = ""
    status: str = "available"
    evidence_refs: tuple[str, ...] = ()
    semantic_overlay_ids: tuple[str, ...] = ()
    created_at: str = ""
    updated_at: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    authority: str = "file_management.project_structure.project_network_path_candidate"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["node_ids"] = list(self.node_ids)
        payload["edge_ids"] = list(self.edge_ids)
        payload["stable_refs"] = list(self.stable_refs)
        payload["evidence_refs"] = list(self.evidence_refs)
        payload["semantic_overlay_ids"] = list(self.semantic_overlay_ids)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class ProjectNetworkOpenedRefRecord:
    opened_ref_id: str
    navigation_session_id: str
    build_id: str
    generation: int
    ref_kind: str
    ref_id: str
    reason: str = ""
    created_at: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    authority: str = "file_management.project_structure.project_network_opened_ref"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class ProjectNetworkPathDecisionRecord:
    decision_id: str
    navigation_session_id: str
    build_id: str
    generation: int
    decision_kind: str
    selected_path_candidate_id: str = ""
    selected_node_id: str = ""
    selected_edge_id: str = ""
    reason: str = ""
    status: str = "recorded"
    evidence_refs: tuple[str, ...] = ()
    created_by_task_run_id: str = ""
    created_by_agent_id: str = ""
    created_at: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    authority: str = "file_management.project_structure.project_network_path_decision"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_refs"] = list(self.evidence_refs)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class ProjectNetworkNavigationProjection:
    navigation_session: ProjectNetworkNavigationSessionRecord
    path_candidates: tuple[ProjectNetworkPathCandidateRecord, ...] = ()
    opened_refs: tuple[ProjectNetworkOpenedRefRecord, ...] = ()
    recent_decisions: tuple[ProjectNetworkPathDecisionRecord, ...] = ()
    local_slice: dict[str, Any] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()
    authority: str = "file_management.project_structure.project_network_navigation_projection"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "navigation_session": self.navigation_session.to_dict(),
                "path_candidates": [item.to_dict() for item in self.path_candidates],
                "opened_refs": [item.to_dict() for item in self.opened_refs],
                "recent_decisions": [item.to_dict() for item in self.recent_decisions],
                "local_slice": dict(self.local_slice or {}),
                "limitations": list(self.limitations),
                "authority": self.authority,
            }
        )


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
