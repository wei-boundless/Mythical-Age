from __future__ import annotations

from typing import Any


PHYSICAL_PREFIX_FRAME_REPLAY_AUTHORITY = "runtime.context_management.physical_prefix_frame.replay"
PHYSICAL_PREFIX_FRAME_REPLAY_POLICY = "physical_prefix_frame_replay"
PHYSICAL_PREFIX_FRAME_REPLAY_STATUS = "sealed_from_physical_prefix_frame"
PROVIDER_PROTOCOL_REPLAY_AUTHORITY = "runtime.provider_protocol.replay"
PROVIDER_PROTOCOL_REPLAY_POLICY = "provider_protocol_replay"
PROVIDER_PROTOCOL_REPLAY_STATUS = "provider_protocol_replay"
PROVIDER_PROTOCOL_APPEND_AUTHORITY = "runtime.provider_protocol.append_candidate"
PROVIDER_PROTOCOL_APPEND_POLICY = "provider_protocol_append_candidate"
PROVIDER_PROTOCOL_APPEND_STATUS = "provider_protocol_append_pending_provider_success"


def provider_message_byte_preservation_required(spec: dict[str, Any] | None) -> bool:
    payload = dict(spec or {})
    metadata = dict(payload.get("metadata") or {})
    return (
        physical_prefix_frame_replay_metadata(metadata)
        or provider_protocol_replay_metadata(metadata)
        or provider_protocol_append_candidate_metadata(metadata)
    )


def provider_message_replay_metadata(metadata: dict[str, Any] | None) -> bool:
    payload = dict(metadata or {})
    return physical_prefix_frame_replay_metadata(payload)


def physical_prefix_frame_replay_metadata(metadata: dict[str, Any] | None) -> bool:
    payload = dict(metadata or {})
    if str(payload.get("provider_visible_payload_authority") or "").strip() == PHYSICAL_PREFIX_FRAME_REPLAY_AUTHORITY:
        return True
    if (
        str(payload.get("context_replay_policy") or "").strip() == PHYSICAL_PREFIX_FRAME_REPLAY_POLICY
        and str(payload.get("physical_prefix_frame_id") or "").strip()
    ):
        return True
    return str(payload.get("provider_visible_history_status") or "").strip() == PHYSICAL_PREFIX_FRAME_REPLAY_STATUS


def provider_protocol_replay_metadata(metadata: dict[str, Any] | None) -> bool:
    payload = dict(metadata or {})
    if payload.get("provider_protocol_replay") is True:
        return True
    if str(payload.get("context_replay_policy") or "").strip() == PROVIDER_PROTOCOL_REPLAY_POLICY:
        return True
    if str(payload.get("provider_visible_history_status") or "").strip() == PROVIDER_PROTOCOL_REPLAY_STATUS:
        return True
    if str(payload.get("provider_message_replay_authority") or "").strip() == PROVIDER_PROTOCOL_REPLAY_AUTHORITY:
        return True
    return False


def provider_protocol_append_candidate_metadata(metadata: dict[str, Any] | None) -> bool:
    payload = dict(metadata or {})
    if payload.get("provider_protocol_append_candidate") is True:
        return True
    if str(payload.get("context_replay_policy") or "").strip() == PROVIDER_PROTOCOL_APPEND_POLICY:
        return True
    if str(payload.get("provider_visible_history_status") or "").strip() == PROVIDER_PROTOCOL_APPEND_STATUS:
        return True
    if str(payload.get("provider_message_append_authority") or "").strip() == PROVIDER_PROTOCOL_APPEND_AUTHORITY:
        return True
    return False


def provider_message_replay_kind(spec: dict[str, Any] | None) -> str:
    payload = dict(spec or {})
    metadata = dict(payload.get("metadata") or {})
    if physical_prefix_frame_replay_metadata(metadata):
        return PHYSICAL_PREFIX_FRAME_REPLAY_POLICY
    if provider_protocol_replay_metadata(metadata):
        return PROVIDER_PROTOCOL_REPLAY_POLICY
    if provider_protocol_append_candidate_metadata(metadata):
        return PROVIDER_PROTOCOL_APPEND_POLICY
    return ""
