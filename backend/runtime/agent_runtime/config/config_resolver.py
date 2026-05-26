from __future__ import annotations

from typing import Any

from ..policies import ToolPolicy
from .presets import (
    default_closeout_policy,
    default_control_policy,
    default_evidence_policy,
    default_mode_policy,
    default_planning_policy,
    default_verification_policy,
    normalize_interaction_mode,
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
