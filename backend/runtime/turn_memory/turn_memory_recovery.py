from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .turn_memory_models import TurnMemoryRecord


@dataclass(frozen=True, slots=True)
class TurnMemoryRecoveryDecision:
    action: str
    reason: str
    turn_id: str = ""
    commit_state: str = ""
    recoverable: bool = False
    payload: dict[str, Any] | None = None
    authority: str = "runtime.turn_memory.recovery"

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "turn_id": self.turn_id,
            "commit_state": self.commit_state,
            "recoverable": self.recoverable,
            "payload": dict(self.payload or {}),
            "authority": self.authority,
        }


def decide_turn_memory_recovery(record: TurnMemoryRecord | None) -> TurnMemoryRecoveryDecision:
    if record is None:
        return TurnMemoryRecoveryDecision(action="none", reason="turn_memory_missing", recoverable=False)
    if record.status == "released":
        return TurnMemoryRecoveryDecision(
            action="none",
            reason="turn_memory_released",
            turn_id=record.turn_id,
            recoverable=False,
            payload={"tombstone_hash": record.tombstone_hash},
        )
    if record.status == "commit_pending" or record.commit_state == "pending_commit":
        return TurnMemoryRecoveryDecision(
            action="retry_commit",
            reason="assistant_final_pending_commit",
            turn_id=record.turn_id,
            commit_state=record.commit_state,
            recoverable=True,
            payload={"assistant_final_ref": record.assistant_final_ref, "assistant_final_sha256": record.assistant_final_sha256},
        )
    if record.status == "frame_pending" or record.commit_state == "pending_frame_promotion":
        return TurnMemoryRecoveryDecision(
            action="retry_frame_promotion",
            reason="physical_frame_pending",
            turn_id=record.turn_id,
            commit_state=record.commit_state,
            recoverable=True,
            payload={"frame_promotion_ref": record.frame_promotion_ref},
        )
    if record.assistant_draft_ref or record.assistant_draft_sha256:
        return TurnMemoryRecoveryDecision(
            action="recover_from_checkpoint",
            reason="assistant_draft_checkpoint_available",
            turn_id=record.turn_id,
            commit_state=record.commit_state,
            recoverable=True,
            payload={"assistant_draft_ref": record.assistant_draft_ref, "assistant_draft_sha256": record.assistant_draft_sha256},
        )
    return TurnMemoryRecoveryDecision(
        action="inspect",
        reason="turn_memory_present_without_recovery_action",
        turn_id=record.turn_id,
        commit_state=record.commit_state,
        recoverable=False,
    )
