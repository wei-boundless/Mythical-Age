from __future__ import annotations

from typing import Any

from .turn_memory_projector import project_current_turn_context, project_handoff_context
from .turn_memory_recovery import decide_turn_memory_recovery


TURN_MEMORY_RECOVERY_CONTEXT_AUTHORITY = "runtime.turn_memory.recovery_context"

_TURN_MEMORY_RECOVERY_STATUSES = frozenset({"handoff_ready", "commit_pending", "frame_pending"})
_TURN_MEMORY_RECOVERY_COMMIT_STATES = frozenset({"pending_commit", "pending_frame_promotion"})


def build_turn_memory_recovery_context(store: Any, *, session_id: str) -> dict[str, Any]:
    normalized_session = str(session_id or "").strip()
    if not normalized_session:
        return {}
    lister = getattr(store, "list_session_turns", None)
    if not callable(lister):
        return {}
    try:
        records = list(lister(normalized_session, include_released=False) or [])
    except Exception:
        return {}
    candidates = [
        record
        for record in records
        if _turn_memory_record_is_recovery_candidate(record)
    ]
    if not candidates:
        return {}
    selected = sorted(
        candidates,
        key=lambda item: (
            float(getattr(item, "updated_at", 0.0) or 0.0),
            float(getattr(item, "created_at", 0.0) or 0.0),
        ),
        reverse=True,
    )[0]
    decision = decide_turn_memory_recovery(selected).to_dict()
    if not bool(decision.get("recoverable") is True):
        return {}
    current_projection = project_current_turn_context(selected)
    handoff_projection = project_handoff_context(selected)
    return _drop_empty_turn_memory_payload(
        {
            "authority": TURN_MEMORY_RECOVERY_CONTEXT_AUTHORITY,
            "session_id": normalized_session,
            "previous_turn_id": str(getattr(selected, "turn_id", "") or ""),
            "turn_run_id": str(getattr(selected, "turn_run_id", "") or ""),
            "branch_id": str(getattr(selected, "branch_id", "") or ""),
            "status": str(getattr(selected, "status", "") or ""),
            "phase": str(getattr(selected, "phase", "") or ""),
            "recovery_state": str(getattr(selected, "recovery_state", "") or ""),
            "recovery_decision": decision,
            "current_turn_context": current_projection,
            "handoff_context": handoff_projection,
            "provider_request_refs": list(getattr(selected, "provider_request_refs", ()) or ())[-16:],
            "provider_payload_manifest_refs": list(getattr(selected, "provider_payload_manifest_refs", ()) or ())[-16:],
            "physical_prefix_frame_id": str(getattr(selected, "physical_prefix_frame_id", "") or ""),
            "current_append_hash": str(getattr(selected, "current_append_hash", "") or ""),
            "frame_promotion_ref": str(getattr(selected, "frame_promotion_ref", "") or ""),
            "assistant_final_ref": str(getattr(selected, "assistant_final_ref", "") or ""),
            "assistant_final_sha256": str(getattr(selected, "assistant_final_sha256", "") or ""),
            "assistant_draft_ref": str(getattr(selected, "assistant_draft_ref", "") or ""),
            "assistant_draft_sha256": str(getattr(selected, "assistant_draft_sha256", "") or ""),
            "closed_tool_round_refs": list(getattr(selected, "closed_tool_round_refs", ()) or ())[-16:],
            "active_steer_refs": list(getattr(selected, "active_steer_refs", ()) or ())[-16:],
            "pending_tool_summary": dict(getattr(selected, "pending_tool_summary", {}) or {}),
            "pending_commit_summary": dict(getattr(selected, "pending_commit_summary", {}) or {}),
        }
    )


def _turn_memory_record_is_recovery_candidate(record: Any) -> bool:
    status = str(getattr(record, "status", "") or "").strip()
    if status in {"released", "superseded", "terminal"}:
        return False
    if status in _TURN_MEMORY_RECOVERY_STATUSES:
        return True
    commit_state = str(getattr(record, "commit_state", "") or "").strip()
    if commit_state in _TURN_MEMORY_RECOVERY_COMMIT_STATES:
        return True
    return bool(
        str(getattr(record, "assistant_draft_ref", "") or "").strip()
        or str(getattr(record, "assistant_draft_sha256", "") or "").strip()
    )


def _drop_empty_turn_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}
