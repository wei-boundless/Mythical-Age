from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from .context_compactor import CompactResult
from structured_memory.models import Message

PressureLevel = Literal["normal", "warning", "microcompact", "full_compact"]


@dataclass(slots=True)
class ContextBudget:
    total: int = 0
    reserved_output: int = 0
    available_context: int = 0
    static: int = 0
    active_process: int = 0
    hot_truth: int = 0
    warm_snapshots: int = 0
    durable: int = 0
    retrieval: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(slots=True)
class ContextPackage:
    pressure_level: PressureLevel = "normal"
    budget: ContextBudget = field(default_factory=ContextBudget)
    sections: dict[str, list[str]] = field(default_factory=dict)
    selected_sections: list[str] = field(default_factory=list)
    dropped_sections: list[str] = field(default_factory=list)
    dropped_items: list[str] = field(default_factory=list)
    rebuild_reason: str = "unknown"
    compaction_strategy: str = "none"
    compaction_decisions: list[str] = field(default_factory=list)
    token_accounting: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "pressure_level": self.pressure_level,
            "budget": self.budget.to_dict(),
            "sections": self.sections,
            "selected_sections": self.selected_sections,
            "dropped_sections": self.dropped_sections,
            "dropped_items": self.dropped_items,
            "rebuild_reason": self.rebuild_reason,
            "compaction_strategy": self.compaction_strategy,
            "compaction_decisions": self.compaction_decisions,
            "token_accounting": self.token_accounting,
        }


@dataclass(slots=True)
class ContextControllerResult:
    messages: list[Message]
    package: ContextPackage
    compact_result: CompactResult
