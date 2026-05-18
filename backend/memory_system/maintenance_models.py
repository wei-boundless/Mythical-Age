from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


MEMORY_MANAGER_AGENT_ID = "agent:1"
MEMORY_MANAGER_PROFILE_ID = "memory_system_agent"
ALLOWED_DURABLE_MEMORY_TYPES = {"user", "feedback", "project", "reference"}
ALLOWED_DURABLE_MEMORY_CLASSES = {"work", "preference"}
ALLOWED_DURABLE_ACTIONS = {"none", "create", "update", "merge"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def normalize_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.splitlines() if item.strip()]
    if isinstance(value, (list, tuple)):
        return [normalize_text(item) for item in value if normalize_text(item)]
    return [normalize_text(value)] if normalize_text(value) else []


class SessionMemoryMaintenanceDraft(BaseModel):
    session_title: str = ""
    active_goal: str = ""
    flow_state: list[str] = Field(default_factory=list)
    context_slots: list[str] = Field(default_factory=list)
    current_task_state: list[str] = Field(default_factory=list)
    warm_context: list[str] = Field(default_factory=list)
    key_user_requests: list[str] = Field(default_factory=list)
    files_and_functions: list[str] = Field(default_factory=list)
    conventions_and_constraints: list[str] = Field(default_factory=list)
    errors_and_corrections: list[str] = Field(default_factory=list)
    decisions_and_learnings: list[str] = Field(default_factory=list)
    key_results: list[str] = Field(default_factory=list)
    historical_results: list[str] = Field(default_factory=list)
    risk_watch: list[str] = Field(default_factory=list)
    next_step: list[str] = Field(default_factory=list)
    worklog: list[str] = Field(default_factory=list)

    @field_validator(
        "flow_state",
        "context_slots",
        "current_task_state",
        "warm_context",
        "key_user_requests",
        "files_and_functions",
        "conventions_and_constraints",
        "errors_and_corrections",
        "decisions_and_learnings",
        "key_results",
        "historical_results",
        "risk_watch",
        "next_step",
        "worklog",
        mode="before",
    )
    @classmethod
    def _coerce_list(cls, value: Any) -> list[str]:
        return normalize_text_list(value)

    @field_validator("session_title", "active_goal", mode="before")
    @classmethod
    def _coerce_text(cls, value: Any) -> str:
        return normalize_text(value)

    def is_empty(self) -> bool:
        if self.session_title or self.active_goal:
            return False
        list_fields = (
            self.flow_state,
            self.context_slots,
            self.current_task_state,
            self.warm_context,
            self.key_user_requests,
            self.files_and_functions,
            self.conventions_and_constraints,
            self.errors_and_corrections,
            self.decisions_and_learnings,
            self.key_results,
            self.historical_results,
            self.risk_watch,
            self.next_step,
            self.worklog,
        )
        return not any(list_fields)

    def render_markdown(self) -> str:
        sections: list[tuple[str, list[str]]] = [
            ("# Session Title", [self.session_title] if self.session_title else []),
            ("# Active Goal", [self.active_goal] if self.active_goal else []),
            ("# Flow State", self.flow_state),
            ("# Context Slots", self.context_slots),
            ("# Current Task State", self.current_task_state),
            ("# Warm Context", self.warm_context),
            ("# Key User Requests", self.key_user_requests),
            ("# Files and Functions", self.files_and_functions),
            ("# Conventions and Constraints", self.conventions_and_constraints),
            ("# Errors and Corrections", self.errors_and_corrections),
            ("# Decisions and Learnings", self.decisions_and_learnings),
            ("# Key Results", self.key_results),
            ("# Historical Results", self.historical_results),
            ("# Risk Watch", self.risk_watch),
            ("# Next Step", self.next_step),
            ("# Worklog", self.worklog),
        ]
        chunks: list[str] = []
        for header, items in sections:
            chunks.append(header)
            for item in items:
                text = normalize_text(item)
                if not text:
                    continue
                if header == "# Session Title":
                    chunks.append(text)
                elif text.startswith("- "):
                    chunks.append(text)
                else:
                    chunks.append(f"- {text}")
            chunks.append("")
        return "\n".join(chunks).strip() + "\n"


class DurableMemoryWriteAction(BaseModel):
    action: Literal["none", "create", "update", "merge"] = "none"
    note_id: str = ""
    target_note_id: str = ""
    merge_note_ids: list[str] = Field(default_factory=list)
    memory_type: Literal["user", "feedback", "project", "reference"] = "project"
    memory_class: Literal["work", "preference"] = "work"
    title: str = ""
    canonical_statement: str = ""
    summary: str = ""
    retrieval_hints: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"
    reason: str = ""
    how_to_apply: str = ""
    evidence_excerpt: str = ""
    source_message_refs: list[str] = Field(default_factory=list)

    @field_validator(
        "note_id",
        "target_note_id",
        "title",
        "canonical_statement",
        "summary",
        "reason",
        "how_to_apply",
        "evidence_excerpt",
        mode="before",
    )
    @classmethod
    def _coerce_text(cls, value: Any) -> str:
        return normalize_text(value)

    @field_validator("retrieval_hints", "source_message_refs", "merge_note_ids", mode="before")
    @classmethod
    def _coerce_list(cls, value: Any) -> list[str]:
        return normalize_text_list(value)


class DurableMemoryWritePlan(BaseModel):
    actions: list[DurableMemoryWriteAction] = Field(default_factory=list)
    skipped_reason: str = ""
    reasoning_summary: str = ""

    @field_validator("skipped_reason", "reasoning_summary", mode="before")
    @classmethod
    def _coerce_text(cls, value: Any) -> str:
        return normalize_text(value)

    def normalized_actions(self) -> list[DurableMemoryWriteAction]:
        return [item for item in self.actions if item.action != "none"]


class MemoryMaintenanceResult(BaseModel):
    session_memory: SessionMemoryMaintenanceDraft
    durable_memory: DurableMemoryWritePlan = Field(default_factory=DurableMemoryWritePlan)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class MemoryMaintenanceRequest(BaseModel):
    run_id: str
    session_id: str
    turn_id: str = ""
    agent_id: str = MEMORY_MANAGER_AGENT_ID
    message_count: int = 0
    last_memory_message_index: int = 0
    message_slice: list[dict[str, Any]] = Field(default_factory=list)
    previous_session_memory: str = ""
    main_context: dict[str, Any] = Field(default_factory=dict)
    task_summary_refs: list[dict[str, Any]] = Field(default_factory=list)
    bundle_summary_refs: list[dict[str, Any]] = Field(default_factory=list)
    manifest_headers: list[dict[str, Any]] = Field(default_factory=list)
    source_message_refs: list[str] = Field(default_factory=list)
    durable_lane_enabled: bool = True


class MemoryMaintenanceReceipt(BaseModel):
    run_id: str
    session_id: str
    turn_id: str = ""
    agent_id: str = MEMORY_MANAGER_AGENT_ID
    status: Literal["succeeded", "failed", "skipped", "queued"] = "skipped"
    attempted: bool = False
    queued: bool = False
    session_memory_succeeded: bool = False
    durable_memory_succeeded: bool = False
    durable_write_count: int = 0
    durable_skipped: bool = False
    durable_skip_reason: str = ""
    last_memory_message_index: int = 0
    processed_message_count: int = 0
    error: str = ""
    receipt_path: str = ""
    created_at: str = Field(default_factory=utc_now_iso)
    diagnostics: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()
