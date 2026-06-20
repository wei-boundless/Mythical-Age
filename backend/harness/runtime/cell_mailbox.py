from __future__ import annotations

from dataclasses import dataclass, field
import queue
import time
import uuid
from typing import Any, Callable


MailboxOverflowCallback = Callable[["CellMailboxItem", dict[str, Any]], None]


@dataclass(frozen=True, slots=True)
class CellMailboxItem:
    item_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    item_id: str = ""
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "item_type": self.item_type,
            "payload": dict(self.payload or {}),
            "created_at": self.created_at,
        }


class BoundedCellMailbox:
    def __init__(self, *, maxsize: int = 128, on_overflow: MailboxOverflowCallback | None = None) -> None:
        self.maxsize = max(1, int(maxsize or 128))
        self._queue: queue.Queue[CellMailboxItem] = queue.Queue(maxsize=self.maxsize)
        self._closed = False
        self._dropped_count = 0
        self._on_overflow = on_overflow

    def put(self, item_type: str, payload: dict[str, Any] | None = None) -> CellMailboxItem | None:
        if self._closed:
            return None
        item = CellMailboxItem(
            item_type=str(item_type or "").strip(),
            payload=dict(payload or {}),
            item_id=f"cellmsg:{uuid.uuid4().hex[:16]}",
            created_at=time.time(),
        )
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            self._dropped_count += 1
            callback = self._on_overflow
            if callable(callback):
                try:
                    callback(
                        item,
                        {
                            "queue_size": self.qsize(),
                            "maxsize": self.maxsize,
                            "dropped_count": self._dropped_count,
                        },
                    )
                except Exception:
                    pass
            return None
        return item

    def get_nowait(self) -> CellMailboxItem | None:
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def drain(self, *, limit: int = 100) -> list[CellMailboxItem]:
        items: list[CellMailboxItem] = []
        for _ in range(max(1, int(limit or 100))):
            item = self.get_nowait()
            if item is None:
                break
            items.append(item)
        return items

    def close(self) -> None:
        self._closed = True

    def qsize(self) -> int:
        return self._queue.qsize()

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    @property
    def closed(self) -> bool:
        return self._closed
