from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .working_memory_models import WorkingMemoryItem
from .working_memory_service import WorkingMemoryService


PROMOTION_CANDIDATE_KINDS = {
    "promotion_candidate",
    "story_bible_delta",
    "character_state_delta",
    "world_state_delta",
    "style_constraint",
    "decision_record",
}
ARTIFACT_KINDS = {
    "artifact_ref",
    "chapter_draft",
    "scene_draft",
    "draft_artifact",
}
CONFLICT_KINDS = {
    "conflict_flag",
    "continuity_conflict",
}
RETENTION_KINDS = {
    "failure_reflection",
    "retry_guidance",
    "rejected_attempt_summary",
}


@dataclass(frozen=True, slots=True)
class WorkingMemoryFinalizationResult:
    task_run_id: str
    finalized_count: int
    archived_count: int
    discarded_count: int
    promotion_candidate_count: int
    artifact_candidate_count: int
    unresolved_conflict_count: int
    unchanged_count: int
    archive_report_path: str
    item_actions: tuple[dict[str, Any], ...]
    authority: str = "working_memory.finalizer"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_run_id": self.task_run_id,
            "finalized_count": self.finalized_count,
            "archived_count": self.archived_count,
            "discarded_count": self.discarded_count,
            "promotion_candidate_count": self.promotion_candidate_count,
            "artifact_candidate_count": self.artifact_candidate_count,
            "unresolved_conflict_count": self.unresolved_conflict_count,
            "unchanged_count": self.unchanged_count,
            "archive_report_path": self.archive_report_path,
            "item_actions": [dict(item) for item in self.item_actions],
            "authority": self.authority,
        }


class WorkingMemoryFinalizer:
    def __init__(self, working_memory: WorkingMemoryService) -> None:
        self.working_memory = working_memory

    def finalize_task_run(
        self,
        task_run_id: str,
        *,
        actor_id: str = "runloop",
        terminal_reason: str = "completed",
        policy: dict[str, Any] | None = None,
    ) -> WorkingMemoryFinalizationResult:
        task_run = str(task_run_id or "").strip()
        if not task_run:
            raise ValueError("WorkingMemoryFinalizer requires task_run_id")
        finalization_policy = dict(policy or {})
        items = self.working_memory.query_items(task_run_id=task_run, limit=1000)
        actions: list[dict[str, Any]] = []
        counts = {
            "archived": 0,
            "discarded": 0,
            "promotion_candidate": 0,
            "artifact_candidate": 0,
            "unresolved_conflict": 0,
            "unchanged": 0,
        }
        for item in items:
            action = self._finalize_item(
                item,
                actor_id=actor_id,
                terminal_reason=terminal_reason,
                policy=finalization_policy,
            )
            counts[action["action"]] = counts.get(action["action"], 0) + 1
            actions.append(action)
        report = WorkingMemoryFinalizationResult(
            task_run_id=task_run,
            finalized_count=len(actions),
            archived_count=counts["archived"],
            discarded_count=counts["discarded"],
            promotion_candidate_count=counts["promotion_candidate"],
            artifact_candidate_count=counts["artifact_candidate"],
            unresolved_conflict_count=counts["unresolved_conflict"],
            unchanged_count=counts["unchanged"],
            archive_report_path="",
            item_actions=tuple(actions),
        )
        report_path = self.working_memory.store.write_archive_report(task_run, report.to_dict())
        return WorkingMemoryFinalizationResult(
            task_run_id=report.task_run_id,
            finalized_count=report.finalized_count,
            archived_count=report.archived_count,
            discarded_count=report.discarded_count,
            promotion_candidate_count=report.promotion_candidate_count,
            artifact_candidate_count=report.artifact_candidate_count,
            unresolved_conflict_count=report.unresolved_conflict_count,
            unchanged_count=report.unchanged_count,
            archive_report_path=str(report_path),
            item_actions=report.item_actions,
        )

    def _finalize_item(
        self,
        item: WorkingMemoryItem,
        *,
        actor_id: str,
        terminal_reason: str,
        policy: dict[str, Any],
    ) -> dict[str, Any]:
        base = {
            "work_memory_id": item.work_memory_id,
            "kind": item.kind,
            "memory_semantics": item.memory_semantics,
            "before_status": item.status,
            "before_promotion_state": item.promotion_state,
            "owner_node_id": item.owner_node_id,
            "node_run_id": item.node_run_id,
        }
        if item.status in {"archived", "promoted", "discarded"}:
            return {**base, "action": "unchanged", "after_status": item.status, "after_promotion_state": item.promotion_state}

        if item.status == "conflicted" or item.memory_semantics == "conflict" or item.kind in CONFLICT_KINDS:
            updated = self.working_memory.store.update_item_lifecycle(
                item.work_memory_id,
                status="conflicted",
                promotion_state="promoted_to_health_issue" if policy.get("mark_conflicts_for_health_review", True) else item.promotion_state,
                actor_id=actor_id,
                metadata={"finalization_terminal_reason": terminal_reason, "finalization_action": "unresolved_conflict"},
                event_type="finalized_unresolved_conflict",
            )
            return {**base, "action": "unresolved_conflict", "after_status": updated.status, "after_promotion_state": updated.promotion_state}

        if item.kind in RETENTION_KINDS or item.memory_semantics == "reflection":
            keep_reflection = bool(policy.get("keep_failure_reflection", True))
            updated = self.working_memory.store.update_item_lifecycle(
                item.work_memory_id,
                status="archived" if keep_reflection else "discarded",
                promotion_state=item.promotion_state,
                actor_id=actor_id,
                metadata={
                    "finalization_terminal_reason": terminal_reason,
                    "finalization_action": "archived" if keep_reflection else "discarded",
                    "retention_rule": "retry_memory_rules.keep_failure_reflection",
                    "run_attempt_id": item.run_attempt_id,
                },
                event_type="finalized_retry_memory_retained" if keep_reflection else "finalized_retry_memory_discarded",
            )
            return {
                **base,
                "action": "archived" if keep_reflection else "discarded",
                "after_status": updated.status,
                "after_promotion_state": updated.promotion_state,
            }

        if item.promotion_state in {"candidate", "needs_review", "approved"} or item.kind in PROMOTION_CANDIDATE_KINDS:
            updated = self.working_memory.store.update_item_lifecycle(
                item.work_memory_id,
                status="archived",
                promotion_state="needs_review" if item.promotion_state in {"", "not_applicable"} else item.promotion_state,
                actor_id=actor_id,
                metadata={"finalization_terminal_reason": terminal_reason, "finalization_action": "promotion_candidate"},
                event_type="finalized_promotion_candidate",
            )
            return {**base, "action": "promotion_candidate", "after_status": updated.status, "after_promotion_state": updated.promotion_state}

        if item.kind in ARTIFACT_KINDS or item.memory_semantics == "draft_artifact" or item.artifact_refs:
            updated = self.working_memory.store.update_item_lifecycle(
                item.work_memory_id,
                status="archived",
                promotion_state="promoted_to_artifact_store" if item.artifact_refs else item.promotion_state,
                actor_id=actor_id,
                metadata={"finalization_terminal_reason": terminal_reason, "finalization_action": "artifact_candidate"},
                event_type="finalized_artifact_candidate",
            )
            return {**base, "action": "artifact_candidate", "after_status": updated.status, "after_promotion_state": updated.promotion_state}

        if item.status in {"draft", "proposed"}:
            updated = self.working_memory.store.update_item_lifecycle(
                item.work_memory_id,
                status="discarded" if policy.get("discard_unaccepted_candidates", True) else "archived",
                actor_id=actor_id,
                metadata={"finalization_terminal_reason": terminal_reason, "finalization_action": "discarded"},
                event_type="finalized_discarded",
            )
            return {**base, "action": "discarded", "after_status": updated.status, "after_promotion_state": updated.promotion_state}

        updated = self.working_memory.store.update_item_lifecycle(
            item.work_memory_id,
            status="archived",
            actor_id=actor_id,
            metadata={"finalization_terminal_reason": terminal_reason, "finalization_action": "archived"},
            event_type="finalized_archived",
        )
        return {**base, "action": "archived", "after_status": updated.status, "after_promotion_state": updated.promotion_state}
