from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ContinuationState = Literal[
    "none",
    "recoverable",
    "waiting_approval",
    "paused",
    "blocked",
    "terminal_read_only",
]

InterruptedTurnContinuationState = Literal["interrupted_read_only"]


@dataclass(frozen=True, slots=True)
class ContinuationRecord:
    continuation_id: str
    session_id: str
    task_run_id: str
    previous_turn_id: str = ""
    previous_active_turn_id: str = ""
    previous_stream_run_id: str = ""
    state: ContinuationState = "none"
    resume_allowed: bool = False
    resume_strategy: str = "unavailable"
    resume_scheduler: str = "conversation_recovery_resume"
    recovery_cause: str = ""
    task_status: str = ""
    executor_status: str = ""
    control_state: str = ""
    user_visible_goal: str = ""
    latest_progress: str = ""
    last_completed_step: str = ""
    next_recommended_step: str = ""
    task_contract_ref: str = ""
    work_rollout_ref: str = ""
    event_log_ref: str = ""
    event_cursor: int = -1
    artifact_refs: tuple[dict[str, Any], ...] = ()
    model_visible_summary: str = ""
    requires_user_confirmation: bool = False
    control_version: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0
    expires_at: float | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.continuation.record"

    def __post_init__(self) -> None:
        if self.authority != "harness.continuation.record":
            raise ValueError("ContinuationRecord authority must be harness.continuation.record")
        if self.state != "none" and not self.session_id:
            raise ValueError("ContinuationRecord requires session_id")
        if self.state != "none" and not self.task_run_id:
            raise ValueError("ContinuationRecord requires task_run_id")
        if self.state != "none" and not self.continuation_id:
            raise ValueError("ContinuationRecord requires continuation_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifact_refs"] = [dict(item) for item in self.artifact_refs]
        return payload


@dataclass(frozen=True, slots=True)
class InterruptedTurnContinuationRecord:
    """Read-only continuity context for an interrupted ordinary conversation turn."""

    continuation_id: str
    session_id: str
    turn_run_id: str
    turn_id: str
    previous_stream_run_id: str = ""
    state: InterruptedTurnContinuationState = "interrupted_read_only"
    resume_allowed: bool = False
    resume_strategy: str = "read_only_next_turn_continuation"
    interruption_kind: str = ""
    terminal_status: str = ""
    terminal_reason: str = ""
    latest_progress: str = ""
    latest_step: str = ""
    next_recommended_step: str = ""
    event_log_ref: str = ""
    event_cursor: int = -1
    model_visible_summary: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.continuation.interrupted_turn_record"

    def __post_init__(self) -> None:
        if self.authority != "harness.continuation.interrupted_turn_record":
            raise ValueError("InterruptedTurnContinuationRecord authority must be harness.continuation.interrupted_turn_record")
        if self.state != "interrupted_read_only":
            raise ValueError("InterruptedTurnContinuationRecord state must be interrupted_read_only")
        if not self.session_id:
            raise ValueError("InterruptedTurnContinuationRecord requires session_id")
        if not self.turn_run_id:
            raise ValueError("InterruptedTurnContinuationRecord requires turn_run_id")
        if not self.turn_id:
            raise ValueError("InterruptedTurnContinuationRecord requires turn_id")
        if not self.continuation_id:
            raise ValueError("InterruptedTurnContinuationRecord requires continuation_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def continuation_record_from_payload(payload: dict[str, Any] | None) -> ContinuationRecord | None:
    data = dict(payload or {})
    if not data:
        return None
    try:
        return ContinuationRecord(
            continuation_id=str(data.get("continuation_id") or ""),
            session_id=str(data.get("session_id") or ""),
            task_run_id=str(data.get("task_run_id") or ""),
            previous_turn_id=str(data.get("previous_turn_id") or ""),
            previous_active_turn_id=str(data.get("previous_active_turn_id") or ""),
            previous_stream_run_id=str(data.get("previous_stream_run_id") or ""),
            state=_state(data.get("state")),
            resume_allowed=bool(data.get("resume_allowed") is True),
            resume_strategy=str(data.get("resume_strategy") or "unavailable"),
            resume_scheduler=str(data.get("resume_scheduler") or "conversation_recovery_resume"),
            recovery_cause=str(data.get("recovery_cause") or ""),
            task_status=str(data.get("task_status") or ""),
            executor_status=str(data.get("executor_status") or ""),
            control_state=str(data.get("control_state") or ""),
            user_visible_goal=str(data.get("user_visible_goal") or ""),
            latest_progress=str(data.get("latest_progress") or ""),
            last_completed_step=str(data.get("last_completed_step") or ""),
            next_recommended_step=str(data.get("next_recommended_step") or ""),
            task_contract_ref=str(data.get("task_contract_ref") or ""),
            work_rollout_ref=str(data.get("work_rollout_ref") or ""),
            event_log_ref=str(data.get("event_log_ref") or ""),
            event_cursor=_int_value(data.get("event_cursor"), -1),
            artifact_refs=tuple(dict(item) for item in list(data.get("artifact_refs") or []) if isinstance(item, dict)),
            model_visible_summary=str(data.get("model_visible_summary") or ""),
            requires_user_confirmation=bool(data.get("requires_user_confirmation") is True),
            control_version=_int_value(data.get("control_version"), 0),
            created_at=float(data.get("created_at") or 0.0),
            updated_at=float(data.get("updated_at") or 0.0),
            expires_at=float(data["expires_at"]) if data.get("expires_at") not in (None, "") else None,
            diagnostics=dict(data.get("diagnostics") or {}),
        )
    except Exception:
        return None


def interrupted_turn_record_from_payload(payload: dict[str, Any] | None) -> InterruptedTurnContinuationRecord | None:
    data = dict(payload or {})
    if not data:
        return None
    try:
        return InterruptedTurnContinuationRecord(
            continuation_id=str(data.get("continuation_id") or ""),
            session_id=str(data.get("session_id") or ""),
            turn_run_id=str(data.get("turn_run_id") or ""),
            turn_id=str(data.get("turn_id") or ""),
            previous_stream_run_id=str(data.get("previous_stream_run_id") or ""),
            state="interrupted_read_only",
            resume_allowed=False,
            resume_strategy=str(data.get("resume_strategy") or "read_only_next_turn_continuation"),
            interruption_kind=str(data.get("interruption_kind") or ""),
            terminal_status=str(data.get("terminal_status") or ""),
            terminal_reason=str(data.get("terminal_reason") or ""),
            latest_progress=str(data.get("latest_progress") or ""),
            latest_step=str(data.get("latest_step") or ""),
            next_recommended_step=str(data.get("next_recommended_step") or ""),
            event_log_ref=str(data.get("event_log_ref") or data.get("turn_run_id") or ""),
            event_cursor=_int_value(data.get("event_cursor"), -1),
            model_visible_summary=str(data.get("model_visible_summary") or ""),
            created_at=float(data.get("created_at") or 0.0),
            updated_at=float(data.get("updated_at") or 0.0),
            diagnostics=dict(data.get("diagnostics") or {}),
        )
    except Exception:
        return None


def continuation_id_for_task_run(task_run_id: str, *, event_cursor: int = -1, control_version: int = 0) -> str:
    normalized = str(task_run_id or "").strip()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    cursor = max(-1, int(event_cursor or -1))
    version = max(0, int(control_version or 0))
    return f"cont:{digest}:{cursor}:{version}"


def continuation_id_for_turn_run(turn_run_id: str, *, event_cursor: int = -1, control_version: int = 0) -> str:
    normalized = str(turn_run_id or "").strip()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    cursor = max(-1, int(event_cursor or -1))
    version = max(0, int(control_version or 0))
    return f"turncont:{digest}:{cursor}:{version}"


def now_timestamp() -> float:
    return time.time()


def _state(value: Any) -> ContinuationState:
    raw = str(value or "").strip()
    if raw in {"recoverable", "waiting_approval", "paused", "blocked", "terminal_read_only"}:
        return raw  # type: ignore[return-value]
    return "none"


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
