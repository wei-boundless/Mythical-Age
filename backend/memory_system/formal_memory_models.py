from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class FormalMemoryRepository:
    repository_id: str
    logical_repository_id: str = ""
    effective_repository_id: str = ""
    task_run_id: str = ""
    scope_kind: str = "run_scoped"
    scope_id: str = ""
    graph_id: str = ""
    node_id: str = ""
    title: str = ""
    repository_kind: str = "formal_memory"
    lifecycle_policy: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    authority: str = "formal_memory.repository"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class FormalMemoryCollection:
    repository_id: str
    collection_id: str
    logical_repository_id: str = ""
    effective_repository_id: str = ""
    task_run_id: str = ""
    scope_kind: str = "run_scoped"
    scope_id: str = ""
    title: str = ""
    schema_id: str = ""
    record_kinds: tuple[str, ...] = ()
    key_strategy: str = "stable_key"
    default_version_selector: str = "latest_committed_before_clock"
    retention_policy: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    authority: str = "formal_memory.collection"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["record_kinds"] = list(self.record_kinds)
        return payload


@dataclass(slots=True, frozen=True)
class FormalMemoryRecord:
    record_id: str
    repository_id: str
    collection_id: str
    record_key: str
    logical_repository_id: str = ""
    effective_repository_id: str = ""
    task_run_id: str = ""
    scope_kind: str = "run_scoped"
    scope_id: str = ""
    record_kind: str = ""
    status: str = "active"
    current_committed_version: int = 0
    head_version_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    authority: str = "formal_memory.record"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class FormalMemoryRecordVersion:
    version_id: str
    record_id: str
    repository_id: str
    collection_id: str
    record_key: str
    logical_repository_id: str = ""
    effective_repository_id: str = ""
    task_run_id: str = ""
    scope_kind: str = "run_scoped"
    scope_id: str = ""
    record_kind: str = ""
    version: int = 1
    status: str = "candidate"
    payload: dict[str, Any] = field(default_factory=dict)
    canonical_text: str = ""
    summary: str = ""
    artifact_refs: tuple[str, ...] = ()
    source_node_id: str = ""
    source_edge_id: str = ""
    source_node_run_id: str = ""
    source_clock: str = ""
    source_clock_seq: int = 0
    visible_after_clock: str = ""
    visible_after_clock_seq: int = 0
    content_hash: str = ""
    supersedes_version_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    authority: str = "formal_memory.record_version"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifact_refs"] = list(self.artifact_refs)
        return payload


@dataclass(slots=True, frozen=True)
class FormalMemoryTransaction:
    transaction_id: str
    operation: str
    edge_id: str = ""
    node_run_id: str = ""
    repository_id: str = ""
    collection_id: str = ""
    record_key: str = ""
    record_id: str = ""
    logical_repository_id: str = ""
    effective_repository_id: str = ""
    task_run_id: str = ""
    scope_kind: str = "run_scoped"
    scope_id: str = ""
    candidate_version_id: str = ""
    committed_version_id: str = ""
    receipt: dict[str, Any] = field(default_factory=dict)
    status: str = "completed"
    idempotency_key: str = ""
    created_at: str = ""
    authority: str = "formal_memory.transaction"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class FormalMemoryReadLog:
    read_log_id: str
    edge_id: str = ""
    node_run_id: str = ""
    repository_id: str = ""
    collection_id: str = ""
    logical_repository_id: str = ""
    effective_repository_id: str = ""
    task_run_id: str = ""
    scope_kind: str = "run_scoped"
    scope_id: str = ""
    selector: dict[str, Any] = field(default_factory=dict)
    selected_version_ids: tuple[str, ...] = ()
    clock: str = ""
    clock_seq: int = 0
    created_at: str = ""
    authority: str = "formal_memory.read_log"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["selected_version_ids"] = list(self.selected_version_ids)
        return payload


