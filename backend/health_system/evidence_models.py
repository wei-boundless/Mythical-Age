from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class EvidenceScore:
    causal_score: float = 0.0
    temporal_score: float = 0.0
    decision_score: float = 0.0
    recovery_score: float = 0.0
    reproduction_score: float = 0.0
    semantic_score: float = 0.0
    novelty_score: float = 0.0
    negative_score: float = 0.0

    @property
    def total(self) -> float:
        return round(
            self.causal_score
            + self.temporal_score
            + self.decision_score
            + self.recovery_score
            + self.reproduction_score
            + self.semantic_score
            + self.novelty_score
            + self.negative_score,
            4,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["total"] = self.total
        return payload


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    candidate_id: str
    source_kind: str
    source_ref: str
    subject_type: str
    subject_id: str
    event_type: str
    time_index: int
    summary: str
    raw_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    score: EvidenceScore = field(default_factory=EvidenceScore)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["score"] = self.score.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class RecoveryHandle:
    kind: str
    ref: str
    safe_to_resume: bool = False
    side_effect_replay_risk: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvidencePacket:
    packet_id: str
    question: str
    verdict: str
    confidence: float
    summary: str
    selected_evidence: tuple[EvidenceCandidate, ...] = ()
    excluded_evidence_summary: dict[str, Any] = field(default_factory=dict)
    recovery_handles: tuple[RecoveryHandle, ...] = ()
    test_handles: tuple[dict[str, Any], ...] = ()
    authority: str = "health_system.evidence_packet"

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "question": self.question,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "summary": self.summary,
            "selected_evidence": [item.to_dict() for item in self.selected_evidence],
            "excluded_evidence_summary": dict(self.excluded_evidence_summary),
            "recovery_handles": [item.to_dict() for item in self.recovery_handles],
            "test_handles": [dict(item) for item in self.test_handles],
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class TaskGraphRecoveryCandidate:
    candidate_id: str
    coordination_run_ref: str
    checkpoint_ref: str
    node_ref: str = ""
    edge_ref: str = ""
    stage_ref: str = ""
    risk: str = "unknown"
    reason: str = ""
    side_effect_replay_risk: str = "unknown"
    authority: str = "health_system.task_graph_recovery_candidate"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
