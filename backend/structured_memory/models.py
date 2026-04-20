from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from .frontmatter import format_frontmatter
from .text_utils import normalize_storage_text

MemoryType = Literal["user", "feedback", "project", "reference"]
MemoryClass = Literal["work", "preference"]
MessageRole = Literal["system", "user", "assistant", "tool"]
DEFAULT_DURABLE_SCHEMA_VERSION = "durable-memory.v2"


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
            }
        )
        return f"{frontmatter}\n\n{body}\n"


@dataclass(slots=True)
class Message:
    role: MessageRole
    content: str
    meta: dict[str, Any] = field(default_factory=dict)
