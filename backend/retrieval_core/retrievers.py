from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RetrievalRequest:
    query: str
    top_k: int = 5
    query_mode: str = "semantic_lookup"
    collections: tuple[str, ...] = field(default_factory=tuple)
    filters: dict[str, Any] = field(default_factory=dict)
