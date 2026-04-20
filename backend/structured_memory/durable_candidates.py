from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from durable_write_policy import DurableCandidateDecision, evaluate_candidate_text

from .text_utils import normalize_storage_text

CandidateSourceKind = Literal["user_preference", "session_convention", "project_decision", "user_request"]
CandidateStatus = Literal["candidate", "accepted", "session_only", "rejected"]


@dataclass(slots=True)
class DurableCandidate:
    candidate_id: str
    source_kind: CandidateSourceKind
    title: str
    canonical_statement: str
    summary: str
    memory_type: str
    memory_class: str
    confidence: str
    rationale: str
    source_role: str
    source_excerpt: str
    retrieval_hints: list[str]
    status: CandidateStatus = "candidate"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "DurableCandidate":
        return cls(
            candidate_id=str(payload.get("candidate_id", "") or ""),
            source_kind=_normalize_source_kind(payload.get("source_kind", "project_decision")),
            title=str(payload.get("title", "") or ""),
            canonical_statement=str(payload.get("canonical_statement", "") or ""),
            summary=str(payload.get("summary", "") or ""),
            memory_type=str(payload.get("memory_type", "reference") or "reference"),
            memory_class=str(payload.get("memory_class", "work") or "work"),
            confidence=str(payload.get("confidence", "medium") or "medium"),
            rationale=str(payload.get("rationale", "") or ""),
            source_role=str(payload.get("source_role", "user") or "user"),
            source_excerpt=str(payload.get("source_excerpt", "") or ""),
            retrieval_hints=[
                str(item)
                for item in list(payload.get("retrieval_hints", []) or [])
                if str(item).strip()
            ],
            status=_normalize_status(payload.get("status", "candidate")),
        )

def evaluate_durable_candidate(candidate: DurableCandidate) -> DurableCandidateDecision:
    text = " ".join(
        [
            normalize_storage_text(candidate.title),
            normalize_storage_text(candidate.canonical_statement),
            normalize_storage_text(candidate.source_excerpt),
            normalize_storage_text(candidate.rationale),
        ]
    ).lower()
    return evaluate_candidate_text(
        text,
        source_kind=candidate.source_kind,
        fallback_type=candidate.memory_type,
        fallback_class=candidate.memory_class,
    )


def _normalize_source_kind(value: object) -> CandidateSourceKind:
    normalized = str(value or "project_decision")
    legacy_map = {
        "workflow_rule": "session_convention",
        "project_rule": "user_request",
        "decision": "project_decision",
    }
    normalized = legacy_map.get(normalized, normalized)
    if normalized in {"user_preference", "session_convention", "project_decision", "user_request"}:
        return normalized
    return "project_decision"


def _normalize_status(value: object) -> CandidateStatus:
    normalized = str(value or "candidate")
    if normalized in {"candidate", "accepted", "session_only", "rejected"}:
        return normalized
    return "candidate"
