from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from context_system.segments.policy import (
    CONTEXT_APPEND,
    CONTEXT_MEMORY_PREFIX,
    DYNAMIC_TAIL,
    STATIC_PREFIX,
    ContextSegmentPolicy,
    context_segment_policy_for_spec,
    context_segment_policy_metadata,
)
from context_system.segments.declarations import (
    context_segment_dynamic_tier_defaults,
    context_segment_kind_source_kind,
    context_segment_layer_defaults,
)


STABLE_CACHE_ROLES = {"cacheable_prefix", "session_stable"}
VOLATILE_CACHE_ROLES = {"volatile", "never_cache"}

CONTEXT_APPEND_LAYER_NAMES = {
    "append_only_runtime_evidence",
    "attachment_context_index",
    "current_turn_user_context",
    "editor_context_index",
    "evidence_index_cursor",
    "file_evidence_cursor",
    "runtime_memory_context",
}

PREFIX_TIER_ORDER = {
    "provider_global": 100,
    "session": 200,
    "volatile": 900,
    "none": 990,
}

LOAD_PHASE_ORDER = {
    "stable_prefix": 100,
    "active_skills": 200,
    "history_replay": 300,
    "runtime_cursor_prefix": 350,
    "append_only_runtime_evidence": 400,
    "context_memory_append": 410,
    "user_context_append": 420,
    "evidence_index_cursor": 435,
    "attachment_context_index": 440,
    "editor_context_index": 450,
    "current_runtime_cursor": 500,
    "file_evidence_cursor": 600,
    "current_exact_evidence": 620,
    "user_editor_volatile": 700,
    "runtime_baseline_refs": 760,
    "runtime_delta_tail": 820,
    "dynamic_context_tail": 870,
    "runtime_memory_context": 880,
    "assistant_completion_prefix": 900,
    "unknown_dynamic": 990,
}

_KIND_LAYER = context_segment_layer_defaults()

_KIND_TIER_LAYER = {
    "action_schema_static": {
        "session": "session_stable_capability",
        "default": "task_capability_context",
    },
    "dynamic_projection": {
        "volatile": "runtime_delta_tail",
        "none": "runtime_delta_tail",
        "default": "task_scope_context",
    },
    "graph_task_shared_stable": {"default": "task_run_contract_context"},
    "runtime_baseline_refs": {
        "session": "session_stable_protocol",
        "default": "task_scope_context",
    },
    "task_prompt_contract": {"default": "task_run_contract_context"},
    "tool_index_stable": {
        "session": "session_stable_capability",
        "default": "task_capability_context",
    },
}

_REGISTRY_DYNAMIC_TIER_BY_KIND = context_segment_dynamic_tier_defaults()

_DYNAMIC_TIER_BY_LAYER = {
    "append_only_runtime_evidence": "append_only_runtime_evidence",
    "assistant_completion_prefix": "assistant_completion_prefix",
    "attachment_context_index": "attachment_context_index",
    "current_exact_evidence": "current_exact_evidence",
    "current_turn_user_context": "user_context_append",
    "editor_context_index": "editor_context_index",
    "evidence_index_cursor": "evidence_index_cursor",
    "file_evidence_cursor": "file_evidence_cursor",
    "runtime_cursor_prefix": "runtime_cursor_prefix",
    "runtime_delta_tail": "runtime_delta_tail",
    "runtime_memory_context": "runtime_memory_context",
}

_DYNAMIC_TIER_BY_KIND = _REGISTRY_DYNAMIC_TIER_BY_KIND


@dataclass(frozen=True, slots=True)
class PromptSlotPolicy:
    source_kind: str
    layer: str
    cache_scope: str
    cache_role: str
    prefix_tier: str
    dynamic_tier: str
    load_phase: str
    phase_order: int
    compression_role: str
    context_policy: ContextSegmentPolicy
    authority: str = "prompt_composition.slot_policy"


def runtime_source_kind_for_segment(segment: dict[str, Any]) -> str:
    payload = dict(segment or {})
    kind = str(payload.get("kind") or "").strip()
    source_kind = context_segment_kind_source_kind(kind)
    if source_kind:
        return source_kind
    context_policy = context_segment_policy_for_spec(payload)
    if context_policy.section in {CONTEXT_MEMORY_PREFIX, CONTEXT_APPEND}:
        return "runtime_append_only_context"
    if context_policy.section == DYNAMIC_TAIL:
        return "dynamic_context_fragment"
    if context_policy.section == STATIC_PREFIX:
        return "runtime_unregistered_static_text"
    return "unclassified_runtime_prompt"


def resolve_prompt_slot_policy(
    spec: dict[str, Any],
    *,
    source_kind: str = "",
) -> PromptSlotPolicy:
    payload = dict(spec or {})
    metadata = dict(payload.get("metadata") or {})
    payload["metadata"] = metadata
    kind = str(payload.get("kind") or "unknown_unplanned").strip() or "unknown_unplanned"
    resolved_source_kind = str(source_kind or "").strip() or runtime_source_kind_for_segment(payload)
    context_policy = context_segment_policy_for_spec(payload)
    cache_role = context_policy.prefix_cache_role
    prefix_tier = context_policy.prefix_tier
    layer = _layer_for_context_section(
        _base_layer(
            kind=kind,
            cache_role=cache_role,
            prefix_tier=prefix_tier,
        ),
        section=context_policy.section,
    )
    dynamic_tier = _dynamic_tier(
        kind=kind,
        cache_role=cache_role,
        prefix_tier=prefix_tier,
        layer=layer,
    )
    load_phase = load_phase_for_slot(slot_kind=kind, dynamic_tier=dynamic_tier)
    return PromptSlotPolicy(
        source_kind=resolved_source_kind,
        layer=layer,
        cache_scope=_cache_scope_for_prefix(
            context_policy.prefix_cache_scope,
            cache_role=cache_role,
            prefix_tier=prefix_tier,
        ),
        cache_role=cache_role,
        prefix_tier=prefix_tier,
        dynamic_tier=dynamic_tier,
        load_phase=load_phase,
        phase_order=phase_order_for_load_phase(load_phase),
        compression_role=normalize_compression_role(payload.get("compression_role")),
        context_policy=context_policy,
    )


def prompt_slot_policy_metadata(policy: PromptSlotPolicy) -> dict[str, Any]:
    return {
        **context_segment_policy_metadata(policy.context_policy),
        "prompt_slot_policy_source_kind": policy.source_kind,
        "prompt_slot_policy_layer": policy.layer,
        "prompt_slot_policy_prefix_tier": policy.prefix_tier,
        "prompt_slot_policy_dynamic_tier": policy.dynamic_tier,
        "prompt_slot_policy_load_phase": policy.load_phase,
        "prompt_slot_policy_phase_order": policy.phase_order,
        "prompt_slot_policy_authority": policy.authority,
    }


def load_phase_for_slot(*, slot_kind: str, dynamic_tier: str) -> str:
    kind = str(slot_kind or "").strip()
    tier = str(dynamic_tier or "").strip()
    if kind == "graph_node_completion_prefix":
        return "assistant_completion_prefix"
    if tier in LOAD_PHASE_ORDER:
        return tier
    return "unknown_dynamic"


def phase_order_for_load_phase(load_phase: str) -> int:
    return LOAD_PHASE_ORDER.get(str(load_phase or "").strip(), LOAD_PHASE_ORDER["unknown_dynamic"])


def stability_for_prefix(*, cache_role: str, prefix_tier: str) -> str:
    if cache_role in VOLATILE_CACHE_ROLES or prefix_tier in {"volatile", "none"}:
        return "runtime_dynamic"
    if prefix_tier == "provider_global":
        return "global_static"
    return "session_stable"


def normalize_compression_role(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized in {"preserve", "summarize", "drop_if_cold", "ref_only"}:
        return normalized
    return "summarize"


def _base_layer(*, kind: str, cache_role: str, prefix_tier: str) -> str:
    if prefix_tier == "provider_global" or cache_role == "cacheable_prefix":
        return "provider_global_stable"
    layer = _tiered_lookup(_KIND_TIER_LAYER.get(kind), prefix_tier)
    if layer:
        return layer
    layer = _KIND_LAYER.get(kind)
    if layer:
        return layer
    if cache_role in VOLATILE_CACHE_ROLES or prefix_tier in {"volatile", "none"}:
        return "volatile"
    return "session_stable_protocol"


def _layer_for_context_section(layer: str, *, section: str) -> str:
    if section in {CONTEXT_MEMORY_PREFIX, CONTEXT_APPEND}:
        return _context_append_layer(layer)
    if section == DYNAMIC_TAIL:
        return "dynamic_context_tail"
    if section == STATIC_PREFIX and layer == "volatile":
        return "task_scope_context"
    return layer


def _context_append_layer(layer: str) -> str:
    normalized = str(layer or "").strip()
    if normalized in CONTEXT_APPEND_LAYER_NAMES:
        return normalized
    return "context_memory_append"


def _dynamic_tier(
    *,
    kind: str,
    cache_role: str,
    prefix_tier: str,
    layer: str,
) -> str:
    declared_dynamic_tier = _DYNAMIC_TIER_BY_KIND.get(kind)
    if declared_dynamic_tier:
        return declared_dynamic_tier
    if layer == "context_memory_append":
        return "context_memory_append"
    if layer == "dynamic_context_tail":
        return "dynamic_context_tail"
    if cache_role in STABLE_CACHE_ROLES and prefix_tier not in {"volatile", "none"}:
        return "stable_prefix"
    dynamic_tier = _DYNAMIC_TIER_BY_LAYER.get(layer)
    if dynamic_tier:
        return dynamic_tier
    return "current_runtime_cursor"


def _cache_scope_for_prefix(value: Any, *, cache_role: str, prefix_tier: str) -> str:
    if cache_role == "cacheable_prefix" or prefix_tier == "provider_global":
        return "global"
    if cache_role == "session_stable":
        return "session"
    if prefix_tier in {"volatile", "none"}:
        return "none"
    return str(value or "none")


def _tiered_lookup(mapping: dict[str, str] | None, prefix_tier: str) -> str:
    if not mapping:
        return ""
    return mapping.get(prefix_tier) or mapping.get("default") or ""
