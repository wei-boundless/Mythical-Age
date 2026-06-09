from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from prompt_library import ALL_ENVIRONMENT_LIFECYCLE_PROMPT_IDS


GENERAL_ENVIRONMENT_ID = "env.general.workspace"
ENVIRONMENT_SWITCH_REQUEST_ACTION = "environment_switch_request"

_LIFECYCLE_REFS = set(ALL_ENVIRONMENT_LIFECYCLE_PROMPT_IDS)
_SUBAGENT_TOOL_NAMES = {
    "spawn_subagent",
    "send_subagent_message",
    "wait_subagent",
    "list_subagents",
    "close_subagent",
}


@dataclass(frozen=True, slots=True)
class PromptMountPlan:
    base_environment_id: str = GENERAL_ENVIRONMENT_ID
    selected_environment_id: str = GENERAL_ENVIRONMENT_ID
    personality_prompt_refs: tuple[str, ...] = ()
    base_prompt_refs: tuple[str, ...] = ()
    overlay_prompt_refs: tuple[str, ...] = ()
    lifecycle_prompt_refs: tuple[str, ...] = ()
    lifecycle_prompt_keys: tuple[str, ...] = ()
    lifecycle_prompt_defaults: dict[str, str] = field(default_factory=dict)
    lifecycle_prompt_overrides: dict[str, str] = field(default_factory=dict)
    lifecycle_trigger_reasons: dict[str, str] = field(default_factory=dict)
    tool_guidance_prompt_defaults: dict[str, str] = field(default_factory=dict)
    tool_guidance_prompt_overrides: dict[str, str] = field(default_factory=dict)
    environment_prompt_refs: tuple[str, ...] = ()
    environment_switch_policy: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.environment_prompt_controller"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["personality_prompt_refs"] = list(self.personality_prompt_refs)
        payload["base_prompt_refs"] = list(self.base_prompt_refs)
        payload["overlay_prompt_refs"] = list(self.overlay_prompt_refs)
        payload["lifecycle_prompt_refs"] = list(self.lifecycle_prompt_refs)
        payload["lifecycle_prompt_keys"] = list(self.lifecycle_prompt_keys)
        payload["lifecycle_prompt_defaults"] = dict(self.lifecycle_prompt_defaults)
        payload["lifecycle_prompt_overrides"] = dict(self.lifecycle_prompt_overrides)
        payload["lifecycle_trigger_reasons"] = dict(self.lifecycle_trigger_reasons)
        payload["tool_guidance_prompt_defaults"] = dict(self.tool_guidance_prompt_defaults)
        payload["tool_guidance_prompt_overrides"] = dict(self.tool_guidance_prompt_overrides)
        payload["environment_prompt_refs"] = list(self.environment_prompt_refs)
        payload["environment_switch_policy"] = dict(self.environment_switch_policy)
        payload["diagnostics"] = dict(self.diagnostics)
        return payload


@dataclass(frozen=True, slots=True)
class LifecyclePromptSelection:
    refs: tuple[str, ...] = ()
    keys: tuple[str, ...] = ()
    trigger_reasons: dict[str, str] = field(default_factory=dict)
    omitted_keys: tuple[str, ...] = ()


def build_base_prompt_mount_plan(
    *,
    selected_environment: dict[str, Any],
    base_environment: dict[str, Any] | None = None,
    personality_prompt_refs: tuple[str, ...] | list[str] = (),
    personality_diagnostics: dict[str, Any] | None = None,
    prompt_policy: dict[str, Any] | None = None,
) -> PromptMountPlan:
    selected_payload = dict(selected_environment or {})
    selected_environment_id = _environment_id(selected_payload) or GENERAL_ENVIRONMENT_ID
    base_environment_id = selected_environment_id
    boundary = dict(selected_payload.get("environment_boundary") or {})
    prompt_policy_payload = dict(prompt_policy or {})
    lifecycle_defaults = _prompt_ref_map(boundary.get("lifecycle_prompt_defaults"))
    lifecycle_overrides = _prompt_ref_map(boundary.get("lifecycle_prompt_overrides"))
    tool_guidance_defaults = _prompt_ref_map(prompt_policy_payload.get("tool_guidance_prompt_defaults"))
    tool_guidance_overrides = _prompt_ref_map(boundary.get("tool_guidance_prompt_overrides"))
    selected_refs = _environment_prompt_refs(selected_payload)
    lifecycle_ref_set = _lifecycle_ref_set(lifecycle_defaults, lifecycle_overrides)
    selected_refs_without_lifecycle = _without_lifecycle_refs(selected_refs, lifecycle_ref_set=lifecycle_ref_set)
    base_refs = selected_refs_without_lifecycle
    overlay_refs: tuple[str, ...] = ()
    environment_refs = _dedupe(base_refs)
    return PromptMountPlan(
        base_environment_id=base_environment_id,
        selected_environment_id=selected_environment_id,
        personality_prompt_refs=_string_tuple(personality_prompt_refs),
        base_prompt_refs=base_refs,
        overlay_prompt_refs=overlay_refs,
        environment_prompt_refs=environment_refs,
        lifecycle_prompt_defaults=lifecycle_defaults,
        lifecycle_prompt_overrides=lifecycle_overrides,
        tool_guidance_prompt_defaults=tool_guidance_defaults,
        tool_guidance_prompt_overrides=tool_guidance_overrides,
        environment_switch_policy=_environment_switch_policy(),
        diagnostics={
            "base_prompt_count": len(base_refs),
            "overlay_prompt_count": len(overlay_refs),
            "selected_environment_prompt_count": len(selected_refs_without_lifecycle),
            "removed_static_lifecycle_refs": [
                ref for ref in selected_refs if ref in lifecycle_ref_set
            ],
            "overlay_mode": "selected_environment_only",
            "lifecycle_prompt_default_count": len(lifecycle_defaults),
            "lifecycle_prompt_override_count": len(lifecycle_overrides),
            "tool_guidance_prompt_default_count": len(tool_guidance_defaults),
            "tool_guidance_prompt_override_count": len(tool_guidance_overrides),
            "personality": dict(personality_diagnostics or {}),
        },
    )


def prompt_mount_plan_from_payload(payload: Any) -> PromptMountPlan:
    raw = dict(payload or {}) if isinstance(payload, dict) else {}
    base_prompt_refs = _string_tuple(raw.get("base_prompt_refs"))
    overlay_prompt_refs = _string_tuple(raw.get("overlay_prompt_refs"))
    environment_prompt_refs = _string_tuple(raw.get("environment_prompt_refs")) or _dedupe(
        (*base_prompt_refs, *overlay_prompt_refs)
    )
    return PromptMountPlan(
        base_environment_id=str(raw.get("base_environment_id") or GENERAL_ENVIRONMENT_ID),
        selected_environment_id=str(raw.get("selected_environment_id") or GENERAL_ENVIRONMENT_ID),
        personality_prompt_refs=_string_tuple(raw.get("personality_prompt_refs")),
        base_prompt_refs=base_prompt_refs,
        overlay_prompt_refs=overlay_prompt_refs,
        lifecycle_prompt_refs=_string_tuple(raw.get("lifecycle_prompt_refs")),
        lifecycle_prompt_keys=_string_tuple(raw.get("lifecycle_prompt_keys")),
        lifecycle_prompt_defaults=_string_dict(raw.get("lifecycle_prompt_defaults")),
        lifecycle_prompt_overrides=_string_dict(raw.get("lifecycle_prompt_overrides")),
        lifecycle_trigger_reasons=_string_dict(raw.get("lifecycle_trigger_reasons")),
        tool_guidance_prompt_defaults=_string_dict(raw.get("tool_guidance_prompt_defaults")),
        tool_guidance_prompt_overrides=_string_dict(raw.get("tool_guidance_prompt_overrides")),
        environment_prompt_refs=environment_prompt_refs,
        environment_switch_policy=dict(raw.get("environment_switch_policy") or _environment_switch_policy()),
        diagnostics=dict(raw.get("diagnostics") or {}),
    )


def prompt_mount_plan_for_invocation(
    base_plan: PromptMountPlan | dict[str, Any] | None,
    *,
    invocation_kind: str,
    allowed_actions: tuple[str, ...] = (),
    active_work_context: dict[str, Any] | None = None,
    memory_context: dict[str, Any] | None = None,
    observations: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    visible_tools: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    execution_state: dict[str, Any] | None = None,
    session_context: dict[str, Any] | None = None,
    prompt_pack_refs: tuple[str, ...] = (),
) -> PromptMountPlan:
    plan = base_plan if isinstance(base_plan, PromptMountPlan) else prompt_mount_plan_from_payload(base_plan)
    lifecycle_selection = _lifecycle_prompt_selection_for_invocation(
        invocation_kind=invocation_kind,
        allowed_actions=allowed_actions,
        active_work_context=active_work_context,
        memory_context=memory_context,
        observations=observations,
        visible_tools=visible_tools,
        execution_state=execution_state,
        session_context=session_context,
        prompt_pack_refs=prompt_pack_refs,
        lifecycle_prompt_defaults=plan.lifecycle_prompt_defaults,
        lifecycle_prompt_overrides=plan.lifecycle_prompt_overrides,
    )
    diagnostics = {
        **dict(plan.diagnostics or {}),
        "invocation_kind": str(invocation_kind or ""),
        "lifecycle_prompt_count": len(lifecycle_selection.refs),
        "lifecycle_prompt_keys": list(lifecycle_selection.keys),
        "lifecycle_prompt_omitted_keys": list(lifecycle_selection.omitted_keys),
        "lifecycle_trigger_reasons": dict(lifecycle_selection.trigger_reasons),
        "lifecycle_selector_authority": "harness.runtime.environment_prompt_controller.lifecycle_selector",
    }
    return PromptMountPlan(
        base_environment_id=plan.base_environment_id,
        selected_environment_id=plan.selected_environment_id,
        personality_prompt_refs=plan.personality_prompt_refs,
        base_prompt_refs=plan.base_prompt_refs,
        overlay_prompt_refs=plan.overlay_prompt_refs,
        lifecycle_prompt_refs=lifecycle_selection.refs,
        lifecycle_prompt_keys=lifecycle_selection.keys,
        lifecycle_prompt_defaults=plan.lifecycle_prompt_defaults,
        lifecycle_prompt_overrides=plan.lifecycle_prompt_overrides,
        lifecycle_trigger_reasons=lifecycle_selection.trigger_reasons,
        tool_guidance_prompt_defaults=plan.tool_guidance_prompt_defaults,
        tool_guidance_prompt_overrides=plan.tool_guidance_prompt_overrides,
        environment_prompt_refs=plan.environment_prompt_refs,
        environment_switch_policy=plan.environment_switch_policy,
        diagnostics=diagnostics,
    )


def _lifecycle_prompt_selection_for_invocation(
    *,
    invocation_kind: str,
    allowed_actions: tuple[str, ...],
    active_work_context: dict[str, Any] | None,
    memory_context: dict[str, Any] | None,
    observations: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    visible_tools: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    execution_state: dict[str, Any] | None,
    session_context: dict[str, Any] | None,
    prompt_pack_refs: tuple[str, ...],
    lifecycle_prompt_defaults: dict[str, str],
    lifecycle_prompt_overrides: dict[str, str],
) -> LifecyclePromptSelection:
    invocation = str(invocation_kind or "").strip()
    if "runtime.pack.graph_node_execution" in set(prompt_pack_refs):
        return LifecyclePromptSelection()
    refs: list[str] = []
    keys: list[str] = []
    omitted_keys: list[str] = []
    trigger_reasons: dict[str, str] = {}

    def add(lifecycle_key: str, reason: str) -> None:
        prompt_ref = _resolve_prompt_slot(
            lifecycle_key,
            defaults=lifecycle_prompt_defaults,
            overrides=lifecycle_prompt_overrides,
        )
        if not prompt_ref:
            if lifecycle_key not in omitted_keys:
                omitted_keys.append(lifecycle_key)
            return
        if prompt_ref in trigger_reasons:
            return
        keys.append(lifecycle_key)
        refs.append(prompt_ref)
        trigger_reasons[prompt_ref] = reason

    allowed = {str(item) for item in allowed_actions if str(item)}
    has_memory = _has_visible_memory(memory_context) or _has_visible_memory(dict(session_context or {}).get("memory_context"))
    has_observations = bool([item for item in list(observations or []) if isinstance(item, dict)])
    has_pending_steers = _has_pending_user_steers(execution_state)
    has_tool_dispatch = "tool_call" in allowed
    has_subagent_tools = _has_visible_tool_names(visible_tools, _SUBAGENT_TOOL_NAMES)
    has_subagent_results = _has_subagent_observation(observations)
    has_plan_signal = _has_plan_signal(execution_state, session_context)
    has_memory_write = _has_memory_write_signal(execution_state, session_context)
    has_compaction = _has_compaction_signal(execution_state, session_context)
    if invocation == "single_agent_turn":
        add("context_intake", "single_agent_turn always needs context authority intake")
        add("request_judgment", "single_agent_turn must judge the latest user request")
        if active_work_context:
            add("work_relation", "active_work_context is visible")
        add("environment_capability_alignment", "environment boundary and runtime capabilities are visible")
        if has_plan_signal or "request_task_run" in allowed:
            add("plan_gate", "plan signal is visible or request_task_run is allowed")
        add("action_selection", "single_agent_turn must choose one schema-valid action")
        if active_work_context and "active_work_control" in allowed:
            add("active_work_control", "active_work_context is visible and active_work_control is allowed")
            add("user_steer_contract_revision", "current user message may steer visible active work")
        if "request_task_run" in allowed:
            add("task_run_handoff", "request_task_run action is allowed")
        if has_tool_dispatch:
            add("tool_dispatch", "tool_call action is allowed")
        if has_subagent_tools:
            add("subagent_delegation", "subagent control tools are visible")
        if has_memory:
            add("memory_read_context", "memory_context has model-visible sections")
        if has_compaction:
            add("compaction_handoff", "compaction or checkpoint signal is visible")
        add("finalization", "single_agent_turn must check reply readiness before responding")
        return LifecyclePromptSelection(refs=_dedupe(refs), keys=_dedupe(keys), trigger_reasons=trigger_reasons, omitted_keys=_dedupe(omitted_keys))
    if invocation == "tool_observation_followup":
        add("context_intake", "tool_observation_followup must preserve context authority")
        add("environment_capability_alignment", "followup still runs inside current environment boundary")
        add("tool_observation_recovery", "tool observations are available for followup")
        if has_subagent_results:
            add("subagent_result_integration", "subagent observation is visible")
        add("action_selection", "followup must choose one schema-valid next action")
        if "request_task_run" in allowed:
            add("task_run_handoff", "followup may upgrade to request_task_run")
        if has_tool_dispatch:
            add("tool_dispatch", "tool_call action is allowed after observation")
        if has_subagent_tools:
            add("subagent_delegation", "subagent control tools are visible")
        if has_memory:
            add("memory_read_context", "memory_context has model-visible sections")
        add("finalization", "followup must check whether observation is sufficient to respond")
        return LifecyclePromptSelection(refs=_dedupe(refs), keys=_dedupe(keys), trigger_reasons=trigger_reasons, omitted_keys=_dedupe(omitted_keys))
    if invocation == "task_execution":
        add("context_intake", "task_execution must preserve task and context authority")
        add("environment_capability_alignment", "task_execution runs inside a selected environment boundary")
        if has_plan_signal:
            add("plan_gate", "plan or implementation lock signal is visible")
        if has_pending_steers:
            add("user_steer_contract_revision", "pending_user_steers are visible")
        if has_observations:
            add("tool_observation_recovery", "tool observations are visible")
        if has_subagent_results:
            add("subagent_result_integration", "subagent observation is visible")
        add("action_selection", "task_execution must choose one schema-valid next action")
        if has_tool_dispatch:
            add("tool_dispatch", "tool_call action is allowed")
        if has_subagent_tools:
            add("subagent_delegation", "subagent control tools are visible")
        add("verification_gate", "task_execution must verify readiness before final respond")
        if has_memory:
            add("memory_read_context", "memory_context has model-visible sections")
        if has_memory_write:
            add("memory_write_handoff", "memory write or maintenance signal is visible")
        if has_compaction:
            add("compaction_handoff", "compaction or checkpoint signal is visible")
        add("finalization", "task_execution must report only true completion, risk, or blockage")
        return LifecyclePromptSelection(refs=_dedupe(refs), keys=_dedupe(keys), trigger_reasons=trigger_reasons, omitted_keys=_dedupe(omitted_keys))
    return LifecyclePromptSelection()


def _environment_id(payload: dict[str, Any]) -> str:
    return str(payload.get("environment_id") or payload.get("task_environment_id") or "").strip()


def _environment_prompt_refs(payload: dict[str, Any]) -> tuple[str, ...]:
    boundary = dict(payload.get("environment_boundary") or {})
    refs = _string_tuple(boundary.get("prompt_refs"))
    if refs:
        return refs
    return _string_tuple(
        str(item.get("prompt_id") or "").strip()
        for item in list(payload.get("environment_prompts") or [])
        if isinstance(item, dict)
    )


def _without_lifecycle_refs(refs: tuple[str, ...], *, lifecycle_ref_set: set[str] | None = None) -> tuple[str, ...]:
    blocked = lifecycle_ref_set or _LIFECYCLE_REFS
    return tuple(ref for ref in refs if ref and ref not in blocked)


def _lifecycle_ref_set(defaults: dict[str, str], overrides: dict[str, str]) -> set[str]:
    return {
        *set(_LIFECYCLE_REFS),
        *{str(item).strip() for item in defaults.values() if str(item).strip()},
        *{str(item).strip() for item in overrides.values() if str(item).strip()},
    }


def _prompt_ref_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, raw_ref in value.items():
        slot = str(key or "").strip()
        ref = _first_string(raw_ref)
        if slot and ref:
            result[slot] = ref
    return result


def _resolve_prompt_slot(key: str, *, defaults: dict[str, str], overrides: dict[str, str]) -> str:
    slot = str(key or "").strip()
    if not slot:
        return ""
    return str(overrides.get(slot) or defaults.get(slot) or "").strip()


def _environment_switch_policy() -> dict[str, Any]:
    return {
        "mode": "user_or_session_controlled",
        "default_environment_id": GENERAL_ENVIRONMENT_ID,
        "autonomous_switch_request": {
            "designed": True,
            "implemented": False,
            "action_type": ENVIRONMENT_SWITCH_REQUEST_ACTION,
            "handling": "future_ui_or_control_plane_confirmation_required",
        },
        "model_may_switch_environment": False,
        "authority": "harness.runtime.environment_switch_policy",
    }


def _has_visible_memory(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    sections = value.get("model_visible_sections")
    return isinstance(sections, dict) and any(bool(list(items or [])) for items in sections.values())


def _has_pending_user_steers(execution_state: dict[str, Any] | None) -> bool:
    state = dict(execution_state or {})
    projection = dict(state.get("system_projection") or {})
    return bool([item for item in list(projection.get("pending_user_steers") or []) if isinstance(item, dict)])


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


def _has_subagent_observation(observations: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> bool:
    for raw_observation in list(observations or []):
        if not isinstance(raw_observation, dict):
            continue
        observation = dict(raw_observation)
        nested = dict(observation.get("tool_result") or {})
        structured = dict(observation.get("structured_payload") or {})
        structured_tool_result = dict(structured.get("tool_result") or {})
        tool_name = str(
            observation.get("tool_name")
            or observation.get("source")
            or nested.get("tool_name")
            or structured_tool_result.get("tool_name")
            or ""
        )
        if "wait_subagent" in tool_name or "subagent" in tool_name:
            return True
    return False


def _has_plan_signal(
    execution_state: dict[str, Any] | None,
    session_context: dict[str, Any] | None,
) -> bool:
    values = _deep_values(dict(execution_state or {}), limit=120) + _deep_values(dict(session_context or {}), limit=120)
    markers = {
        "plan_mode",
        "requires_plan",
        "planning_required",
        "planning_policy",
        "approved_plan",
        "plan_ref",
        "implementation_lock",
    }
    return any(str(value).strip() in markers or any(marker in str(value) for marker in markers) for value in values)


def _has_memory_write_signal(
    execution_state: dict[str, Any] | None,
    session_context: dict[str, Any] | None,
) -> bool:
    values = _deep_values(dict(execution_state or {}), limit=120) + _deep_values(dict(session_context or {}), limit=120)
    markers = {
        "memory_write",
        "memory_maintenance",
        "memory_candidate",
        "durable_memory",
        "ready_to_finish",
    }
    return any(str(value).strip() in markers or any(marker in str(value) for marker in markers) for value in values)


def _has_compaction_signal(
    execution_state: dict[str, Any] | None,
    session_context: dict[str, Any] | None,
) -> bool:
    values = _deep_values(dict(execution_state or {}), limit=120) + _deep_values(dict(session_context or {}), limit=120)
    markers = {"semantic_compaction", "compaction", "context_compaction", "checkpoint_summary"}
    return any(str(value).strip() in markers or any(marker in str(value) for marker in markers) for value in values)


def _deep_values(value: Any, *, limit: int) -> list[str]:
    if limit <= 0:
        return []
    if isinstance(value, dict):
        values: list[str] = []
        for key, item in value.items():
            values.append(str(key))
            values.extend(_deep_values(item, limit=limit - len(values)))
            if len(values) >= limit:
                return values[:limit]
        return values
    if isinstance(value, (list, tuple)):
        values = []
        for item in value:
            values.extend(_deep_values(item, limit=limit - len(values)))
            if len(values) >= limit:
                return values[:limit]
        return values
    return [str(value)] if value is not None else []


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_values = [value]
    else:
        raw_values = list(value or [])
    return tuple(str(item).strip() for item in raw_values if str(item).strip())


def _first_string(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    for item in list(value or []) if isinstance(value, (list, tuple, set)) else []:
        text = str(item or "").strip()
        if text:
            return text
    return ""


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
