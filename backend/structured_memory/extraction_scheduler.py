from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from typing import Callable

from .extractor import MemoryExtractor
from .models import Message


@dataclass(slots=True)
class ExtractionConfig:
    min_messages_between_runs: int = 4


class ExtractionScheduler:
    """Small coalescing scheduler for post-turn durable memory extraction."""

    def __init__(
        self,
        extractor: MemoryExtractor,
        config: ExtractionConfig | None = None,
        on_saved: Callable[[int], None] | None = None,
    ) -> None:
        self.extractor = extractor
        self.config = config or ExtractionConfig()
        self.on_saved = on_saved
        self._lock = threading.Lock()
        self._in_progress = False
        self._pending_messages: list[Message] | None = None
        self._messages_since_run = 0
        self._last_processed_signature: str | None = None

    def submit(self, messages: list[Message]) -> int:
        trailing: list[Message] | None = None
        total_saved = 0
        signature = self._signature(messages)
        with self._lock:
            if signature and signature == self._last_processed_signature:
                return 0
            self._messages_since_run += 1
            if self._in_progress:
                self._pending_messages = list(messages)
                return 0
            if self._messages_since_run < self.config.min_messages_between_runs:
                return 0
            self._in_progress = True
            self._messages_since_run = 0
            trailing = list(messages)

        while trailing is not None:
            saved_notes = self.extractor.save_extracted(trailing)
            saved_count = len(saved_notes)
            total_saved += saved_count
            self._last_processed_signature = self._signature(trailing)
            if saved_count and self.on_saved is not None:
                self.on_saved(saved_count)
            with self._lock:
                if self._pending_messages is None:
                    self._in_progress = False
                    trailing = None
                else:
                    trailing = self._pending_messages
                    self._pending_messages = None

        return total_saved

    def _signature(self, messages: list[Message]) -> str:
        visible_parts = [
            f"{msg.role}:{msg.content.strip()}"
            for msg in messages
            if msg.role in {"user", "assistant"} and msg.content.strip()
        ]
        if not visible_parts:
            return ""
        joined = "\n".join(visible_parts[-12:])
        return hashlib.sha1(joined.encode("utf-8")).hexdigest()
