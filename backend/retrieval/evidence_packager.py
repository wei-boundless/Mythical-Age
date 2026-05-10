from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    text: str
    source_ref: str
    page: int | None = None
    doc_id: str = ""
    retrieval_reason: str = ""
    confidence: str = "medium"
    allowed_use: str = "answer_grounding"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "source_ref": self.source_ref,
            "page": self.page,
            "doc_id": self.doc_id,
            "retrieval_reason": self.retrieval_reason,
            "confidence": self.confidence,
            "allowed_use": self.allowed_use,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class EvidencePack:
    query: str
    answer_contract: str
    evidence_items: tuple[EvidenceItem, ...] = ()
    trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "answer_contract": self.answer_contract,
            "evidence_items": [item.to_dict() for item in self.evidence_items],
            "trace": dict(self.trace),
        }


def build_evidence_pack(
    *,
    query: str,
    results: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    retrieval_plan: dict[str, Any] | None = None,
) -> EvidencePack:
    items = tuple(_evidence_item(row) for row in results)
    trace = {
        "retrieval_plan": dict(retrieval_plan or {}),
        "evidence_count": len(items),
    }
    return EvidencePack(
        query=str(query or ""),
        answer_contract=(
            "以下是与你当前问题相关的本地资料证据。"
            "只能基于这些证据回答；如果证据不足，需要明确说明不足。"
            "每条证据包含来源、页码和检索理由。"
        ),
        evidence_items=items,
        trace=trace,
    )


def _evidence_item(row: dict[str, Any]) -> EvidenceItem:
    metadata = dict(row.get("metadata", {}) or {})
    source = str(row.get("source", "") or metadata.get("source_path", "") or "")
    page = _optional_int(row.get("page", metadata.get("page")))
    source_ref = f"{source}#page={page}" if source and page is not None else source
    score = _float(row.get("score", row.get("retrieval_score", 0.0)))
    return EvidenceItem(
        text=str(row.get("text", "") or ""),
        source_ref=source_ref,
        page=page,
        doc_id=str(metadata.get("doc_id", "") or row.get("doc_id", "") or ""),
        retrieval_reason=_retrieval_reason(row, metadata),
        confidence=_confidence(score),
        metadata={
            "score": score,
            "collection": row.get("collection"),
            "result_granularity": row.get("result_granularity") or metadata.get("result_granularity"),
            "retrieval_stage": metadata.get("retrieval_stage"),
            "retrieval_modes": list(metadata.get("retrieval_modes", []) or []),
            "candidate_graph_bucket_kind": metadata.get("candidate_graph_bucket_kind"),
        },
    )


def _retrieval_reason(row: dict[str, Any], metadata: dict[str, Any]) -> str:
    if metadata.get("candidate_graph_bucket_kind"):
        return f"candidate_graph:{metadata['candidate_graph_bucket_kind']}"
    if row.get("reason"):
        return str(row["reason"])
    if metadata.get("retrieval_stage"):
        return f"retrieval_stage:{metadata['retrieval_stage']}"
    return "retrieval_result"


def _confidence(score: float) -> str:
    if score >= 0.7:
        return "high"
    if score >= 0.35:
        return "medium"
    return "low"


def _optional_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
