from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..policies import (
    CloseoutPolicy,
    ControlPolicy,
    EvidencePolicy,
    PlanningPolicy,
    ToolPolicy,
    VerificationPolicy,
)
from .mode_policy import ModePolicy


@dataclass(frozen=True, slots=True)
class AgentRuntimeProfileConfig:
    agent_id: str = ""
    agent_profile_id: str = ""
    runtime_lane: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_profile_id": self.agent_profile_id,
            "runtime_lane": self.runtime_lane,
        }


@dataclass(frozen=True, slots=True)
class AgentRuntimeConfig:
    profile: AgentRuntimeProfileConfig = field(default_factory=AgentRuntimeProfileConfig)
    mode_policy: ModePolicy = field(default_factory=ModePolicy)
    control_policy: ControlPolicy = field(default_factory=ControlPolicy)
    planning_policy: PlanningPolicy = field(default_factory=PlanningPolicy)
    evidence_policy: EvidencePolicy = field(default_factory=EvidencePolicy)
    verification_policy: VerificationPolicy = field(default_factory=VerificationPolicy)
    closeout_policy: CloseoutPolicy = field(default_factory=CloseoutPolicy)
    tool_policy: ToolPolicy = field(default_factory=ToolPolicy)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def interaction_mode(self) -> str:
        return self.mode_policy.interaction_mode

    @property
    def enabled_phases(self) -> tuple[str, ...]:
        phases = ["model_turn"]
        if self.planning_policy.required:
            phases.insert(0, "planning")
        if self.control_policy.followup_allowed:
            phases.append("tool_followup")
        if self.evidence_policy.required:
            phases.append("evidence")
        if self.verification_policy.required:
            phases.append("verification")
        if self.closeout_policy.required:
            phases.append("closeout")
        return tuple(dict.fromkeys(phases))

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.to_dict(),
            "mode_policy": self.mode_policy.to_dict(),
            "control_policy": self.control_policy.to_dict(),
            "planning_policy": self.planning_policy.to_dict(),
            "evidence_policy": self.evidence_policy.to_dict(),
            "verification_policy": self.verification_policy.to_dict(),
            "closeout_policy": self.closeout_policy.to_dict(),
            "tool_policy": self.tool_policy.to_dict(),
            "enabled_phases": list(self.enabled_phases),
            "diagnostics": dict(self.diagnostics),
            "authority": "runtime.agent_runtime.config",
        }
