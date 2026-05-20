from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ContinuationCandidate:
    candidate_id: str
    target_kind: str
    source_kind: str
    file_kind: str = ""
    identity: str = ""
    source: str = ""
    score: float = 0.0
    compatible: bool = True
    conflict_reasons: tuple[str, ...] = ()
    binding_payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "continuation.candidate"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["conflict_reasons"] = list(self.conflict_reasons)
        return payload


@dataclass(frozen=True, slots=True)
class ContinuationDecision:
    decision_kind: str = "none"
    selected_candidate_id: str = ""
    selected_target_kind: str = ""
    source_kind: str = ""
    followup_target_kind: str = ""
    followup_scope: str = ""
    followup_target_refs: tuple[str, ...] = ()
    constraint_policy: str = ""
    active_bindings: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    reason: str = ""
    rejected_candidate_ids: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "continuation.decision"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["followup_target_refs"] = list(self.followup_target_refs)
        payload["rejected_candidate_ids"] = list(self.rejected_candidate_ids)
        return payload
