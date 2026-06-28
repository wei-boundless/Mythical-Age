from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .source_bundle import PromptSource, PromptSourceBundle
from .slot_policy import (
    PREFIX_TIER_ORDER,
    STABLE_CACHE_ROLES,
    VOLATILE_CACHE_ROLES,
    prompt_slot_policy_metadata,
    resolve_prompt_slot_policy,
)

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
        "compression_role": source.compression_role,
        "metadata": dict(source.metadata or {}),
    }
    slot_policy = resolve_prompt_slot_policy(source_spec, source_kind=source.source_kind)
    slot_id = _slot_id(
        packet_id=source.packet_id,
        invocation_kind=source.invocation_kind,
        source_id=source.source_id,
        kind=source.kind,
        layer=slot_policy.layer,
        prefix_tier=slot_policy.prefix_tier,
    )
    metadata = {
        **dict(source.metadata or {}),
        "prompt_source_kind": slot_policy.source_kind,
        "prompt_source_order": int(source.source_order or 0),
        "assembly_decided_by": "prompt_composition.slot_policy",
        **prompt_slot_policy_metadata(slot_policy),
    }
    return PromptAssemblySlot(
        slot_id=slot_id,
        source_id=source.source_id,
        invocation_kind=source.invocation_kind,
        packet_id=source.packet_id,
        source_order=source.source_order,
        assembly_order=0,
        layer=slot_policy.layer,
        slot_kind=source.kind,
        target_role=source.role,
        source_kind=slot_policy.source_kind,
        source_ref=source.source_ref,
        cache_scope=slot_policy.cache_scope,
        cache_role=slot_policy.cache_role,
        prefix_tier=slot_policy.prefix_tier,
        dynamic_tier=slot_policy.dynamic_tier,
        compression_role=slot_policy.compression_role,
        content_hash=source.content_hash,
        model_message_hash=source.model_message_hash,
        message_spec=dict(source.message_spec or {}),
        metadata=metadata,
    )


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
        "prompt_lineage_contract": (
            "prompt composition preserves source lineage; physical provider-visible order is assigned later by "
            "PhysicalContextPlan, while cache_role, prefix_tier, provider policy, and context_cache_section remain diagnostics here"
        ),
        "assembly_reordered_slot_count": sum(1 for slot in slots if slot.assembly_order != slot.source_order),
    }


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
