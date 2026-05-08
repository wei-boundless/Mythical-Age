from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


WorkingMemoryScope = Literal[
    "task_scope",
    "graph_scope",
    "node_scope",
    "edge_scope",
    "artifact_scope",
]
WorkingMemoryStatus = Literal[
    "draft",
    "proposed",
    "accepted",
    "conflicted",
    "superseded",
    "archived",
    "promoted",
    "discarded",
]
WorkingMemoryVisibility = Literal[
    "private_to_agent",
    "private_to_node",
    "shared_in_graph",
    "handoff_only",
    "coordinator_only",
    "human_review_only",
]
WorkingMemoryPromotionState = Literal[
    "not_applicable",
    "candidate",
    "needs_review",
    "approved",
    "rejected",
    "promoted_to_task_durable",
    "promoted_to_artifact_store",
    "promoted_to_health_issue",
]
WorkingMemorySemantics = Literal[
    "working_fact",
    "draft_artifact",
    "reflection",
    "instruction",
    "temporal_event",
    "conflict",
    "decision",
    "handoff_note",
    "evaluation",
]
WorkingMemoryAuthority = Literal[
    "candidate_only",
    "runloop_adopted",
    "coordinator_adopted",
    "human_gate_adopted",
]
WorkingMemoryTransactionStatus = Literal[
    "pending",
    "committed",
    "rejected",
    "rolled_back",
    "conflicted",
]


@dataclass(slots=True, frozen=True)
class WorkingMemoryItem:
    work_memory_id: str
    task_run_id: str
    task_id: str = ""
    graph_id: str = ""
    owner_node_id: str = ""
    owner_node_role: str = ""
    node_run_id: str = ""
    run_attempt_id: str = ""
    stage_id: str = ""
    writer_agent_id: str = ""
    last_writer_agent_id: str = ""
    scope: WorkingMemoryScope = "node_scope"
    kind: str = "intermediate_result"
    memory_semantics: WorkingMemorySemantics = "working_fact"
    title: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    status: WorkingMemoryStatus = "draft"
    visibility: WorkingMemoryVisibility = "private_to_node"
    read_policy: dict[str, Any] = field(default_factory=dict)
    write_policy: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    parent_item_id: str = ""
    source_event_refs: tuple[str, ...] = ()
    source_message_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    contract_refs: tuple[str, ...] = ()
    reader_policy: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    temporal_refs: tuple[str, ...] = ()
    conflict_refs: tuple[str, ...] = ()
    adopted_from_handoff_id: str = ""
    idempotency_key: str = ""
    source_message_hash: str = ""
    created_at: str = ""
    updated_at: str = ""
    expires_at: str = ""
    promotion_state: WorkingMemoryPromotionState = "not_applicable"
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: WorkingMemoryAuthority = "candidate_only"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_event_refs"] = list(self.source_event_refs)
        payload["source_message_refs"] = list(self.source_message_refs)
        payload["artifact_refs"] = list(self.artifact_refs)
        payload["contract_refs"] = list(self.contract_refs)
        payload["tags"] = list(self.tags)
        payload["temporal_refs"] = list(self.temporal_refs)
        payload["conflict_refs"] = list(self.conflict_refs)
        return payload


@dataclass(slots=True, frozen=True)
class WorkingMemoryReadLog:
    read_log_id: str
    task_run_id: str
    graph_id: str = ""
    owner_node_id: str = ""
    node_run_id: str = ""
    run_attempt_id: str = ""
    reader_agent_id: str = ""
    request: dict[str, Any] = field(default_factory=dict)
    selected_item_ids: tuple[str, ...] = ()
    excluded_item_ids: tuple[str, ...] = ()
    token_estimate: int = 0
    denied_reason: str = ""
    created_at: str = ""
    authority: str = "working_memory.read_log"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["selected_item_ids"] = list(self.selected_item_ids)
        payload["excluded_item_ids"] = list(self.excluded_item_ids)
        return payload


@dataclass(slots=True, frozen=True)
class WorkingMemoryTemporalEdge:
    edge_id: str
    task_run_id: str
    graph_id: str = ""
    source_item_id: str = ""
    target_item_id: str = ""
    relation: str = "depends_on"
    confidence: float = 0.0
    source_node_id: str = ""
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "working_memory.temporal_edge"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class WorkingMemoryHandoffTransaction:
    transaction_id: str
    task_run_id: str
    graph_id: str = ""
    edge_id: str = ""
    source_node_run_id: str = ""
    target_node_run_id: str = ""
    handoff_id: str = ""
    source_message_hash: str = ""
    idempotency_key: str = ""
    candidate_work_memory_ids: tuple[str, ...] = ()
    adopted_work_memory_ids: tuple[str, ...] = ()
    rejected_work_memory_ids: tuple[str, ...] = ()
    ephemeral_context_refs: tuple[str, ...] = ()
    transaction_status: WorkingMemoryTransactionStatus = "pending"
    created_at: str = ""
    committed_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "working_memory.handoff_transaction"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["candidate_work_memory_ids"] = list(self.candidate_work_memory_ids)
        payload["adopted_work_memory_ids"] = list(self.adopted_work_memory_ids)
        payload["rejected_work_memory_ids"] = list(self.rejected_work_memory_ids)
        payload["ephemeral_context_refs"] = list(self.ephemeral_context_refs)
        return payload


@dataclass(slots=True, frozen=True)
class WorkingMemoryPolicyProfile:
    profile_id: str
    task_family: str = ""
    allowed_kinds: tuple[str, ...] = ()
    allowed_semantics: tuple[WorkingMemorySemantics, ...] = ()
    readable_scopes_by_node_role: dict[str, list[str]] = field(default_factory=dict)
    writable_kinds_by_node_role: dict[str, list[str]] = field(default_factory=dict)
    default_visibility_by_kind: dict[str, str] = field(default_factory=dict)
    default_status_by_semantics: dict[str, str] = field(default_factory=dict)
    promotion_rules: dict[str, Any] = field(default_factory=dict)
    retention_rules: dict[str, Any] = field(default_factory=dict)
    conflict_rules: dict[str, Any] = field(default_factory=dict)
    dynamic_read_rules: dict[str, Any] = field(default_factory=dict)
    temporal_rules: dict[str, Any] = field(default_factory=dict)
    retry_memory_rules: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "working_memory.policy_profile"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_kinds"] = list(self.allowed_kinds)
        payload["allowed_semantics"] = list(self.allowed_semantics)
        return payload


@dataclass(slots=True, frozen=True)
class WorkingMemoryQuery:
    task_run_id: str = ""
    task_id: str = ""
    graph_id: str = ""
    owner_node_id: str = ""
    node_run_id: str = ""
    run_attempt_id: str = ""
    writer_agent_id: str = ""
    kind: str = ""
    memory_semantics: str = ""
    status: str = ""
    visibility: str = ""
    limit: int = 200

    def normalized_limit(self) -> int:
        return max(1, min(int(self.limit or 200), 1000))
