from __future__ import annotations

from typing import Any

from ..policies import (
    CloseoutPolicy,
    ControlPolicy,
    EvidencePolicy,
    ModePolicy,
    PlanningPolicy,
    ToolPolicy,
    VerificationPolicy,
)
from .profile import AgentRuntimeConfig, AgentRuntimeProfileConfig


def build_agent_runtime_config(
    *,
    selected_recipe_payload: dict[str, Any] | None = None,
    task_operation: dict[str, Any] | None = None,
    agent_runtime_spec: dict[str, Any] | None = None,
    execution_permit: dict[str, Any] | None = None,
) -> AgentRuntimeConfig:
    recipe = dict(selected_recipe_payload or {})
    operation = dict(task_operation or {})
    current_turn = dict(operation.get("current_turn_context") or {})
    metadata = dict(recipe.get("metadata") or {})
    mode_policy_payload = _first_dict(
        metadata.get("mode_policy"),
        current_turn.get("mode_policy"),
        operation.get("mode_policy"),
    )
    interaction_mode = normalize_interaction_mode(
        str(mode_policy_payload.get("interaction_mode") or "")
        or str(metadata.get("interaction_mode") or "")
        or str(recipe.get("task_mode") or "")
        or str(current_turn.get("interaction_mode") or "")
    )
    mode_policy = _mode_policy_from_payload(interaction_mode, mode_policy_payload)
    planning_policy = default_planning_policy(interaction_mode)
    evidence_policy = default_evidence_policy(interaction_mode)
    verification_policy = default_verification_policy(interaction_mode)
    closeout_policy = default_closeout_policy(interaction_mode)
    control_policy = default_control_policy(
        interaction_mode=interaction_mode,
        planning_policy=planning_policy,
        evidence_policy=evidence_policy,
        verification_policy=verification_policy,
        closeout_policy=closeout_policy,
    )
    tool_policy = _tool_policy_from_payload(
        _first_dict(
            metadata.get("tool_execution_policy"),
            mode_policy_payload.get("tool_policy"),
            current_turn.get("tool_policy"),
        )
    )
    spec = dict(agent_runtime_spec or operation.get("agent_runtime_spec") or {})
    return AgentRuntimeConfig(
        profile=AgentRuntimeProfileConfig(
            agent_id=str(spec.get("agent_id") or ""),
            agent_profile_id=str(spec.get("agent_profile_id") or ""),
            runtime_lane=str(spec.get("runtime_lane") or metadata.get("runtime_lane_hint") or ""),
        ),
        mode_policy=mode_policy,
        control_policy=control_policy,
        planning_policy=planning_policy,
        evidence_policy=evidence_policy,
        verification_policy=verification_policy,
        closeout_policy=closeout_policy,
        tool_policy=tool_policy,
        diagnostics={
            "source": "runtime.agent_runtime.config_resolver",
            "interaction_mode": interaction_mode,
            "execution_permit_ref": str(dict(execution_permit or {}).get("permit_id") or ""),
        },
    )


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


def _mode_policy_from_payload(interaction_mode: str, payload: dict[str, Any]) -> Any:
    base = default_mode_policy(interaction_mode)
    raw = dict(payload or {})
    return type(base)(
        interaction_mode=interaction_mode,
        prompt_profile=str(raw.get("prompt_profile") or base.prompt_profile),
        memory_scope=str(raw.get("memory_scope") or base.memory_scope),
        output_style=str(raw.get("output_style") or base.output_style),
        metadata={key: value for key, value in raw.items() if key not in {"interaction_mode", "prompt_profile", "memory_scope", "output_style"}},
    )


def _tool_policy_from_payload(payload: dict[str, Any]) -> ToolPolicy:
    raw = dict(payload or {})
    return ToolPolicy(
        approval_required_for_risky_tools=bool(raw.get("approval_required_for_risky_tools", True) is not False),
        allowed_tool_names=tuple(_string_list(raw.get("allowed_tool_names"))),
        allowed_operation_refs=tuple(_string_list(raw.get("allowed_operation_refs"))),
    )


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict) and value:
            return dict(value)
    return {}


def _string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in list(value or []) if str(item).strip()]
