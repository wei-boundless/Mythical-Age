from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


TaskDurableMemoryStatus = Literal["active", "archived", "deprecated", "rejected"]
TaskDurableGlobalPromotionState = Literal[
    "not_applicable",
    "candidate",
    "needs_review",
    "approved",
    "rejected",
    "promoted_to_global",
]


@dataclass(slots=True, frozen=True)
class TaskDurableMemoryItem:
    task_memory_id: str
    namespace_id: str
    domain_id: str = ""
    task_id: str = ""
    graph_id: str = ""
    project_id: str = ""
    artifact_namespace: str = ""
    source_work_memory_ids: tuple[str, ...] = ()
    source_artifact_refs: tuple[str, ...] = ()
    memory_type: str = "project"
    memory_class: str = "work"
    kind: str = "task_memory"
    memory_semantics: str = "working_fact"
    title: str = ""
    canonical_statement: str = ""
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    retrieval_hints: tuple[str, ...] = ()
    status: TaskDurableMemoryStatus = "active"
    confidence: str = "medium"
    stability: str = "stable"
    eligible_for_task_injection: bool = True
    eligible_for_global_promotion: bool = False
    global_promotion_state: TaskDurableGlobalPromotionState = "not_applicable"
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_durable_memory.task_asset"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_work_memory_ids"] = list(self.source_work_memory_ids)
        payload["source_artifact_refs"] = list(self.source_artifact_refs)
        payload["retrieval_hints"] = list(self.retrieval_hints)
        return payload


@dataclass(slots=True, frozen=True)
class TaskDurableMemoryQuery:
    namespace_id: str = ""
    domain_id: str = ""
    task_id: str = ""
    graph_id: str = ""
    project_id: str = ""
    artifact_namespace: str = ""
    kind: str = ""
    memory_semantics: str = ""
    status: str = ""
    limit: int = 200

    def normalized_limit(self) -> int:
        return max(1, min(int(self.limit or 200), 1000))


@dataclass(slots=True, frozen=True)
class TaskDurableMemoryNamespace:
    namespace_id: str
    domain_id: str = ""
    task_id: str = ""
    graph_id: str = ""
    project_id: str = ""
    artifact_namespace: str = ""
    item_count: int = 0
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
