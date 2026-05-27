from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ModelToolCallAccumulator:
    pending_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    assistant_content: str = ""
    assistant_additional_kwargs: dict[str, Any] = field(default_factory=dict)

    def ingest_event(self, event: dict[str, Any]) -> None:
        if str(event.get("type") or "") != "tool_call_requested":
            return
        tool_call = dict(event.get("tool_call") or {})
        if tool_call:
            self.pending_tool_calls.append(tool_call)
        self.assistant_content = str(event.get("assistant_content") or self.assistant_content)
        event_kwargs = dict(event.get("assistant_additional_kwargs") or {})
        if event_kwargs:
            self.assistant_additional_kwargs.update(event_kwargs)
