from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ParsedChunk:
    text: str
    source: str
    modality: str
    page: int | None = None
    section: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RetrievalHit:
    text: str
    source: str
    modality: str
    score: float
    page: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
