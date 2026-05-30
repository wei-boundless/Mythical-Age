from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


ROLE_MODE = "role"
STANDARD_MODE = "standard"
PROFESSIONAL_MODE = "professional"
CUSTOM_MODE = "custom"
DEFAULT_RUNTIME_MODE = CUSTOM_MODE
RUNTIME_MODE_ORDER = (ROLE_MODE, STANDARD_MODE, PROFESSIONAL_MODE, CUSTOM_MODE)


@dataclass(frozen=True, slots=True)
class AgentRuntimeModeConfig:
    mode: str
    label: str
    interaction_mode: str
    recipe_id: str
    projection_strength: str
    execution_strategy: str = ""
    default_environment_id: str = ""
    interaction_policy: dict[str, Any] | None = None
    planning_policy: dict[str, Any] | None = None
    task_lifecycle_policy: dict[str, Any] | None = None
    tool_exposure_policy: dict[str, Any] | None = None
    context_policy: dict[str, Any] | None = None
    memory_policy: dict[str, Any] | None = None
    self_review_policy: dict[str, Any] | None = None
    step_summary_policy: dict[str, Any] | None = None
    approval_policy: dict[str, Any] | None = None
    prompt_pack_refs_by_invocation: dict[str, Any] | None = None
    builtin: bool = True
    editable: bool = False
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


MODE_CONFIGS: dict[str, AgentRuntimeModeConfig] = {
    ROLE_MODE: AgentRuntimeModeConfig(
        mode=ROLE_MODE,
        label="角色模式",
        interaction_mode="role_mode",
        recipe_id="runtime.recipe.role_interaction",
        projection_strength="primary",
        interaction_policy={
            "style": "role_conversation",
            "task_orientation": "conversation_first",
            "user_clarification": "allowed",
        },
        planning_policy={"plan_mode": "disabled", "specified_plan_allowed": False},
        task_lifecycle_policy={"request_task_run": False, "requires_completion_evidence": False},
        tool_exposure_policy={},
        context_policy={
            "history_scope": "conversation",
            "task_context": "disabled",
            "task_run_context": "disabled",
            "active_work_context": "disabled",
        },
        memory_policy={"read_scope": "conversation_readonly", "write_scope": "none"},
        self_review_policy={"enabled": False, "before_final": "basic_consistency"},
        step_summary_policy={"enabled": True, "detail": "compact"},
        approval_policy={"permission_scope": "role_conversation_readonly"},
        prompt_pack_refs_by_invocation={
            "turn_action": ("runtime.pack.turn_action.v1",),
            "task_execution": ("runtime.pack.task_execution.v1",),
            "tool_observation_followup": ("runtime.pack.observation_followup.v1",),
        },
    ),
    STANDARD_MODE: AgentRuntimeModeConfig(
        mode=STANDARD_MODE,
        label="标准模式",
        interaction_mode="standard_mode",
        recipe_id="runtime.recipe.standard_task",
        projection_strength="companion",
        interaction_policy={
            "style": "general_agent",
            "task_orientation": "agent_decides_next_action",
            "user_clarification": "allowed",
        },
        planning_policy={"plan_mode": "disabled", "specified_plan_allowed": False},
        task_lifecycle_policy={"request_task_run": True, "requires_completion_evidence": True},
        tool_exposure_policy={},
        context_policy={
            "history_scope": "conversation_and_task",
            "task_context": "available",
            "task_run_context": "enabled",
            "active_work_context": "available",
        },
        memory_policy={"read_scope": "agent_profile", "write_scope": "candidate_only"},
        self_review_policy={"enabled": True, "before_final": "check_answer_or_task_state"},
        step_summary_policy={"enabled": True, "detail": "compact"},
        approval_policy={"permission_scope": "standard_agent_profile_ceiling"},
        prompt_pack_refs_by_invocation={
            "turn_action": ("runtime.pack.turn_action.v1",),
            "task_execution": ("runtime.pack.task_execution.v1",),
            "tool_observation_followup": ("runtime.pack.observation_followup.v1",),
        },
    ),
    PROFESSIONAL_MODE: AgentRuntimeModeConfig(
        mode=PROFESSIONAL_MODE,
        label="专家模式",
        interaction_mode="professional_mode",
        recipe_id="runtime.recipe.professional_task",
        projection_strength="style_only",
        execution_strategy="interaction_mode_run",
        interaction_policy={
            "style": "professional_agent",
            "task_orientation": "complete_real_work",
            "user_clarification": "only_when_blocked",
        },
        planning_policy={"plan_mode": "available", "specified_plan_allowed": True, "todo_required_when_task_run": True},
        task_lifecycle_policy={"request_task_run": True, "requires_completion_evidence": True, "artifact_evidence_required": True},
        tool_exposure_policy={},
        context_policy={
            "history_scope": "conversation_task_and_recovery",
            "task_context": "required_for_task_run",
            "task_run_context": "enabled",
            "active_work_context": "required_for_task_run",
        },
        memory_policy={"read_scope": "agent_profile", "write_scope": "candidate_with_receipt"},
        self_review_policy={
            "enabled": True,
            "checkpoints": ("before_tool", "after_tool", "before_final"),
            "failure_recovery": "replan_or_report_blocker",
        },
        step_summary_policy={"enabled": True, "detail": "stepwise"},
        approval_policy={"permission_scope": "professional_agent_profile_ceiling"},
        prompt_pack_refs_by_invocation={
            "turn_action": ("runtime.pack.turn_action.v1",),
            "task_execution": ("runtime.pack.task_execution.v1",),
            "tool_observation_followup": ("runtime.pack.observation_followup.v1",),
        },
    ),
    CUSTOM_MODE: AgentRuntimeModeConfig(
        mode=CUSTOM_MODE,
        label="自定义模式",
        interaction_mode="custom_mode",
        recipe_id="runtime.recipe.custom",
        projection_strength="manual",
        editable=True,
    ),
}


def runtime_mode_catalog(metadata: Any | None = None) -> dict[str, AgentRuntimeModeConfig]:
    _ = metadata
    return dict(MODE_CONFIGS)


def normalize_runtime_modes(
    values: Any,
    *,
    fallback: tuple[str, ...] = (CUSTOM_MODE,),
    mode_catalog: dict[str, AgentRuntimeModeConfig] | None = None,
) -> tuple[str, ...]:
    catalog = mode_catalog or MODE_CONFIGS
    if isinstance(values, str):
        raw_values = [values]
    else:
        raw_values = list(values or [])
    normalized: list[str] = []
    for item in raw_values:
        mode = str(item or "").strip()
        if mode in catalog and mode not in normalized:
            normalized.append(mode)
    if not normalized:
        normalized.extend(mode for mode in fallback if mode in catalog)
    return tuple(normalized)


def normalize_default_runtime_mode(value: Any, enabled_modes: tuple[str, ...]) -> str:
    if not enabled_modes:
        return ""
    mode = str(value or "").strip()
    if mode in enabled_modes:
        return mode
    if DEFAULT_RUNTIME_MODE in enabled_modes:
        return DEFAULT_RUNTIME_MODE
    return enabled_modes[0] if enabled_modes else DEFAULT_RUNTIME_MODE


def mode_config_catalog(metadata: Any | None = None) -> list[dict[str, Any]]:
    catalog = runtime_mode_catalog(metadata)
    ordered = [mode for mode in RUNTIME_MODE_ORDER if mode in catalog]
    ordered.extend(mode for mode in catalog if mode not in ordered)
    return [catalog[mode].to_dict() for mode in ordered]


