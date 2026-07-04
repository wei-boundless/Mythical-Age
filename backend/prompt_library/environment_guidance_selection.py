from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .environment_guidance_prompts import ENVIRONMENT_GUIDANCE_PROMPT_SLOTS


_SUBAGENT_TOOL_NAMES = {"subagent"}


@dataclass(frozen=True, slots=True)
class EnvironmentGuidancePromptSelection:
    refs: tuple[str, ...] = ()
    keys: tuple[str, ...] = ()
    trigger_reasons: dict[str, str] = field(default_factory=dict)
    omitted_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EnvironmentGuidancePromptSplitSelection:
    stable: EnvironmentGuidancePromptSelection = field(default_factory=EnvironmentGuidancePromptSelection)
    runtime: EnvironmentGuidancePromptSelection = field(default_factory=EnvironmentGuidancePromptSelection)


def select_environment_guidance_for_invocation(
    *,
    selected_environment_id: str,
    invocation_kind: str,
    allowed_actions: tuple[str, ...] = (),
    operation_availability: dict[str, Any] | None = None,
    active_work_context: dict[str, Any] | None = None,
    memory_context: dict[str, Any] | None = None,
    observations: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    visible_tools: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    execution_state: dict[str, Any] | None = None,
    session_context: dict[str, Any] | None = None,
    prompt_pack_refs: tuple[str, ...] = (),
    environment_guidance_prompt_defaults: dict[str, str] | None = None,
    environment_guidance_prompt_overrides: dict[str, str] | None = None,
) -> EnvironmentGuidancePromptSplitSelection:
    invocation = str(invocation_kind or "").strip()
    if "runtime.pack.graph_node_execution" in set(prompt_pack_refs or ()):
        return EnvironmentGuidancePromptSplitSelection()

    defaults = _string_dict(environment_guidance_prompt_defaults)
    overrides = _string_dict(environment_guidance_prompt_overrides)
    if not defaults and not overrides:
        return EnvironmentGuidancePromptSplitSelection()

    environment_kind = _environment_kind_for_id(selected_environment_id)
    stable_reasons: dict[str, str] = {}
    runtime_reasons: dict[str, str] = {}
    for guidance_key, reason in _core_environment_guidance_reasons(
        invocation_kind=invocation,
        environment_kind=environment_kind,
    ):
        _select_environment_guidance_key(stable_reasons, guidance_key, reason)
    for guidance_key, reason in _capability_environment_guidance_reasons(
        invocation_kind=invocation,
        environment_kind=environment_kind,
        allowed_actions=allowed_actions,
        operation_availability=operation_availability,
        visible_tools=visible_tools,
        active_work_context=active_work_context,
    ):
        _select_environment_guidance_key(stable_reasons, guidance_key, reason)
    for guidance_key, reason in _state_environment_guidance_reasons(
        invocation_kind=invocation,
        environment_kind=environment_kind,
        active_work_context=active_work_context,
        memory_context=memory_context,
        observations=observations,
        execution_state=execution_state,
        session_context=session_context,
        visible_tools=visible_tools,
    ):
        _select_environment_guidance_key(runtime_reasons, guidance_key, reason)
    runtime_reasons = {
        key: reason
        for key, reason in runtime_reasons.items()
        if key not in stable_reasons
    }

    return EnvironmentGuidancePromptSplitSelection(
        stable=_resolve_environment_guidance_selection(
            stable_reasons,
            environment_guidance_prompt_defaults=defaults,
            environment_guidance_prompt_overrides=overrides,
        ),
        runtime=_resolve_environment_guidance_selection(
            runtime_reasons,
            environment_guidance_prompt_defaults=defaults,
            environment_guidance_prompt_overrides=overrides,
        ),
    )


def _resolve_environment_guidance_selection(
    selected_reasons: dict[str, str],
    *,
    environment_guidance_prompt_defaults: dict[str, str],
    environment_guidance_prompt_overrides: dict[str, str],
) -> EnvironmentGuidancePromptSelection:
    refs: list[str] = []
    keys: list[str] = []
    omitted_keys: list[str] = []
    trigger_reasons: dict[str, str] = {}
    for guidance_key in ENVIRONMENT_GUIDANCE_PROMPT_SLOTS:
        if guidance_key not in selected_reasons:
            continue
        prompt_ref = _resolve_prompt_slot(
            guidance_key,
            defaults=environment_guidance_prompt_defaults,
            overrides=environment_guidance_prompt_overrides,
        )
        if not prompt_ref:
            if guidance_key not in omitted_keys:
                omitted_keys.append(guidance_key)
            continue
        if prompt_ref in trigger_reasons:
            continue
        keys.append(guidance_key)
        refs.append(prompt_ref)
        trigger_reasons[prompt_ref] = selected_reasons[guidance_key]
    return EnvironmentGuidancePromptSelection(
        refs=_dedupe(refs),
        keys=_dedupe(keys),
        trigger_reasons=trigger_reasons,
        omitted_keys=_dedupe(omitted_keys),
    )


def _core_environment_guidance_reasons(
    *,
    invocation_kind: str,
    environment_kind: str,
) -> tuple[tuple[str, str], ...]:
    if environment_kind == "chat":
        return ()
    if invocation_kind == "single_agent_turn":
        if environment_kind == "coding":
            keys = (
                "context_intake",
                "request_judgment",
                "environment_capability_alignment",
                "plan_gate",
                "action_boundary",
                "finalization",
            )
        else:
            keys = (
                "context_intake",
                "request_judgment",
                "environment_capability_alignment",
                "action_boundary",
                "finalization",
            )
        return tuple((key, f"core: {environment_kind} single_agent_turn requires {key}") for key in keys)
    if invocation_kind == "task_execution":
        keys = (
            "context_intake",
            "environment_capability_alignment",
            "tool_observation_recovery",
            "action_boundary",
            "verification_gate",
            "finalization",
        )
        return tuple((key, f"core: {environment_kind} task_execution requires {key}") for key in keys)
    if invocation_kind == "tool_observation_followup":
        keys = (
            "context_intake",
            "tool_observation_recovery",
            "action_boundary",
            "finalization",
        )
        return tuple(
            (key, f"core: {environment_kind} tool_observation_followup requires {key}")
            for key in keys
        )
    return ()


def _capability_environment_guidance_reasons(
    *,
    invocation_kind: str,
    environment_kind: str,
    allowed_actions: tuple[str, ...],
    operation_availability: dict[str, Any] | None,
    visible_tools: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    active_work_context: dict[str, Any] | None,
) -> tuple[tuple[str, str], ...]:
    if environment_kind == "chat":
        return ()
    allowed = {str(item) for item in allowed_actions if str(item)}
    reasons: list[tuple[str, str]] = []
    has_visible_tools = _has_visible_tools(visible_tools)
    has_tool_dispatch = "tool_call" in allowed and has_visible_tools
    has_subagent_tools = _has_visible_tool_names(visible_tools, _SUBAGENT_TOOL_NAMES)
    has_active_work = _has_structural_payload(active_work_context)
    active_work_control_available = dict(operation_availability or {}).get("active_work_control") is True
    if invocation_kind == "single_agent_turn":
        if "active_work_control" in allowed and has_active_work and active_work_control_available:
            reasons.append(("active_work_control", "operation: active_work_control is available for the current active work"))
        if "request_task_run" in allowed:
            reasons.append(("task_run_handoff", "capability: request_task_run action is allowed"))
        if has_tool_dispatch:
            reasons.append(("tool_dispatch", "capability: tool_call action is allowed and visible tools are present"))
        if has_subagent_tools:
            reasons.append(("subagent_delegation", "capability: subagent control tools are visible"))
        return tuple(reasons)
    if invocation_kind == "task_execution":
        if has_tool_dispatch:
            reasons.append(("tool_dispatch", "capability: tool_call action is allowed and visible tools are present"))
        if has_subagent_tools:
            reasons.append(("subagent_delegation", "capability: subagent control tools are visible"))
        return tuple(reasons)
    if invocation_kind == "tool_observation_followup":
        if "request_task_run" in allowed:
            reasons.append(("task_run_handoff", "capability: followup action contract allows request_task_run"))
        if has_tool_dispatch:
            reasons.append(("tool_dispatch", "capability: tool_call action is allowed after observation"))
        if has_subagent_tools:
            reasons.append(("subagent_delegation", "capability: subagent control tools are visible"))
        return tuple(reasons)
    return ()


def _state_environment_guidance_reasons(
    *,
    invocation_kind: str,
    environment_kind: str,
    active_work_context: dict[str, Any] | None,
    memory_context: dict[str, Any] | None,
    observations: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    execution_state: dict[str, Any] | None,
    session_context: dict[str, Any] | None,
    visible_tools: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> tuple[tuple[str, str], ...]:
    if environment_kind == "chat":
        return ()
    reasons: list[tuple[str, str]] = []
    has_active_work = _has_structural_payload(active_work_context)
    has_pending_steer = _has_pending_steer(active_work_context, execution_state, session_context)
    if invocation_kind == "single_agent_turn" and has_active_work:
        reasons.append(("work_relation", "state: active_work_context is present"))
    if has_pending_steer or (invocation_kind == "single_agent_turn" and has_active_work):
        reasons.append(("user_steer_contract_revision", "state: active work or pending user steer is present"))
    if _has_plan_boundary(execution_state, session_context):
        reasons.append(("plan_gate", "state: plan or high-risk execution boundary is present"))
    if invocation_kind == "tool_observation_followup" and _observations_include_boundary_observation(observations):
        reasons.append(("environment_capability_alignment", "state: observation shows capability, permission, or environment boundary"))
    if _observations_include_subagent_result(observations):
        reasons.append(("subagent_result_integration", "state: subagent result observation is present"))
    if _has_structural_payload(memory_context):
        reasons.append(("memory_read_context", "state: memory_context is present"))
    if _has_memory_write_handoff(memory_context, execution_state, session_context, visible_tools):
        reasons.append(("memory_write_handoff", "state: memory write candidate or capability is present"))
    if _has_compaction_boundary(execution_state, session_context):
        reasons.append(("compaction_handoff", "state: compaction or recovery boundary is present"))
    return tuple(reasons)


def _select_environment_guidance_key(selected_reasons: dict[str, str], guidance_key: str, reason: str) -> None:
    key = str(guidance_key or "").strip()
    if key and key not in selected_reasons:
        selected_reasons[key] = str(reason or "").strip()


def _resolve_prompt_slot(key: str, *, defaults: dict[str, str], overrides: dict[str, str]) -> str:
    slot = str(key or "").strip()
    if not slot:
        return ""
    return str(overrides.get(slot) or defaults.get(slot) or "").strip()


def _environment_kind_for_id(environment_id: str) -> str:
    value = str(environment_id or "").strip()
    if value.startswith("env.coding.") or value.startswith("env.development."):
        return "coding"
    if value.startswith("env.office."):
        return "office"
    if value.startswith("env.chat."):
        return "chat"
    if value.startswith("env.general."):
        return "general"
    return "general"


def _has_visible_tool_names(
    visible_tools: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    names: set[str],
) -> bool:
    for raw_tool in list(visible_tools or []):
        if not isinstance(raw_tool, dict):
            continue
        tool_name = str(raw_tool.get("tool_name") or raw_tool.get("name") or "").strip()
        if tool_name in names:
            return True
    return False


def _has_visible_tools(visible_tools: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> bool:
    for raw_tool in list(visible_tools or []):
        if not isinstance(raw_tool, dict):
            continue
        if str(raw_tool.get("tool_name") or raw_tool.get("name") or "").strip():
            return True
    return False


def _has_structural_payload(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, dict):
        for item in value.values():
            if _has_structural_payload(item):
                return True
        return False
    if isinstance(value, (list, tuple, set)):
        for item in value:
            if _has_structural_payload(item):
                return True
        return False
    return True


def _has_pending_steer(
    active_work_context: dict[str, Any] | None,
    execution_state: dict[str, Any] | None,
    session_context: dict[str, Any] | None,
) -> bool:
    return any(
        _nested_payload_present(payload, _PENDING_STEER_KEYS)
        for payload in (active_work_context, execution_state, session_context)
    )


def _has_plan_boundary(
    execution_state: dict[str, Any] | None,
    session_context: dict[str, Any] | None,
) -> bool:
    return any(
        _nested_payload_present(payload, _PLAN_BOUNDARY_KEYS)
        for payload in (execution_state, session_context)
    )


def _has_compaction_boundary(
    execution_state: dict[str, Any] | None,
    session_context: dict[str, Any] | None,
) -> bool:
    return any(
        _nested_payload_present(payload, _COMPACTION_BOUNDARY_KEYS)
        for payload in (execution_state, session_context)
    )


def _has_memory_write_handoff(
    memory_context: dict[str, Any] | None,
    execution_state: dict[str, Any] | None,
    session_context: dict[str, Any] | None,
    visible_tools: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> bool:
    if _has_visible_tool_names(visible_tools, _MEMORY_WRITE_TOOL_NAMES):
        return True
    return any(
        _nested_payload_present(payload, _MEMORY_WRITE_KEYS)
        for payload in (memory_context, execution_state, session_context)
    )


def _observations_include_subagent_result(observations: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> bool:
    for observation in list(observations or []):
        if not isinstance(observation, dict):
            continue
        if _nested_payload_present(observation, _SUBAGENT_RESULT_KEYS):
            return True
        source = str(observation.get("source") or observation.get("tool_name") or "").strip()
        if "subagent" in source or source in _SUBAGENT_TOOL_NAMES:
            return True
    return False


def _observations_include_boundary_observation(observations: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> bool:
    for observation in list(observations or []):
        if not isinstance(observation, dict):
            continue
        status = str(observation.get("status") or "").strip().lower()
        if status in {"error", "failed", "failure", "blocked", "denied", "timeout", "rejected"}:
            return True
        if _nested_payload_present(observation, _BOUNDARY_OBSERVATION_KEYS):
            return True
    return False


def _nested_payload_present(payload: Any, keys: set[str]) -> bool:
    if not isinstance(payload, dict):
        return False
    for key, value in payload.items():
        normalized_key = str(key or "").strip()
        if normalized_key in keys and _has_structural_payload(value):
            return True
        if isinstance(value, dict) and _nested_payload_present(value, keys):
            return True
        if isinstance(value, (list, tuple)):
            for item in value:
                if _nested_payload_present(item, keys):
                    return True
    return False


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key).strip(): str(item).strip()
        for key, item in value.items()
        if str(key).strip() and str(item).strip()
    }


def _dedupe(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in list(values or []):
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)


_PENDING_STEER_KEYS = {
    "pending_user_steer",
    "pending_steer",
    "user_steer",
    "contract_revision",
    "contract_revision_request",
    "steering_event",
}
_PLAN_BOUNDARY_KEYS = {
    "plan_mode",
    "planning_mode",
    "requires_plan",
    "planning_required",
    "implementation_plan_required",
    "plan_required",
    "high_risk_change",
    "structural_change",
    "approved_plan_ref",
    "plan_ref",
}
_COMPACTION_BOUNDARY_KEYS = {
    "compaction",
    "compaction_handoff",
    "semantic_compaction",
    "context_compaction",
    "context_compression",
    "rehydration_plan",
}
_MEMORY_WRITE_KEYS = {
    "memory_write_candidate",
    "memory_write_candidates",
    "memory_handoff",
    "durable_memory_candidate",
    "memory_candidate",
}
_MEMORY_WRITE_TOOL_NAMES = {
    "memory_write",
    "write_memory",
    "save_memory",
    "persist_memory",
}
_SUBAGENT_RESULT_KEYS = {
    "subagent_result",
    "subagent_run_ref",
    "child_agent_run",
    "subagent_control",
    "result_available",
}
_BOUNDARY_OBSERVATION_KEYS = {
    "error",
    "error_code",
    "permission_denied",
    "denied",
    "tool_unavailable",
    "capability_unavailable",
    "timeout",
    "recoverable_error",
}
