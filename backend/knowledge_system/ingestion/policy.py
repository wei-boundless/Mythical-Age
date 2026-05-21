from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ChunkingPolicy:
    target_tokens: int = 320
    soft_max_tokens: int = 480
    hard_max_tokens: int = 640
    min_tokens: int = 96
    overlap_tokens: int = 64
    split_by_sentence: bool = True
    preserve_page_boundary: bool = True
    preserve_section_boundary: bool = True
    preserve_object_boundary: bool = True

    @classmethod
    def from_settings(cls, settings: Any) -> "ChunkingPolicy":
        target = _positive_int(getattr(settings, "rag_chunk_size", None), cls.target_tokens)
        overlap = _non_negative_int(getattr(settings, "rag_chunk_overlap", None), cls.overlap_tokens)
        soft_max = max(target, int(round(target * 1.5)))
        hard_max = max(soft_max, int(round(target * 2.0)))
        min_tokens = max(24, min(128, int(round(target * 0.3))))
        return cls(
            target_tokens=target,
            soft_max_tokens=soft_max,
            hard_max_tokens=hard_max,
            min_tokens=min_tokens,
            overlap_tokens=min(overlap, max(target - 1, 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_tokens": self.target_tokens,
            "soft_max_tokens": self.soft_max_tokens,
            "hard_max_tokens": self.hard_max_tokens,
            "min_tokens": self.min_tokens,
            "overlap_tokens": self.overlap_tokens,
            "split_by_sentence": self.split_by_sentence,
            "preserve_page_boundary": self.preserve_page_boundary,
            "preserve_section_boundary": self.preserve_section_boundary,
            "preserve_object_boundary": self.preserve_object_boundary,
        }


@dataclass(frozen=True, slots=True)
class IndexUnitPolicy:
    include_document_summary: bool = True
    include_parent_sections: bool = True
    include_page_summaries: bool = True
    include_object_blocks: bool = True
    include_leaf_blocks: bool = True


@dataclass(frozen=True, slots=True)
class ParserPolicy:
    prefer_page_aware_pdf: bool = True
    markdown_fallback_allowed: bool = True


@dataclass(frozen=True, slots=True)
class ChunkPlan:
    document_id: str
    source_path: str
    source_type: str
    chunking_policy: dict[str, Any]
    planned_units: int
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "source_path": self.source_path,
            "source_type": self.source_type,
            "chunking_policy": dict(self.chunking_policy),
            "planned_units": self.planned_units,
            "warnings": list(self.warnings),
        }


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return int(default)
    return parsed if parsed > 0 else int(default)


def _non_negative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return int(default)
    return parsed if parsed >= 0 else int(default)
