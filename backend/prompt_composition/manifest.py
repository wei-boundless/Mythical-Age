from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any

from .graph import build_prompt_composition_graph
from .models import (
    PromptCompositionLayerInput,
    PromptCompositionManifest,
    PromptCompositionPlan,
    PromptCompositionSlot,
)
from .planner import build_prompt_composition_plan
from .tracing import bind_segments_to_slots, runtime_source_kind_for_segment


def build_shadow_prompt_composition_manifest(
    *,
    invocation_kind: str,
    packet_id: str,
    layers: tuple[PromptCompositionLayerInput, ...],
    segment_plan: dict[str, Any],
    dynamic_fragment_refs: tuple[str, ...] = (),
    volatile_state_refs: tuple[str, ...] = (),
    diagnostics: dict[str, Any] | None = None,
) -> PromptCompositionManifest:
    plan = build_prompt_composition_plan(
        invocation_kind=invocation_kind,
        packet_id=packet_id,
        layers=layers,
        dynamic_fragment_refs=dynamic_fragment_refs,
        volatile_state_refs=volatile_state_refs,
        diagnostics=diagnostics,
    )
    segments = tuple(dict(item) for item in list(segment_plan.get("segments") or []) if isinstance(item, dict))
    initial_bindings = bind_segments_to_slots(segments=segments, slots=plan.slots)
    runtime_slots = _runtime_slots_for_unbound_segments(
        invocation_kind=invocation_kind,
        packet_id=packet_id,
        base_order=len(plan.slots) + 1,
        segments=segments,
        bindings=initial_bindings,
    )
    if runtime_slots:
        plan = replace(
            plan,
            plan_id=_plan_id(invocation_kind=invocation_kind, packet_id=packet_id, slots=tuple((*plan.slots, *runtime_slots))),
            slots=tuple((*plan.slots, *runtime_slots)),
            diagnostics={
                **dict(plan.diagnostics),
                "registered_slot_count": len(plan.slots),
                "runtime_shadow_slot_count": len(runtime_slots),
            },
        )
    bindings = bind_segments_to_slots(segments=segments, slots=plan.slots)
    graph = build_prompt_composition_graph(plan)
    coverage = _coverage(plan=plan, bindings=bindings)
    seed = {
        "invocation_kind": invocation_kind,
        "packet_id": packet_id,
        "plan_id": plan.plan_id,
        "graph_id": graph.graph_id,
        "binding_statuses": [item.binding_status for item in bindings],
    }
    digest = hashlib.sha256(json.dumps(seed, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return PromptCompositionManifest(
        manifest_id=f"pcmanifest:{digest}",
        invocation_kind=str(invocation_kind or ""),
        packet_id=str(packet_id or ""),
        shadow_mode=True,
        plan=plan,
        graph=graph,
        segment_bindings=bindings,
        coverage=coverage,
        diagnostics={
            **dict(diagnostics or {}),
            "segment_plan_ref": str(segment_plan.get("segment_plan_id") or ""),
            "provider_request_content_changed": False,
            "authority": "prompt_composition.shadow_manifest_builder",
        },
    )


def _runtime_slots_for_unbound_segments(
    *,
    invocation_kind: str,
    packet_id: str,
    base_order: int,
    segments: tuple[dict[str, Any], ...],
    bindings: tuple[Any, ...],
) -> tuple[PromptCompositionSlot, ...]:
    slots: list[PromptCompositionSlot] = []
    bound_by_segment_id = {
        str(binding.segment_id or ""): tuple(binding.bound_slot_ids or ())
        for binding in bindings
    }
    for offset, segment in enumerate(segments, start=0):
        segment_id = str(segment.get("segment_id") or "")
        if bound_by_segment_id.get(segment_id):
            continue
        kind = str(segment.get("kind") or "unknown_unplanned").strip() or "unknown_unplanned"
        order = base_order + offset
        source_kind = runtime_source_kind_for_segment(segment)
        slot_id = _runtime_slot_id(
            invocation_kind=invocation_kind,
            packet_id=packet_id,
            order=order,
            kind=kind,
            source_ref=str(segment.get("source_ref") or ""),
        )
        slots.append(
            PromptCompositionSlot(
                slot_id=slot_id,
                invocation_kind=str(invocation_kind or ""),
                layer=_runtime_layer(kind=kind, source_kind=source_kind),
                slot_kind=kind,
                target_role=str(segment.get("model_message_role") or "system"),
                lifecycle=_runtime_lifecycle(segment),
                cache_scope=str(segment.get("cache_scope") or "none"),
                cache_role=str(segment.get("cache_role") or "volatile"),
                prefix_tier=str(segment.get("prefix_tier") or "volatile"),
                source_kind=source_kind,
                source_ref=str(segment.get("source_ref") or ""),
                content_hash=str(segment.get("content_hash") or ""),
                order=order,
                required=False,
                message_kinds=(kind,),
                metadata={
                    "segment_id": segment_id,
                    "model_message_index": int(segment.get("model_message_index") or 0),
                    "byte_length": int(segment.get("byte_length") or 0),
                    "shadow_mode": True,
                },
            )
        )
    return tuple(slots)


def _coverage(*, plan: PromptCompositionPlan, bindings: tuple[Any, ...]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for binding in bindings:
        status = str(binding.binding_status or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    registered_slots = [slot for slot in plan.slots if slot.source_kind == "registered_prompt"]
    runtime_slots = [slot for slot in plan.slots if slot.source_kind != "registered_prompt"]
    return {
        "slot_count": len(plan.slots),
        "registered_prompt_slot_count": len(registered_slots),
        "runtime_shadow_slot_count": len(runtime_slots),
        "segment_count": len(bindings),
        "segment_binding_status_counts": status_counts,
        "all_segments_explained": len(bindings) == sum(status_counts.values()),
        "legacy_runtime_text_count": status_counts.get("legacy_runtime_text", 0),
        "dynamic_context_fragment_count": status_counts.get("dynamic_context_fragment", 0),
        "runtime_action_schema_count": status_counts.get("runtime_action_schema", 0),
        "runtime_artifact_scope_count": status_counts.get("runtime_artifact_scope", 0),
        "runtime_contract_count": status_counts.get("runtime_contract", 0),
        "runtime_protocol_count": status_counts.get("runtime_protocol", 0),
        "tool_catalog_count": status_counts.get("tool_catalog", 0),
        "registered_prompt_bound_count": status_counts.get("registered_prompt_bound", 0),
        "authority": "prompt_composition.coverage",
    }


def _runtime_slot_id(*, invocation_kind: str, packet_id: str, order: int, kind: str, source_ref: str) -> str:
    seed = {
        "invocation_kind": invocation_kind,
        "packet_id": packet_id,
        "order": order,
        "kind": kind,
        "source_ref": source_ref,
    }
    digest = hashlib.sha256(json.dumps(seed, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return f"pcslot:{invocation_kind}:runtime:{order}:{digest}"


def _plan_id(*, invocation_kind: str, packet_id: str, slots: tuple[PromptCompositionSlot, ...]) -> str:
    seed = {
        "invocation_kind": invocation_kind,
        "packet_id": packet_id,
        "slots": [
            {
                "slot_id": slot.slot_id,
                "layer": slot.layer,
                "source_kind": slot.source_kind,
                "source_ref": slot.source_ref,
                "prompt_ref": slot.prompt_ref,
                "content_hash": slot.content_hash,
            }
            for slot in slots
        ],
    }
    digest = hashlib.sha256(json.dumps(seed, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"pcplan:{digest}"


def _runtime_layer(*, kind: str, source_kind: str) -> str:
    if source_kind == "dynamic_context_fragment":
        return "runtime_dynamic"
    if source_kind in {"runtime_action_schema", "tool_catalog"}:
        return "capability_stable"
    if source_kind == "runtime_artifact_scope":
        return "artifact_scope_stable"
    if source_kind == "runtime_contract":
        return "task_contract_stable"
    if source_kind == "runtime_protocol":
        return "runtime_protocol_stable"
    return "legacy_runtime_stable"


def _runtime_lifecycle(segment: dict[str, Any]) -> str:
    cache_role = str(segment.get("cache_role") or "").strip()
    prefix_tier = str(segment.get("prefix_tier") or "").strip()
    if cache_role in {"volatile", "never_cache"} or prefix_tier in {"volatile", "none"}:
        return "runtime_dynamic"
    if prefix_tier == "provider_global":
        return "global_static"
    if prefix_tier == "task":
        return "task_stable"
    return "session_stable"
