from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .contracts import MemoryWriteCandidate


@dataclass(slots=True, frozen=True)
class MemoryGateDecision:
    """Preview-only memory writeback gate.

    MemorySystem may produce write candidates, but it cannot commit them. This
    gate is intentionally fail-closed until orchestration/commit governance is
    allowed to grant real write authority.
    """

    gate_id: str
    write_candidates: tuple[MemoryWriteCandidate, ...] = ()
    status: str = "blocked"
    reason: str = "preview_only"
    memory_write_allowed: bool = False
    commit_allowed: bool = False
    preview_only: bool = True
    authority: str = "memory_gate_preview"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != "memory_gate_preview":
            raise ValueError("MemoryGateDecision cannot carry commit authority")
        if self.status != "blocked":
            raise ValueError("MemoryGateDecision must stay blocked")
        if self.memory_write_allowed:
            raise ValueError("MemoryGateDecision cannot allow memory writes")
        if self.commit_allowed:
            raise ValueError("MemoryGateDecision cannot allow commits")
        if not self.preview_only:
            raise ValueError("MemoryGateDecision must remain preview_only")
        for candidate in self.write_candidates:
            if candidate.authority != "candidate_only":
                raise ValueError("MemoryGateDecision only accepts candidate-only write candidates")
            if candidate.gate_decision == "accepted":
                raise ValueError("MemoryGateDecision cannot accept memory write candidates")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["write_candidates"] = [candidate.to_dict() for candidate in self.write_candidates]
        return payload


def build_blocked_memory_gate_preview(
    write_candidates: tuple[MemoryWriteCandidate, ...] | list[MemoryWriteCandidate],
    *,
    gate_id: str = "memory-gate:preview",
    reason: str = "memory_write_requires_commit_gate",
) -> MemoryGateDecision:
    candidates = tuple(write_candidates or ())
    return MemoryGateDecision(
        gate_id=gate_id,
        write_candidates=candidates,
        status="blocked",
        reason=reason,
        memory_write_allowed=False,
        commit_allowed=False,
        preview_only=True,
        diagnostics={
            "preview_only": True,
            "fail_closed": True,
            "write_candidate_count": len(candidates),
            "memory_write_allowed": False,
            "commit_allowed": False,
            "blocked_candidate_ids": [candidate.candidate_id for candidate in candidates],
        },
    )
