from __future__ import annotations

import time
import asyncio
from dataclasses import dataclass
import threading
import uuid
from typing import Any


FILE_CHANGE_RECORDED_EVENT = "file_change_recorded"


@dataclass(slots=True)
class FileChangeSignalSubscription:
    subscription_id: str
    queue: asyncio.Queue[dict[str, Any]]
    loop: asyncio.AbstractEventLoop | None = None


class FileChangeSignalHub:
    def __init__(self) -> None:
        self._subscriptions: list[FileChangeSignalSubscription] = []
        self._lock = threading.RLock()

    def subscribe(self, *, max_queue_size: int = 200) -> FileChangeSignalSubscription:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        subscription = FileChangeSignalSubscription(
            subscription_id=f"filechangesub:{uuid.uuid4().hex}",
            queue=asyncio.Queue(maxsize=max(1, int(max_queue_size or 200))),
            loop=loop,
        )
        with self._lock:
            self._subscriptions.append(subscription)
        return subscription

    def unsubscribe(self, subscription: FileChangeSignalSubscription) -> None:
        with self._lock:
            self._subscriptions = [
                item for item in self._subscriptions if item.subscription_id != subscription.subscription_id
            ]

    def publish(self, payload: dict[str, Any]) -> None:
        signal = dict(payload or {})
        with self._lock:
            subscriptions = list(self._subscriptions)
        for subscription in subscriptions:
            if subscription.loop is not None and subscription.loop.is_running():
                subscription.loop.call_soon_threadsafe(_put_signal_drop_oldest, subscription.queue, signal)
                continue
            _put_signal_drop_oldest(subscription.queue, signal)


_FILE_CHANGE_SIGNAL_HUB = FileChangeSignalHub()


def subscribe_file_change_signals(*, max_queue_size: int = 200) -> FileChangeSignalSubscription:
    return _FILE_CHANGE_SIGNAL_HUB.subscribe(max_queue_size=max_queue_size)


def unsubscribe_file_change_signals(subscription: FileChangeSignalSubscription) -> None:
    _FILE_CHANGE_SIGNAL_HUB.unsubscribe(subscription)


def publish_file_change_record(
    runtime_or_host: Any,
    record: dict[str, Any],
    *,
    action: str,
    source: str,
) -> dict[str, Any]:
    normalized = dict(record or {})
    record_id = str(normalized.get("record_id") or "").strip()
    if not record_id:
        return {"published": False, "reason": "missing_record_id", "authority": "runtime.file_change_signal"}
    host = _runtime_host(runtime_or_host)
    event_log = getattr(host, "event_log", None)
    append = getattr(event_log, "append", None)
    if not callable(append):
        return {"published": False, "reason": "event_log_unavailable", "authority": "runtime.file_change_signal"}
    run_id = _file_change_run_id(normalized)
    payload = {
        "file_change_record": normalized,
        "record_id": record_id,
        "session_id": str(normalized.get("session_id") or ""),
        "task_run_id": str(normalized.get("task_run_id") or ""),
        "logical_path": str(normalized.get("logical_path") or ""),
        "action": str(action or "recorded"),
        "source": str(source or "runtime"),
        "updated_at": time.time(),
        "authority": "runtime.file_change_signal",
    }
    publish_payload = {
        **payload,
        "event_type": FILE_CHANGE_RECORDED_EVENT,
        "event_id": "",
        "event_offset": 0,
        "run_id": run_id,
        "source": str(source or "runtime"),
    }
    try:
        event = append(
            run_id,
            FILE_CHANGE_RECORDED_EVENT,  # type: ignore[arg-type]
            payload=payload,
            refs={
                "session_id": payload["session_id"],
                "task_run_id": payload["task_run_id"],
                "file_change_record_id": record_id,
            },
        )
    except Exception as exc:
        return {
            "published": False,
            "reason": "event_log_append_failed",
            "error": str(exc),
            "authority": "runtime.file_change_signal",
        }
    publish_payload.update(
        {
            "event_id": str(getattr(event, "event_id", "") or ""),
            "event_offset": int(getattr(event, "offset", 0) or 0),
            "run_id": str(getattr(event, "run_id", "") or run_id),
        }
    )
    _FILE_CHANGE_SIGNAL_HUB.publish(publish_payload)
    return {
        "published": True,
        "event_id": str(getattr(event, "event_id", "") or ""),
        "run_id": str(getattr(event, "run_id", "") or run_id),
        "record_id": record_id,
        "authority": "runtime.file_change_signal",
    }


def _runtime_host(runtime_or_host: Any) -> Any:
    harness_runtime = getattr(runtime_or_host, "harness_runtime", None)
    host = getattr(harness_runtime, "single_agent_runtime_host", None)
    return host or runtime_or_host


def _file_change_run_id(record: dict[str, Any]) -> str:
    task_run_id = str(record.get("task_run_id") or "").strip()
    if task_run_id:
        return task_run_id
    session_id = str(record.get("session_id") or "").strip()
    if session_id:
        return f"session:{session_id}:file_changes"
    agent_run_id = str(record.get("agent_run_id") or "").strip()
    if agent_run_id:
        return agent_run_id
    return "file_changes"


def _put_signal_drop_oldest(queue: asyncio.Queue[dict[str, Any]], payload: dict[str, Any]) -> None:
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    try:
        queue.put_nowait(dict(payload or {}))
    except asyncio.QueueFull:
        pass
