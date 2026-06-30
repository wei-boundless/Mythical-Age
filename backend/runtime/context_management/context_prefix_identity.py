from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from .provider_message_replay_contract import (
    physical_prefix_frame_replay_metadata,
    provider_protocol_replay_metadata,
)


CONTEXT_PREFIX_IDENTITY_SCHEMA = "context_prefix_identity"
CONTEXT_PREFIX_IDENTITY_AUTHORITY = "runtime.context_management.context_prefix_identity"
PROVIDER_PROMPT_PREFIX_DOMAIN = "provider_prompt_prefix"


@dataclass(frozen=True, slots=True)
class PrefixIdentity:
    schema: str
    prefix_domain: str
    physical_lane: str
    lifecycle_state: str
    semantic_slot: str
    origin_authority: str
    origin_ref: str
    logical_segment_ref: str
    content_version_hash: str = ""
    provider_serialized_hash: str = ""
    frame_ref: str = ""
    frame_ordinal: int = 0
    request_ordinal: int = 0
    cache_read_expectation: str = ""
    authority: str = CONTEXT_PREFIX_IDENTITY_AUTHORITY

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_context_prefix_identity(
    *,
    kind: Any,
    metadata: dict[str, Any] | None = None,
    source_ref: Any = "",
    physical_lane: Any = "",
    semantic_source: Any = "",
    semantic_slot: Any = "",
    content_version_hash: Any = "",
    provider_serialized_hash: Any = "",
    request_ordinal: Any = 0,
    transport_location: Any = "",
    frame_ref: Any = "",
    frame_ordinal: Any = 0,
) -> PrefixIdentity:
    payload = dict(metadata or {})
    normalized_kind = _clean(kind) or "unknown_segment"
    lane = _clean(physical_lane or payload.get("physical_prefix_lane"))
    slot = _clean(
        semantic_slot
        or payload.get("context_semantic_slot")
        or payload.get("semantic_slot")
        or payload.get("slot")
        or normalized_kind
    )
    origin_authority = _origin_authority(
        payload,
        semantic_source=semantic_source,
        source_ref=source_ref,
        kind=normalized_kind,
    )
    origin_ref = _origin_ref(
        payload,
        source_ref=source_ref,
        kind=normalized_kind,
        transport_location=transport_location,
        request_ordinal=request_ordinal,
    )
    lifecycle_state = _lifecycle_state(lane=lane, metadata=payload, kind=normalized_kind)
    version_hash = _clean(content_version_hash)
    serialized_hash = _clean(provider_serialized_hash) or version_hash
    logical_segment_ref = _logical_segment_ref(
        physical_lane=lane,
        semantic_slot=slot,
        origin_authority=origin_authority,
        origin_ref=origin_ref,
    )
    cache_read_expectation = _cache_read_expectation(
        lane=lane,
        lifecycle_state=lifecycle_state,
    )
    return PrefixIdentity(
        schema=CONTEXT_PREFIX_IDENTITY_SCHEMA,
        prefix_domain=PROVIDER_PROMPT_PREFIX_DOMAIN,
        physical_lane=lane,
        lifecycle_state=lifecycle_state,
        semantic_slot=slot,
        origin_authority=origin_authority,
        origin_ref=origin_ref,
        logical_segment_ref=logical_segment_ref,
        content_version_hash=version_hash,
        provider_serialized_hash=serialized_hash,
        frame_ref=_clean(frame_ref or payload.get("physical_prefix_frame_id")),
        frame_ordinal=_safe_int(frame_ordinal or payload.get("physical_prefix_frame_ordinal")),
        request_ordinal=_safe_int(request_ordinal),
        cache_read_expectation=cache_read_expectation,
    )


def _origin_authority(
    metadata: dict[str, Any],
    *,
    semantic_source: Any,
    source_ref: Any,
    kind: str,
) -> str:
    return _first_text(
        metadata.get("context_origin_authority"),
        metadata.get("prefix_origin_authority"),
        metadata.get("origin_authority"),
        metadata.get("context_semantic_source"),
        metadata.get("semantic_source"),
        semantic_source,
        source_ref,
        kind,
    )


def _origin_ref(
    metadata: dict[str, Any],
    *,
    source_ref: Any,
    kind: str,
    transport_location: Any,
    request_ordinal: Any,
) -> str:
    stable = _first_text(
        metadata.get("context_origin_ref"),
        metadata.get("prefix_origin_ref"),
        metadata.get("origin_ref"),
        metadata.get("stable_origin_ref"),
        metadata.get("provider_visible_append_item_key"),
        metadata.get("append_only_context_item_key"),
        metadata.get("provider_visible_append_candidate_source_ref"),
        metadata.get("runtime_contract_ref"),
        metadata.get("context_contract_ref"),
        source_ref,
    )
    if stable:
        return stable
    return "request-local:{transport}:{ordinal}:{kind}".format(
        transport=_safe_token(transport_location) or "segment",
        ordinal=_safe_int(request_ordinal),
        kind=_safe_token(kind) or "segment",
    )


def _lifecycle_state(*, lane: str, metadata: dict[str, Any], kind: str) -> str:
    explicit = _first_text(
        metadata.get("context_prefix_lifecycle_state"),
        metadata.get("prefix_lifecycle_state"),
        metadata.get("lifecycle_state"),
    )
    if explicit:
        return explicit
    if lane in {"global_static_prefix", "provider_tool_schema_prefix"}:
        return "static_prefix"
    if lane == "provider_visible_context_prefix":
        if _confirmed_frame_replay(metadata):
            return "confirmed_frame_replay"
        if _provider_protocol_replay(metadata):
            return "provider_protocol_replay"
        return "provider_visible_prefix_unconfirmed"
    if lane == "current_turn_tail":
        return "current_append_pending_provider_success"
    if lane == "never_replay_tail":
        return "dynamic_tail_never_replay"
    if lane == "provider_tool_schema_blocker":
        return "transport_blocker"
    if lane:
        return "unknown_physical_lane"
    return "request_local_transport_contract"


def _confirmed_frame_replay(metadata: dict[str, Any]) -> bool:
    return physical_prefix_frame_replay_metadata(metadata)


def _provider_protocol_replay(metadata: dict[str, Any]) -> bool:
    return provider_protocol_replay_metadata(metadata)


def _cache_read_expectation(*, lane: str, lifecycle_state: str) -> str:
    if lifecycle_state == "transport_blocker":
        return "blocker"
    if lane == "global_static_prefix":
        return "expected_read"
    if lane == "provider_tool_schema_prefix":
        return "expected_read"
    if lifecycle_state == "confirmed_frame_replay":
        return "expected_read"
    if lifecycle_state == "provider_protocol_replay":
        return "expected_read"
    if lifecycle_state in {
        "current_append_pending_provider_success",
        "provider_visible_prefix_unconfirmed",
    }:
        return "write_candidate"
    return "excluded"


def _logical_segment_ref(
    *,
    physical_lane: str,
    semantic_slot: str,
    origin_authority: str,
    origin_ref: str,
) -> str:
    seed = {
        "schema": CONTEXT_PREFIX_IDENTITY_SCHEMA,
        "prefix_domain": PROVIDER_PROMPT_PREFIX_DOMAIN,
        "physical_lane": str(physical_lane or ""),
        "semantic_slot": str(semantic_slot or ""),
        "origin_authority": str(origin_authority or ""),
        "origin_ref": str(origin_ref or ""),
    }
    digest = _stable_json_hash(seed).removeprefix("sha256:")[:16]
    return "ctxprefix:{lane}:{slot}:{digest}".format(
        lane=_safe_token(physical_lane) or "unplaced",
        slot=_safe_token(semantic_slot) or "segment",
        digest=digest,
    )


def _first_text(*values: Any) -> str:
    for value in values:
        text = _clean(value)
        if text:
            return text
    return ""


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_token(value: Any) -> str:
    text = _clean(value).lower()
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text).strip("_")[:80]


def _stable_text_hash(text: Any) -> str:
    return "sha256:" + hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()


def _stable_json_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _stable_text_hash(payload)


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
