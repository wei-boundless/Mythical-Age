from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    ephemeral_system_messages: list[str] = field(default_factory=list)
    explicit_subtasks: list[dict[str, Any]] = field(default_factory=list)
    search_policy: list[str] | None = None
    task_selection: dict[str, Any] = field(default_factory=dict)
    model_selection: dict[str, Any] = field(default_factory=dict)
    image_generation: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class QueryResult:
    content: str
    segments: list[dict[str, Any]] = field(default_factory=list)


