from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class MemoryCompactionPreview:
    """Preview-only context compaction result for runtime adapters."""

    session_id: str
    pressure_level: str = "normal"
    compaction_strategy: str = "memory_system_preview_only"
    compacted: bool = False
    preview_only: bool = True
    authority: str = "memory_compaction_preview"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.preview_only:
            raise ValueError("MemoryCompactionPreview must remain preview_only")
        if self.authority != "memory_compaction_preview":
            raise ValueError("MemoryCompactionPreview cannot carry runtime authority")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_memory_compaction_preview(
    *,
    session_id: str,
    history_count: int = 0,
    context_candidate_count: int = 0,
    restore_candidate_count: int = 0,
) -> MemoryCompactionPreview:
    return MemoryCompactionPreview(
        session_id=session_id,
        diagnostics={
            "history_count": int(history_count or 0),
            "context_candidate_count": int(context_candidate_count or 0),
            "restore_candidate_count": int(restore_candidate_count or 0),
            "legacy_compactor_used": False,
        },
    )
