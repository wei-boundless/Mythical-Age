from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from prompt_library import GENERAL_LIFECYCLE_PROMPT_IDS


GENERAL_ENVIRONMENT_ID = "env.general.workspace"
ENVIRONMENT_SWITCH_REQUEST_ACTION = "environment_switch_request"

_GENERAL_BASE_FALLBACK_REFS = (
    "environment.general.workspace.orientation.v1",
    "environment.rule.general_workspace.v1",
)

_LIFECYCLE = {
    "context_intake": "environment.general.lifecycle.context_intake",
    "request_judgment": "environment.general.lifecycle.request_judgment",
    "environment_capability_alignment": "environment.general.lifecycle.environment_capability_alignment",
    "action_selection": "environment.general.lifecycle.action_selection",
    "active_work_control": "environment.general.lifecycle.active_work_control",
    "task_run_handoff": "environment.general.lifecycle.task_run_handoff",
    "user_steer_contract_revision": "environment.general.lifecycle.user_steer_contract_revision",
    "tool_observation_recovery": "environment.general.lifecycle.tool_observation_recovery",
    "memory_state_handoff": "environment.general.lifecycle.memory_state_handoff",
    "finalization": "environment.general.lifecycle.finalization",
}
_LIFECYCLE_REFS = set(GENERAL_LIFECYCLE_PROMPT_IDS)


@dataclass(frozen=True, slots=True)
class PromptMountPlan:
    base_environment_id: str = GENERAL_ENVIRONMENT_ID
    selected_environment_id: str = GENERAL_ENVIRONMENT_ID
    personality_prompt_refs: tuple[str, ...] = ()
    base_prompt_refs: tuple[str, ...] = ()
    overlay_prompt_refs: tuple[str, ...] = ()
    lifecycle_prompt_refs: tuple[str, ...] = ()
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
) -> PromptMountPlan:
    selected_payload = dict(selected_environment or {})
    base_payload = dict(base_environment or {})
    selected_environment_id = _environment_id(selected_payload) or GENERAL_ENVIRONMENT_ID
    base_environment_id = _environment_id(base_payload) or GENERAL_ENVIRONMENT_ID
    selected_refs = _environment_prompt_refs(selected_payload)
    selected_refs_without_lifecycle = _without_lifecycle_refs(selected_refs)
    if selected_environment_id == GENERAL_ENVIRONMENT_ID:
        base_refs = selected_refs_without_lifecycle
        overlay_refs: tuple[str, ...] = ()
    else:
        base_refs = _general_base_prompt_refs(base_payload)
        overlay_refs = selected_refs_without_lifecycle
    environment_refs = _dedupe((*base_refs, *overlay_refs))
    return PromptMountPlan(
        base_environment_id=base_environment_id,
        selected_environment_id=selected_environment_id,
        personality_prompt_refs=_string_tuple(personality_prompt_refs),
        base_prompt_refs=base_refs,
        overlay_prompt_refs=overlay_refs,
        environment_prompt_refs=environment_refs,
        environment_switch_policy=_environment_switch_policy(),
        diagnostics={
            "base_prompt_count": len(base_refs),
            "overlay_prompt_count": len(overlay_refs),
            "selected_environment_prompt_count": len(selected_refs_without_lifecycle),
            "removed_static_lifecycle_refs": [
                ref for ref in selected_refs if ref in _LIFECYCLE_REFS
            ],
            "overlay_mode": "base_only" if selected_environment_id == GENERAL_ENVIRONMENT_ID else "general_base_plus_selected_overlay",
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
    execution_state: dict[str, Any] | None = None,
    session_context: dict[str, Any] | None = None,
    prompt_pack_refs: tuple[str, ...] = (),
) -> PromptMountPlan:
    plan = base_plan if isinstance(base_plan, PromptMountPlan) else prompt_mount_plan_from_payload(base_plan)
    lifecycle_refs = _lifecycle_prompt_refs_for_invocation(
        invocation_kind=invocation_kind,
        allowed_actions=allowed_actions,
        active_work_context=active_work_context,
        memory_context=memory_context,
        observations=observations,
        execution_state=execution_state,
        session_context=session_context,
        prompt_pack_refs=prompt_pack_refs,
    )
    diagnostics = {
        **dict(plan.diagnostics or {}),
        "invocation_kind": str(invocation_kind or ""),
        "lifecycle_prompt_count": len(lifecycle_refs),
        "lifecycle_selector_authority": "harness.runtime.environment_prompt_controller.lifecycle_selector",
    }
    return PromptMountPlan(
        base_environment_id=plan.base_environment_id,
        selected_environment_id=plan.selected_environment_id,
        personality_prompt_refs=plan.personality_prompt_refs,
        base_prompt_refs=plan.base_prompt_refs,
        overlay_prompt_refs=plan.overlay_prompt_refs,
        lifecycle_prompt_refs=lifecycle_refs,
        environment_prompt_refs=plan.environment_prompt_refs,
        environment_switch_policy=plan.environment_switch_policy,
        diagnostics=diagnostics,
    )


def _lifecycle_prompt_refs_for_invocation(
    *,
    invocation_kind: str,
    allowed_actions: tuple[str, ...],
    active_work_context: dict[str, Any] | None,
    memory_context: dict[str, Any] | None,
    observations: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    execution_state: dict[str, Any] | None,
    session_context: dict[str, Any] | None,
    prompt_pack_refs: tuple[str, ...],
) -> tuple[str, ...]:
    invocation = str(invocation_kind or "").strip()
    if "runtime.pack.graph_node_execution.v1" in set(prompt_pack_refs):
        return ()
    refs: list[str] = []
    allowed = {str(item) for item in allowed_actions if str(item)}
    has_memory = _has_visible_memory(memory_context) or _has_visible_memory(dict(session_context or {}).get("memory_context"))
    has_observations = bool([item for item in list(observations or []) if isinstance(item, dict)])
    has_pending_steers = _has_pending_user_steers(execution_state)
    if invocation == "single_agent_turn":
        refs.extend(
            [
                _LIFECYCLE["context_intake"],
                _LIFECYCLE["request_judgment"],
                _LIFECYCLE["environment_capability_alignment"],
                _LIFECYCLE["action_selection"],
            ]
        )
        if active_work_context and "active_work_control" in allowed:
            refs.append(_LIFECYCLE["active_work_control"])
            refs.append(_LIFECYCLE["user_steer_contract_revision"])
        if "request_task_run" in allowed:
            refs.append(_LIFECYCLE["task_run_handoff"])
        if has_memory:
            refs.append(_LIFECYCLE["memory_state_handoff"])
        refs.append(_LIFECYCLE["finalization"])
        return _dedupe(refs)
    if invocation == "tool_observation_followup":
        refs.extend(
            [
                _LIFECYCLE["context_intake"],
                _LIFECYCLE["environment_capability_alignment"],
                _LIFECYCLE["action_selection"],
                _LIFECYCLE["tool_observation_recovery"],
            ]
        )
        if has_memory:
            refs.append(_LIFECYCLE["memory_state_handoff"])
        refs.append(_LIFECYCLE["finalization"])
        return _dedupe(refs)
    if invocation == "task_execution":
        refs.extend(
            [
                _LIFECYCLE["context_intake"],
                _LIFECYCLE["environment_capability_alignment"],
                _LIFECYCLE["action_selection"],
            ]
        )
        if has_observations:
            refs.append(_LIFECYCLE["tool_observation_recovery"])
        if has_pending_steers:
            refs.append(_LIFECYCLE["user_steer_contract_revision"])
        if has_memory:
            refs.append(_LIFECYCLE["memory_state_handoff"])
        refs.append(_LIFECYCLE["finalization"])
        return _dedupe(refs)
    return ()


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


def _general_base_prompt_refs(base_payload: dict[str, Any]) -> tuple[str, ...]:
    boundary = dict(base_payload.get("environment_boundary") or {})
    specific = _without_lifecycle_refs(_string_tuple(boundary.get("environment_specific_prompt_refs")))
    if specific:
        return specific
    refs = _without_lifecycle_refs(_environment_prompt_refs(base_payload))
    resource_refs = set(_string_tuple(boundary.get("resource_prompt_refs")))
    filtered = tuple(ref for ref in refs if ref not in resource_refs)
    return filtered or _GENERAL_BASE_FALLBACK_REFS


def _without_lifecycle_refs(refs: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(ref for ref in refs if ref and ref not in _LIFECYCLE_REFS)


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


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_values = [value]
    else:
        raw_values = list(value or [])
    return tuple(str(item).strip() for item in raw_values if str(item).strip())


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
