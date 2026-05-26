from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class VerificationPolicy:
    required: bool = False
    mode: str = "task_or_tool_dependent"

    def to_dict(self) -> dict[str, Any]:
        return {"required": self.required, "mode": self.mode}
