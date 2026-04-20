from __future__ import annotations

from typing import Iterable

from memory.write_models import DurableMutationPlan


class DurableStoreWriter:
    def __init__(self, memory_manager) -> None:
        self.memory_manager = memory_manager

    def plan_notes(self, plan: DurableMutationPlan):
        notes = []
        for payload in list(plan.notes_to_create) + list(plan.notes_to_update):
            notes.append(self._note_from_payload(payload))
        return notes

    def apply(self, plan: DurableMutationPlan) -> dict[str, object]:
        notes = self.plan_notes(plan)
        saved: list[str] = []
        for note in notes:
            self.memory_manager.save_note(note)
            saved.append(note.slug)
        return {"saved": saved, "count": len(saved)}

    def save_notes(self, notes: Iterable[object]):
        saved = []
        for note in notes:
            self.memory_manager.save_note(note)
            saved.append(note)
        return saved

    def _note_from_payload(self, payload: dict[str, object]):
        from structured_memory.models import MemoryNote, utc_now_iso

        title = str(payload.get("title", "") or payload.get("canonical_statement", "") or "Memory Note").strip()
        canonical = str(payload.get("canonical_statement", "") or title).strip()
        why = str(payload.get("why", "") or "Durable memory candidate").strip()
        how_to_apply = str(payload.get("how_to_apply", "") or "").strip()
        evidence = str(payload.get("evidence_excerpt", "") or canonical).strip()
        body_lines = [
            f"Canonical: {canonical}",
            f"Why: {why}",
        ]
        if how_to_apply:
            body_lines.append(f"How to apply: {how_to_apply}")
        body_lines.append(f"Evidence: {evidence}")
        now = utc_now_iso()
        note_id = str(payload.get("note_id", "") or payload.get("slug", "") or self.memory_manager.slugify(title))
        retrieval_hints = [
            item
            for item in [
                title,
                canonical,
                *list(payload.get("retrieval_hints", []) or []),
            ]
            if str(item or "").strip()
        ]
        return MemoryNote(
            slug=note_id,
            title=title,
            summary=str(payload.get("non_obvious_value", "") or canonical)[:120],
            canonical_statement=canonical,
            body="\n".join(body_lines),
            memory_type=str(payload.get("memory_type", "project") or "project"),
            memory_class=str(payload.get("memory_class", "work") or "work"),
            tags=[
                str(payload.get("memory_type", "project") or "project"),
                str(payload.get("memory_class", "work") or "work"),
            ],
            retrieval_hints=[str(item) for item in retrieval_hints[:8]],
            created_by="durable_write_agent",
            source_role=str(payload.get("source_scope", "assistant") or "assistant"),
            source_message_excerpt=evidence[:160],
            confidence="medium",
            created_at=now,
            updated_at=now,
        )
