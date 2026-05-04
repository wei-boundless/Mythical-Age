from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryRecallRequest(BaseModel):
    query: str = ""
    main_context: dict[str, object] = Field(default_factory=dict)
    task_summaries: list[dict[str, object]] = Field(default_factory=list)
    session_summary: str = ""
    manifest_headers: list[dict[str, object]] = Field(default_factory=list)
    recently_surfaced_note_ids: list[str] = Field(default_factory=list)
    explicit_memory_mode: str = "none"
    ignore_memory: bool = False
    recent_tools: list[str] = Field(default_factory=list)
    preferred_types: list[str] = Field(default_factory=list)
    preferred_memory_classes: list[str] = Field(default_factory=list)


class MemoryRecallSelection(BaseModel):
    should_recall: bool = False
    selected_note_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    confidence: float = 0.0
    needs_verification: bool = False
    manifest_only: bool = False
    ignore_memory: bool = False


class MemoryRecallResult(BaseModel):
    selection: MemoryRecallSelection = Field(default_factory=MemoryRecallSelection)
    selected_headers: list[dict[str, object]] = Field(default_factory=list)
    selected_notes: list[dict[str, object]] = Field(default_factory=list)
    rendered_summary: str = ""
