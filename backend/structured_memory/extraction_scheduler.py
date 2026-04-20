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
        self._last_processed_cursor: str | None = None
        self._last_pending_signature: str | None = None
        self._last_run_status: str = "idle"
        self._last_error: str = ""

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
                self._last_pending_signature = signature or None
                return 0
            if self._messages_since_run < self.config.min_messages_between_runs:
                return 0
            self._in_progress = True
            self._messages_since_run = 0
            trailing = list(messages)

        while trailing is not None:
            run_failed = False
            try:
                saved_notes = self.extractor.save_extracted(trailing)
                saved_count = len(saved_notes)
            except Exception as exc:
                saved_notes = []
                saved_count = 0
                run_failed = True
                self._last_run_status = "failed"
                self._last_error = f"{type(exc).__name__}: {exc}"

            total_saved += saved_count
            if not run_failed:
                self._last_processed_signature = self._signature(trailing)
                self._last_processed_cursor = self._cursor(trailing)
                self._last_run_status = "completed"
                self._last_error = ""
            if saved_count and self.on_saved is not None:
                self.on_saved(saved_count)
            with self._lock:
                if self._pending_messages is None:
                    self._in_progress = False
                    trailing = None
                else:
                    trailing = self._pending_messages
                    self._pending_messages = None
                    self._last_pending_signature = None

        return total_saved

    def describe_runtime_state(self) -> dict[str, object]:
        with self._lock:
            pending_count = len(self._pending_messages or [])
            pending_signature = self._last_pending_signature
            in_progress = self._in_progress
            messages_since_run = self._messages_since_run
        return {
            "in_progress": in_progress,
            "messages_since_run": messages_since_run,
            "has_pending_messages": pending_count > 0,
            "pending_message_count": pending_count,
            "last_processed_signature": self._last_processed_signature or "",
            "last_processed_cursor": self._last_processed_cursor or "",
            "last_processed_message_cursor": self._last_processed_cursor or "",
            "last_pending_signature": pending_signature or "",
            "last_run_status": self._last_run_status,
            "last_error": self._last_error,
        }

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

    def _cursor(self, messages: list[Message]) -> str:
        visible_parts = [
            f"{msg.role}:{msg.content.strip()}"
            for msg in messages
            if msg.role in {"user", "assistant"} and msg.content.strip()
        ]
        if not visible_parts:
            return ""
        return visible_parts[-1][:240]
