from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class ArtifactRepository:
    repository_id: str
    logical_repository_id: str = ""
    effective_repository_id: str = ""
    task_run_id: str = ""
    scope_kind: str = "run_scoped"
    scope_id: str = ""
    graph_id: str = ""
    node_id: str = ""
    title: str = ""
    lifecycle_policy: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    authority: str = "artifact_repository.repository"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ArtifactRecord:
    artifact_id: str
    artifact_ref: str
    path: str
    repository_id: str
    collection_id: str
    output_contract_id: str = ""
    artifact_kind: str = "file"
    producer_node_id: str = ""
    content_type: str = ""
    materialization_id: str = ""
    logical_repository_id: str = ""
    effective_repository_id: str = ""
    task_run_id: str = ""
    scope_kind: str = "run_scoped"
    scope_id: str = ""
    graph_id: str = ""
    stage_id: str = ""
    node_run_id: str = ""
    task_ref: str = ""
    coordination_run_id: str = ""
    status: str = "accepted"
    content_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    authority: str = "artifact_repository.record"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
