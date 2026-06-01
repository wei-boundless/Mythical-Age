from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ArtifactTypeSpec:
    artifact_type: str
    title: str
    stage_id: str = ""
    default_contract_id: str = ""
    requires_review: bool = True
    displayable: bool = True
    project_memory_allowed: bool = False
    environment_memory_candidate_allowed: bool = False
    committed_readable_by_execution: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.artifact_type_spec"

    def __post_init__(self) -> None:
        if not self.artifact_type:
            raise ValueError("ArtifactTypeSpec requires artifact_type")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DesignSystemSection:
    section_id: str
    title: str
    parent_section_id: str = ""
    accepted_artifact_types: tuple[str, ...] = ()
    read_visibility: str = "committed_only"
    write_policy: str = "lifecycle_adoption_only"
    versioning: str = "append_with_supersede"
    required_review: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.design_system_section"

    def __post_init__(self) -> None:
        if not self.section_id:
            raise ValueError("DesignSystemSection requires section_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["accepted_artifact_types"] = list(self.accepted_artifact_types)
        return payload


@dataclass(frozen=True, slots=True)
class ArtifactProjectionTarget:
    repository_id: str
    section_id: str = ""
    collection_id: str = ""
    state: str = "candidate"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.repository_id:
            raise ValueError("ArtifactProjectionTarget requires repository_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ArtifactProjectionRule:
    rule_id: str
    artifact_type: str
    target: ArtifactProjectionTarget
    environment_id: str = ""
    project_kind: str = ""
    source_contract_id: str = ""
    adoption_graph_id: str = ""
    read_visibility: str = "not_visible_until_committed"
    failure_policy: str = "quarantine_unmapped_artifact"
    version: str = "1.0.0"
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.artifact_projection_rule"

    def __post_init__(self) -> None:
        if not self.rule_id:
            raise ValueError("ArtifactProjectionRule requires rule_id")
        if not self.artifact_type:
            raise ValueError("ArtifactProjectionRule requires artifact_type")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["target"] = self.target.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class LifecycleAdoptionRule:
    rule_id: str
    artifact_type: str
    target_state: str = "committed"
    required_review_artifact_type: str = ""
    required_verdict: str = "approved"
    write_targets: tuple[ArtifactProjectionTarget, ...] = ()
    post_actions: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.lifecycle_adoption_rule"

    def __post_init__(self) -> None:
        if not self.rule_id:
            raise ValueError("LifecycleAdoptionRule requires rule_id")
        if not self.artifact_type:
            raise ValueError("LifecycleAdoptionRule requires artifact_type")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["write_targets"] = [item.to_dict() for item in self.write_targets]
        payload["post_actions"] = list(self.post_actions)
        return payload


def artifact_projection_target_from_dict(payload: dict[str, Any]) -> ArtifactProjectionTarget:
    return ArtifactProjectionTarget(
        repository_id=str(payload.get("repository_id") or "").strip(),
        section_id=str(payload.get("section_id") or "").strip(),
        collection_id=str(payload.get("collection_id") or "").strip(),
        state=str(payload.get("state") or "candidate").strip() or "candidate",
        metadata=dict(payload.get("metadata") or {}),
    )
