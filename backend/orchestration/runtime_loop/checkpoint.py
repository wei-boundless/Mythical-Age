from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import RuntimeLoopState


@dataclass(frozen=True, slots=True)
class RuntimeCheckpoint:
    """Recovery snapshot for a TaskRunLoop event offset."""

    checkpoint_id: str
    task_run_id: str
    event_offset: int
    loop_state: RuntimeLoopState
    context_snapshot_ref: str = ""
    prompt_manifest_ref: str = ""
    approval_state: dict[str, Any] = field(default_factory=dict)
    commit_state: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    checksum: str = ""
    authority: str = "orchestration.runtime_checkpoint"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.runtime_checkpoint":
            raise ValueError("RuntimeCheckpoint authority must be orchestration.runtime_checkpoint")
        if not self.checkpoint_id:
            raise ValueError("RuntimeCheckpoint requires checkpoint_id")
        if not self.task_run_id:
            raise ValueError("RuntimeCheckpoint requires task_run_id")
        if self.event_offset < 0:
            raise ValueError("RuntimeCheckpoint event_offset must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["loop_state"] = self.loop_state.to_dict()
        return payload


class RuntimeCheckpointStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.checkpoint_dir = self.root_dir / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def write(self, state: RuntimeLoopState, *, event_offset: int) -> RuntimeCheckpoint:
        created_at = time.time()
        checkpoint_id = f"rtchk:{state.task_run_id}:{event_offset}"
        checkpoint = RuntimeCheckpoint(
            checkpoint_id=checkpoint_id,
            task_run_id=state.task_run_id,
            event_offset=event_offset,
            loop_state=state,
            context_snapshot_ref=state.context_snapshot_ref,
            prompt_manifest_ref=state.prompt_manifest_ref,
            approval_state=dict(state.pending_approval_state),
            commit_state=dict(state.commit_state),
            created_at=created_at,
            checksum=_checksum(state.to_dict(), event_offset=event_offset),
        )
        self._atomic_write(self._checkpoint_path(state.task_run_id), checkpoint.to_dict())
        return checkpoint

    def load_latest(self, task_run_id: str) -> RuntimeCheckpoint | None:
        path = self._checkpoint_path(task_run_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        state_payload = dict(payload.get("loop_state") or {})
        state = RuntimeLoopState(
            task_run_id=str(state_payload.get("task_run_id") or task_run_id),
            status=state_payload.get("status", "created"),
            turn_count=int(state_payload.get("turn_count") or 0),
            step_count=int(state_payload.get("step_count") or 0),
            current_step_id=str(state_payload.get("current_step_id") or ""),
            transition=state_payload.get("transition", "start"),
            terminal_reason=state_payload.get("terminal_reason", ""),
            messages_ref=str(state_payload.get("messages_ref") or ""),
            context_snapshot_ref=str(state_payload.get("context_snapshot_ref") or ""),
            memory_state_ref=str(state_payload.get("memory_state_ref") or ""),
            projection_ref=str(state_payload.get("projection_ref") or ""),
            prompt_manifest_ref=str(state_payload.get("prompt_manifest_ref") or ""),
            pending_action_requests=tuple(state_payload.get("pending_action_requests") or ()),
            pending_approval_state=dict(state_payload.get("pending_approval_state") or {}),
            denial_tracking_state=dict(state_payload.get("denial_tracking_state") or {}),
            token_pressure=dict(state_payload.get("token_pressure") or {}),
            compaction_state=dict(state_payload.get("compaction_state") or {}),
            result_refs=tuple(state_payload.get("result_refs") or ()),
            commit_state=dict(state_payload.get("commit_state") or {}),
            diagnostics=dict(state_payload.get("diagnostics") or {}),
        )
        return RuntimeCheckpoint(
            checkpoint_id=str(payload.get("checkpoint_id") or ""),
            task_run_id=str(payload.get("task_run_id") or task_run_id),
            event_offset=int(payload.get("event_offset") or 0),
            loop_state=state,
            context_snapshot_ref=str(payload.get("context_snapshot_ref") or ""),
            prompt_manifest_ref=str(payload.get("prompt_manifest_ref") or ""),
            approval_state=dict(payload.get("approval_state") or {}),
            commit_state=dict(payload.get("commit_state") or {}),
            created_at=float(payload.get("created_at") or 0.0),
            checksum=str(payload.get("checksum") or ""),
        )

    def _checkpoint_path(self, task_run_id: str) -> Path:
        return self.checkpoint_dir / f"{_safe_id(task_run_id)}.json"

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)


def _checksum(payload: dict[str, Any], *, event_offset: int) -> str:
    raw = json.dumps({"event_offset": event_offset, "state": payload}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))

