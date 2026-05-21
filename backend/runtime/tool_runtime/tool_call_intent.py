from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolCallIntent:
    call_id: str
    tool_name: str
    args: dict[str, Any] = field(default_factory=dict)
    provider: str = ""
    source: str = "native_tool_call"
    raw_ref: str = ""
    protocol_violation: bool = False
    violation_reason: str = ""
    authority: str = "execution.tool_call_intent"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)