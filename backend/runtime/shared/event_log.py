from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
from json import JSONDecodeError
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .events import RuntimeEvent, RuntimeEventType


@dataclass(slots=True)
class RuntimeEventSubscription:
    subscription_id: str
    queue: asyncio.Queue[RuntimeEvent]
    loop: asyncio.AbstractEventLoop | None = None
    task_run_id: str = ""


class RuntimeEventLog:
    """JSONL event log for Harness traces."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.event_dir = self.root_dir / "events"
        self.event_dir.mkdir(parents=True, exist_ok=True)
        self._subscriptions: list[RuntimeEventSubscription] = []
        self._subscription_lock = threading.RLock()
        self._write_lock = threading.RLock()

    def append(
        self,
        task_run_id: str,
        event_type: RuntimeEventType,
        *,
        payload: dict[str, Any] | None = None,
        refs: dict[str, Any] | None = None,
    ) -> RuntimeEvent:
        with self._write_lock:
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
        self._publish(event)
        return event

    def subscribe(self, *, task_run_id: str = "", max_queue_size: int = 500) -> RuntimeEventSubscription:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        subscription = RuntimeEventSubscription(
            subscription_id=f"rtesub:{uuid.uuid4().hex}",
            queue=asyncio.Queue(maxsize=max(1, int(max_queue_size or 500))),
            loop=loop,
            task_run_id=task_run_id.strip(),
        )
        with self._subscription_lock:
            self._subscriptions.append(subscription)
        return subscription

    def unsubscribe(self, subscription: RuntimeEventSubscription) -> None:
        with self._subscription_lock:
            self._subscriptions = [
                item for item in self._subscriptions if item.subscription_id != subscription.subscription_id
            ]

    def list_events(self, task_run_id: str) -> list[RuntimeEvent]:
        path = self._event_path(task_run_id)
        if not path.exists():
            return []
        events: list[RuntimeEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except JSONDecodeError:
                continue
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
        path = self._event_path(task_run_id)
        if not path.exists():
            return 0
        physical_line_count = 0
        max_seen_offset = -1
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            physical_line_count += 1
            try:
                payload = json.loads(stripped)
            except JSONDecodeError:
                continue
            try:
                max_seen_offset = max(max_seen_offset, int(payload.get("offset") or 0))
            except (TypeError, ValueError):
                continue
        return max(physical_line_count, max_seen_offset + 1)

    def _publish(self, event: RuntimeEvent) -> None:
        with self._subscription_lock:
            subscriptions = list(self._subscriptions)
        if not subscriptions:
            return
        for subscription in subscriptions:
            if subscription.task_run_id and subscription.task_run_id != event.task_run_id:
                continue
            if subscription.loop is not None and subscription.loop.is_running():
                subscription.loop.call_soon_threadsafe(_put_event_drop_oldest, subscription.queue, event)
                continue
            _put_event_drop_oldest(subscription.queue, event)

    def _event_path(self, task_run_id: str) -> Path:
        return self.event_dir / f"{_safe_id(task_run_id)}.jsonl"


def _put_event_drop_oldest(queue: asyncio.Queue[RuntimeEvent], event: RuntimeEvent) -> None:
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        pass


def _safe_id(value: str, *, limit: int = 180) -> str:
    raw = str(value or "")
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw).strip("_")
    if not safe:
        return "runtime"
    if len(safe) <= limit:
        return safe
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    head_limit = max(1, limit - len(digest) - 1)
    return f"{safe[:head_limit].rstrip('_')}_{digest}"


