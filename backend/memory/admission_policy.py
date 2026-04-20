from __future__ import annotations

from memory.manifest_scan import MemoryHeader
from memory.write_models import DurableAdmissionDecision, DurableCandidateDraft
from understanding.memory_policy import evaluate_memory_write


class DurableAdmissionPolicy:
    def evaluate(
        self,
        draft: DurableCandidateDraft,
        existing_headers: list[MemoryHeader],
    ) -> DurableAdmissionDecision:
        statement = (draft.canonical_statement or "").strip()
        decision = evaluate_memory_write(statement)
        if decision.action != "durable_fact" or decision.memory_type is None or decision.memory_class is None:
            return DurableAdmissionDecision(
                decision="reject",
                reason=decision.reason,
                normalized_candidate=draft.model_dump(),
            )

        matched = self._find_duplicate(statement, decision.memory_type, decision.memory_class, existing_headers)
        if matched is not None:
            normalized = draft.model_copy(
                update={
                    "memory_type": decision.memory_type,
                    "memory_class": decision.memory_class,
                    "target_note_id": matched.note_id,
                    "proposed_action": "update",
                }
            )
            return DurableAdmissionDecision(
                decision="update",
                reason="duplicate_existing",
                normalized_candidate=normalized.model_dump(),
                matched_note_id=matched.note_id,
            )

        normalized = draft.model_copy(
            update={
                "memory_type": decision.memory_type,
                "memory_class": decision.memory_class,
                "proposed_action": "create",
            }
        )
        return DurableAdmissionDecision(
            decision="accept",
            reason="stable_and_admissible",
            normalized_candidate=normalized.model_dump(),
        )

    def evaluate_many(
        self,
        drafts: list[DurableCandidateDraft],
        existing_headers: list[MemoryHeader],
    ) -> list[DurableAdmissionDecision]:
        return [self.evaluate(draft, existing_headers) for draft in drafts]

    def _find_duplicate(
        self,
        statement: str,
        memory_type: str,
        memory_class: str,
        existing_headers: list[MemoryHeader],
    ) -> MemoryHeader | None:
        normalized = statement.strip().lower()
        for header in existing_headers:
            if header.memory_type != memory_type or header.memory_class != memory_class:
                continue
            canonical = (header.canonical_statement or header.summary or header.description).strip().lower()
            if canonical and canonical == normalized:
                return header
        return None
