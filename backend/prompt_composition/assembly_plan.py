from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .source_bundle import PromptSource, PromptSourceBundle
from runtime.context_management.context_assembly import (
    CONTEXT_APPEND,
    CONTEXT_MEMORY_PREFIX,
    DYNAMIC_TAIL,
    STATIC_PREFIX,
    classify_context_spec,
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
    "task": 300,
    "volatile": 900,
    "none": 990,
}

@dataclass(frozen=True, slots=True)
class PromptAssemblySlot:
    slot_id: str
    source_id: str
    invocation_kind: str
    packet_id: str
    source_order: int
    assembly_order: int
    layer: str
    slot_kind: str
    target_role: str
    source_kind: str
    source_ref: str = ""
    cache_scope: str = "none"
    cache_role: str = "volatile"
    prefix_tier: str = "volatile"
    dynamic_tier: str = "volatile"
    compression_role: str = "summarize"
    content_hash: str = ""
    model_message_hash: str = ""
    message_spec: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_composition.assembly_plan.slot"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["message_spec"] = dict(self.message_spec)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class PromptAssemblyPlan:
    plan_id: str
    invocation_kind: str
    packet_id: str
    source_bundle_id: str
    slots: tuple[PromptAssemblySlot, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_composition.assembly_plan"

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "invocation_kind": self.invocation_kind,
            "packet_id": self.packet_id,
            "source_bundle_id": self.source_bundle_id,
            "slots": [slot.to_dict() for slot in self.slots],
            "diagnostics": dict(self.diagnostics),
            "authority": self.authority,
        }


def build_prompt_assembly_plan(
    *,
    source_bundle: PromptSourceBundle,
    provider_profile: dict[str, Any] | None = None,
) -> PromptAssemblyPlan:
    provider_profile_payload = dict(provider_profile or {})
    planned: list[PromptAssemblySlot] = []
    for source in tuple(source_bundle.sources or ()):
        slot = _slot_from_source(source, provider_profile=provider_profile_payload)
        planned.append(slot)

    ordered_sources = sorted(planned, key=_assembly_order_key)
    slots: list[PromptAssemblySlot] = []
    for order, slot in enumerate(ordered_sources, start=1):
        metadata = {
            **dict(slot.metadata or {}),
            "prompt_assembly_source_bundle_id": source_bundle.bundle_id,
            "prompt_assembly_source_id": slot.source_id,
            "prompt_assembly_original_order": int(slot.source_order or 0),
            "prompt_assembly_order": order,
            "prompt_assembly_layer": slot.layer,
            "prompt_assembly_prefix_tier": slot.prefix_tier,
            "prompt_assembly_dynamic_tier": slot.dynamic_tier,
        }
        spec = dict(slot.message_spec or {})
        spec["cache_scope"] = slot.cache_scope
        spec["cache_role"] = slot.cache_role
        spec["prefix_tier"] = slot.prefix_tier
        spec["compression_role"] = slot.compression_role
        spec["metadata"] = {**dict(spec.get("metadata") or {}), **metadata}
        slots.append(
            PromptAssemblySlot(
                slot_id=slot.slot_id,
                source_id=slot.source_id,
                invocation_kind=slot.invocation_kind,
                packet_id=slot.packet_id,
                source_order=slot.source_order,
                assembly_order=order,
                layer=slot.layer,
                slot_kind=slot.slot_kind,
                target_role=slot.target_role,
                source_kind=slot.source_kind,
                source_ref=slot.source_ref,
                cache_scope=slot.cache_scope,
                cache_role=slot.cache_role,
                prefix_tier=slot.prefix_tier,
                dynamic_tier=slot.dynamic_tier,
                compression_role=slot.compression_role,
                content_hash=slot.content_hash,
                model_message_hash=slot.model_message_hash,
                message_spec=spec,
                metadata=metadata,
            )
        )

    diagnostics = _diagnostics(slots)
    seed = {
        "source_bundle_id": source_bundle.bundle_id,
        "slots": [
            {
                "source_id": slot.source_id,
                "assembly_order": slot.assembly_order,
                "kind": slot.slot_kind,
                "layer": slot.layer,
                "cache_role": slot.cache_role,
                "prefix_tier": slot.prefix_tier,
                "content_hash": slot.content_hash,
                "model_message_hash": slot.model_message_hash,
            }
            for slot in slots
        ],
    }
    return PromptAssemblyPlan(
        plan_id="passembly:" + _stable_hash(seed)[:16],
        invocation_kind=source_bundle.invocation_kind,
        packet_id=source_bundle.packet_id,
        source_bundle_id=source_bundle.bundle_id,
        slots=tuple(slots),
        diagnostics={
            **diagnostics,
            "source_bundle_ref": source_bundle.bundle_id,
            "provider_profile": provider_profile_payload,
            "assembly_order_policy": "source_lineage_order_pre_physical_assembly",
            "authority": "prompt_composition.assembly_plan.builder",
        },
    )


def _assembly_order_key(slot: PromptAssemblySlot) -> tuple[int]:
    return (int(slot.source_order or 0),)


def _slot_from_source(source: PromptSource, *, provider_profile: dict[str, Any]) -> PromptAssemblySlot:
    source_spec = {
        **dict(source.message_spec or {}),
        "kind": source.kind,
        "cache_scope": source.cache_scope,
        "cache_role": source.cache_role,
        "prefix_tier": source.prefix_tier,
        "metadata": dict(source.metadata or {}),
    }
    classification = classify_context_spec(source_spec)
    cache_role = classification.cache_role
    prefix_tier = classification.prefix_tier
    source_cache_scope = classification.cache_scope
    layer = _layer_for_source(source, cache_role=cache_role, prefix_tier=prefix_tier)
    if classification.context_cache_section in {CONTEXT_MEMORY_PREFIX, CONTEXT_APPEND}:
        layer = _context_append_layer(layer)
    elif classification.context_cache_section == DYNAMIC_TAIL:
        layer = "dynamic_context_tail"
    elif classification.context_cache_section == STATIC_PREFIX and layer == "volatile":
        layer = "task_stable_scope"
    dynamic_tier = _dynamic_tier_for_source(source, cache_role=cache_role, prefix_tier=prefix_tier, layer=layer)
    cache_scope = _cache_scope_for_tier(
        source_cache_scope,
        cache_role=cache_role,
        prefix_tier=prefix_tier,
        layer=layer,
    )
    slot_id = _slot_id(
        packet_id=source.packet_id,
        invocation_kind=source.invocation_kind,
        source_id=source.source_id,
        kind=source.kind,
        layer=layer,
        prefix_tier=prefix_tier,
    )
    metadata = {
        **dict(source.metadata or {}),
        "prompt_source_kind": source.source_kind,
        "prompt_source_order": int(source.source_order or 0),
        "assembly_decided_by": "prompt_composition.assembly_plan",
        **classification.to_dict(),
    }
    if source.kind == "tool_schema_catalog":
        metadata.setdefault("provider_tool_schema_cache_profile", dict(provider_profile or {}))
    return PromptAssemblySlot(
        slot_id=slot_id,
        source_id=source.source_id,
        invocation_kind=source.invocation_kind,
        packet_id=source.packet_id,
        source_order=source.source_order,
        assembly_order=0,
        layer=layer,
        slot_kind=source.kind,
        target_role=source.role,
        source_kind=source.source_kind,
        source_ref=source.source_ref,
        cache_scope=cache_scope,
        cache_role=cache_role,
        prefix_tier=prefix_tier,
        dynamic_tier=dynamic_tier,
        compression_role=_compression_role(source.compression_role),
        content_hash=source.content_hash,
        model_message_hash=source.model_message_hash,
        message_spec=dict(source.message_spec or {}),
        metadata=metadata,
    )


def _context_append_layer(layer: str) -> str:
    normalized = str(layer or "").strip()
    if normalized in CONTEXT_APPEND_LAYER_NAMES:
        return normalized
    return "context_memory_append"


def _layer_for_source(source: PromptSource, *, cache_role: str, prefix_tier: str) -> str:
    kind = str(source.kind or "")
    source_kind = str(source.source_kind or "")
    if prefix_tier == "provider_global" or cache_role == "cacheable_prefix":
        return "provider_global_stable"
    if kind in {"action_schema_static", "tool_schema_catalog", "tool_index_stable"} or source_kind in {
        "runtime_action_schema",
        "tool_catalog",
    }:
        return "session_stable_capability" if prefix_tier == "session" else "task_stable_capability"
    if kind == "file_evidence_policy_stable" or source_kind == "runtime_file_evidence_policy":
        return "session_stable_file_evidence"
    if kind in {"environment_stable"} or source_kind == "runtime_environment_boundary":
        return "session_stable_environment"
    if kind == "lifecycle_stable" or (source_kind == "runtime_lifecycle" and prefix_tier == "session"):
        return "session_stable_lifecycle"
    if kind == "lifecycle_runtime_guidance" or source_kind == "runtime_lifecycle":
        return "dynamic_context_tail"
    if kind == "personality_stable":
        return "session_stable_personality"
    if kind == "agent_stable":
        return "session_stable_agent"
    if kind == "project_instructions_stable" or source_kind == "runtime_project_instructions":
        return "session_stable_project"
    if kind in {"task_contract_stable", "task_prompt_contract", "graph_task_shared_stable"} or source_kind == "runtime_contract":
        return "task_stable_contract"
    if kind in {
        "bound_task_context_stable",
        "artifact_scope_stable",
        "agent_function_shared_stable",
        "task_runtime_boundary_stable",
    } or source_kind in {"runtime_artifact_scope", "runtime_task_boundary"}:
        return "task_stable_scope"
    if kind in {"task_runtime_boundary_dynamic", "task_start_inherited_context"} or source_kind == "runtime_dynamic_boundary":
        return "runtime_cursor_prefix"
    if kind == "runtime_baseline_refs" or source_kind == "runtime_baseline_refs":
        return "session_stable_protocol" if prefix_tier == "session" else "task_stable_scope"
    if kind == "dynamic_projection":
        return "runtime_delta_tail" if prefix_tier in {"volatile", "none"} else "task_stable_scope"
    if kind in {
        "read_evidence_context",
        "task_state_replay_entry",
        "single_agent_turn_tool_call",
        "single_agent_turn_tool_observation",
        "tool_observations",
    } or source_kind in {"runtime_task_state_replay", "runtime_read_evidence_context"}:
        return "append_only_runtime_evidence"
    if kind in {"task_goal_context", "task_plan_context", "task_todo_context"} or source_kind in {
        "runtime_task_goal_context",
        "runtime_task_plan_context",
        "runtime_task_todo_context",
    }:
        return "dynamic_context_tail"
    if kind == "evidence_index_cursor" or source_kind == "runtime_evidence_index_cursor":
        return "evidence_index_cursor"
    if kind == "attachment_context_index" or source_kind == "runtime_attachment_context_index":
        return "attachment_context_index"
    if kind == "editor_context_index" or source_kind == "runtime_editor_context_index":
        return "editor_context_index"
    if kind in {"read_evidence_injection"}:
        return "current_exact_evidence"
    if kind == "current_editor_evidence_delta" or source_kind == "runtime_editor_evidence_delta":
        return "current_exact_evidence"
    if kind in {"bound_task_runtime_context", "graph_node_runtime_context"} or source_kind == "runtime_bound_task_context":
        return "file_evidence_cursor"
    if kind == "runtime_memory_context" or source_kind == "runtime_memory_context":
        return "runtime_memory_context"
    if kind in {"incremental_context_frame", "incremental_context_cursor"} or source_kind in {
        "runtime_incremental_context_frame",
        "runtime_incremental_context_cursor",
    }:
        return "dynamic_context_tail"
    if kind == "current_turn_user_context":
        return "current_turn_user_context"
    if kind == "graph_node_completion_prefix":
        return "assistant_completion_prefix"
    if cache_role in VOLATILE_CACHE_ROLES or prefix_tier in {"volatile", "none"}:
        return "volatile"
    return "session_stable_protocol" if prefix_tier == "session" else "task_stable_scope"


def _dynamic_tier_for_source(source: PromptSource, *, cache_role: str, prefix_tier: str, layer: str) -> str:
    kind = str(source.kind or "")
    source_kind = str(source.source_kind or "")
    if layer == "context_memory_append":
        if kind in {"provider_protocol_history", "single_agent_turn_tool_call", "single_agent_turn_tool_observation", "tool_observations"}:
            return "append_only_runtime_evidence"
        if kind == "runtime_memory_context":
            return "runtime_memory_context"
        if kind in {"current_turn_user_context", "single_agent_turn_user_steer_context", "user_steering_context_append"}:
            return "user_context_append"
        return "context_memory_append"
    if layer == "dynamic_context_tail":
        if kind == "read_evidence_injection":
            return "current_exact_evidence"
        if kind in {"active_skills", "skill_candidates"}:
            return "active_skills"
        if kind == "graph_node_completion_prefix":
            return "assistant_completion_prefix"
        return "dynamic_context_tail"
    if cache_role in STABLE_CACHE_ROLES and prefix_tier not in {"volatile", "none"}:
        return "stable_prefix"
    if layer == "append_only_runtime_evidence" or source_kind in {
        "runtime_task_state_replay",
        "runtime_read_evidence_context",
    }:
        return "append_only_runtime_evidence"
    if layer == "runtime_cursor_prefix" or kind in {"task_runtime_boundary_dynamic", "task_start_inherited_context"}:
        return "runtime_cursor_prefix"
    if layer == "dynamic_context_tail" or kind == "lifecycle_runtime_guidance":
        return "dynamic_context_tail"
    if kind == "runtime_baseline_refs" or source_kind == "runtime_baseline_refs":
        return "stable_prefix" if cache_role in STABLE_CACHE_ROLES and prefix_tier not in {"volatile", "none"} else "runtime_baseline_refs"
    if kind == "dynamic_projection":
        return "runtime_delta_tail"
    if kind in {"task_goal_context", "task_plan_context", "task_todo_context"} or source_kind in {
        "runtime_task_goal_context",
        "runtime_task_plan_context",
        "runtime_task_todo_context",
    }:
        return "dynamic_context_tail"
    if kind == "evidence_index_cursor" or source_kind == "runtime_evidence_index_cursor":
        return "evidence_index_cursor"
    if kind == "attachment_context_index" or source_kind == "runtime_attachment_context_index":
        return "attachment_context_index"
    if kind == "editor_context_index" or source_kind == "runtime_editor_context_index":
        return "editor_context_index"
    if kind == "read_evidence_injection":
        return "current_exact_evidence"
    if kind == "current_editor_evidence_delta" or source_kind == "runtime_editor_evidence_delta":
        return "current_exact_evidence"
    if kind in {"bound_task_runtime_context", "graph_node_runtime_context"}:
        return "file_evidence_cursor"
    if kind in {
        "read_evidence_context",
        "single_agent_turn_tool_call",
        "single_agent_turn_tool_observation",
        "tool_observations",
    }:
        return "append_only_runtime_evidence"
    if kind in {"session_history", "session_history_context", "session_history_entry", "provider_protocol_history"}:
        return "history_replay"
    if kind == "session_history_tail_context":
        return "dynamic_context_tail"
    if kind == "current_turn_user_context":
        return "user_context_append"
    if kind == "semantic_compaction_request":
        return "user_editor_volatile"
    if kind == "runtime_memory_context" or source_kind == "runtime_memory_context":
        return "runtime_memory_context"
    if kind in {"incremental_context_frame", "incremental_context_cursor"} or source_kind in {
        "runtime_incremental_context_frame",
        "runtime_incremental_context_cursor",
    }:
        return "dynamic_context_tail"
    if kind in {"active_skills", "skill_candidates"}:
        return "active_skills"
    if kind == "graph_node_completion_prefix":
        return "assistant_completion_prefix"
    return "runtime_cursor"


def _diagnostics(slots: list[PromptAssemblySlot]) -> dict[str, Any]:
    prefix_sequence = [slot.prefix_tier for slot in slots]
    cache_role_sequence = [slot.cache_role for slot in slots]
    layer_sequence = [slot.layer for slot in slots]
    cache_order_warnings: list[dict[str, Any]] = []
    previous_rank = 0
    previous_tier = ""
    volatile_seen = False
    for slot in slots:
        rank = PREFIX_TIER_ORDER.get(slot.prefix_tier, 999)
        stable = slot.cache_role in STABLE_CACHE_ROLES and slot.prefix_tier not in {"volatile", "none"}
        if volatile_seen and stable:
            cache_order_warnings.append(
                {
                    "code": "stable_slot_after_volatile_cache_boundary",
                    "slot_id": slot.slot_id,
                    "kind": slot.slot_kind,
                    "prefix_tier": slot.prefix_tier,
                    "cache_role": slot.cache_role,
                    "severity": "diagnostic_only",
                }
            )
        if stable and previous_rank and rank < previous_rank:
            cache_order_warnings.append(
                {
                    "code": "prefix_tier_cache_order_regression",
                    "slot_id": slot.slot_id,
                    "kind": slot.slot_kind,
                    "previous_prefix_tier": previous_tier,
                    "prefix_tier": slot.prefix_tier,
                    "severity": "diagnostic_only",
                }
            )
        if slot.prefix_tier in {"volatile", "none"} or slot.cache_role in VOLATILE_CACHE_ROLES:
            volatile_seen = True
        if stable:
            previous_rank = rank
            previous_tier = slot.prefix_tier
    return {
        "status": "ok" if not cache_order_warnings else "warning",
        "slot_count": len(slots),
        "prefix_tier_sequence": prefix_sequence,
        "cache_role_sequence": cache_role_sequence,
        "layer_sequence": layer_sequence,
        "prefix_tier_counts": _count_by(slots, "prefix_tier"),
        "cache_role_counts": _count_by(slots, "cache_role"),
        "layer_counts": _count_by(slots, "layer"),
        "dynamic_tier_counts": _count_by(slots, "dynamic_tier"),
        "cache_order_warnings": cache_order_warnings,
        "segment_prefix_violations": cache_order_warnings,
        "physical_model_contract": (
            "assembly order is fixed by source_order; cache_role, prefix_tier, provider policy, and "
            "context_cache_section are diagnostics only and must not reorder provider-visible messages"
        ),
        "assembly_reordered_slot_count": sum(1 for slot in slots if slot.assembly_order != slot.source_order),
    }


def _cache_role(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized in {"cacheable_prefix", "session_stable", "volatile", "never_cache"}:
        return normalized
    return "volatile"


def _prefix_tier(value: Any, *, cache_scope: str, cache_role: str) -> str:
    explicit = str(value or "").strip()
    if explicit in {"provider_global", "session", "task", "volatile", "none"}:
        return explicit
    if cache_role == "cacheable_prefix":
        return "provider_global"
    if cache_role == "session_stable":
        scope = str(cache_scope or "").strip()
        if scope == "task":
            return "task"
        if scope == "global":
            return "provider_global"
        return "session"
    if cache_role == "never_cache":
        return "none"
    return "volatile"


def _cache_scope_for_tier(value: Any, *, cache_role: str, prefix_tier: str, layer: str) -> str:
    if cache_role == "cacheable_prefix" or prefix_tier == "provider_global":
        return "global"
    if cache_role == "session_stable":
        if prefix_tier == "task":
            return "task"
        return "session"
    if prefix_tier in {"volatile", "none"}:
        return "none"
    return str(value or "none")


def _compression_role(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized in {"preserve", "summarize", "drop_if_cold", "ref_only"}:
        return normalized
    return "summarize"


def _count_by(slots: list[PromptAssemblySlot], field_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for slot in slots:
        key = str(getattr(slot, field_name, "") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _slot_id(
    *,
    packet_id: str,
    invocation_kind: str,
    source_id: str,
    kind: str,
    layer: str,
    prefix_tier: str,
) -> str:
    digest = _stable_hash(
        {
            "packet_id": packet_id,
            "invocation_kind": invocation_kind,
            "source_id": source_id,
            "kind": kind,
            "layer": layer,
            "prefix_tier": prefix_tier,
        }
    )[:12]
    return f"paslot:{invocation_kind}:{kind}:{digest}"


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8", errors="ignore")).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
