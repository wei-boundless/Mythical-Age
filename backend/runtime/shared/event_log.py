from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import threading
import time
import uuid
from pathlib import Path
from json import JSONDecodeError
from typing import Any

from .event_index import RuntimeEventIndex, read_event_tail_raw
from .event_payload_store import RuntimeEventPayloadStore
from .events import RuntimeEvent, RuntimeEventType


@dataclass(slots=True)
class RuntimeEventSubscription:
    subscription_id: str
    queue: asyncio.Queue[RuntimeEvent]
    loop: asyncio.AbstractEventLoop | None = None
    run_id: str = ""


class RuntimeEventLog:
    """JSONL event log for Harness traces."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.event_dir = self.root_dir / "events"
        self.event_dir.mkdir(parents=True, exist_ok=True)
        self.index = RuntimeEventIndex(self.root_dir)
        self.payload_store = RuntimeEventPayloadStore(self.root_dir)
        self._subscriptions: list[RuntimeEventSubscription] = []
        self._subscription_lock = threading.RLock()
        self._write_lock = threading.RLock()

    def append(
        self,
        run_id: str,
        event_type: RuntimeEventType,
        *,
        payload: dict[str, Any] | None = None,
        refs: dict[str, Any] | None = None,
    ) -> RuntimeEvent:
        with self._write_lock:
            path = self._event_path(run_id)
            offset = self.index.next_offset(run_id=run_id, event_path=path)
            event = RuntimeEvent(
                event_id=f"rtevt:{run_id}:{offset}:{uuid.uuid4().hex[:8]}",
                run_id=run_id,
                event_type=event_type,
                offset=offset,
                created_at=time.time(),
                payload={},
                refs={},
            )
            compact_payload, compact_refs = self.payload_store.externalize_if_needed(
                run_id=run_id,
                event_id=event.event_id,
                offset=offset,
                event_type=str(event_type),
                payload=dict(payload or {}),
                refs=dict(refs or {}),
            )
            event = RuntimeEvent(
                event_id=event.event_id,
                run_id=event.run_id,
                event_type=event.event_type,
                offset=event.offset,
                created_at=event.created_at,
                payload=compact_payload,
                refs=compact_refs,
            )
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
            self.index.record_append(event, event_path=path)
        self._publish(event)
        return event

    def subscribe(self, *, run_id: str = "", max_queue_size: int = 500) -> RuntimeEventSubscription:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        subscription = RuntimeEventSubscription(
            subscription_id=f"rtesub:{uuid.uuid4().hex}",
            queue=asyncio.Queue(maxsize=max(1, int(max_queue_size or 500))),
            loop=loop,
            run_id=run_id.strip(),
        )
        with self._subscription_lock:
            self._subscriptions.append(subscription)
        return subscription

    def unsubscribe(self, subscription: RuntimeEventSubscription) -> None:
        with self._subscription_lock:
            self._subscriptions = [
                item for item in self._subscriptions if item.subscription_id != subscription.subscription_id
            ]

    def list_events(self, run_id: str) -> list[RuntimeEvent]:
        path = self._event_path(run_id)
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
                self._event_from_payload(
                    self.payload_store.hydrate_event_payload(payload if isinstance(payload, dict) else {}),
                    run_id=run_id,
                )
            )
        return events

    def list_event_window(self, run_id: str, *, limit: int = 240, include_payloads: bool = False) -> list[RuntimeEvent]:
        if include_payloads:
            return [
                self._event_from_payload(self.payload_store.hydrate_event_payload(item), run_id=run_id)
                for item in read_event_tail_raw(self._event_path(run_id), tail_limit=max(1, int(limit or 240)))
            ]
        return self.list_recent_events(run_id, limit=limit)

    def list_recent_events(self, run_id: str, *, limit: int = 160) -> list[RuntimeEvent]:
        if max(1, int(limit or 160)) <= 0:
            return []
        path = self._event_path(run_id)
        if not path.exists():
            return []
        events = self.index.list_recent_events(run_id, limit=max(1, int(limit or 160)), event_path=path)
        if events:
            return events
        self.index.next_offset(run_id=run_id, event_path=path)
        return self.index.list_recent_events(run_id, limit=max(1, int(limit or 160)), event_path=path)

    def event_count(self, run_id: str) -> int:
        return self.index.event_count(run_id, event_path=self._event_path(run_id))

    def estimated_event_count(self, run_id: str) -> int:
        return self.index.estimated_event_count(run_id, event_path=self._event_path(run_id))

    def delete_events(self, run_id: str) -> bool:
        path = self._event_path(run_id)
        if not path.exists():
            return False
        with self._write_lock:
            path.unlink(missing_ok=True)
            self.index.delete_index(run_id)
            self.payload_store.delete_payloads_for_run(run_id)
        return True

    def next_offset(self, run_id: str) -> int:
        return self.index.next_offset(run_id=run_id, event_path=self._event_path(run_id))

    def _publish(self, event: RuntimeEvent) -> None:
        with self._subscription_lock:
            subscriptions = list(self._subscriptions)
        if not subscriptions:
            return
        for subscription in subscriptions:
            if subscription.run_id and subscription.run_id != event.run_id:
                continue
            if subscription.loop is not None and subscription.loop.is_running():
                subscription.loop.call_soon_threadsafe(_put_event_drop_oldest, subscription.queue, event)
                continue
            _put_event_drop_oldest(subscription.queue, event)

    def _event_path(self, run_id: str) -> Path:
        return self.event_dir / f"{_safe_id(run_id)}.jsonl"

    def _event_from_payload(self, payload: dict[str, Any], *, run_id: str) -> RuntimeEvent:
        return RuntimeEvent(
            event_id=str(payload.get("event_id") or ""),
            run_id=str(payload.get("run_id") or payload.get("task_run_id") or run_id),
            event_type=payload.get("event_type", "loop_error"),
            offset=int(payload.get("offset") or 0),
            created_at=float(payload.get("created_at") or 0.0),
            payload=dict(payload.get("payload") or {}),
            refs=dict(payload.get("refs") or {}),
        )


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


