from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ModePolicy:
    interaction_mode: str = "standard_mode"
    prompt_profile: str = ""
    memory_scope: str = ""
    output_style: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "interaction_mode": self.interaction_mode,
            "prompt_profile": self.prompt_profile,
            "memory_scope": self.memory_scope,
            "output_style": self.output_style,
            "metadata": dict(self.metadata),
        }


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


@dataclass(frozen=True, slots=True)
class EvidencePolicy:
    required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"required": self.required}


@dataclass(frozen=True, slots=True)
class VerificationPolicy:
    required: bool = False
    mode: str = "task_or_tool_dependent"

    def to_dict(self) -> dict[str, Any]:
        return {"required": self.required, "mode": self.mode}


@dataclass(frozen=True, slots=True)
class CloseoutPolicy:
    required: bool = False
    strict: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"required": self.required, "strict": self.strict}


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

__all__ = [
    "CloseoutPolicy",
    "ControlPolicy",
    "EvidencePolicy",
    "ModePolicy",
    "PlanningPolicy",
    "ToolPolicy",
    "VerificationPolicy",
]
