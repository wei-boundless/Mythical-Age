from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .consolidation import ConsolidationReport, DurableMemoryConsolidator


@dataclass(slots=True)
class ConsolidationConfig:
    min_saved_notes_between_runs: int = 3
    min_seconds_between_runs: int = 1800


class ConsolidationScheduler:
    """Lightweight background scheduler for durable memory consolidation."""

    def __init__(
        self,
        root_dir: str | Path,
        config: ConsolidationConfig | None = None,
        on_completed: Callable[[ConsolidationReport], None] | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.config = config or ConsolidationConfig()
        self.on_completed = on_completed
        self._lock = threading.Lock()
        self._saved_since_run = 0
        self._last_run_at = 0.0
        self._in_progress = False
        self._last_report: ConsolidationReport | None = None

    def notify_saved(self, saved_count: int) -> bool:
        if saved_count <= 0:
            return False

        with self._lock:
            self._saved_since_run += saved_count
            if self._in_progress:
                return False
            if self._saved_since_run < self.config.min_saved_notes_between_runs:
                return False
            now = time.time()
            if (now - self._last_run_at) < self.config.min_seconds_between_runs:
                return False
            self._in_progress = True
            self._saved_since_run = 0

        threading.Thread(
            target=self._run_background,
            name="durable-memory-consolidation",
            daemon=True,
        ).start()
        return True

    def last_report(self) -> ConsolidationReport | None:
        with self._lock:
            return self._last_report

    def _run_background(self) -> None:
        report: ConsolidationReport | None = None
        try:
            report = DurableMemoryConsolidator(self.root_dir).run()
            if self.on_completed is not None:
                self.on_completed(report)
        finally:
            with self._lock:
                self._in_progress = False
                self._last_run_at = time.time()
                self._last_report = report
