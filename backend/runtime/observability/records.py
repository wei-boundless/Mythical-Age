from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .context import ObservabilityContext


@dataclass(frozen=True, slots=True)
class ObservabilityRecord:
    record_id: str
    record_kind: str
    context: ObservabilityContext
    name: str
    status: str = ""
    summary: str = ""
    refs: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    retention_class: str = "diagnostic_ttl"
    visibility: str = "internal"
    authority: str = "runtime.observability.record"

    def __post_init__(self) -> None:
        if not self.record_id:
            raise ValueError("ObservabilityRecord requires record_id")
        if not self.record_kind:
            raise ValueError("ObservabilityRecord requires record_kind")
        if not self.name:
            raise ValueError("ObservabilityRecord requires name")
        if not self.created_at:
            object.__setattr__(self, "created_at", time.time())

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["context"] = self.context.to_dict()
        return payload
