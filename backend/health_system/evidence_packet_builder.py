from __future__ import annotations

from typing import Any

from .evidence_models import EvidenceCandidate, EvidencePacket, RecoveryHandle


def build_evidence_packet(
    *,
    question: str,
    candidates: list[EvidenceCandidate],
    verdict: str = "unknown",
    confidence: float = 0.0,
    summary: str = "",
    recovery_handles: list[RecoveryHandle] | None = None,
    test_handles: list[dict[str, Any]] | None = None,
    selected_limit: int = 8,
) -> EvidencePacket:
    ranked = sorted(candidates, key=lambda item: item.score.total, reverse=True)
    selected = tuple(ranked[: max(0, selected_limit)])
    excluded = ranked[max(0, selected_limit):]
    selected_ids = {item.candidate_id for item in selected}
    excluded_summary = {
        "candidate_count": len(candidates),
        "selected_count": len(selected),
        "excluded_count": len(excluded),
        "excluded_source_kinds": _count_items([item.source_kind for item in excluded]),
        "excluded_event_types": _count_items([item.event_type for item in excluded]),
        "selected_ids": list(selected_ids),
    }
    return EvidencePacket(
        packet_id=_packet_id(question, selected),
        question=question,
        verdict=verdict,
        confidence=round(float(confidence), 4),
        summary=summary or _default_summary(question, selected),
        selected_evidence=selected,
        excluded_evidence_summary=excluded_summary,
        recovery_handles=tuple(recovery_handles or ()),
        test_handles=tuple(dict(item) for item in list(test_handles or [])),
    )


def _packet_id(question: str, selected: tuple[EvidenceCandidate, ...]) -> str:
    subject = selected[0].subject_id if selected else "empty"
    return f"evpkt:{_slug(question)}:{_slug(subject)}"


def _default_summary(question: str, selected: tuple[EvidenceCandidate, ...]) -> str:
    if not selected:
        return question.strip()
    top = selected[0]
    return f"{question.strip()}；首要证据：{top.summary}"


def _slug(value: str) -> str:
    chars: list[str] = []
    for char in str(value or ""):
        if char.isalnum():
            chars.append(char.lower())
        else:
            chars.append("-")
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "item"


def _count_items(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


