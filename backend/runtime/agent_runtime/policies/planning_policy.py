from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PlanningPolicy:
    required: bool = False
    allowed: bool = True
    plan_owner: str = "agent"
    review_owner: str = "system"

    def to_dict(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "allowed": self.allowed,
            "plan_owner": self.plan_owner,
            "review_owner": self.review_owner,
        }
