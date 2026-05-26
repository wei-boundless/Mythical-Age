from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    approval_required_for_risky_tools: bool = True
    allowed_tool_names: tuple[str, ...] = ()
    allowed_operation_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_required_for_risky_tools": self.approval_required_for_risky_tools,
            "allowed_tool_names": list(self.allowed_tool_names),
            "allowed_operation_refs": list(self.allowed_operation_refs),
        }
