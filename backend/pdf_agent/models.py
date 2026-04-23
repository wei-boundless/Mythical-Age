from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


PDF_CANONICAL_PREFIX = "PDF_CANONICAL_RESULT::"


@dataclass(slots=True)
class PDFReadRequest:
    query: str
    path: str = ""
    mode: str = "document"
    max_chunks: int = 4


@dataclass(slots=True)
class PDFRouteDecision:
    requested_mode: str = "document"
    effective_mode: str = "document"
    target_page: int | None = None
    target_section: str = ""
    reason: str = ""


@dataclass(slots=True)
class PDFPreparedPage:
    page_number: int
    text: str
    section: str = ""
    body_text: str = ""
    quality_score: float = 0.0
    quality_flags: list[str] = field(default_factory=list)
    parse_strategy: str = "text_fast"
    parse_confidence: float = 0.0
    page_has_text: bool = True
    dominant_element_type: str = "body_text"
    excluded_ratio: float = 0.0
    body_chars: int = 0
    usable: bool = True


@dataclass(slots=True)
class PDFPreparedDocument:
    source: str
    pages: list[PDFPreparedPage] = field(default_factory=list)
    total_pages: int = 0
    readable_pages: int = 0
    usable_pages: int = 0
    parse_strategy: str = "text_fast"
    parse_confidence: float = 0.0


@dataclass(slots=True)
class PDFCanonicalEvidence:
    page_number: int
    score: float = 0.0
    snippet: str = ""


@dataclass(slots=True)
class PDFCanonicalResult:
    status: str
    source: str = ""
    requested_mode: str = "document"
    effective_mode: str = "document"
    summary: str = ""
    degraded_reason: str = ""
    pages: list[int] = field(default_factory=list)
    evidence: list[PDFCanonicalEvidence] = field(default_factory=list)
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok" and bool(self.summary.strip())

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    def to_tool_output(self) -> str:
        return f"{PDF_CANONICAL_PREFIX}{json.dumps(self.to_payload(), ensure_ascii=False, separators=(',', ':'))}"

    @classmethod
    def from_tool_output(cls, text: str) -> "PDFCanonicalResult | None":
        normalized = str(text or "").strip()
        if not normalized.startswith(PDF_CANONICAL_PREFIX):
            return None
        payload_text = normalized[len(PDF_CANONICAL_PREFIX) :].strip()
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            return None
        evidence = [
            PDFCanonicalEvidence(
                page_number=int(item.get("page_number", 0) or 0),
                score=float(item.get("score", 0.0) or 0.0),
                snippet=str(item.get("snippet", "") or ""),
            )
            for item in list(payload.get("evidence") or [])
            if int(item.get("page_number", 0) or 0) > 0
        ]
        return cls(
            status=str(payload.get("status", "") or ""),
            source=str(payload.get("source", "") or ""),
            requested_mode=str(payload.get("requested_mode", "document") or "document"),
            effective_mode=str(payload.get("effective_mode", "document") or "document"),
            summary=str(payload.get("summary", "") or ""),
            degraded_reason=str(payload.get("degraded_reason", "") or ""),
            pages=[int(page) for page in list(payload.get("pages") or []) if int(page or 0) > 0],
            evidence=evidence,
            error=str(payload.get("error", "") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )
