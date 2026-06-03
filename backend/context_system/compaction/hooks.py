from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


CompactTrigger = Literal["auto", "manual", "context_overflow", "preview"]


@dataclass(frozen=True, slots=True)
class PreCompactHookRequest:
    request_id: str
    session_id: str = ""
    turn_id: str = ""
    task_run_id: str = ""
    task_environment_id: str = ""
    trigger: CompactTrigger = "preview"
    reason: str = ""
    token_before: int = 0
    planned_strategy: str = "none"
    pressure_level: str = "normal"
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "context_system.compaction.pre_compact_hook_request"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CompactHookDecision:
    allowed: bool = True
    reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "context_system.compaction.hook_decision"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CompactBoundaryReceipt:
    receipt_id: str
    request_id: str
    session_id: str = ""
    turn_id: str = ""
    task_run_id: str = ""
    task_environment_id: str = ""
    trigger: CompactTrigger = "preview"
    reason: str = ""
    token_before: int = 0
    token_after: int = 0
    planned_strategy: str = "none"
    applied_strategy: str = "none"
    pressure_level: str = "normal"
    preserved_segments: tuple[str, ...] = ()
    dropped_segments: tuple[str, ...] = ()
    summarized_segments: tuple[str, ...] = ()
    replaced_message_count: int = 0
    preserved_recent_count: int = 0
    summary_source: str = ""
    invariant_status: str = "not_checked"
    blocked: bool = False
    block_reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "context_system.compaction.boundary_receipt"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["preserved_segments"] = list(self.preserved_segments)
        payload["dropped_segments"] = list(self.dropped_segments)
        payload["summarized_segments"] = list(self.summarized_segments)
        return payload
