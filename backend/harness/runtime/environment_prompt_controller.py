from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from prompt_library import (
    ALL_ENVIRONMENT_GUIDANCE_PROMPT_IDS,
    ENVIRONMENT_GUIDANCE_PROMPT_DEFAULTS_BY_ENVIRONMENT,
)
from prompt_library.environment_guidance_selection import select_environment_guidance_for_invocation


GENERAL_ENVIRONMENT_ID = "env.general.workspace"

_ENVIRONMENT_GUIDANCE_REFS = set(ALL_ENVIRONMENT_GUIDANCE_PROMPT_IDS)


@dataclass(frozen=True, slots=True)
class PromptMountPlan:
    base_environment_id: str = GENERAL_ENVIRONMENT_ID
    selected_environment_id: str = GENERAL_ENVIRONMENT_ID
    personality_prompt_refs: tuple[str, ...] = ()
    base_prompt_refs: tuple[str, ...] = ()
    overlay_prompt_refs: tuple[str, ...] = ()
    environment_guidance_prompt_refs: tuple[str, ...] = ()
    environment_guidance_prompt_keys: tuple[str, ...] = ()
    turn_state_guidance_prompt_refs: tuple[str, ...] = ()
    turn_state_guidance_prompt_keys: tuple[str, ...] = ()
    environment_guidance_prompt_defaults: dict[str, str] = field(default_factory=dict)
    environment_guidance_prompt_overrides: dict[str, str] = field(default_factory=dict)
    environment_guidance_trigger_reasons: dict[str, str] = field(default_factory=dict)
    turn_state_guidance_trigger_reasons: dict[str, str] = field(default_factory=dict)
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
        payload["environment_guidance_prompt_refs"] = list(self.environment_guidance_prompt_refs)
        payload["environment_guidance_prompt_keys"] = list(self.environment_guidance_prompt_keys)
        payload["turn_state_guidance_prompt_refs"] = list(self.turn_state_guidance_prompt_refs)
        payload["turn_state_guidance_prompt_keys"] = list(self.turn_state_guidance_prompt_keys)
        payload["environment_guidance_prompt_defaults"] = dict(self.environment_guidance_prompt_defaults)
        payload["environment_guidance_prompt_overrides"] = dict(self.environment_guidance_prompt_overrides)
        payload["environment_guidance_trigger_reasons"] = dict(self.environment_guidance_trigger_reasons)
        payload["turn_state_guidance_trigger_reasons"] = dict(self.turn_state_guidance_trigger_reasons)
        payload["tool_guidance_prompt_defaults"] = dict(self.tool_guidance_prompt_defaults)
        payload["tool_guidance_prompt_overrides"] = dict(self.tool_guidance_prompt_overrides)
        payload["environment_prompt_refs"] = list(self.environment_prompt_refs)
        payload["environment_switch_policy"] = dict(self.environment_switch_policy)
        payload["diagnostics"] = dict(self.diagnostics)
        return payload


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
    prompt_policy_payload = dict(prompt_policy or {})
    guidance_defaults = _environment_guidance_prompt_defaults_for_environment(
        prompt_policy_payload,
        environment_id=selected_environment_id,
    )
    guidance_overrides = _environment_guidance_prompt_overrides_for_environment(
        prompt_policy_payload,
        environment_id=selected_environment_id,
    )
    tool_guidance_defaults = _prompt_ref_map(prompt_policy_payload.get("tool_guidance_prompt_defaults"))
    tool_guidance_overrides = _prompt_ref_map(prompt_policy_payload.get("tool_guidance_prompt_overrides"))
    selected_refs = _environment_prompt_refs(selected_payload)
    guidance_ref_set = _environment_guidance_ref_set(guidance_defaults, guidance_overrides)
    selected_refs_without_guidance = _without_environment_guidance_refs(selected_refs, guidance_ref_set=guidance_ref_set)
    base_refs = selected_refs_without_guidance
    overlay_refs: tuple[str, ...] = ()
    environment_refs = _dedupe(base_refs)
    return PromptMountPlan(
        base_environment_id=base_environment_id,
        selected_environment_id=selected_environment_id,
        personality_prompt_refs=_string_tuple(personality_prompt_refs),
        base_prompt_refs=base_refs,
        overlay_prompt_refs=overlay_refs,
        environment_prompt_refs=environment_refs,
        environment_guidance_prompt_defaults=guidance_defaults,
        environment_guidance_prompt_overrides=guidance_overrides,
        tool_guidance_prompt_defaults=tool_guidance_defaults,
        tool_guidance_prompt_overrides=tool_guidance_overrides,
        environment_switch_policy=_environment_switch_policy(),
        diagnostics={
            "base_prompt_count": len(base_refs),
            "overlay_prompt_count": len(overlay_refs),
            "selected_environment_prompt_count": len(selected_refs_without_guidance),
            "removed_static_environment_guidance_refs": [
                ref for ref in selected_refs if ref in guidance_ref_set
            ],
            "overlay_mode": "selected_environment_only",
            "environment_guidance_prompt_authority": "prompt_set.environment_guidance_catalog",
            "environment_guidance_prompt_default_count": len(guidance_defaults),
            "environment_guidance_prompt_override_count": len(guidance_overrides),
            "ignored_global_environment_guidance_prompt_defaults": list(
                _prompt_ref_map(prompt_policy_payload.get("environment_guidance_prompt_defaults"))
            ),
            "ignored_global_environment_guidance_prompt_overrides": list(
                _prompt_ref_map(prompt_policy_payload.get("environment_guidance_prompt_overrides"))
            ),
            "tool_guidance_prompt_default_count": len(tool_guidance_defaults),
            "tool_guidance_prompt_override_count": len(tool_guidance_overrides),
            "prompt_configuration_authority": "environment_mount_fact_adapter",
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
        environment_guidance_prompt_refs=_string_tuple(raw.get("environment_guidance_prompt_refs")),
        environment_guidance_prompt_keys=_string_tuple(raw.get("environment_guidance_prompt_keys")),
        turn_state_guidance_prompt_refs=_string_tuple(raw.get("turn_state_guidance_prompt_refs")),
        turn_state_guidance_prompt_keys=_string_tuple(raw.get("turn_state_guidance_prompt_keys")),
        environment_guidance_prompt_defaults=_string_dict(raw.get("environment_guidance_prompt_defaults")),
        environment_guidance_prompt_overrides=_string_dict(raw.get("environment_guidance_prompt_overrides")),
        environment_guidance_trigger_reasons=_string_dict(raw.get("environment_guidance_trigger_reasons")),
        turn_state_guidance_trigger_reasons=_string_dict(raw.get("turn_state_guidance_trigger_reasons")),
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
    operation_availability: dict[str, Any] | None = None,
    active_work_context: dict[str, Any] | None = None,
    memory_context: dict[str, Any] | None = None,
    observations: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    visible_tools: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    execution_state: dict[str, Any] | None = None,
    session_context: dict[str, Any] | None = None,
    prompt_pack_refs: tuple[str, ...] = (),
) -> PromptMountPlan:
    plan = base_plan if isinstance(base_plan, PromptMountPlan) else prompt_mount_plan_from_payload(base_plan)
    guidance_selection = select_environment_guidance_for_invocation(
        selected_environment_id=plan.selected_environment_id,
        invocation_kind=invocation_kind,
        allowed_actions=allowed_actions,
        operation_availability=operation_availability,
        active_work_context=active_work_context,
        memory_context=memory_context,
        observations=observations,
        visible_tools=visible_tools,
        execution_state=execution_state,
        session_context=session_context,
        prompt_pack_refs=prompt_pack_refs,
        environment_guidance_prompt_defaults=plan.environment_guidance_prompt_defaults,
        environment_guidance_prompt_overrides=plan.environment_guidance_prompt_overrides,
    )
    diagnostics = {
        **dict(plan.diagnostics or {}),
        "invocation_kind": str(invocation_kind or ""),
        "environment_guidance_prompt_count": len(guidance_selection.stable.refs),
        "environment_guidance_prompt_keys": list(guidance_selection.stable.keys),
        "environment_guidance_prompt_omitted_keys": list(guidance_selection.stable.omitted_keys),
        "environment_guidance_trigger_reasons": dict(guidance_selection.stable.trigger_reasons),
        "turn_state_guidance_prompt_count": len(guidance_selection.runtime.refs),
        "turn_state_guidance_prompt_keys": list(guidance_selection.runtime.keys),
        "runtime_environment_guidance_prompt_omitted_keys": list(guidance_selection.runtime.omitted_keys),
        "turn_state_guidance_trigger_reasons": dict(guidance_selection.runtime.trigger_reasons),
        "environment_guidance_selector_authority": "prompt_library.wiring.environment_guidance_selection",
        "prompt_mount_plan_role": "environment_mount_fact_adapter",
    }
    return PromptMountPlan(
        base_environment_id=plan.base_environment_id,
        selected_environment_id=plan.selected_environment_id,
        personality_prompt_refs=plan.personality_prompt_refs,
        base_prompt_refs=plan.base_prompt_refs,
        overlay_prompt_refs=plan.overlay_prompt_refs,
        environment_guidance_prompt_refs=guidance_selection.stable.refs,
        environment_guidance_prompt_keys=guidance_selection.stable.keys,
        turn_state_guidance_prompt_refs=guidance_selection.runtime.refs,
        turn_state_guidance_prompt_keys=guidance_selection.runtime.keys,
        environment_guidance_prompt_defaults=plan.environment_guidance_prompt_defaults,
        environment_guidance_prompt_overrides=plan.environment_guidance_prompt_overrides,
        environment_guidance_trigger_reasons=guidance_selection.stable.trigger_reasons,
        turn_state_guidance_trigger_reasons=guidance_selection.runtime.trigger_reasons,
        tool_guidance_prompt_defaults=plan.tool_guidance_prompt_defaults,
        tool_guidance_prompt_overrides=plan.tool_guidance_prompt_overrides,
        environment_prompt_refs=plan.environment_prompt_refs,
        environment_switch_policy=plan.environment_switch_policy,
        diagnostics=diagnostics,
    )


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


def _without_environment_guidance_refs(refs: tuple[str, ...], *, guidance_ref_set: set[str] | None = None) -> tuple[str, ...]:
    blocked = guidance_ref_set or _ENVIRONMENT_GUIDANCE_REFS
    return tuple(ref for ref in refs if ref and ref not in blocked)


def _environment_guidance_ref_set(defaults: dict[str, str], overrides: dict[str, str]) -> set[str]:
    return {
        *set(_ENVIRONMENT_GUIDANCE_REFS),
        *{str(item).strip() for item in defaults.values() if str(item).strip()},
        *{str(item).strip() for item in overrides.values() if str(item).strip()},
    }


def _environment_guidance_prompt_defaults_for_environment(prompt_policy: dict[str, Any], *, environment_id: str) -> dict[str, str]:
    environment_defaults = dict(ENVIRONMENT_GUIDANCE_PROMPT_DEFAULTS_BY_ENVIRONMENT.get(environment_id) or {})
    by_environment = _environment_prompt_ref_map(
        prompt_policy.get("environment_guidance_prompt_defaults_by_environment"),
        environment_id=environment_id,
    )
    return {**environment_defaults, **by_environment}


def _environment_guidance_prompt_overrides_for_environment(prompt_policy: dict[str, Any], *, environment_id: str) -> dict[str, str]:
    by_environment = _environment_prompt_ref_map(
        prompt_policy.get("environment_guidance_prompt_overrides_by_environment"),
        environment_id=environment_id,
    )
    return by_environment


def _environment_prompt_ref_map(value: Any, *, environment_id: str) -> dict[str, str]:
    if isinstance(value, dict):
        environment_map = value.get(environment_id)
        if isinstance(environment_map, dict):
            return _prompt_ref_map(environment_map)
    return {}


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


def _environment_switch_policy() -> dict[str, Any]:
    return {
        "mode": "user_or_session_controlled",
        "default_environment_id": GENERAL_ENVIRONMENT_ID,
        "model_may_switch_environment": False,
        "authority": "harness.runtime.environment_switch_policy",
    }


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


