from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_CHECKPOINT_LOCK = threading.RLock()


@dataclass(frozen=True, slots=True)
class CoordinationCheckpoint:
    thread_id: str
    checkpoint_id: str
    state: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "checkpoint_id": self.checkpoint_id,
            "state": dict(self.state),
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "authority": "harness.graph_coordination_checkpoint",
        }


class GraphCoordinationCheckpointStore:
    """Durable coordination checkpoint store keyed by graph thread_id.

    This adapter keeps the graph checkpoint surface small while preserving the
    physical LangGraph `thread_id` key used by the kernel.
    """

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.checkpoint_dir = self.root_dir / "coordination_checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def put_state(
        self,
        *,
        thread_id: str,
        state: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> CoordinationCheckpoint:
        cleaned_thread_id = str(thread_id or "").strip()
        if not cleaned_thread_id:
            raise ValueError("coordination checkpoint requires thread_id")
        checkpoint = CoordinationCheckpoint(
            thread_id=cleaned_thread_id,
            checkpoint_id=f"coordchk:{cleaned_thread_id}:{uuid.uuid4().hex[:10]}",
            state=dict(state or {}),
            metadata=dict(metadata or {}),
            created_at=time.time(),
        )
        self._atomic_write(self._path(cleaned_thread_id), checkpoint.to_dict())
        return checkpoint

    def get_state(self, *, thread_id: str) -> dict[str, Any]:
        checkpoint = self.get_checkpoint(thread_id=thread_id)
        return dict(checkpoint.state) if checkpoint is not None else {}

    def get_checkpoint(self, *, thread_id: str) -> CoordinationCheckpoint | None:
        path = self._path(str(thread_id or "").strip())
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return CoordinationCheckpoint(
            thread_id=str(payload.get("thread_id") or ""),
            checkpoint_id=str(payload.get("checkpoint_id") or ""),
            state=dict(payload.get("state") or {}),
            metadata=dict(payload.get("metadata") or {}),
            created_at=float(payload.get("created_at") or 0.0),
        )

    def _path(self, thread_id: str) -> Path:
        return self.checkpoint_dir / f"{_safe_id(thread_id)}.json"

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        with _CHECKPOINT_LOCK:
            tmp.write_text(text, encoding="utf-8")
            last_error: OSError | None = None
            for attempt in range(8):
                try:
                    os.replace(tmp, path)
                    return
                except PermissionError as exc:
                    last_error = exc
                    time.sleep(0.05 * (attempt + 1))
            try:
                path.write_text(text, encoding="utf-8")
                tmp.unlink(missing_ok=True)
            except OSError as exc:
                tmp.unlink(missing_ok=True)
                if last_error is not None:
                    raise last_error from exc
                raise


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))[:180]




