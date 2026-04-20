from __future__ import annotations

from pydantic import BaseModel, Field


class DurableExtractionBundle(BaseModel):
    session_id: str = ""
    turn_id: str = ""
    message_slice: list[dict[str, object]] = Field(default_factory=list)
    main_context: dict[str, object] = Field(default_factory=dict)
    task_summaries: list[dict[str, object]] = Field(default_factory=list)
    corrections: list[str] = Field(default_factory=list)
    session_projection: dict[str, object] = Field(default_factory=dict)
    manifest_headers: list[dict[str, object]] = Field(default_factory=list)


class DurableCandidateDraft(BaseModel):
    draft_id: str = ""
    memory_type: str = "project"
    memory_class: str = "work"
    title: str = ""
    canonical_statement: str = ""
    why: str = ""
    how_to_apply: str = ""
    stability: str = "unknown"
    non_obvious_value: str = ""
    source_scope: str = "private"
    evidence_excerpt: str = ""
    target_note_id: str = ""
    proposed_action: str = "none"


class DurableAdmissionDecision(BaseModel):
    decision: str = "reject"
    reason: str = ""
    normalized_candidate: dict[str, object] = Field(default_factory=dict)
    matched_note_id: str = ""
    conflicts_with: list[str] = Field(default_factory=list)


class DurableMutationPlan(BaseModel):
    actions: list[dict[str, object]] = Field(default_factory=list)
    index_updates: list[dict[str, object]] = Field(default_factory=list)
    notes_to_create: list[dict[str, object]] = Field(default_factory=list)
    notes_to_update: list[dict[str, object]] = Field(default_factory=list)
    notes_to_deprecate: list[dict[str, object]] = Field(default_factory=list)
