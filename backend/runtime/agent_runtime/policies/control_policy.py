from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ControlPolicy:
    planning_required: bool = False
    planning_allowed: bool = True
    evidence_required: bool = False
    verification_required: bool = False
    closeout_required: bool = False
    followup_allowed: bool = True
    max_model_turns: int = 0
    max_tool_calls: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "planning_required": self.planning_required,
            "planning_allowed": self.planning_allowed,
            "evidence_required": self.evidence_required,
            "verification_required": self.verification_required,
            "closeout_required": self.closeout_required,
            "followup_allowed": self.followup_allowed,
            "max_model_turns": self.max_model_turns,
            "max_tool_calls": self.max_tool_calls,
        }
