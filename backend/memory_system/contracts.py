from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


MemoryLayer = Literal["conversation", "state", "working", "task_durable", "long_term"]
BudgetClass = Literal["required", "preferred", "optional", "debug_only"]
RestoreKind = Literal[
    "active_binding",
    "bundle_ref",
    "context_slot",
    "flow_state",
    "task_state",
    "file_awareness",
    "result_handle",
]
WriteKind = Literal["update_summary", "update_state", "propose_long_term_fact"]
GateDecision = Literal["pending", "accepted", "rejected"]
MemoryCommitLayer = Literal["conversation", "state", "long_term", "governance_log"]
MemoryCommitAction = Literal[
    "manual_create",
    "manual_update",
    "manual_disable",
    "manual_activate",
    "manual_archive",
    "manual_delete",
    "manual_merge",
]
LongTermMemoryType = Literal[
    "user_preference",
    "feedback_correction",
    "project_convention",
    "external_reference",
]
ViewKind = Literal["full", "partial", "generated_summary"]


@dataclass(slots=True, frozen=True)
class MemoryContextCandidate:
    """Candidate-only memory material for ContextPolicy.

    Memory reads are never current-turn truth by themselves. ContextPolicy may
    include them in a package, and OrchestrationSystem may adopt compatible
    state candidates, but this object cannot grant decision authority.
    """

    candidate_id: str
    memory_layer: MemoryLayer
    source: str
    content_ref: str = ""
    rendered_preview: str = ""
    relevance: float = 0.0
    confidence: float = 0.0
    staleness: str = "unknown"
    owner_task_id: str = ""
    token_estimate: int = 0
    budget_class: BudgetClass = "optional"
    can_override_current_turn: bool = False
    requires_verification_before_use: bool = True
    authority: str = "candidate_only"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != "candidate_only":
            raise ValueError("MemoryContextCandidate must remain candidate_only")
        if self.can_override_current_turn:
            raise ValueError("MemoryContextCandidate cannot override current-turn truth")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class StateMemoryRestoreCandidate:
    """Recoverable working-state hint; restore still does not equal decide."""

    candidate_id: str
    restore_kind: RestoreKind
    value: Any
    source: str
    owner_task_id: str = ""
    observed_at: str = ""
    confidence: float = 0.0
    stale_after: str = ""
    promotion_rule: str = "orchestration_must_validate_against_task_contract"
    can_promote_to_current_fact: bool = False
    rejection_reason: str = ""
    authority: str = "candidate_only"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != "candidate_only":
            raise ValueError("StateMemoryRestoreCandidate must remain candidate_only")
        if self.can_promote_to_current_fact:
            raise ValueError("StateMemoryRestoreCandidate cannot self-promote to current fact")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ConversationMemorySnapshot:
    session_id: str
    recent_dialogue_refs: tuple[str, ...] = ()
    hot_truth_window: tuple[str, ...] = ()
    compact_summary_ref: str = ""
    key_results: tuple[str, ...] = ()
    worklog: tuple[str, ...] = ()
    last_updated_at: str = ""
    extraction_trigger: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["recent_dialogue_refs"] = list(self.recent_dialogue_refs)
        payload["hot_truth_window"] = list(self.hot_truth_window)
        payload["key_results"] = list(self.key_results)
        payload["worklog"] = list(self.worklog)
        return payload


@dataclass(slots=True, frozen=True)
class StateMemoryFileRef:
    path: str
    observed_at: str = ""
    view_kind: ViewKind = "generated_summary"
    offset: int | None = None
    limit: int | None = None
    content_hash: str = ""
    editable_without_reread: bool = False
    restore_priority: int = 0
    owner_task_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class StateMemorySnapshot:
    session_id: str
    active_goal: str = ""
    flow_state: dict[str, Any] = field(default_factory=dict)
    task_state: dict[str, Any] = field(default_factory=dict)
    context_slots: dict[str, Any] = field(default_factory=dict)
    active_handles: dict[str, str] = field(default_factory=dict)
    bundle_result_refs: tuple[dict[str, Any], ...] = ()
    file_refs: tuple[StateMemoryFileRef, ...] = ()
    operation_refs: tuple[str, ...] = ()
    next_step: tuple[str, ...] = ()
    updated_at: str = ""
    source: str = "state_memory"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["bundle_result_refs"] = [dict(item) for item in self.bundle_result_refs]
        payload["file_refs"] = [item.to_dict() for item in self.file_refs]
        payload["operation_refs"] = list(self.operation_refs)
        payload["next_step"] = list(self.next_step)
        return payload


@dataclass(slots=True, frozen=True)
class LongTermMemoryRecord:
    memory_id: str
    memory_type: LongTermMemoryType
    canonical_statement: str
    evidence_ref: str = ""
    created_at: str = ""
    updated_at: str = ""
    staleness_policy: str = "verify_against_current_state_before_use"
    verification_policy: str = "required_for_file_function_flag_claims"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class MemoryWriteCandidate:
    """Candidate-only writeback request; CommitGate owns persistence."""

    candidate_id: str
    target_layer: MemoryLayer
    write_kind: WriteKind
    content: str
    source_event_refs: tuple[str, ...] = ()
    stability: str = "unknown"
    risk_flags: tuple[str, ...] = ()
    gate_decision: GateDecision = "pending"
    gate_reason: str = "not_evaluated"
    authority: str = "candidate_only"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != "candidate_only":
            raise ValueError("MemoryWriteCandidate must remain candidate_only")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_event_refs"] = list(self.source_event_refs)
        payload["risk_flags"] = list(self.risk_flags)
        return payload


@dataclass(slots=True, frozen=True)
class MemoryCommitRecord:
    """Governance-only memory commit audit record."""

    record_id: str
    commit_layer: MemoryCommitLayer
    action: MemoryCommitAction
    target_refs: tuple[str, ...] = ()
    created_ref: str = ""
    reason: str = ""
    actor: str = "memory_governance"
    allowed: bool = False
    source_candidate_refs: tuple[str, ...] = ()
    authority: str = "memory_governance_commit_record"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != "memory_governance_commit_record":
            raise ValueError("MemoryCommitRecord cannot carry runtime authority")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["target_refs"] = list(self.target_refs)
        payload["source_candidate_refs"] = list(self.source_candidate_refs)
        return payload
