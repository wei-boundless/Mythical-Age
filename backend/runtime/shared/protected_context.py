from __future__ import annotations

from typing import Any


PHYSICAL_PREFIX_FRAME_REPLAY_AUTHORITY = "runtime.context_management.physical_prefix_frame.replay"


def protected_old_context_spec(spec: dict[str, Any] | None) -> bool:
    """Return True for provider-visible old context that must be replayed verbatim."""

    payload = dict(spec or {})
    metadata = dict(payload.get("metadata") or {})
    return protected_old_context_metadata(metadata)


def protected_old_context_metadata(metadata: dict[str, Any] | None) -> bool:
    payload = dict(metadata or {})
    if payload.get("current_turn_exact_old_context") is True:
        return True
    if payload.get("provider_protocol_replay") is True:
        return True
    if str(payload.get("context_replay_policy") or "").strip() == "current_turn_exact_old_context":
        return True
    if str(payload.get("provider_visible_history_status") or "").strip() == "current_turn_exact_old_context":
        return True
    if str(payload.get("provider_visible_payload_authority") or "").strip() == PHYSICAL_PREFIX_FRAME_REPLAY_AUTHORITY:
        return True
    if (
        str(payload.get("context_replay_policy") or "").strip() == "physical_prefix_frame_replay"
        and str(payload.get("physical_prefix_frame_id") or "").strip()
    ):
        return True
    return str(payload.get("provider_visible_history_status") or "").strip() == "sealed_from_physical_prefix_frame"
