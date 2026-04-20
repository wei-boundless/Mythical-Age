from __future__ import annotations

import re

from memory.write_models import DurableAdmissionDecision, DurableMutationPlan


class DurableMutationPlanner:
    def build_plan(self, decisions: list[DurableAdmissionDecision]) -> DurableMutationPlan:
        plan = DurableMutationPlan()
        for decision in decisions:
            candidate = dict(decision.normalized_candidate or {})
            if decision.decision == "accept":
                slug = _slugify(
                    str(candidate.get("title", "") or candidate.get("canonical_statement", "") or "memory-note")
                )
                candidate.setdefault("slug", slug)
                candidate.setdefault("note_id", slug)
                plan.notes_to_create.append(candidate)
                plan.actions.append({"action": "create_note", "note_id": slug})
            elif decision.decision == "update" and decision.matched_note_id:
                candidate.setdefault("note_id", decision.matched_note_id)
                plan.notes_to_update.append(candidate)
                plan.actions.append({"action": "update_note", "note_id": decision.matched_note_id})
        return plan


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", text.strip().lower()).strip("-")
    return slug or "memory-note"
