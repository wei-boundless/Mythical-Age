from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

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
) -> RuntimePromptWiringPlan:
    registry = PromptLibraryRegistry(base_dir)
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
                source_prompt_sets=_dedupe(
                    (*tuple(existing.source_prompt_sets if existing else ()), prompt_set.prompt_set_id)
                ),
                metadata={
                    **dict(existing.metadata if existing else {}),
                    **dict(slot.metadata or {}),
                },
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
            "rejected_prompt_sets": rejected_sets,
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


def _digest(payload: Any) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:20]
