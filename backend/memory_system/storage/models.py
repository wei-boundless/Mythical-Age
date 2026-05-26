from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from .frontmatter import format_frontmatter
from .text_utils import normalize_storage_text

MemoryType = Literal["user", "feedback", "project", "reference"]
MemoryClass = Literal["work", "preference"]
MessageRole = Literal["system", "user", "assistant", "tool"]
TemporalFactRelation = Literal["supersedes", "merged_into", "invalidates", "refines", "conflicts_with"]
DEFAULT_DURABLE_SCHEMA_VERSION = "durable-memory.v3"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class MemoryNote:
    slug: str
    title: str
    summary: str
    body: str
    memory_type: MemoryType = "project"
    memory_class: MemoryClass = "work"
    tags: list[str] = field(default_factory=list)
    schema_version: str = DEFAULT_DURABLE_SCHEMA_VERSION
    canonical_statement: str = ""
    retrieval_hints: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    created_by: str = "manual"
    source_session_id: str = ""
    source_role: str = "user"
    source_message_excerpt: str = ""
    confidence: str = "medium"
    status: str = "active"
    last_confirmed_at: str = ""
    scope: str = "project"
    stability: str = "stable"
    source_kind: str = ""
    eligible_for_injection: str = "true"
    review_after: str = ""
    supersedes: str = ""
    invalidation_reason: str = ""

    def to_markdown(self) -> str:
        title = normalize_storage_text(self.title)
        summary = normalize_storage_text(self.summary)
        body = normalize_storage_text(self.body)
        tags = [normalize_storage_text(tag) for tag in self.tags if normalize_storage_text(tag)]
        canonical_statement = (
            normalize_storage_text(self.canonical_statement)
            or summary
            or title
        )
        retrieval_hints = [
            normalize_storage_text(hint)
            for hint in self.retrieval_hints
            if normalize_storage_text(hint)
        ]
        frontmatter = format_frontmatter(
            {
                "schema_version": normalize_storage_text(self.schema_version) or DEFAULT_DURABLE_SCHEMA_VERSION,
                "title": title,
                "summary": summary,
                "canonical_statement": canonical_statement,
                "type": self.memory_type,
                "memory_class": self.memory_class,
                "tags": tags,
                "retrieval_hints": retrieval_hints,
                "created_at": normalize_storage_text(self.created_at),
                "updated_at": self.updated_at,
                "created_by": normalize_storage_text(self.created_by),
                "source_session_id": normalize_storage_text(self.source_session_id),
                "source_role": normalize_storage_text(self.source_role),
                "source_message_excerpt": normalize_storage_text(self.source_message_excerpt),
                "confidence": normalize_storage_text(self.confidence),
                "status": normalize_storage_text(self.status),
                "last_confirmed_at": normalize_storage_text(self.last_confirmed_at),
                "scope": normalize_storage_text(self.scope),
                "stability": normalize_storage_text(self.stability),
                "source_kind": normalize_storage_text(self.source_kind),
                "eligible_for_injection": normalize_storage_text(self.eligible_for_injection),
                "review_after": normalize_storage_text(self.review_after),
                "supersedes": normalize_storage_text(self.supersedes),
                "invalidation_reason": normalize_storage_text(self.invalidation_reason),
            }
        )
        return f"{frontmatter}\n\n{body}\n"


@dataclass(slots=True)
class TemporalFactEdge:
    edge_id: str
    relation: TemporalFactRelation
    source_note_id: str
    target_note_id: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    actor: str = "memory_manager"
    reason: str = ""
    source_evidence_ref: str = ""
    source_note_sha256: str = ""
    target_note_sha256: str = ""
    before_sha256: str = ""
    after_sha256: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "durable_memory.temporal_fact_edge"

    def __post_init__(self) -> None:
        allowed = {"supersedes", "merged_into", "invalidates", "refines", "conflicts_with"}
        if self.relation not in allowed:
            raise ValueError(f"Unsupported temporal fact relation: {self.relation}")
        if not normalize_storage_text(self.source_note_id):
            raise ValueError("TemporalFactEdge requires source_note_id")
        if self.authority != "durable_memory.temporal_fact_edge":
            raise ValueError("TemporalFactEdge cannot carry runtime authority")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Message:
    role: MessageRole
    content: str
    meta: dict[str, Any] = field(default_factory=dict)
