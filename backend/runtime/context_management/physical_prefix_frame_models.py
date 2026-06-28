from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


PHYSICAL_PREFIX_FRAME_SCHEMA_VERSION = 1
PHYSICAL_PREFIX_FRAME_CONFIRMED_STATUS = "confirmed"


@dataclass(frozen=True, slots=True)
class PhysicalPrefixFrameSegment:
    ordinal: int
    segment_id: str
    transport_location: str
    role: str
    kind: str
    source_ref: str
    content_hash: str
    byte_length: int = 0
    physical_prefix_lane: str = ""
    prefix_family: str = ""
    cache_scope: str = "none"
    cache_role: str = "volatile"
    prefix_tier: str = "volatile"
    provider_visible_entry_index: int = 0
    provider_visible_hash: str = ""
    provider_visible_item_key: str = ""
    provider_tool_round_id: str = ""
    provider_tool_round_closed: bool = False
    boundary_participation: str = ""
    model_message_index: int = -1
    provider_message: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.context_management.physical_prefix_frame.segment"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["provider_message"] = dict(self.provider_message)
        payload["metadata"] = dict(self.metadata)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PhysicalPrefixFrameSegment":
        item = dict(payload or {})
        return cls(
            ordinal=_safe_int(item.get("ordinal")),
            segment_id=str(item.get("segment_id") or ""),
            transport_location=str(item.get("transport_location") or ""),
            role=str(item.get("role") or ""),
            kind=str(item.get("kind") or ""),
            source_ref=str(item.get("source_ref") or ""),
            content_hash=str(item.get("content_hash") or ""),
            byte_length=_safe_int(item.get("byte_length")),
            physical_prefix_lane=str(item.get("physical_prefix_lane") or ""),
            prefix_family=str(item.get("prefix_family") or ""),
            cache_scope=str(item.get("cache_scope") or "none"),
            cache_role=str(item.get("cache_role") or "volatile"),
            prefix_tier=str(item.get("prefix_tier") or "volatile"),
            provider_visible_entry_index=_safe_int(item.get("provider_visible_entry_index")),
            provider_visible_hash=str(item.get("provider_visible_hash") or ""),
            provider_visible_item_key=str(item.get("provider_visible_item_key") or ""),
            provider_tool_round_id=str(item.get("provider_tool_round_id") or ""),
            provider_tool_round_closed=bool(item.get("provider_tool_round_closed") is True),
            boundary_participation=str(item.get("boundary_participation") or ""),
            model_message_index=_safe_int(item.get("model_message_index"), default=-1),
            provider_message=dict(item.get("provider_message") or {}),
            metadata=dict(item.get("metadata") or {}),
            authority=str(item.get("authority") or "runtime.context_management.physical_prefix_frame.segment"),
        )


@dataclass(frozen=True, slots=True)
class PhysicalPrefixFrame:
    frame_id: str
    scope_id: str
    provider: str
    model: str
    provider_lane: str
    source_request_id: str
    source_run_id: str = ""
    source_task_run_id: str = ""
    source_session_id: str = ""
    source_turn_id: str = ""
    previous_frame_id: str = ""
    status: str = PHYSICAL_PREFIX_FRAME_CONFIRMED_STATUS
    transport_contract_hash: str = ""
    provider_payload_prefix_hash: str = ""
    physical_cache_spine_message_subtotal_hash: str = ""
    provider_payload_messages_hash: str = ""
    physical_payload_family_hash: str = ""
    boundary_segment_id: str = ""
    segment_count: int = 0
    message_segment_count: int = 0
    tool_segment_count: int = 0
    segments: tuple[PhysicalPrefixFrameSegment, ...] = ()
    current_append_entry_indexes: tuple[int, ...] = ()
    turn_snapshot: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    confirmed_at: float = 0.0
    authority: str = "runtime.context_management.physical_prefix_frame"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["segments"] = [segment.to_dict() for segment in self.segments]
        payload["current_append_entry_indexes"] = list(self.current_append_entry_indexes)
        payload["turn_snapshot"] = dict(self.turn_snapshot)
        payload["diagnostics"] = dict(self.diagnostics)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PhysicalPrefixFrame":
        item = dict(payload or {})
        segments = tuple(
            PhysicalPrefixFrameSegment.from_dict(segment)
            for segment in list(item.get("segments") or [])
            if isinstance(segment, dict)
        )
        return cls(
            frame_id=str(item.get("frame_id") or ""),
            scope_id=str(item.get("scope_id") or ""),
            provider=str(item.get("provider") or ""),
            model=str(item.get("model") or ""),
            provider_lane=str(item.get("provider_lane") or ""),
            source_request_id=str(item.get("source_request_id") or ""),
            source_run_id=str(item.get("source_run_id") or ""),
            source_task_run_id=str(item.get("source_task_run_id") or ""),
            source_session_id=str(item.get("source_session_id") or ""),
            source_turn_id=str(item.get("source_turn_id") or ""),
            previous_frame_id=str(item.get("previous_frame_id") or ""),
            status=str(item.get("status") or PHYSICAL_PREFIX_FRAME_CONFIRMED_STATUS),
            transport_contract_hash=str(item.get("transport_contract_hash") or ""),
            provider_payload_prefix_hash=str(item.get("provider_payload_prefix_hash") or ""),
            physical_cache_spine_message_subtotal_hash=str(
                item.get("physical_cache_spine_message_subtotal_hash") or ""
            ),
            provider_payload_messages_hash=str(item.get("provider_payload_messages_hash") or ""),
            physical_payload_family_hash=str(item.get("physical_payload_family_hash") or ""),
            boundary_segment_id=str(item.get("boundary_segment_id") or ""),
            segment_count=_safe_int(item.get("segment_count")) or len(segments),
            message_segment_count=_safe_int(item.get("message_segment_count")),
            tool_segment_count=_safe_int(item.get("tool_segment_count")),
            segments=segments,
            current_append_entry_indexes=tuple(
                _safe_int(value)
                for value in list(item.get("current_append_entry_indexes") or [])
                if _safe_int(value) > 0
            ),
            turn_snapshot=dict(item.get("turn_snapshot") or {}),
            diagnostics=dict(item.get("diagnostics") or {}),
            created_at=_safe_float(item.get("created_at")),
            confirmed_at=_safe_float(item.get("confirmed_at")),
            authority=str(item.get("authority") or "runtime.context_management.physical_prefix_frame"),
        )


def stable_json_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def json_stable(value: Any) -> Any:
    return _json_stable(value)


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
