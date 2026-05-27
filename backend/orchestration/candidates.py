from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Literal


CandidateAuthority = Literal["candidate_only"]


@dataclass(slots=True, frozen=True)
class CandidateEnvelope:
    """Standard envelope for non-authoritative planning and recovery signals."""

    candidate_id: str
    producer: str
    candidate_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    reasons: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, Any] = field(default_factory=dict)
    authority: CandidateAuthority = "candidate_only"

    def __post_init__(self) -> None:
        if self.authority != "candidate_only":
            raise ValueError("CandidateEnvelope cannot carry decision authority")
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("CandidateEnvelope.confidence must be between 0.0 and 1.0")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass(slots=True)
class CandidateSet:
    """Collection passed into the control kernel before arbitration."""

    candidates: list[CandidateEnvelope] = field(default_factory=list)

    def add(self, candidate: CandidateEnvelope) -> None:
        if candidate.authority != "candidate_only":
            raise ValueError("CandidateSet only accepts candidate_only envelopes")
        self.candidates.append(candidate)

    def extend(self, candidates: Iterable[CandidateEnvelope]) -> None:
        for candidate in candidates:
            self.add(candidate)

    def by_type(self, candidate_type: str) -> list[CandidateEnvelope]:
        return [item for item in self.candidates if item.candidate_type == candidate_type]

    def to_list(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.candidates]


