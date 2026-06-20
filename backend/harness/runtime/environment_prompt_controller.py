from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from prompt_library import ALL_ENVIRONMENT_LIFECYCLE_PROMPT_IDS, ENVIRONMENT_LIFECYCLE_PROMPT_SLOTS


GENERAL_ENVIRONMENT_ID = "env.general.workspace"

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
    runtime_lifecycle_prompt_refs: tuple[str, ...] = ()
    runtime_lifecycle_prompt_keys: tuple[str, ...] = ()
    lifecycle_prompt_defaults: dict[str, str] = field(default_factory=dict)
    lifecycle_prompt_overrides: dict[str, str] = field(default_factory=dict)
    lifecycle_trigger_reasons: dict[str, str] = field(default_factory=dict)
    runtime_lifecycle_trigger_reasons: dict[str, str] = field(default_factory=dict)
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
        payload["runtime_lifecycle_prompt_refs"] = list(self.runtime_lifecycle_prompt_refs)
        payload["runtime_lifecycle_prompt_keys"] = list(self.runtime_lifecycle_prompt_keys)
        payload["lifecycle_prompt_defaults"] = dict(self.lifecycle_prompt_defaults)
        payload["lifecycle_prompt_overrides"] = dict(self.lifecycle_prompt_overrides)
        payload["lifecycle_trigger_reasons"] = dict(self.lifecycle_trigger_reasons)
        payload["runtime_lifecycle_trigger_reasons"] = dict(self.runtime_lifecycle_trigger_reasons)
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


@dataclass(frozen=True, slots=True)
class LifecyclePromptSplitSelection:
    stable: LifecyclePromptSelection = field(default_factory=LifecyclePromptSelection)
    runtime: LifecyclePromptSelection = field(default_factory=LifecyclePromptSelection)


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
        runtime_lifecycle_prompt_refs=_string_tuple(raw.get("runtime_lifecycle_prompt_refs")),
        runtime_lifecycle_prompt_keys=_string_tuple(raw.get("runtime_lifecycle_prompt_keys")),
        lifecycle_prompt_defaults=_string_dict(raw.get("lifecycle_prompt_defaults")),
        lifecycle_prompt_overrides=_string_dict(raw.get("lifecycle_prompt_overrides")),
        lifecycle_trigger_reasons=_string_dict(raw.get("lifecycle_trigger_reasons")),
        runtime_lifecycle_trigger_reasons=_string_dict(raw.get("runtime_lifecycle_trigger_reasons")),
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
    lifecycle_selection = _lifecycle_prompt_selection_for_invocation(
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
        lifecycle_prompt_defaults=plan.lifecycle_prompt_defaults,
        lifecycle_prompt_overrides=plan.lifecycle_prompt_overrides,
    )
    diagnostics = {
        **dict(plan.diagnostics or {}),
        "invocation_kind": str(invocation_kind or ""),
        "lifecycle_prompt_count": len(lifecycle_selection.stable.refs),
        "lifecycle_prompt_keys": list(lifecycle_selection.stable.keys),
        "lifecycle_prompt_omitted_keys": list(lifecycle_selection.stable.omitted_keys),
        "lifecycle_trigger_reasons": dict(lifecycle_selection.stable.trigger_reasons),
        "runtime_lifecycle_prompt_count": len(lifecycle_selection.runtime.refs),
        "runtime_lifecycle_prompt_keys": list(lifecycle_selection.runtime.keys),
        "runtime_lifecycle_prompt_omitted_keys": list(lifecycle_selection.runtime.omitted_keys),
        "runtime_lifecycle_trigger_reasons": dict(lifecycle_selection.runtime.trigger_reasons),
        "lifecycle_selector_authority": "harness.runtime.environment_prompt_controller.lifecycle_selector",
    }
    return PromptMountPlan(
        base_environment_id=plan.base_environment_id,
        selected_environment_id=plan.selected_environment_id,
        personality_prompt_refs=plan.personality_prompt_refs,
        base_prompt_refs=plan.base_prompt_refs,
        overlay_prompt_refs=plan.overlay_prompt_refs,
        lifecycle_prompt_refs=lifecycle_selection.stable.refs,
        lifecycle_prompt_keys=lifecycle_selection.stable.keys,
        runtime_lifecycle_prompt_refs=lifecycle_selection.runtime.refs,
        runtime_lifecycle_prompt_keys=lifecycle_selection.runtime.keys,
        lifecycle_prompt_defaults=plan.lifecycle_prompt_defaults,
        lifecycle_prompt_overrides=plan.lifecycle_prompt_overrides,
        lifecycle_trigger_reasons=lifecycle_selection.stable.trigger_reasons,
        runtime_lifecycle_trigger_reasons=lifecycle_selection.runtime.trigger_reasons,
        tool_guidance_prompt_defaults=plan.tool_guidance_prompt_defaults,
        tool_guidance_prompt_overrides=plan.tool_guidance_prompt_overrides,
        environment_prompt_refs=plan.environment_prompt_refs,
        environment_switch_policy=plan.environment_switch_policy,
        diagnostics=diagnostics,
    )


def _lifecycle_prompt_selection_for_invocation(
    *,
    selected_environment_id: str,
    invocation_kind: str,
    allowed_actions: tuple[str, ...],
    operation_availability: dict[str, Any] | None,
    active_work_context: dict[str, Any] | None,
    memory_context: dict[str, Any] | None,
    observations: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    visible_tools: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    execution_state: dict[str, Any] | None,
    session_context: dict[str, Any] | None,
    prompt_pack_refs: tuple[str, ...],
    lifecycle_prompt_defaults: dict[str, str],
    lifecycle_prompt_overrides: dict[str, str],
) -> LifecyclePromptSplitSelection:
    invocation = str(invocation_kind or "").strip()
    if "runtime.pack.graph_node_execution" in set(prompt_pack_refs):
        return LifecyclePromptSplitSelection()
    if not lifecycle_prompt_defaults and not lifecycle_prompt_overrides:
        return LifecyclePromptSplitSelection()

    environment_kind = _environment_kind_for_id(selected_environment_id)
    stable_reasons: dict[str, str] = {}
    runtime_reasons: dict[str, str] = {}
    for lifecycle_key, reason in _core_lifecycle_reasons(
        invocation_kind=invocation,
        environment_kind=environment_kind,
    ):
        _select_lifecycle_key(stable_reasons, lifecycle_key, reason)
    for lifecycle_key, reason in _capability_lifecycle_reasons(
        invocation_kind=invocation,
        environment_kind=environment_kind,
        allowed_actions=allowed_actions,
        operation_availability=operation_availability,
        visible_tools=visible_tools,
        active_work_context=active_work_context,
    ):
        _select_lifecycle_key(stable_reasons, lifecycle_key, reason)
    for lifecycle_key, reason in _state_lifecycle_reasons(
        invocation_kind=invocation,
        environment_kind=environment_kind,
        active_work_context=active_work_context,
        memory_context=memory_context,
        observations=observations,
        execution_state=execution_state,
        session_context=session_context,
        visible_tools=visible_tools,
    ):
        _select_lifecycle_key(runtime_reasons, lifecycle_key, reason)
    runtime_reasons = {
        key: reason
        for key, reason in runtime_reasons.items()
        if key not in stable_reasons
    }

    return LifecyclePromptSplitSelection(
        stable=_resolve_lifecycle_selection(
            stable_reasons,
            lifecycle_prompt_defaults=lifecycle_prompt_defaults,
            lifecycle_prompt_overrides=lifecycle_prompt_overrides,
        ),
        runtime=_resolve_lifecycle_selection(
            runtime_reasons,
            lifecycle_prompt_defaults=lifecycle_prompt_defaults,
            lifecycle_prompt_overrides=lifecycle_prompt_overrides,
        ),
    )


def _resolve_lifecycle_selection(
    selected_reasons: dict[str, str],
    *,
    lifecycle_prompt_defaults: dict[str, str],
    lifecycle_prompt_overrides: dict[str, str],
) -> LifecyclePromptSelection:
    refs: list[str] = []
    keys: list[str] = []
    omitted_keys: list[str] = []
    trigger_reasons: dict[str, str] = {}
    for lifecycle_key in ENVIRONMENT_LIFECYCLE_PROMPT_SLOTS:
        if lifecycle_key not in selected_reasons:
            continue
        prompt_ref = _resolve_prompt_slot(
            lifecycle_key,
            defaults=lifecycle_prompt_defaults,
            overrides=lifecycle_prompt_overrides,
        )
        if not prompt_ref:
            if lifecycle_key not in omitted_keys:
                omitted_keys.append(lifecycle_key)
            continue
        if prompt_ref in trigger_reasons:
            continue
        keys.append(lifecycle_key)
        refs.append(prompt_ref)
        trigger_reasons[prompt_ref] = selected_reasons[lifecycle_key]
    return LifecyclePromptSelection(
        refs=_dedupe(refs),
        keys=_dedupe(keys),
        trigger_reasons=trigger_reasons,
        omitted_keys=_dedupe(omitted_keys),
    )


def _core_lifecycle_reasons(
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
                "action_selection",
                "finalization",
            )
        else:
            keys = (
                "context_intake",
                "request_judgment",
                "environment_capability_alignment",
                "action_selection",
                "finalization",
            )
        return tuple((key, f"core: {environment_kind} single_agent_turn requires {key}") for key in keys)
    if invocation_kind == "task_execution":
        keys = (
            "context_intake",
            "environment_capability_alignment",
            "tool_observation_recovery",
            "action_selection",
            "verification_gate",
            "finalization",
        )
        return tuple((key, f"core: {environment_kind} task_execution requires {key}") for key in keys)
    if invocation_kind == "tool_observation_followup":
        keys = (
            "context_intake",
            "tool_observation_recovery",
            "action_selection",
            "finalization",
        )
        return tuple(
            (key, f"core: {environment_kind} tool_observation_followup requires {key}")
            for key in keys
        )
    return ()


def _capability_lifecycle_reasons(
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


def _state_lifecycle_reasons(
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
    if invocation_kind == "tool_observation_followup" and _observations_include_recovery_boundary(observations):
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


def _select_lifecycle_key(selected_reasons: dict[str, str], lifecycle_key: str, reason: str) -> None:
    key = str(lifecycle_key or "").strip()
    if key and key not in selected_reasons:
        selected_reasons[key] = str(reason or "").strip()


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
        "model_may_switch_environment": False,
        "authority": "harness.runtime.environment_switch_policy",
    }


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


def _observations_include_recovery_boundary(observations: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> bool:
    for observation in list(observations or []):
        if not isinstance(observation, dict):
            continue
        status = str(observation.get("status") or "").strip().lower()
        if status in {"error", "failed", "failure", "blocked", "denied", "timeout", "rejected"}:
            return True
        if _nested_payload_present(observation, _RECOVERY_BOUNDARY_KEYS):
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
    "recoverable_work",
    "recovery_boundary",
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
_RECOVERY_BOUNDARY_KEYS = {
    "error",
    "error_code",
    "permission_denied",
    "denied",
    "tool_unavailable",
    "capability_unavailable",
    "timeout",
    "recoverable_error",
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
