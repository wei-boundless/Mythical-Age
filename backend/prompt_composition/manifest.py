from __future__ import annotations

import hashlib
import json
from typing import Any

from .graph import build_prompt_composition_graph
from .models import (
    PromptCompositionManifest,
    PromptCompositionMessageProjection,
    PromptCompositionPlan,
    PromptManifestBinding,
    RuntimeLoadSegmentPlan,
)
from .runtime_slot_plan import composition_slots_from_runtime_slot_plan
from .tracing import bind_segments_to_slots


def build_runtime_slot_prompt_composition_manifest(
    *,
    invocation_kind: str,
    packet_id: str,
    runtime_slot_plan: RuntimeLoadSegmentPlan,
    segment_plan: dict[str, Any],
    dynamic_fragment_refs: tuple[str, ...] = (),
    volatile_state_refs: tuple[str, ...] = (),
    diagnostics: dict[str, Any] | None = None,
) -> PromptCompositionManifest:
    runtime_slots = composition_slots_from_runtime_slot_plan(runtime_slot_plan)
    plan = PromptCompositionPlan(
        plan_id=str(runtime_slot_plan.plan_id or ""),
        invocation_kind=str(invocation_kind or ""),
        packet_id=str(packet_id or ""),
        slots=runtime_slots,
        dynamic_fragment_refs=tuple(str(item).strip() for item in tuple(dynamic_fragment_refs or ()) if str(item).strip()),
        volatile_state_refs=tuple(str(item).strip() for item in tuple(volatile_state_refs or ()) if str(item).strip()),
        diagnostics={
            **dict(runtime_slot_plan.diagnostics or {}),
            "runtime_slot_plan_ref": str(runtime_slot_plan.plan_id or ""),
            "slot_plan_authority": str(runtime_slot_plan.authority or ""),
            "authority": "prompt_composition.runtime_slot_manifest_builder",
        },
    )
    segments = tuple(dict(item) for item in list(segment_plan.get("segments") or []) if isinstance(item, dict))
    bindings = bind_segments_to_slots(segments=segments, slots=plan.slots)
    graph = build_prompt_composition_graph(plan)
    message_projection = _message_projection(segments=segments, bindings=bindings)
    coverage = _coverage(plan=plan, bindings=bindings)
    cache_boundary = _cache_boundary_diagnostics(plan=plan, segments=segments)
    prompt_source_audit = _prompt_source_audit(plan)
    seed = {
        "invocation_kind": invocation_kind,
        "packet_id": packet_id,
        "runtime_slot_plan_id": runtime_slot_plan.plan_id,
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
        shadow_mode=False,
        plan=plan,
        graph=graph,
        segment_bindings=bindings,
        message_projection=message_projection,
        coverage=coverage,
        diagnostics={
            **dict(diagnostics or {}),
            "segment_plan_ref": str(segment_plan.get("segment_plan_id") or ""),
            "runtime_slot_plan_ref": str(runtime_slot_plan.plan_id or ""),
            "cache_boundary": cache_boundary,
            "prompt_source_audit": prompt_source_audit,
            "provider_request_content_changed": False,
            "authority": "prompt_composition.runtime_slot_manifest_builder",
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
    unregistered_static_bindings = [
        binding
        for binding in stable_unregistered_bindings
        if str(binding.binding_status or "") == "runtime_unregistered_static_text"
    ]
    return {
        "slot_count": len(plan.slots),
        "registered_prompt_slot_count": len(registered_slots),
        "runtime_prompt_slot_count": len(runtime_slots),
        "runtime_prompt_slot_source_kind_counts": runtime_slot_source_counts,
        "segment_count": len(bindings),
        "segment_binding_status_counts": status_counts,
        "all_segments_explained": len(bindings) == sum(status_counts.values()),
        "stable_unregistered_segment_count": len(stable_unregistered_bindings),
        "stable_unregistered_segment_samples": _binding_samples(stable_unregistered_bindings),
        "runtime_unregistered_static_text_count": status_counts.get("runtime_unregistered_static_text", 0),
        "runtime_unregistered_static_text_samples": _binding_samples(unregistered_static_bindings),
        "dynamic_context_fragment_count": status_counts.get("dynamic_context_fragment", 0),
        "runtime_action_schema_count": status_counts.get("runtime_action_schema", 0),
        "runtime_artifact_scope_count": status_counts.get("runtime_artifact_scope", 0),
        "runtime_project_instructions_count": status_counts.get("runtime_project_instructions", 0),
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


def _prompt_source_audit(plan: PromptCompositionPlan) -> list[dict[str, Any]]:
    audit: list[dict[str, Any]] = []
    for slot in tuple(plan.slots or ()):
        metadata = dict(slot.metadata or {})
        prompt_audit = dict(metadata.get("prompt_source_audit") or {})
        if not prompt_audit:
            prompt_audit = {
                "prompt_ref": str(slot.prompt_ref or slot.source_ref or ""),
                "source_ref": str(slot.source_ref or ""),
                "content_hash": str(slot.content_hash or ""),
            }
        prompt_audit.update(
            {
                "manifest_binding_id": slot.slot_id,
                "slot_kind": slot.slot_kind,
                "layer": slot.layer,
                "cache_role": slot.cache_role,
                "prefix_tier": slot.prefix_tier,
                "order": int(slot.order or 0),
            }
        )
        audit.append(prompt_audit)
    return audit


_PREFIX_TIER_ORDER = {
    "provider_global": 1,
    "session": 2,
    "volatile": 4,
    "none": 5,
}

_LAYER_CACHE_POLICY = {
    "provider_global_stable": {
        "allowed_prefix_tiers": {"provider_global"},
        "allowed_cache_roles": {"cacheable_prefix"},
    },
    "session_stable_environment": {
        "allowed_prefix_tiers": {"session"},
        "allowed_cache_roles": {"cacheable_prefix", "session_stable"},
    },
    "session_stable_file_evidence": {
        "allowed_prefix_tiers": {"session"},
        "allowed_cache_roles": {"session_stable"},
    },
    "session_stable_turn_state": {
        "allowed_prefix_tiers": {"session"},
        "allowed_cache_roles": {"cacheable_prefix", "session_stable"},
    },
    "session_stable_project": {
        "allowed_prefix_tiers": {"session"},
        "allowed_cache_roles": {"session_stable"},
    },
    "session_stable_personality": {
        "allowed_prefix_tiers": {"session"},
        "allowed_cache_roles": {"session_stable"},
    },
    "session_stable_agent": {
        "allowed_prefix_tiers": {"session"},
        "allowed_cache_roles": {"session_stable"},
    },
    "session_stable_capability": {
        "allowed_prefix_tiers": {"session"},
        "allowed_cache_roles": {"session_stable"},
    },
    "task_capability_context": {
        "allowed_prefix_tiers": {"session"},
        "allowed_cache_roles": {"session_stable"},
    },
    "task_scope_context": {
        "allowed_prefix_tiers": {"session"},
        "allowed_cache_roles": {"session_stable"},
    },
    "task_run_contract_context": {
        "allowed_prefix_tiers": {"session"},
        "allowed_cache_roles": {"session_stable"},
    },
    "append_only_runtime_evidence": {
        "allowed_prefix_tiers": {"session", "volatile", "none"},
        "allowed_cache_roles": {"session_stable", "volatile", "never_cache"},
    },
    "context_memory_append": {
        "allowed_prefix_tiers": {"session", "volatile", "none"},
        "allowed_cache_roles": {"session_stable", "volatile", "never_cache"},
    },
    "session_stable_protocol": {
        "allowed_prefix_tiers": {"session"},
        "allowed_cache_roles": {"session_stable"},
    },
    "runtime_cursor_prefix": {
        "allowed_prefix_tiers": {"volatile", "none"},
        "allowed_cache_roles": {"volatile", "never_cache"},
    },
    "runtime_delta_tail": {
        "allowed_prefix_tiers": {"volatile", "none"},
        "allowed_cache_roles": {"volatile", "never_cache"},
    },
    "dynamic_context_tail": {
        "allowed_prefix_tiers": {"volatile", "none"},
        "allowed_cache_roles": {"volatile", "never_cache"},
    },
    "current_exact_evidence": {
        "allowed_prefix_tiers": {"volatile", "none"},
        "allowed_cache_roles": {"volatile", "never_cache"},
    },
    "current_turn_user_context": {
        "allowed_prefix_tiers": {"session", "volatile", "none"},
        "allowed_cache_roles": {"session_stable", "volatile", "never_cache"},
    },
    "evidence_index_cursor": {
        "allowed_prefix_tiers": {"session", "volatile", "none"},
        "allowed_cache_roles": {"session_stable", "volatile", "never_cache"},
    },
    "attachment_context_index": {
        "allowed_prefix_tiers": {"session", "volatile", "none"},
        "allowed_cache_roles": {"session_stable", "volatile", "never_cache"},
    },
    "editor_context_index": {
        "allowed_prefix_tiers": {"session", "volatile", "none"},
        "allowed_cache_roles": {"session_stable", "volatile", "never_cache"},
    },
    "file_evidence_cursor": {
        "allowed_prefix_tiers": {"session", "volatile", "none"},
        "allowed_cache_roles": {"session_stable", "volatile", "never_cache"},
    },
    "runtime_memory_context": {
        "allowed_prefix_tiers": {"session", "volatile", "none"},
        "allowed_cache_roles": {"session_stable", "volatile", "never_cache"},
    },
    "assistant_completion_prefix": {
        "allowed_prefix_tiers": {"volatile", "none"},
        "allowed_cache_roles": {"volatile", "never_cache"},
    },
    "volatile": {
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
    segment_warnings = _segment_cache_order_warnings(segments)
    prefix_counts: dict[str, int] = {}
    cache_role_counts: dict[str, int] = {}
    for segment in segments:
        prefix_tier = str(segment.get("prefix_tier") or "volatile").strip() or "volatile"
        cache_role = str(segment.get("cache_role") or "volatile").strip() or "volatile"
        prefix_counts[prefix_tier] = prefix_counts.get(prefix_tier, 0) + 1
        cache_role_counts[cache_role] = cache_role_counts.get(cache_role, 0) + 1
    return {
        "status": "warning" if layer_violations or segment_warnings else "ok",
        "prefix_tier_counts": prefix_counts,
        "cache_role_counts": cache_role_counts,
        "prefix_tier_sequence": [
            str(segment.get("prefix_tier") or "volatile").strip() or "volatile"
            for segment in segments
        ],
        "layer_cache_policy_violations": layer_violations,
        "segment_cache_order_warnings": segment_warnings,
        "segment_prefix_violations": segment_warnings,
        "deepseek_prefix_principle": (
            "provider payload cache is prefix based; physical order is fixed by the runtime packet, "
            "while cache_role and prefix_tier only diagnose whether that fixed order exposes a stable prefix"
        ),
        "prompt_lineage_contract": (
            "cache diagnostics must not reorder, promote, or reject provider-visible messages"
        ),
        "authority": "prompt_composition.cache_boundary_diagnostics",
    }


def _layer_cache_policy_violations(slots: tuple[PromptManifestBinding, ...]) -> list[dict[str, Any]]:
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


def _segment_cache_order_warnings(segments: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    previous_rank = 0
    previous_tier = ""
    volatile_seen = False
    for segment in sorted(segments, key=lambda item: int(item.get("ordinal") or 0)):
        prefix_tier = str(segment.get("prefix_tier") or "volatile").strip() or "volatile"
        cache_role = str(segment.get("cache_role") or "volatile").strip() or "volatile"
        rank = _PREFIX_TIER_ORDER.get(prefix_tier, 99)
        stable = cache_role in {"cacheable_prefix", "session_stable"} and prefix_tier not in {"volatile", "none"}
        if volatile_seen and stable:
            warnings.append(
                {
                    "code": "stable_segment_after_volatile_cache_boundary",
                    "segment_id": str(segment.get("segment_id") or ""),
                    "kind": str(segment.get("kind") or ""),
                    "prefix_tier": prefix_tier,
                    "cache_role": cache_role,
                    "severity": "diagnostic_only",
                }
            )
        if stable and previous_rank and rank < previous_rank:
            warnings.append(
                {
                    "code": "prefix_tier_cache_order_regression",
                    "segment_id": str(segment.get("segment_id") or ""),
                    "kind": str(segment.get("kind") or ""),
                    "previous_prefix_tier": previous_tier,
                    "prefix_tier": prefix_tier,
                    "severity": "diagnostic_only",
                }
            )
        if prefix_tier in {"volatile", "none"} or cache_role in {"volatile", "never_cache"}:
            volatile_seen = True
        if stable:
            previous_rank = rank
            previous_tier = prefix_tier
    return warnings
