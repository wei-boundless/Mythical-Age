from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .descriptor_resolver import PromptDescriptorResolver
from .environment_guidance_selection import select_environment_guidance_for_invocation
from .models import (
    AgentPromptBinding,
    PromptBindingSlot,
    PromptSet,
    RuntimePromptWiringPlan,
    PromptWiringBinding,
)
from .prompt_set_resolver import PromptSetResolver
from .registry import PromptLibraryRegistry
from .taxonomy import contract_priority_rank


CORE_RUNTIME_SCHEMA_REFS = (
    "action_protocol_schema",
    "control_action_schema",
    "provider_tool_schema",
    "output_commit_schema",
    "context_fragment_metadata",
)

_CONFLICT_POLICY_ORDER = {
    "override": 0,
    "constrain": 1,
    "factual_correction": 2,
    "scoped_guidance": 3,
    "background_only": 4,
    "advisory": 5,
}


@dataclass(frozen=True, slots=True)
class _SlotBindingCandidate:
    slot: str
    refs: tuple[str, ...]
    pack_refs: tuple[str, ...]
    owner_layer: str
    cache_scope: str
    visibility: str
    locked: bool
    contract_priority: str
    conflict_policy: str
    scope: str
    source_prompt_set: str
    order: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_slot(
        cls,
        slot: PromptBindingSlot,
        *,
        slot_name: str,
        refs: tuple[str, ...],
        pack_refs: tuple[str, ...],
        prompt_set: PromptSet,
        order: int,
    ) -> "_SlotBindingCandidate":
        return cls(
            slot=str(slot_name or slot.slot or "").strip(),
            refs=_dedupe(refs),
            pack_refs=_dedupe(pack_refs),
            owner_layer=str(slot.owner_layer or "").strip(),
            cache_scope=str(slot.cache_scope or "").strip(),
            visibility=str(slot.visibility or "model_visible").strip() or "model_visible",
            locked=bool(slot.locked),
            contract_priority=str(slot.contract_priority or "").strip(),
            conflict_policy=str(slot.conflict_policy or "").strip(),
            scope=str(slot.scope or "").strip(),
            source_prompt_set=str(prompt_set.prompt_set_id or "").strip(),
            order=int(order or 0),
            metadata=dict(slot.metadata or {}),
        )

    @property
    def priority_rank(self) -> int:
        return contract_priority_rank(self.contract_priority)

    def to_diagnostic(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "refs": list(self.refs),
            "pack_refs": list(self.pack_refs),
            "owner_layer": self.owner_layer,
            "cache_scope": self.cache_scope,
            "visibility": self.visibility,
            "locked": self.locked,
            "contract_priority": self.contract_priority,
            "priority_rank": self.priority_rank,
            "conflict_policy": self.conflict_policy,
            "scope": self.scope,
            "source_prompt_set": self.source_prompt_set,
            "order": self.order,
        }


def agent_prompt_binding_from_profile(
    agent_profile: Any,
    *,
    environment_id: str = "",
) -> AgentPromptBinding:
    profile_id = str(getattr(agent_profile, "agent_profile_id", "") or "").strip()
    metadata = dict(getattr(agent_profile, "metadata", {}) or {})
    prompt_set_refs = tuple(
        str(item).strip()
        for item in tuple(getattr(agent_profile, "prompt_set_refs", ()) or metadata.get("prompt_set_refs") or ())
        if str(item).strip()
    )
    if not prompt_set_refs:
        prompt_set_refs = _default_prompt_set_refs(profile_id=profile_id, metadata=metadata, environment_id=environment_id)
    return AgentPromptBinding(
        agent_profile_id=profile_id,
        prompt_set_refs=prompt_set_refs,
        invocation_overrides=_string_tuple_map(metadata.get("prompt_set_refs_by_invocation")),
        locked_slots=("runtime_prompt_pack", "action_protocol_schema", "output_commit_schema"),
        metadata={
            "source": "agent_runtime_profile",
        },
    )


def build_runtime_prompt_wiring_plan(
    *,
    base_dir: Path,
    agent_profile: Any,
    invocation_kind: str,
    environment_id: str = "",
    allowed_actions: tuple[str, ...] = (),
    operation_availability: dict[str, Any] | None = None,
    active_work_context: dict[str, Any] | None = None,
    memory_context: dict[str, Any] | None = None,
    observations: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    visible_tools: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    execution_state: dict[str, Any] | None = None,
    session_context: dict[str, Any] | None = None,
    prompt_pack_refs: tuple[str, ...] = (),
) -> RuntimePromptWiringPlan:
    registry = PromptLibraryRegistry(base_dir)
    descriptor_resolver = PromptDescriptorResolver(base_dir)
    profile_id = str(getattr(agent_profile, "agent_profile_id", "") or "").strip()
    binding = agent_prompt_binding_from_profile(agent_profile, environment_id=environment_id)
    invocation = str(invocation_kind or "").strip()
    prompt_set_refs = _prompt_set_refs_for_invocation(binding, invocation_kind=invocation)
    prompt_set_resolution = PromptSetResolver(registry).resolve(prompt_set_refs)
    resolved_sets: list[PromptSet] = []
    prompt_set_resolution_diagnostics = dict(prompt_set_resolution.diagnostics)
    rejected_sets = list(prompt_set_resolution_diagnostics.get("rejected_prompt_sets") or ())
    for prompt_set in prompt_set_resolution.prompt_sets:
        rejection_reason = _prompt_set_rejection_reason(
            prompt_set,
            agent_profile_id=profile_id,
            environment_id=environment_id,
        )
        if rejection_reason:
            rejected_sets.append(
                {
                    "prompt_set_ref": prompt_set.prompt_set_id,
                    "reason": rejection_reason,
                    "owner_kind": prompt_set.owner_kind,
                    "owner_ref": prompt_set.owner_ref,
                }
            )
            continue
        resolved_sets.append(prompt_set)

    slot_candidates_by_name: dict[str, list[_SlotBindingCandidate]] = {}
    for prompt_set in resolved_sets:
        for slot_name, slot in prompt_set.slots.items():
            refs = slot.refs_for_invocation(invocation)
            pack_refs = slot.packs_for_invocation(invocation)
            if not refs and not pack_refs:
                continue
            slot_candidates_by_name.setdefault(slot_name, []).append(
                _SlotBindingCandidate.from_slot(
                    slot,
                    slot_name=slot_name,
                    refs=refs,
                    pack_refs=pack_refs,
                    prompt_set=prompt_set,
                    order=len(slot_candidates_by_name.get(slot_name, ())),
                )
            )
    slots_by_name, slot_conflict_decisions = _resolve_prompt_wiring_slots(
        slot_candidates_by_name,
        descriptor_resolver=descriptor_resolver,
    )

    environment_guidance_defaults = _environment_guidance_defaults_from_prompt_sets(
        resolved_sets,
        environment_id=environment_id,
    )
    environment_guidance_overrides = _environment_guidance_overrides_from_profile(
        agent_profile,
        environment_id=environment_id,
    )
    guidance_selection = select_environment_guidance_for_invocation(
        selected_environment_id=environment_id,
        invocation_kind=invocation,
        allowed_actions=_dedupe(tuple(allowed_actions or ())),
        operation_availability=dict(operation_availability or {}),
        active_work_context=dict(active_work_context or {}),
        memory_context=dict(memory_context or {}),
        observations=tuple(dict(item) for item in list(observations or []) if isinstance(item, dict)),
        visible_tools=tuple(dict(item) for item in list(visible_tools or []) if isinstance(item, dict)),
        execution_state=dict(execution_state or {}),
        session_context=dict(session_context or {}),
        prompt_pack_refs=tuple(prompt_pack_refs or ()),
        environment_guidance_prompt_defaults=environment_guidance_defaults,
        environment_guidance_prompt_overrides=environment_guidance_overrides,
    )
    _upsert_environment_guidance_wiring_slot(
        slots_by_name,
        descriptor_resolver=descriptor_resolver,
        slot_name="environment_guidance_stable",
        refs=guidance_selection.stable.refs,
        keys=guidance_selection.stable.keys,
        trigger_reasons=guidance_selection.stable.trigger_reasons,
        omitted_keys=guidance_selection.stable.omitted_keys,
        source_prompt_sets=tuple(item.prompt_set_id for item in resolved_sets),
        cache_scope="static_environment",
    )
    _upsert_environment_guidance_wiring_slot(
        slots_by_name,
        descriptor_resolver=descriptor_resolver,
        slot_name="environment_guidance_runtime",
        refs=guidance_selection.runtime.refs,
        keys=guidance_selection.runtime.keys,
        trigger_reasons=guidance_selection.runtime.trigger_reasons,
        omitted_keys=guidance_selection.runtime.omitted_keys,
        source_prompt_sets=tuple(item.prompt_set_id for item in resolved_sets),
        cache_scope="none",
    )

    slots = tuple(slots_by_name[key] for key in sorted(slots_by_name))
    identity = {
        "agent_profile_id": profile_id,
        "invocation_kind": invocation,
        "environment_id": str(environment_id or ""),
        "slots": [slot.to_dict() for slot in slots],
        "schema_refs": list(CORE_RUNTIME_SCHEMA_REFS),
    }
    return RuntimePromptWiringPlan(
        wiring_id=f"promptwiring:{_digest(identity)}",
        agent_profile_id=profile_id,
        invocation_kind=invocation,
        environment_id=str(environment_id or ""),
        slots=slots,
        schema_refs=CORE_RUNTIME_SCHEMA_REFS,
        diagnostics={
            "binding": binding.to_dict(),
            "source_prompt_sets": [item.prompt_set_id for item in resolved_sets],
            "source_prompt_set_descriptors": [
                descriptor.to_dict()
                for descriptor in descriptor_resolver.resolve_prompt_refs([item.prompt_set_id for item in resolved_sets])
            ],
            "rejected_prompt_sets": rejected_sets,
            "prompt_set_resolution": prompt_set_resolution.to_dict(),
            "conflict_policy": _conflict_policy_diagnostics(slots),
            "slot_conflict_decisions": slot_conflict_decisions,
            "environment_guidance_selection": {
                "source": "prompt_set.environment_guidance_catalog",
                "defaults": dict(environment_guidance_defaults),
                "overrides": dict(environment_guidance_overrides),
                "stable": {
                    "refs": list(guidance_selection.stable.refs),
                    "keys": list(guidance_selection.stable.keys),
                    "trigger_reasons": dict(guidance_selection.stable.trigger_reasons),
                    "omitted_keys": list(guidance_selection.stable.omitted_keys),
                },
                "runtime": {
                    "refs": list(guidance_selection.runtime.refs),
                    "keys": list(guidance_selection.runtime.keys),
                    "trigger_reasons": dict(guidance_selection.runtime.trigger_reasons),
                    "omitted_keys": list(guidance_selection.runtime.omitted_keys),
                },
            },
            "authority": "prompt_library.wiring.build_runtime_prompt_wiring_plan",
        },
    )


def _prompt_set_refs_for_invocation(binding: AgentPromptBinding, *, invocation_kind: str) -> tuple[str, ...]:
    override_refs = tuple(binding.invocation_overrides.get(str(invocation_kind or "").strip()) or ())
    return _dedupe((*binding.prompt_set_refs, *override_refs))


def _default_prompt_set_refs(*, profile_id: str, metadata: dict[str, Any], environment_id: str) -> tuple[str, ...]:
    main_kind = str(metadata.get("main_agent_kind") or "").strip()
    if not main_kind:
        if profile_id == "main_coding_agent":
            main_kind = "coding"
        elif profile_id == "main_office_agent":
            main_kind = "office"
        elif profile_id == "main_interactive_agent":
            main_kind = "general"
    agent_set = {
        "coding": "prompt_set.agent.main_coding",
        "office": "prompt_set.agent.main_office",
        "general": "prompt_set.agent.main_interactive",
    }.get(main_kind, "")
    environment_set = _environment_prompt_set_ref(environment_id or metadata.get("default_task_environment_id"))
    refs = ["prompt_set.runtime.default_turn"]
    if agent_set:
        refs.append(agent_set)
    if environment_set:
        refs.append(environment_set)
    return tuple(refs)


def _environment_prompt_set_ref(environment_id: Any) -> str:
    value = str(environment_id or "").strip()
    if value == "env.coding.vibe_workspace":
        return "prompt_set.environment.coding"
    if value == "env.office.file_search":
        return "prompt_set.environment.office"
    if value == "env.general.workspace":
        return "prompt_set.environment.general"
    return ""


def _prompt_set_rejection_reason(
    prompt_set: PromptSet,
    *,
    agent_profile_id: str,
    environment_id: str,
) -> str:
    allowed_agents = {str(item).strip() for item in tuple(prompt_set.allowed_agent_refs or ()) if str(item).strip()}
    profile = str(agent_profile_id or "").strip()
    if allowed_agents and (not profile or profile not in allowed_agents):
        return "prompt_set_agent_ref_mismatch"
    allowed_environments = {
        str(item).strip() for item in tuple(prompt_set.allowed_environment_refs or ()) if str(item).strip()
    }
    environment = str(environment_id or "").strip()
    if allowed_environments and environment and environment not in allowed_environments:
        return "prompt_set_environment_ref_mismatch"
    return ""


def _resolve_prompt_wiring_slots(
    candidates_by_name: dict[str, list[_SlotBindingCandidate]],
    *,
    descriptor_resolver: PromptDescriptorResolver,
) -> tuple[dict[str, PromptWiringBinding], list[dict[str, Any]]]:
    slots_by_name: dict[str, PromptWiringBinding] = {}
    decisions: list[dict[str, Any]] = []
    for slot_name in sorted(candidates_by_name):
        candidates = list(candidates_by_name.get(slot_name) or [])
        if not candidates:
            continue
        selected, omitted, reason = _select_slot_candidates(candidates)
        if selected:
            slots_by_name[slot_name] = _wiring_binding_from_selected_candidates(
                slot_name,
                selected,
                descriptor_resolver=descriptor_resolver,
                decision_reason=reason,
                omitted=omitted,
            )
        decisions.append(
            {
                "slot": slot_name,
                "decision": reason,
                "selected": [candidate.to_diagnostic() for candidate in selected],
                "omitted": [dict(item) for item in omitted],
                "authority": "prompt_library.wiring.slot_conflict_resolver",
            }
        )
    return slots_by_name, decisions


def _select_slot_candidates(
    candidates: list[_SlotBindingCandidate],
) -> tuple[list[_SlotBindingCandidate], list[dict[str, Any]], str]:
    ordered = sorted(candidates, key=_candidate_order_key)
    locked_candidates = [candidate for candidate in ordered if candidate.locked]
    if locked_candidates:
        selected = [locked_candidates[0]]
        selected_key = _candidate_identity(selected[0])
        omitted = [
            {
                **candidate.to_diagnostic(),
                "reason": "locked_slot_authority_selected_elsewhere"
                if _candidate_identity(candidate) != selected_key
                else "duplicate_locked_slot_candidate",
            }
            for candidate in ordered
            if candidate is not selected[0]
        ]
        return selected, omitted, "locked_slot_authority"

    selected: list[_SlotBindingCandidate] = []
    omitted: list[dict[str, Any]] = []
    for candidate in ordered:
        blocker = _higher_override_blocker(selected, candidate)
        if blocker is not None:
            omitted.append(
                {
                    **candidate.to_diagnostic(),
                    "reason": "blocked_by_higher_priority_override",
                    "blocking_source_prompt_set": blocker.source_prompt_set,
                    "blocking_contract_priority": blocker.contract_priority,
                }
            )
            continue
        if candidate.conflict_policy == "override":
            retained: list[_SlotBindingCandidate] = []
            for selected_candidate in selected:
                if (
                    _slot_scope_conflicts(selected_candidate, candidate)
                    and selected_candidate.priority_rank >= candidate.priority_rank
                ):
                    omitted.append(
                        {
                            **selected_candidate.to_diagnostic(),
                            "reason": "replaced_by_slot_override",
                            "replacing_source_prompt_set": candidate.source_prompt_set,
                            "replacing_contract_priority": candidate.contract_priority,
                        }
                    )
                    continue
                retained.append(selected_candidate)
            selected = retained
            selected.append(candidate)
            continue
        if candidate.conflict_policy in {"background_only", "advisory"} and _has_higher_hard_candidate(
            selected,
            candidate,
        ):
            omitted.append(
                {
                    **candidate.to_diagnostic(),
                    "reason": "background_or_advisory_omitted_after_hard_slot_candidate",
                }
            )
            continue
        selected.append(candidate)
    selected = sorted(selected, key=_candidate_order_key)
    return selected, omitted, "priority_conflict_policy_resolved"


def _wiring_binding_from_selected_candidates(
    slot_name: str,
    selected: list[_SlotBindingCandidate],
    *,
    descriptor_resolver: PromptDescriptorResolver,
    decision_reason: str,
    omitted: list[dict[str, Any]],
) -> PromptWiringBinding:
    ordered = sorted(selected, key=_candidate_order_key)
    primary = ordered[0]
    refs = _dedupe([ref for candidate in ordered for ref in candidate.refs])
    pack_refs = _dedupe([ref for candidate in ordered for ref in candidate.pack_refs])
    metadata: dict[str, Any] = {}
    for candidate in ordered:
        metadata.update(dict(candidate.metadata or {}))
    metadata.update(
        {
            "prompt_descriptors": [
                descriptor.to_dict()
                for descriptor in descriptor_resolver.resolve_prompt_refs(_dedupe((*refs, *pack_refs)))
            ],
            "slot_conflict_resolution": {
                "decision": decision_reason,
                "selected_source_prompt_sets": [candidate.source_prompt_set for candidate in ordered],
                "selected_contract_priorities": [candidate.contract_priority for candidate in ordered],
                "selected_conflict_policies": [candidate.conflict_policy for candidate in ordered],
                "omitted": [dict(item) for item in omitted],
                "authority": "prompt_library.wiring.slot_conflict_resolver",
            },
        }
    )
    return PromptWiringBinding(
        slot=slot_name,
        refs=refs,
        pack_refs=pack_refs,
        owner_layer=primary.owner_layer,
        cache_scope=primary.cache_scope,
        visibility=primary.visibility,
        locked=any(candidate.locked for candidate in ordered),
        contract_priority=primary.contract_priority,
        conflict_policy=primary.conflict_policy,
        scope=primary.scope,
        source_prompt_sets=_dedupe([candidate.source_prompt_set for candidate in ordered]),
        metadata=metadata,
    )


def _candidate_order_key(candidate: _SlotBindingCandidate) -> tuple[int, int, int]:
    return (
        candidate.priority_rank,
        _CONFLICT_POLICY_ORDER.get(candidate.conflict_policy, _CONFLICT_POLICY_ORDER["scoped_guidance"]),
        candidate.order,
    )


def _candidate_identity(candidate: _SlotBindingCandidate) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    return (candidate.slot, candidate.source_prompt_set, candidate.refs, candidate.pack_refs)


def _higher_override_blocker(
    selected: list[_SlotBindingCandidate],
    candidate: _SlotBindingCandidate,
) -> _SlotBindingCandidate | None:
    for selected_candidate in selected:
        if selected_candidate.conflict_policy != "override":
            continue
        if selected_candidate.priority_rank > candidate.priority_rank:
            continue
        if _slot_scope_conflicts(selected_candidate, candidate):
            return selected_candidate
    return None


def _has_higher_hard_candidate(
    selected: list[_SlotBindingCandidate],
    candidate: _SlotBindingCandidate,
) -> bool:
    for selected_candidate in selected:
        if selected_candidate.priority_rank > candidate.priority_rank:
            continue
        if selected_candidate.conflict_policy not in {"override", "constrain", "factual_correction"}:
            continue
        if _slot_scope_conflicts(selected_candidate, candidate):
            return True
    return False


def _slot_scope_conflicts(left: _SlotBindingCandidate, right: _SlotBindingCandidate) -> bool:
    left_scope = str(left.scope or "").strip()
    right_scope = str(right.scope or "").strip()
    return not left_scope or not right_scope or left_scope == right_scope


def _string_tuple_map(value: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for key, raw_values in value.items():
        refs = tuple(str(item).strip() for item in list(raw_values or []) if str(item).strip())
        if str(key or "").strip() and refs:
            result[str(key).strip()] = refs
    return result


def _environment_guidance_defaults_from_prompt_sets(
    prompt_sets: list[PromptSet],
    *,
    environment_id: str,
) -> dict[str, str]:
    result: dict[str, str] = {}
    target_environment_id = str(environment_id or "").strip()
    for prompt_set in prompt_sets:
        if prompt_set.owner_kind != "environment":
            continue
        if target_environment_id and prompt_set.owner_ref and prompt_set.owner_ref != target_environment_id:
            continue
        metadata_defaults = _string_dict(dict(prompt_set.metadata or {}).get("environment_guidance_prompt_defaults"))
        if metadata_defaults:
            result.update(metadata_defaults)
            continue
        catalog_slot = prompt_set.slots.get("environment_guidance_catalog")
        if catalog_slot is not None:
            result.update(_string_dict(dict(catalog_slot.metadata or {}).get("guidance_slot_refs")))
    return result


def _environment_guidance_overrides_from_profile(agent_profile: Any, *, environment_id: str) -> dict[str, str]:
    prompt_bindings = dict(getattr(agent_profile, "prompt_bindings", {}) or {})
    metadata = dict(getattr(agent_profile, "metadata", {}) or {})
    environment = str(environment_id or "").strip()
    result: dict[str, str] = {}
    for source in (metadata, prompt_bindings):
        result.update(_string_dict(source.get("environment_guidance_prompt_overrides")))
        by_environment = source.get("environment_guidance_prompt_overrides_by_environment")
        if isinstance(by_environment, dict):
            result.update(_string_dict(dict(by_environment.get(environment) or {})))
    return result


def _upsert_environment_guidance_wiring_slot(
    slots_by_name: dict[str, PromptWiringBinding],
    *,
    descriptor_resolver: PromptDescriptorResolver,
    slot_name: str,
    refs: tuple[str, ...],
    keys: tuple[str, ...],
    trigger_reasons: dict[str, str],
    omitted_keys: tuple[str, ...],
    source_prompt_sets: tuple[str, ...],
    cache_scope: str,
) -> None:
    if not refs and not omitted_keys:
        return
    existing = slots_by_name.get(slot_name)
    selected_refs = _dedupe((*tuple(existing.refs if existing else ()), *refs))
    slots_by_name[slot_name] = PromptWiringBinding(
        slot=slot_name,
        refs=selected_refs,
        pack_refs=tuple(existing.pack_refs if existing else ()),
        owner_layer="environment",
        cache_scope=cache_scope,
        visibility="model_visible",
        locked=False,
        contract_priority="owner_guidance",
        conflict_policy="scoped_guidance",
        scope="environment_guidance",
        source_prompt_sets=_dedupe((*tuple(existing.source_prompt_sets if existing else ()), *source_prompt_sets)),
        metadata={
            **dict(existing.metadata if existing else {}),
            "environment_guidance_prompt_keys": list(keys),
            "environment_guidance_trigger_reasons": dict(trigger_reasons),
            "environment_guidance_prompt_omitted_keys": list(omitted_keys),
            "prompt_descriptors": [
                descriptor.to_dict()
                for descriptor in descriptor_resolver.resolve_prompt_refs(selected_refs)
            ],
            "selection_authority": "prompt_library.wiring.environment_guidance_selection",
        },
    )


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key).strip(): str(item).strip()
        for key, item in value.items()
        if str(key).strip() and str(item).strip()
    }


def _dedupe(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def _conflict_policy_diagnostics(slots: tuple[PromptWiringBinding, ...]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for slot in slots:
        diagnostics.append(
            {
                "slot": slot.slot,
                "contract_priority": slot.contract_priority,
                "conflict_policy": slot.conflict_policy,
                "scope": slot.scope,
                "locked": slot.locked,
                "refs": list(slot.refs),
                "pack_refs": list(slot.pack_refs),
            }
        )
    return diagnostics


def _digest(payload: Any) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:20]
