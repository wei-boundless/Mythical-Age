from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any

from .graph import build_prompt_composition_graph
from .models import (
    PromptCompositionLayerInput,
    PromptCompositionManifest,
    PromptCompositionMessageProjection,
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
    message_projection = _message_projection(segments=segments, bindings=bindings)
    coverage = _coverage(plan=plan, bindings=bindings)
    cache_boundary = _cache_boundary_diagnostics(plan=plan, segments=segments)
    seed = {
        "invocation_kind": invocation_kind,
        "packet_id": packet_id,
        "plan_id": plan.plan_id,
        "graph_id": graph.graph_id,
        "binding_statuses": [item.binding_status for item in bindings],
        "message_projection": [
            {
                "segment_id": item.segment_id,
                "kind": item.kind,
                "model_message_index": item.model_message_index,
                "model_message_hash": item.model_message_hash,
                "binding_status": item.binding_status,
            }
            for item in message_projection
        ],
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
        message_projection=message_projection,
        coverage=coverage,
        diagnostics={
            **dict(diagnostics or {}),
            "segment_plan_ref": str(segment_plan.get("segment_plan_id") or ""),
            "cache_boundary": cache_boundary,
            "provider_request_content_changed": False,
            "authority": "prompt_composition.shadow_manifest_builder",
        },
    )


def _message_projection(
    *,
    segments: tuple[dict[str, Any], ...],
    bindings: tuple[Any, ...],
) -> tuple[PromptCompositionMessageProjection, ...]:
    binding_by_segment_id = {str(binding.segment_id or ""): binding for binding in bindings}
    projection: list[PromptCompositionMessageProjection] = []
    for segment in sorted(segments, key=lambda item: int(item.get("ordinal") or 0)):
        segment_id = str(segment.get("segment_id") or "")
        binding = binding_by_segment_id.get(segment_id)
        projection.append(
            PromptCompositionMessageProjection(
                segment_id=segment_id,
                kind=str(segment.get("kind") or ""),
                source_ref=str(segment.get("source_ref") or ""),
                ordinal=int(segment.get("ordinal") or 0),
                model_message_index=int(segment.get("model_message_index") or 0),
                model_message_role=str(segment.get("model_message_role") or ""),
                cache_role=str(segment.get("cache_role") or "volatile"),
                prefix_tier=str(segment.get("prefix_tier") or "volatile"),
                content_hash=str(segment.get("content_hash") or ""),
                model_message_hash=str(segment.get("model_message_hash") or ""),
                binding_status=str(getattr(binding, "binding_status", "") or "unmapped"),
                bound_slot_ids=tuple(str(item) for item in tuple(getattr(binding, "bound_slot_ids", ()) or ())),
            )
        )
    return tuple(projection)


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
    runtime_slot_source_counts: dict[str, int] = {}
    for slot in runtime_slots:
        source_kind = str(slot.source_kind or "unknown")
        runtime_slot_source_counts[source_kind] = runtime_slot_source_counts.get(source_kind, 0) + 1
    stable_unregistered_bindings = [
        binding
        for binding in bindings
        if str(binding.binding_status or "") != "registered_prompt_bound"
        and str(binding.cache_role or "") in {"cacheable_prefix", "session_stable"}
        and str(binding.prefix_tier or "") not in {"volatile", "none"}
    ]
    legacy_runtime_bindings = [
        binding
        for binding in stable_unregistered_bindings
        if str(binding.binding_status or "") == "legacy_runtime_text"
    ]
    return {
        "slot_count": len(plan.slots),
        "registered_prompt_slot_count": len(registered_slots),
        "runtime_shadow_slot_count": len(runtime_slots),
        "runtime_shadow_slot_source_kind_counts": runtime_slot_source_counts,
        "segment_count": len(bindings),
        "segment_binding_status_counts": status_counts,
        "all_segments_explained": len(bindings) == sum(status_counts.values()),
        "stable_unregistered_segment_count": len(stable_unregistered_bindings),
        "stable_unregistered_segment_samples": _binding_samples(stable_unregistered_bindings),
        "legacy_runtime_text_count": status_counts.get("legacy_runtime_text", 0),
        "legacy_runtime_text_samples": _binding_samples(legacy_runtime_bindings),
        "dynamic_context_fragment_count": status_counts.get("dynamic_context_fragment", 0),
        "runtime_action_schema_count": status_counts.get("runtime_action_schema", 0),
        "runtime_artifact_scope_count": status_counts.get("runtime_artifact_scope", 0),
        "runtime_environment_boundary_count": status_counts.get("runtime_environment_boundary", 0),
        "runtime_contract_count": status_counts.get("runtime_contract", 0),
        "runtime_protocol_count": status_counts.get("runtime_protocol", 0),
        "semantic_compaction_boundary_count": status_counts.get("semantic_compaction_boundary", 0),
        "tool_catalog_count": status_counts.get("tool_catalog", 0),
        "registered_prompt_bound_count": status_counts.get("registered_prompt_bound", 0),
        "authority": "prompt_composition.coverage",
    }


def _binding_samples(bindings: list[Any], *, limit: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "segment_id": str(binding.segment_id or ""),
            "kind": str(binding.kind or ""),
            "source_ref": str(binding.source_ref or ""),
            "cache_role": str(binding.cache_role or ""),
            "prefix_tier": str(binding.prefix_tier or ""),
            "binding_status": str(binding.binding_status or ""),
            "binding_reason": str(binding.binding_reason or ""),
        }
        for binding in bindings[:limit]
    ]


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
    if source_kind == "semantic_compaction_boundary":
        return "lifecycle_stable"
    if source_kind == "runtime_artifact_scope":
        return "artifact_scope_stable"
    if source_kind == "runtime_contract":
        return "task_contract_stable"
    if source_kind == "runtime_task_boundary":
        return "task_runtime_boundary_stable"
    if source_kind == "runtime_task_state_replay":
        return "task_state_replay_stable"
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


_PREFIX_TIER_ORDER = {
    "provider_global": 1,
    "session": 2,
    "task": 3,
    "volatile": 4,
    "none": 5,
}

_LAYER_CACHE_POLICY = {
    "global_static": {
        "allowed_prefix_tiers": {"provider_global"},
        "allowed_cache_roles": {"cacheable_prefix"},
    },
    "environment_stable": {
        "allowed_prefix_tiers": {"session"},
        "allowed_cache_roles": {"cacheable_prefix", "session_stable"},
    },
    "lifecycle_stable": {
        "allowed_prefix_tiers": {"session"},
        "allowed_cache_roles": {"cacheable_prefix", "session_stable"},
    },
    "personality_stable": {
        "allowed_prefix_tiers": {"session"},
        "allowed_cache_roles": {"session_stable"},
    },
    "agent_stable": {
        "allowed_prefix_tiers": {"session"},
        "allowed_cache_roles": {"session_stable"},
    },
    "capability_stable": {
        "allowed_prefix_tiers": {"session", "task"},
        "allowed_cache_roles": {"session_stable"},
    },
    "artifact_scope_stable": {
        "allowed_prefix_tiers": {"task"},
        "allowed_cache_roles": {"session_stable"},
    },
    "task_contract_stable": {
        "allowed_prefix_tiers": {"task"},
        "allowed_cache_roles": {"session_stable"},
    },
    "task_state_replay_stable": {
        "allowed_prefix_tiers": {"task"},
        "allowed_cache_roles": {"session_stable"},
    },
    "task_runtime_boundary_stable": {
        "allowed_prefix_tiers": {"task"},
        "allowed_cache_roles": {"session_stable"},
    },
    "runtime_protocol_stable": {
        "allowed_prefix_tiers": {"session"},
        "allowed_cache_roles": {"session_stable"},
    },
    "runtime_dynamic": {
        "allowed_prefix_tiers": {"volatile", "none"},
        "allowed_cache_roles": {"volatile", "never_cache"},
    },
}


def _cache_boundary_diagnostics(
    *,
    plan: PromptCompositionPlan,
    segments: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    layer_violations = _layer_cache_policy_violations(plan.slots)
    segment_violations = _segment_prefix_violations(segments)
    prefix_counts: dict[str, int] = {}
    cache_role_counts: dict[str, int] = {}
    for segment in segments:
        prefix_tier = str(segment.get("prefix_tier") or "volatile").strip() or "volatile"
        cache_role = str(segment.get("cache_role") or "volatile").strip() or "volatile"
        prefix_counts[prefix_tier] = prefix_counts.get(prefix_tier, 0) + 1
        cache_role_counts[cache_role] = cache_role_counts.get(cache_role, 0) + 1
    return {
        "status": "warning" if layer_violations or segment_violations else "ok",
        "prefix_tier_counts": prefix_counts,
        "cache_role_counts": cache_role_counts,
        "prefix_tier_sequence": [
            str(segment.get("prefix_tier") or "volatile").strip() or "volatile"
            for segment in segments
        ],
        "layer_cache_policy_violations": layer_violations,
        "segment_prefix_violations": segment_violations,
        "deepseek_prefix_principle": (
            "provider payload cache is prefix based; stable provider_global/session/task "
            "segments must remain contiguous and byte stable before volatile content"
        ),
        "authority": "prompt_composition.cache_boundary_diagnostics",
    }


def _layer_cache_policy_violations(slots: tuple[PromptCompositionSlot, ...]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for slot in slots:
        policy = _LAYER_CACHE_POLICY.get(str(slot.layer or ""))
        if not policy:
            continue
        allowed_tiers = set(policy["allowed_prefix_tiers"])
        allowed_roles = set(policy["allowed_cache_roles"])
        if slot.prefix_tier not in allowed_tiers:
            violations.append(
                {
                    "code": "slot_prefix_tier_outside_layer_policy",
                    "slot_id": slot.slot_id,
                    "layer": slot.layer,
                    "source_ref": slot.source_ref or slot.prompt_ref,
                    "prefix_tier": slot.prefix_tier,
                    "allowed_prefix_tiers": sorted(allowed_tiers),
                }
            )
        if slot.cache_role not in allowed_roles:
            violations.append(
                {
                    "code": "slot_cache_role_outside_layer_policy",
                    "slot_id": slot.slot_id,
                    "layer": slot.layer,
                    "source_ref": slot.source_ref or slot.prompt_ref,
                    "cache_role": slot.cache_role,
                    "allowed_cache_roles": sorted(allowed_roles),
                }
            )
    return violations


def _segment_prefix_violations(segments: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    previous_rank = 0
    previous_tier = ""
    volatile_seen = False
    for segment in sorted(segments, key=lambda item: int(item.get("ordinal") or 0)):
        prefix_tier = str(segment.get("prefix_tier") or "volatile").strip() or "volatile"
        cache_role = str(segment.get("cache_role") or "volatile").strip() or "volatile"
        rank = _PREFIX_TIER_ORDER.get(prefix_tier, 99)
        stable = cache_role in {"cacheable_prefix", "session_stable"} and prefix_tier not in {"volatile", "none"}
        if volatile_seen and stable:
            violations.append(
                {
                    "code": "stable_segment_after_volatile_boundary",
                    "segment_id": str(segment.get("segment_id") or ""),
                    "kind": str(segment.get("kind") or ""),
                    "prefix_tier": prefix_tier,
                    "cache_role": cache_role,
                }
            )
        if stable and previous_rank and rank < previous_rank:
            violations.append(
                {
                    "code": "prefix_tier_order_regression",
                    "segment_id": str(segment.get("segment_id") or ""),
                    "kind": str(segment.get("kind") or ""),
                    "previous_prefix_tier": previous_tier,
                    "prefix_tier": prefix_tier,
                }
            )
        if prefix_tier in {"volatile", "none"} or cache_role in {"volatile", "never_cache"}:
            volatile_seen = True
        if stable:
            previous_rank = rank
            previous_tier = prefix_tier
    return violations
