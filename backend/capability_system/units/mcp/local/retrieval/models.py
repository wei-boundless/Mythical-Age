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
    hit_id: str | None = None
    doc_id: str | None = None
    block_id: str | None = None
    object_ref_id: str | None = None
    block_type: str | None = None
    section_path: tuple[str, ...] = ()
    score_breakdown: dict[str, float] = field(default_factory=dict)
    retrieval_modes: tuple[str, ...] = ()
    parser_backend: str = ""
    quality_flags: tuple[str, ...] = ()


