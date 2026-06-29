from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal


TURN_MEMORY_AUTHORITY = "runtime.turn_memory"
TURN_MEMORY_SCHEMA_VERSION = 1

TurnMemoryStatus = Literal[
    "active",
    "checkpointed",
    "final_ready",
    "commit_pending",
    "frame_pending",
    "handoff_ready",
    "terminal",
    "superseded",
    "released",
]
TurnMemoryPhase = Literal[
    "user_input",
    "provider_request",
    "tool_round",
    "model_reentry",
    "committing",
    "recovering",
    "terminal",
]

TURN_MEMORY_STATUSES: set[str] = {
    "active",
    "checkpointed",
    "final_ready",
    "commit_pending",
    "frame_pending",
    "handoff_ready",
    "terminal",
    "superseded",
    "released",
}
TURN_MEMORY_PHASES: set[str] = {
    "user_input",
    "provider_request",
    "tool_round",
    "model_reentry",
    "committing",
    "recovering",
    "terminal",
}


@dataclass(frozen=True, slots=True)
class TurnMemoryRecord:
    session_id: str
    turn_id: str
    turn_run_id: str
    branch_id: str
    status: TurnMemoryStatus = "active"
    phase: TurnMemoryPhase = "user_input"
    parent_turn_id: str = ""
    current_user_message_ref: str = ""
    attachments_ref: str = ""
    editor_context_ref: str = ""
    active_steer_refs: tuple[str, ...] = ()
    edit_resend_ref: str = ""
    branch_cutoff_message_index: int = -1
    provider_request_refs: tuple[str, ...] = ()
    provider_payload_manifest_refs: tuple[str, ...] = ()
    physical_prefix_frame_id: str = ""
    current_append_hash: str = ""
    assistant_draft_ref: str = ""
    assistant_draft_sha256: str = ""
    assistant_final_ref: str = ""
    assistant_final_sha256: str = ""
    tool_rounds: tuple[dict[str, Any], ...] = ()
    pending_tool_summary: dict[str, Any] = field(default_factory=dict)
    closed_tool_round_refs: tuple[str, ...] = ()
    pending_action_ref: str = ""
    aborted_action_refs: tuple[str, ...] = ()
    public_event_cursor: dict[str, Any] = field(default_factory=dict)
    public_projection_refs: tuple[str, ...] = ()
    commit_state: str = ""
    session_commit_ref: str = ""
    frame_promotion_ref: str = ""
    pending_commit_summary: dict[str, Any] = field(default_factory=dict)
    recovery_state: str = ""
    recovery_decision_ref: str = ""
    uncertain_side_effect_refs: tuple[str, ...] = ()
    handoff_state: str = ""
    release_state: str = ""
    released_at: float = 0.0
    tombstone_hash: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    authority: str = TURN_MEMORY_AUTHORITY
    schema_version: int = TURN_MEMORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("TurnMemoryRecord requires session_id")
        if not self.turn_id:
            raise ValueError("TurnMemoryRecord requires turn_id")
        if self.status not in TURN_MEMORY_STATUSES:
            raise ValueError(f"invalid TurnMemory status: {self.status}")
        if self.phase not in TURN_MEMORY_PHASES:
            raise ValueError(f"invalid TurnMemory phase: {self.phase}")
        if self.authority != TURN_MEMORY_AUTHORITY:
            raise ValueError(f"TurnMemoryRecord authority must be {TURN_MEMORY_AUTHORITY}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["active_steer_refs"] = list(self.active_steer_refs)
        payload["provider_request_refs"] = list(self.provider_request_refs)
        payload["provider_payload_manifest_refs"] = list(self.provider_payload_manifest_refs)
        payload["tool_rounds"] = [dict(item) for item in self.tool_rounds]
        payload["closed_tool_round_refs"] = list(self.closed_tool_round_refs)
        payload["aborted_action_refs"] = list(self.aborted_action_refs)
        payload["public_event_cursor"] = dict(self.public_event_cursor)
        payload["public_projection_refs"] = list(self.public_projection_refs)
        payload["pending_tool_summary"] = dict(self.pending_tool_summary)
        payload["pending_commit_summary"] = dict(self.pending_commit_summary)
        payload["uncertain_side_effect_refs"] = list(self.uncertain_side_effect_refs)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TurnMemoryRecord":
        item = dict(payload or {})
        return cls(
            session_id=str(item.get("session_id") or ""),
            turn_id=str(item.get("turn_id") or ""),
            turn_run_id=str(item.get("turn_run_id") or ""),
            branch_id=str(item.get("branch_id") or ""),
            status=_status(item.get("status")),
            phase=_phase(item.get("phase")),
            parent_turn_id=str(item.get("parent_turn_id") or ""),
            current_user_message_ref=str(item.get("current_user_message_ref") or ""),
            attachments_ref=str(item.get("attachments_ref") or ""),
            editor_context_ref=str(item.get("editor_context_ref") or ""),
            active_steer_refs=_string_tuple(item.get("active_steer_refs")),
            edit_resend_ref=str(item.get("edit_resend_ref") or ""),
            branch_cutoff_message_index=_safe_int(item.get("branch_cutoff_message_index"), default=-1),
            provider_request_refs=_string_tuple(item.get("provider_request_refs")),
            provider_payload_manifest_refs=_string_tuple(item.get("provider_payload_manifest_refs")),
            physical_prefix_frame_id=str(item.get("physical_prefix_frame_id") or ""),
            current_append_hash=str(item.get("current_append_hash") or ""),
            assistant_draft_ref=str(item.get("assistant_draft_ref") or ""),
            assistant_draft_sha256=str(item.get("assistant_draft_sha256") or ""),
            assistant_final_ref=str(item.get("assistant_final_ref") or ""),
            assistant_final_sha256=str(item.get("assistant_final_sha256") or ""),
            tool_rounds=tuple(
                dict(entry)
                for entry in list(item.get("tool_rounds") or [])
                if isinstance(entry, dict)
            ),
            pending_tool_summary=dict(item.get("pending_tool_summary") or {}),
            closed_tool_round_refs=_string_tuple(item.get("closed_tool_round_refs")),
            pending_action_ref=str(item.get("pending_action_ref") or ""),
            aborted_action_refs=_string_tuple(item.get("aborted_action_refs")),
            public_event_cursor=dict(item.get("public_event_cursor") or {}),
            public_projection_refs=_string_tuple(item.get("public_projection_refs")),
            commit_state=str(item.get("commit_state") or ""),
            session_commit_ref=str(item.get("session_commit_ref") or ""),
            frame_promotion_ref=str(item.get("frame_promotion_ref") or ""),
            pending_commit_summary=dict(item.get("pending_commit_summary") or {}),
            recovery_state=str(item.get("recovery_state") or ""),
            recovery_decision_ref=str(item.get("recovery_decision_ref") or ""),
            uncertain_side_effect_refs=_string_tuple(item.get("uncertain_side_effect_refs")),
            handoff_state=str(item.get("handoff_state") or ""),
            release_state=str(item.get("release_state") or ""),
            released_at=_safe_float(item.get("released_at")),
            tombstone_hash=str(item.get("tombstone_hash") or ""),
            created_at=_safe_float(item.get("created_at")),
            updated_at=_safe_float(item.get("updated_at")),
            authority=str(item.get("authority") or TURN_MEMORY_AUTHORITY),
            schema_version=_safe_int(item.get("schema_version"), default=TURN_MEMORY_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class TurnMemoryCheckpoint:
    checkpoint_id: str
    session_id: str
    turn_id: str
    checkpoint_kind: str
    sequence: int
    turn_memory_hash: str
    payload: dict[str, Any] = field(default_factory=dict)
    previous_checkpoint_hash: str = ""
    checkpoint_hash: str = ""
    created_at: float = 0.0
    authority: str = "runtime.turn_memory.checkpoint"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["payload"] = dict(self.payload)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TurnMemoryCheckpoint":
        item = dict(payload or {})
        return cls(
            checkpoint_id=str(item.get("checkpoint_id") or ""),
            session_id=str(item.get("session_id") or ""),
            turn_id=str(item.get("turn_id") or ""),
            checkpoint_kind=str(item.get("checkpoint_kind") or ""),
            sequence=_safe_int(item.get("sequence")),
            turn_memory_hash=str(item.get("turn_memory_hash") or ""),
            payload=dict(item.get("payload") or {}),
            previous_checkpoint_hash=str(item.get("previous_checkpoint_hash") or ""),
            checkpoint_hash=str(item.get("checkpoint_hash") or ""),
            created_at=_safe_float(item.get("created_at")),
            authority=str(item.get("authority") or "runtime.turn_memory.checkpoint"),
        )


def replace_turn_memory(record: TurnMemoryRecord, **changes: Any) -> TurnMemoryRecord:
    return replace(record, **changes)


def stable_json_hash(value: Any) -> str:
    text = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(str(value or "").encode("utf-8", errors="ignore")).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _status(value: Any) -> TurnMemoryStatus:
    text = str(value or "active")
    return text if text in TURN_MEMORY_STATUSES else "active"  # type: ignore[return-value]


def _phase(value: Any) -> TurnMemoryPhase:
    text = str(value or "user_input")
    return text if text in TURN_MEMORY_PHASES else "user_input"  # type: ignore[return-value]


def _string_tuple(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in list(value or []) if str(item or "").strip())


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
