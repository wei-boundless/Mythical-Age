from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.shared.events import RuntimeEvent

from .control_events import RuntimeSignalEnvelope, RuntimeSignalScope


@dataclass(frozen=True, slots=True)
class RuntimeControlSnapshot:
    run_id: str
    scope: RuntimeSignalScope
    pending_signals: tuple[RuntimeSignalEnvelope, ...]
    source_events: tuple[RuntimeEvent, ...]
    cursor_offset: int
    authority: str = "harness.runtime.control_snapshot"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scope": self.scope.to_dict(),
            "pending_signals": [signal.to_dict() for signal in self.pending_signals],
            "source_event_ids": [event.event_id for event in self.source_events],
            "cursor_offset": self.cursor_offset,
            "authority": self.authority,
        }
