from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class GoalHypothesis:
    task_goal_type: str
    task_domain: str
    confidence: float
    matched_by: tuple[str, ...] = ()
    supporting_evidence: tuple[str, ...] = ()
    rejection_reason: str = ""
    risks: tuple[str, ...] = ()
    authority: str = "intent.goal_hypothesis"

    def __post_init__(self) -> None:
        if self.authority != "intent.goal_hypothesis":
            raise ValueError("GoalHypothesis authority must be intent.goal_hypothesis")
        if not self.task_goal_type:
            raise ValueError("GoalHypothesis requires task_goal_type")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["matched_by"] = list(self.matched_by)
        payload["supporting_evidence"] = list(self.supporting_evidence)
        payload["risks"] = list(self.risks)
        return payload


@dataclass(frozen=True, slots=True)
class GoalHypothesisSet:
    hypothesis_set_id: str
    user_goal: str
    chosen: GoalHypothesis
    candidates: tuple[GoalHypothesis, ...] = ()
    rejected: tuple[GoalHypothesis, ...] = ()
    ambiguity_points: tuple[str, ...] = ()
    clarification_needed: bool = False
    clarification_question: str = ""
    authority: str = "intent.goal_hypothesis_set"

    def __post_init__(self) -> None:
        if self.authority != "intent.goal_hypothesis_set":
            raise ValueError("GoalHypothesisSet authority must be intent.goal_hypothesis_set")
        if not self.hypothesis_set_id:
            raise ValueError("GoalHypothesisSet requires hypothesis_set_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["chosen"] = self.chosen.to_dict()
        payload["candidates"] = [item.to_dict() for item in self.candidates]
        payload["rejected"] = [item.to_dict() for item in self.rejected]
        payload["ambiguity_points"] = list(self.ambiguity_points)
        return payload
