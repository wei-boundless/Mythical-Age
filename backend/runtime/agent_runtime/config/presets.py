from __future__ import annotations

from ..policies import (
    CloseoutPolicy,
    ControlPolicy,
    EvidencePolicy,
    PlanningPolicy,
    VerificationPolicy,
)
from .mode_policy import ModePolicy


def normalize_interaction_mode(value: str) -> str:
    mode = str(value or "").strip()
    if mode in {"role_mode", "standard_mode", "professional_mode"}:
        return mode
    return "standard_mode"


def default_mode_policy(interaction_mode: str) -> ModePolicy:
    mode = normalize_interaction_mode(interaction_mode)
    if mode == "role_mode":
        return ModePolicy(
            interaction_mode=mode,
            prompt_profile="role_profile",
            memory_scope="role_scoped",
            output_style="role_boundary",
        )
    if mode == "professional_mode":
        return ModePolicy(interaction_mode=mode, prompt_profile="professional_profile")
    return ModePolicy(interaction_mode="standard_mode")


def default_planning_policy(interaction_mode: str) -> PlanningPolicy:
    mode = normalize_interaction_mode(interaction_mode)
    if mode == "professional_mode":
        return PlanningPolicy(required=True, allowed=True, plan_owner="agent", review_owner="system")
    return PlanningPolicy(required=False, allowed=True, plan_owner="agent", review_owner="system")


def default_evidence_policy(interaction_mode: str) -> EvidencePolicy:
    return EvidencePolicy(required=normalize_interaction_mode(interaction_mode) == "professional_mode")


def default_verification_policy(interaction_mode: str) -> VerificationPolicy:
    if normalize_interaction_mode(interaction_mode) == "professional_mode":
        return VerificationPolicy(required=True, mode="required")
    return VerificationPolicy(required=False, mode="task_or_tool_dependent")


def default_closeout_policy(interaction_mode: str) -> CloseoutPolicy:
    required = normalize_interaction_mode(interaction_mode) == "professional_mode"
    return CloseoutPolicy(required=required, strict=required)


def default_control_policy(
    *,
    interaction_mode: str,
    planning_policy: PlanningPolicy,
    evidence_policy: EvidencePolicy,
    verification_policy: VerificationPolicy,
    closeout_policy: CloseoutPolicy,
) -> ControlPolicy:
    return ControlPolicy(
        planning_required=planning_policy.required,
        planning_allowed=planning_policy.allowed,
        evidence_required=evidence_policy.required,
        verification_required=verification_policy.required,
        closeout_required=closeout_policy.required,
        followup_allowed=True,
    )
