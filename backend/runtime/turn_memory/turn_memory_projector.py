from __future__ import annotations

from typing import Any

from .turn_memory_models import TurnMemoryRecord


def project_current_turn_context(record: TurnMemoryRecord | None) -> dict[str, Any]:
    if record is None or record.status == "released":
        return {}
    return {
        "authority": "runtime.turn_memory.projector",
        "session_id": record.session_id,
        "turn_id": record.turn_id,
        "turn_run_id": record.turn_run_id,
        "branch_id": record.branch_id,
        "status": record.status,
        "phase": record.phase,
        "current_user_message_ref": record.current_user_message_ref,
        "active_steer_refs": list(record.active_steer_refs),
        "edit_resend_ref": record.edit_resend_ref,
        "branch_cutoff_message_index": record.branch_cutoff_message_index,
        "assistant_draft_ref": record.assistant_draft_ref,
        "assistant_draft_sha256": record.assistant_draft_sha256,
        "assistant_final_ref": record.assistant_final_ref,
        "assistant_final_sha256": record.assistant_final_sha256,
        "closed_tool_round_refs": list(record.closed_tool_round_refs),
        "pending_tool_summary": dict(record.pending_tool_summary),
        "pending_action_ref": record.pending_action_ref,
        "commit_state": record.commit_state,
        "recovery_state": record.recovery_state,
        "public_event_cursor": dict(record.public_event_cursor),
    }


def project_handoff_context(record: TurnMemoryRecord | None) -> dict[str, Any]:
    if record is None or record.status not in {"handoff_ready", "commit_pending", "frame_pending"}:
        return {}
    return {
        "authority": "runtime.turn_memory.handoff_projector",
        "session_id": record.session_id,
        "previous_turn_id": record.turn_id,
        "branch_id": record.branch_id,
        "status": record.status,
        "physical_prefix_frame_id": record.physical_prefix_frame_id,
        "assistant_final_ref": record.assistant_final_ref,
        "assistant_final_sha256": record.assistant_final_sha256,
        "closed_tool_round_refs": list(record.closed_tool_round_refs),
        "active_steer_refs": list(record.active_steer_refs),
        "edit_resend_ref": record.edit_resend_ref,
        "branch_cutoff_message_index": record.branch_cutoff_message_index,
        "commit_state": record.commit_state,
        "pending_commit_summary": dict(record.pending_commit_summary),
        "frame_promotion_ref": record.frame_promotion_ref,
    }
