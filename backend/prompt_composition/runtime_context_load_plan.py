from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import RuntimeContextLoadEntry, RuntimeContextLoadPlan, RuntimePromptSlotPlan


_LOAD_PHASE_ORDER = {
    "stable_prefix": 100,
    "active_skills": 200,
    "history_replay": 300,
    "append_only_task_evidence": 400,
    "current_runtime_cursor": 500,
    "file_evidence_cursor": 600,
    "user_editor_volatile": 700,
    "assistant_completion_prefix": 900,
    "unknown_dynamic": 990,
}


def build_runtime_context_load_plan(slot_plan: RuntimePromptSlotPlan) -> RuntimeContextLoadPlan:
    raw_entries: list[tuple[int, int, RuntimeContextLoadEntry]] = []
    plan_seed = {
        "slot_plan_id": str(slot_plan.plan_id or ""),
        "invocation_kind": str(slot_plan.invocation_kind or ""),
        "packet_id": str(slot_plan.packet_id or ""),
        "slots": [
            {
                "slot_id": slot.slot_id,
                "order": slot.order,
                "dynamic_tier": slot.dynamic_tier,
                "slot_kind": slot.slot_kind,
                "source_kind": slot.source_kind,
            }
            for slot in tuple(slot_plan.slots or ())
        ],
    }
    plan_id = "rtctxload:" + _stable_hash(plan_seed)[:16]
    for slot in tuple(slot_plan.slots or ()):
        phase = _load_phase(slot_kind=slot.slot_kind, dynamic_tier=slot.dynamic_tier)
        phase_order = _LOAD_PHASE_ORDER.get(phase, _LOAD_PHASE_ORDER["unknown_dynamic"])
        raw_entries.append(
            (
                phase_order,
                int(slot.order or 0),
                RuntimeContextLoadEntry(
                    load_entry_id=_entry_id(
                        plan_id=plan_id,
                        slot_id=slot.slot_id,
                        phase=phase,
                        slot_order=slot.order,
                    ),
                    load_plan_id=plan_id,
                    invocation_kind=slot.invocation_kind,
                    packet_id=slot.packet_id,
                    load_phase=phase,
                    phase_order=phase_order,
                    load_order=0,
                    slot_id=slot.slot_id,
                    slot_layer=slot.layer,
                    slot_kind=slot.slot_kind,
                    target_role=slot.target_role,
                    source_kind=slot.source_kind,
                    source_ref=slot.source_ref,
                    cache_tier=slot.cache_tier,
                    dynamic_tier=slot.dynamic_tier,
                    authority_class=slot.authority_class,
                    render_contract=dict(slot.render_contract),
                    message_spec=dict(slot.message_spec),
                    metadata={
                        "prompt_slot_plan_id": str(slot_plan.plan_id or ""),
                        "prompt_slot_id": str(slot.slot_id or ""),
                        "original_slot_order": int(slot.order or 0),
                    },
                ),
            )
        )
    ordered: list[RuntimeContextLoadEntry] = []
    for load_order, (_, _, entry) in enumerate(sorted(raw_entries, key=lambda item: (item[0], item[1])), start=1):
        ordered.append(
            RuntimeContextLoadEntry(
                load_entry_id=entry.load_entry_id,
                load_plan_id=entry.load_plan_id,
                invocation_kind=entry.invocation_kind,
                packet_id=entry.packet_id,
                load_phase=entry.load_phase,
                phase_order=entry.phase_order,
                load_order=load_order,
                slot_id=entry.slot_id,
                slot_layer=entry.slot_layer,
                slot_kind=entry.slot_kind,
                target_role=entry.target_role,
                source_kind=entry.source_kind,
                source_ref=entry.source_ref,
                cache_tier=entry.cache_tier,
                dynamic_tier=entry.dynamic_tier,
                authority_class=entry.authority_class,
                render_contract=dict(entry.render_contract),
                message_spec=dict(entry.message_spec),
                metadata=dict(entry.metadata),
            )
        )
    return RuntimeContextLoadPlan(
        plan_id=plan_id,
        invocation_kind=str(slot_plan.invocation_kind or ""),
        packet_id=str(slot_plan.packet_id or ""),
        entries=tuple(ordered),
        diagnostics={
            "prompt_slot_plan_ref": str(slot_plan.plan_id or ""),
            "entry_count": len(ordered),
            "load_phase_counts": _count_by(ordered, "load_phase"),
            "load_phase_sequence": [entry.load_phase for entry in ordered],
            "cache_tier_sequence": [entry.cache_tier for entry in ordered],
            "dynamic_tier_sequence": [entry.dynamic_tier for entry in ordered],
            "reordered_slot_count": _reordered_slot_count(ordered),
            "authority": "prompt_composition.runtime_context_load_plan.builder",
        },
    )


def materialize_runtime_context_load_plan(load_plan: RuntimeContextLoadPlan) -> tuple[dict[str, Any], ...]:
    specs: list[dict[str, Any]] = []
    for entry in tuple(load_plan.entries or ()):
        spec = dict(entry.message_spec or {})
        metadata = dict(spec.get("metadata") or {})
        metadata.update(
            {
                "prompt_slot_plan_id": dict(entry.metadata).get("prompt_slot_plan_id") or "",
                "prompt_slot_id": entry.slot_id,
                "slot_layer": entry.slot_layer,
                "slot_source_kind": entry.source_kind,
                "slot_cache_tier": entry.cache_tier,
                "slot_dynamic_tier": entry.dynamic_tier,
                "slot_authority_class": entry.authority_class,
                "slot_render_contract": dict(entry.render_contract),
                "runtime_context_load_plan_id": load_plan.plan_id,
                "runtime_context_load_entry_id": entry.load_entry_id,
                "runtime_context_load_phase": entry.load_phase,
                "runtime_context_load_order": entry.load_order,
                "runtime_context_phase_order": entry.phase_order,
                "runtime_context_materialized_by": "prompt_composition.runtime_context_load_plan.materializer",
            }
        )
        spec["metadata"] = metadata
        specs.append(spec)
    return tuple(specs)


def _load_phase(*, slot_kind: str, dynamic_tier: str) -> str:
    kind = str(slot_kind or "").strip()
    tier = str(dynamic_tier or "").strip()
    if kind == "graph_node_completion_prefix":
        return "assistant_completion_prefix"
    if tier in _LOAD_PHASE_ORDER:
        return tier
    return "stable_prefix" if tier == "stable_prefix" else "unknown_dynamic"


def _entry_id(*, plan_id: str, slot_id: str, phase: str, slot_order: int) -> str:
    digest = _stable_hash(
        {
            "plan_id": plan_id,
            "slot_id": slot_id,
            "phase": phase,
            "slot_order": slot_order,
        }
    )[:12]
    return f"rtctxloadentry:{phase}:{slot_order}:{digest}"


def _reordered_slot_count(entries: list[RuntimeContextLoadEntry]) -> int:
    return sum(
        1
        for entry in entries
        if int(dict(entry.metadata).get("original_slot_order") or 0) != int(entry.load_order or 0)
    )


def _count_by(entries: list[RuntimeContextLoadEntry], field_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        key = str(getattr(entry, field_name, "") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _stable_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
