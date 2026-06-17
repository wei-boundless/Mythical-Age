from __future__ import annotations

from typing import Any


AGENT_CORRECTION_LIFECYCLE_VERSION = "2026-06-17"


def agent_correction_lifecycle_payload(
    *,
    state: str,
    mismatch_kind: str,
    signal_kind: str,
    phase: str = "",
    upstream_signal_kind: str = "",
    retryable: bool | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "agent_correction_lifecycle",
        "version": AGENT_CORRECTION_LIFECYCLE_VERSION,
        "state": str(state or "correction_required"),
        "mismatch_kind": str(mismatch_kind or "contract_mismatch"),
        "signal_kind": str(signal_kind or ""),
        "phase": str(phase or ""),
        "upstream_signal_kind": str(upstream_signal_kind or ""),
        "authority_chain": {
            "system_role": "contract_validation_and_factual_feedback_only",
            "agent_role": "semantic_decision_self_correction_and_user_expression",
            "user_expression_owner": "agent",
        },
        "system_boundaries": {
            "may_decline_mismatched_action_execution": True,
            "must_return_correction_to_agent": True,
            "must_not_block_agent_as_semantic_actor": True,
            "must_not_speak_for_agent": True,
            "must_not_commit_assistant_message_from_signal": True,
            "must_not_turn_signal_into_user_facing_summary": True,
        },
        "agent_obligations": {
            "must_absorb_correction_signal": True,
            "must_select_next_legal_action": True,
            "must_author_user_visible_feedback_when_needed": True,
        },
        "public_surface": {
            "signal_is_not_assistant_prose": True,
            "runtime_projection": "trace_or_neutral_status_only",
            "assistant_body_source": "agent_authored_output_only",
        },
    }
    if retryable is not None:
        payload["retryable"] = bool(retryable)
    return _drop_empty(payload)


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}
