from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class EvidencePolicy:
    required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"required": self.required}
