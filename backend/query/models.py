from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from understanding import MemoryIntent, QueryUnderstanding


@dataclass(frozen=True, slots=True)
class QueryEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, **self.payload}


@dataclass(frozen=True, slots=True)
class QueryRequest:
    session_id: str
    message: str
    history: list[dict[str, Any]] | None = None


@dataclass(slots=True)
class QueryPlan:
    session_id: str
    message: str
    history: list[dict[str, Any]]
    subqueries: list[str]
    memory_intent: MemoryIntent
    query_understanding: QueryUnderstanding
    active_skill: Any | None = None


@dataclass(slots=True)
class QueryContext:
    session_id: str
    history: list[dict[str, Any]]
    augmented_history: list[dict[str, Any]]
    context_compaction: dict[str, Any] | None = None
    retrieval_results: list[dict[str, Any]] = field(default_factory=list)
    relevant_memory_notes: list[Any] | None = None


@dataclass(slots=True)
class QueryResult:
    content: str
    segments: list[dict[str, Any]] = field(default_factory=list)
