from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .descriptor_resolver import PromptDescriptorResolver
from .environment_guidance_selection import select_environment_guidance_for_invocation
from .models import (
    AgentPromptBinding,
    PromptSet,
    RuntimePromptWiringPlan,
    RuntimePromptWiringSlot,
)
from .registry import PromptLibraryRegistry


CORE_RUNTIME_SCHEMA_REFS = (
    "action_protocol_schema",
    "control_action_schema",
    "provider_tool_schema",
    "output_commit_schema",
    "context_fragment_metadata",
)


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
    resolved_sets: list[PromptSet] = []
    rejected_sets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for prompt_set_ref in prompt_set_refs:
        _collect_prompt_set(
            registry,
            prompt_set_ref=prompt_set_ref,
            resolved=resolved_sets,
            rejected=rejected_sets,
            seen=seen,
        )

    slots_by_name: dict[str, RuntimePromptWiringSlot] = {}
    for prompt_set in resolved_sets:
        for slot_name, slot in prompt_set.slots.items():
            refs = slot.refs_for_invocation(invocation)
            pack_refs = slot.packs_for_invocation(invocation)
            if not refs and not pack_refs:
                continue
            existing = slots_by_name.get(slot_name)
            slots_by_name[slot_name] = RuntimePromptWiringSlot(
                slot=slot_name,
                refs=_dedupe((*tuple(existing.refs if existing else ()), *refs)),
                pack_refs=_dedupe((*tuple(existing.pack_refs if existing else ()), *pack_refs)),
                owner_layer=slot.owner_layer or (existing.owner_layer if existing else ""),
                cache_scope=slot.cache_scope or (existing.cache_scope if existing else ""),
                visibility=slot.visibility or (existing.visibility if existing else "model_visible"),
                locked=bool(slot.locked or (existing.locked if existing else False)),
                contract_priority=slot.contract_priority or (existing.contract_priority if existing else ""),
                conflict_policy=slot.conflict_policy or (existing.conflict_policy if existing else ""),
                scope=slot.scope or (existing.scope if existing else ""),
                source_prompt_sets=_dedupe(
                    (*tuple(existing.source_prompt_sets if existing else ()), prompt_set.prompt_set_id)
                ),
                metadata={
                    **dict(existing.metadata if existing else {}),
                    **dict(slot.metadata or {}),
                    "prompt_descriptors": [
                        descriptor.to_dict()
                        for descriptor in descriptor_resolver.resolve_prompt_refs(_dedupe((*refs, *pack_refs)))
                    ],
                },
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
            "conflict_policy": _conflict_policy_diagnostics(slots),
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


def _collect_prompt_set(
    registry: PromptLibraryRegistry,
    *,
    prompt_set_ref: str,
    resolved: list[PromptSet],
    rejected: list[dict[str, Any]],
    seen: set[str],
) -> None:
    ref = str(prompt_set_ref or "").strip()
    if not ref or ref in seen:
        return
    seen.add(ref)
    prompt_set = registry.get_prompt_set(ref)
    if prompt_set is None:
        rejected.append({"prompt_set_ref": ref, "reason": "prompt_set_not_found_or_inactive"})
        return
    for parent_ref in prompt_set.extends:
        _collect_prompt_set(registry, prompt_set_ref=parent_ref, resolved=resolved, rejected=rejected, seen=seen)
    resolved.append(prompt_set)


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
    slots_by_name: dict[str, RuntimePromptWiringSlot],
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
    slots_by_name[slot_name] = RuntimePromptWiringSlot(
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


def _conflict_policy_diagnostics(slots: tuple[RuntimePromptWiringSlot, ...]) -> list[dict[str, Any]]:
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
