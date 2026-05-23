from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskGoalDeliverable:
    deliverable_id: str
    title: str
    kind: str
    role: str = "core"
    required: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskGoalCriterion:
    criterion_id: str
    title: str
    verification_kind: str = "evidence"
    required: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskGoalFrame:
    user_goal: str
    goal_summary: str
    task_goal_type: str
    task_domain: str
    task_understanding_frame_ref: str = ""
    task_understanding_frame: dict[str, Any] = field(default_factory=dict)
    goal_hypothesis_set_ref: str = ""
    complexity: str = "short"
    core_deliverables: tuple[TaskGoalDeliverable, ...] = ()
    supporting_deliverables: tuple[TaskGoalDeliverable, ...] = ()
    success_criteria: tuple[TaskGoalCriterion, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    required_verifications: tuple[TaskGoalCriterion, ...] = ()
    explicit_constraints: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    rejected_goal_candidates: tuple[dict[str, Any], ...] = ()
    unacceptable_outcomes: tuple[str, ...] = ()
    ambiguity_points: tuple[str, ...] = ()
    clarification_policy: dict[str, Any] = field(default_factory=dict)
    stage_prompt_profiles: tuple[dict[str, Any], ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    authority: str = "intent.task_goal_frame"

    def __post_init__(self) -> None:
        if self.authority != "intent.task_goal_frame":
            raise ValueError("TaskGoalFrame authority must be intent.task_goal_frame")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["task_understanding_frame"] = dict(self.task_understanding_frame or {})
        payload["core_deliverables"] = [item.to_dict() for item in self.core_deliverables]
        payload["supporting_deliverables"] = [item.to_dict() for item in self.supporting_deliverables]
        payload["success_criteria"] = [item.to_dict() for item in self.success_criteria]
        payload["required_verifications"] = [item.to_dict() for item in self.required_verifications]
        payload["required_capabilities"] = list(self.required_capabilities)
        payload["explicit_constraints"] = list(self.explicit_constraints)
        payload["forbidden_actions"] = list(self.forbidden_actions)
        payload["rejected_goal_candidates"] = [dict(item) for item in self.rejected_goal_candidates]
        payload["unacceptable_outcomes"] = list(self.unacceptable_outcomes)
        payload["ambiguity_points"] = list(self.ambiguity_points)
        payload["clarification_policy"] = dict(self.clarification_policy or {})
        payload["stage_prompt_profiles"] = [dict(item) for item in self.stage_prompt_profiles]
        return payload
