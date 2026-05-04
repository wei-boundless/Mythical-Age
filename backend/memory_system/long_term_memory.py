from __future__ import annotations

from pathlib import Path
from typing import Any

from .manifest_scan import MemoryHeader, scan_memory_headers

from .contracts import LongTermMemoryRecord, MemoryContextCandidate, MemoryWriteCandidate


class LongTermMemoryStoreAdapter:
    """Read-only durable-memory adapter for the new MemorySystem boundary."""

    def __init__(self, durable_root: str | Path) -> None:
        self.durable_root = Path(durable_root)
        self.durable_root.mkdir(parents=True, exist_ok=True)

    def load_records(self, *, limit: int = 200, runtime_visible_only: bool = True) -> tuple[LongTermMemoryRecord, ...]:
        headers = scan_memory_headers(self.durable_root, limit=limit)
        if runtime_visible_only:
            headers = [
                header
                for header in headers
                if header.eligible_for_injection and header.status == "active"
            ]
        return tuple(self._record_from_header(header) for header in headers)

    def context_candidates_from_recall_result(
        self,
        recall_result: Any,
        *,
        session_id: str = "",
        query: str = "",
    ) -> tuple[MemoryContextCandidate, ...]:
        selected_notes = list(getattr(recall_result, "selected_notes", []) or [])
        if not selected_notes and isinstance(recall_result, dict):
            selected_notes = list(recall_result.get("selected_notes", []) or [])
        candidates: list[MemoryContextCandidate] = []
        for index, note in enumerate(selected_notes):
            payload = dict(note or {}) if isinstance(note, dict) else self._note_to_dict(note)
            note_id = str(payload.get("note_id", "") or payload.get("filename", "") or f"note-{index}").strip()
            title = str(payload.get("title", "") or note_id).strip()
            canonical = str(payload.get("canonical_statement", "") or "").strip()
            summary = str(payload.get("summary", "") or "").strip()
            content = str(payload.get("content", "") or "").strip()
            preview = self._render_preview(title=title, canonical=canonical, summary=summary, content=content)
            if not preview:
                continue
            candidates.append(
                MemoryContextCandidate(
                    candidate_id=f"memory-context:{session_id or 'session'}:long-term:{note_id}",
                    memory_layer="long_term",
                    source="durable_memory.recall",
                    content_ref=str(payload.get("filename", "") or note_id),
                    rendered_preview=preview,
                    relevance=0.7,
                    confidence=_confidence_score(str(payload.get("confidence", "") or "")),
                    staleness="durable_memory_may_drift",
                    token_estimate=max(1, len(preview) // 4),
                    budget_class="optional",
                    requires_verification_before_use=True,
                    metadata={
                        "query": query,
                        "memory_type": str(payload.get("memory_type", "") or ""),
                        "memory_class": str(payload.get("memory_class", "") or ""),
                        "status": str(payload.get("status", "") or ""),
                        "verification_policy": "verify_file_function_flag_claims_against_current_state",
                    },
                )
            )
        return tuple(candidates)

    def propose_write_candidate(
        self,
        *,
        candidate_id: str,
        content: str,
        source_event_refs: tuple[str, ...] = (),
        stability: str = "unknown",
        gate_reason: str = "long_term_memory_write_requires_memory_gate",
    ) -> MemoryWriteCandidate:
        return MemoryWriteCandidate(
            candidate_id=candidate_id,
            target_layer="long_term",
            write_kind="propose_long_term_fact",
            content=content,
            source_event_refs=source_event_refs,
            stability=stability,
            gate_decision="pending",
            gate_reason=gate_reason,
            risk_flags=("requires_verification", "no_auto_commit"),
        )

    def write_candidates_from_notes(
        self,
        notes: list[Any] | tuple[Any, ...],
        *,
        source_event_refs: tuple[str, ...] = (),
        candidate_prefix: str = "memory-write:long-term",
    ) -> tuple[MemoryWriteCandidate, ...]:
        candidates: list[MemoryWriteCandidate] = []
        for index, note in enumerate(notes or ()):
            candidate = self.write_candidate_from_note(
                note,
                source_event_refs=source_event_refs,
                candidate_id=f"{candidate_prefix}:{_safe_id(str(getattr(note, 'slug', '') or index))}",
            )
            if candidate is not None:
                candidates.append(candidate)
        return tuple(candidates)

    def write_candidate_from_note(
        self,
        note: Any,
        *,
        source_event_refs: tuple[str, ...] = (),
        candidate_id: str = "",
    ) -> MemoryWriteCandidate | None:
        payload = self._note_to_dict(note)
        canonical = str(payload.get("canonical_statement", "") or "").strip()
        summary = str(payload.get("summary", "") or "").strip()
        title = str(payload.get("title", "") or "").strip()
        content = canonical or summary or title
        if not content:
            return None
        note_id = str(payload.get("note_id", "") or getattr(note, "slug", "") or title).strip()
        refs = tuple(item for item in source_event_refs if str(item).strip())
        source_session_id = str(getattr(note, "source_session_id", "") or "").strip()
        if source_session_id and source_session_id not in refs:
            refs = (*refs, source_session_id)
        return MemoryWriteCandidate(
            candidate_id=candidate_id or f"memory-write:long-term:{_safe_id(note_id or title)}",
            target_layer="long_term",
            write_kind="propose_long_term_fact",
            content=content,
            source_event_refs=refs,
            stability=str(getattr(note, "stability", "") or "unknown"),
            gate_decision="pending",
            gate_reason="long_term_memory_write_requires_memory_gate",
            risk_flags=("requires_verification", "no_auto_commit", "durable_memory_preview"),
            metadata={
                "title": title,
                "summary": summary,
                "memory_type": str(payload.get("memory_type", "") or ""),
                "memory_class": str(payload.get("memory_class", "") or ""),
                "confidence": str(payload.get("confidence", "") or ""),
                "source_message_excerpt": str(getattr(note, "source_message_excerpt", "") or ""),
                "legacy_note_slug": str(getattr(note, "slug", "") or ""),
            },
        )

    def _record_from_header(self, header: MemoryHeader) -> LongTermMemoryRecord:
        canonical = header.canonical_statement or header.summary or header.description or header.title
        return LongTermMemoryRecord(
            memory_id=header.note_id or header.filename,
            memory_type=_map_memory_type(header.memory_type, header.memory_class),
            canonical_statement=canonical,
            evidence_ref=header.filename,
            updated_at=header.updated_at,
            staleness_policy="verify_against_current_state_before_use",
            verification_policy="required_for_file_function_flag_claims",
            metadata={
                "filename": header.filename,
                "file_path": header.file_path,
                "source_memory_type": header.memory_type,
                "source_memory_class": header.memory_class,
                "status": header.status,
                "confidence": header.confidence,
                "eligible_for_injection": header.eligible_for_injection,
                "retrieval_hints": list(header.retrieval_hints),
            },
        )

    def _note_to_dict(self, note: Any) -> dict[str, object]:
        return {
            "note_id": str(getattr(note, "note_id", "") or getattr(note, "filename", "") or ""),
            "filename": str(getattr(note, "filename", "") or ""),
            "title": str(getattr(note, "title", "") or ""),
            "summary": str(getattr(note, "summary", "") or ""),
            "canonical_statement": str(getattr(note, "canonical_statement", "") or ""),
            "content": str(getattr(note, "content", "") or getattr(note, "body", "") or ""),
            "memory_type": str(getattr(note, "memory_type", "") or ""),
            "memory_class": str(getattr(note, "memory_class", "") or ""),
            "confidence": str(getattr(note, "confidence", "") or ""),
            "status": str(getattr(note, "status", "") or ""),
        }

    def _render_preview(self, *, title: str, canonical: str, summary: str, content: str) -> str:
        lines: list[str] = []
        if title:
            lines.append(f"### {title}")
        if canonical:
            lines.append(f"Canonical: {canonical}")
        elif summary:
            lines.append(f"Canonical: {summary}")
        if summary and summary != canonical:
            lines.append(f"Summary: {summary}")
        detail = " ".join(line.strip(" -#*\t") for line in content.splitlines() if line.strip())[:280].strip()
        if detail and detail not in {canonical, summary}:
            lines.append(f"Details: {detail}")
        return "\n".join(lines).strip()


def _map_memory_type(memory_type: str, memory_class: str) -> str:
    normalized_type = str(memory_type or "").strip().lower()
    normalized_class = str(memory_class or "").strip().lower()
    if normalized_type == "feedback":
        return "feedback_correction"
    if normalized_type == "reference":
        return "external_reference"
    if normalized_type == "user" or normalized_class == "preference":
        return "user_preference"
    return "project_convention"


def _confidence_score(confidence: str) -> float:
    normalized = str(confidence or "").strip().lower()
    if normalized == "high":
        return 0.82
    if normalized == "low":
        return 0.35
    if normalized == "medium":
        return 0.6
    return 0.5


def _safe_id(value: str) -> str:
    normalized = "".join(char if char.isalnum() or char in {"-", "_", ":"} else "-" for char in value.strip())
    return normalized.strip("-") or "candidate"
