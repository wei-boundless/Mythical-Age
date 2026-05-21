from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .events import RuntimeEvent, RuntimeEventType


class RuntimeEventLog:
    """JSONL event log for TaskRunLoop traces."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.event_dir = self.root_dir / "events"
        self.event_dir.mkdir(parents=True, exist_ok=True)

    def append(
        self,
        task_run_id: str,
        event_type: RuntimeEventType,
        *,
        payload: dict[str, Any] | None = None,
        refs: dict[str, Any] | None = None,
    ) -> RuntimeEvent:
        offset = self.next_offset(task_run_id)
        event = RuntimeEvent(
            event_id=f"rtevt:{task_run_id}:{offset}:{uuid.uuid4().hex[:8]}",
            task_run_id=task_run_id,
            event_type=event_type,
            offset=offset,
            created_at=time.time(),
            payload=dict(payload or {}),
            refs=dict(refs or {}),
        )
        path = self._event_path(task_run_id)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        return event

    def list_events(self, task_run_id: str) -> list[RuntimeEvent]:
        path = self._event_path(task_run_id)
        if not path.exists():
            return []
        events: list[RuntimeEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            events.append(
                RuntimeEvent(
                    event_id=str(payload.get("event_id") or ""),
                    task_run_id=str(payload.get("task_run_id") or task_run_id),
                    event_type=payload.get("event_type", "loop_error"),
                    offset=int(payload.get("offset") or 0),
                    created_at=float(payload.get("created_at") or 0.0),
                    payload=dict(payload.get("payload") or {}),
                    refs=dict(payload.get("refs") or {}),
                )
            )
        return events

    def next_offset(self, task_run_id: str) -> int:
        return len(self.list_events(task_run_id))

    def _event_path(self, task_run_id: str) -> Path:
        return self.event_dir / f"{_safe_id(task_run_id)}.jsonl"


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))

