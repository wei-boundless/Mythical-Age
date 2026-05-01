from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class MemoryCompactionResult:
    """Read-only context compaction result for runtime adapters."""

    session_id: str
    pressure_level: str = "normal"
    compaction_strategy: str = "none"
    compacted: bool = False
    read_only: bool = True
    authority: str = "memory_compaction_result"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.read_only:
            raise ValueError("MemoryCompactionResult must remain read_only")
        if self.authority != "memory_compaction_result":
            raise ValueError("MemoryCompactionResult cannot carry runtime authority")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_memory_compaction_result(
    *,
    session_id: str,
    history_count: int = 0,
    context_candidate_count: int = 0,
    restore_candidate_count: int = 0,
) -> MemoryCompactionResult:
    return MemoryCompactionResult(
        session_id=session_id,
        diagnostics={
            "history_count": int(history_count or 0),
            "context_candidate_count": int(context_candidate_count or 0),
            "restore_candidate_count": int(restore_candidate_count or 0),
            "legacy_compactor_used": False,
        },
    )
