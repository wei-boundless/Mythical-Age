from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import PromptCompositionSlot, RuntimePromptSlot, RuntimePromptSlotPlan
from .slot_policy import (
    prompt_slot_policy_metadata,
    resolve_prompt_slot_policy,
    stability_for_prefix,
)


def build_runtime_prompt_slot_plan(
    *,
    invocation_kind: str,
    packet_id: str,
    message_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> RuntimePromptSlotPlan:
    slots: list[RuntimePromptSlot] = []
    for index, raw_spec in enumerate(list(message_specs or []), start=1):
        if not isinstance(raw_spec, dict):
            continue
        spec = _normalized_spec(raw_spec)
        kind = str(spec.get("kind") or "unknown_unplanned").strip() or "unknown_unplanned"
        slot_policy = resolve_prompt_slot_policy(spec)
        metadata = dict(spec.get("metadata") or {})
        prompt_source_manifest_id = str(metadata.get("runtime_prompt_source_manifest_id") or "")
        prompt_source_id = str(metadata.get("runtime_prompt_source_id") or "")
        content_hash = _stable_text_hash(str(spec.get("content") or ""))
        slot_id = _slot_id(
            invocation_kind=invocation_kind,
            packet_id=packet_id,
            order=index,
            kind=kind,
            source_ref=str(spec.get("source_ref") or ""),
            content_hash=content_hash,
        )
        slots.append(
            RuntimePromptSlot(
                slot_id=slot_id,
                invocation_kind=str(invocation_kind or ""),
                packet_id=str(packet_id or ""),
                order=index,
                layer=slot_policy.layer,
                slot_kind=kind,
                target_role=str(spec.get("role") or "user"),
                source_kind=slot_policy.source_kind,
                source_ref=str(spec.get("source_ref") or ""),
                cache_scope=slot_policy.cache_scope,
                cache_role=slot_policy.cache_role,
                prefix_tier=slot_policy.prefix_tier,
                dynamic_tier=slot_policy.dynamic_tier,
                load_phase=slot_policy.load_phase,
                phase_order=slot_policy.phase_order,
                compression_role=slot_policy.compression_role,
                authority_class=slot_policy.authority_class,
                render_contract=_render_contract(spec, source_kind=slot_policy.source_kind),
                message_spec=spec,
                content_hash=content_hash,
                metadata={
                    "source_metadata": metadata,
                    "prompt_source_manifest_id": prompt_source_manifest_id,
                    "prompt_source_id": prompt_source_id,
                    "slot_source": "runtime_prompt_source_manifest",
                    **prompt_slot_policy_metadata(slot_policy),
                },
            )
        )
    seed = {
        "invocation_kind": str(invocation_kind or ""),
        "packet_id": str(packet_id or ""),
        "slots": [
            {
                "slot_id": slot.slot_id,
                "order": slot.order,
                "kind": slot.slot_kind,
                "layer": slot.layer,
                "source_kind": slot.source_kind,
                "prefix_tier": slot.prefix_tier,
                "dynamic_tier": slot.dynamic_tier,
                "load_phase": slot.load_phase,
                "source_ref": slot.source_ref,
                "content_hash": slot.content_hash,
            }
            for slot in slots
        ],
    }
    return RuntimePromptSlotPlan(
        plan_id="rtpromptslots:" + _stable_hash(seed)[:16],
        invocation_kind=str(invocation_kind or ""),
        packet_id=str(packet_id or ""),
        slots=tuple(slots),
        diagnostics={
            "slot_count": len(slots),
            "layer_counts": _count_by(slots, "layer"),
            "prefix_tier_counts": _count_by(slots, "prefix_tier"),
            "dynamic_tier_counts": _count_by(slots, "dynamic_tier"),
            "load_phase_counts": _count_by(slots, "load_phase"),
            "source_kind_counts": _count_by(slots, "source_kind"),
            "authority": "prompt_composition.runtime_slot_plan.builder",
        },
    )


def composition_slots_from_runtime_slot_plan(slot_plan: RuntimePromptSlotPlan) -> tuple[PromptCompositionSlot, ...]:
    slots: list[PromptCompositionSlot] = []
    for slot in tuple(slot_plan.slots or ()):
        slots.append(
            PromptCompositionSlot(
                slot_id=slot.slot_id,
                invocation_kind=slot.invocation_kind,
                layer=slot.layer,
                slot_kind=slot.slot_kind,
                target_role=slot.target_role,
                stability=stability_for_prefix(cache_role=slot.cache_role, prefix_tier=slot.prefix_tier),
                cache_scope=slot.cache_scope,
                cache_role=slot.cache_role,
                prefix_tier=slot.prefix_tier,
                source_kind=slot.source_kind,
                source_ref=slot.source_ref,
                content_hash=slot.content_hash,
                order=slot.order,
                required=True,
                message_kinds=(slot.slot_kind,),
                metadata={
                    "runtime_prompt_slot_plan_id": slot_plan.plan_id,
                    "authority_class": slot.authority_class,
                    "dynamic_tier": slot.dynamic_tier,
                    "load_phase": slot.load_phase,
                    "phase_order": slot.phase_order,
                    "render_contract": dict(slot.render_contract),
                },
            )
        )
    return tuple(slots)


def _normalized_spec(spec: dict[str, Any]) -> dict[str, Any]:
    payload = dict(spec or {})
    payload["role"] = str(payload.get("role") or "user")
    payload["content"] = str(payload.get("content") or "")
    payload["kind"] = str(payload.get("kind") or "unknown_unplanned")
    payload["metadata"] = dict(payload.get("metadata") or {})
    return payload


def _render_contract(spec: dict[str, Any], *, source_kind: str) -> dict[str, Any]:
    metadata = dict(spec.get("metadata") or {})
    return _drop_empty(
        {
            "render_kind": "model_message_spec",
            "message_role": str(spec.get("role") or "user"),
            "message_kind": str(spec.get("kind") or ""),
            "content_source": str(metadata.get("content_source") or ""),
            "runtime_fragment_title": str(metadata.get("runtime_fragment_title") or ""),
            "runtime_fragment_payload_keys": list(metadata.get("runtime_fragment_payload_keys") or []),
            "source_kind": source_kind,
        }
    )


def _count_by(slots: list[RuntimePromptSlot], field_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for slot in slots:
        key = str(getattr(slot, field_name, "") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _slot_id(
    *,
    invocation_kind: str,
    packet_id: str,
    order: int,
    kind: str,
    source_ref: str,
    content_hash: str,
) -> str:
    digest = _stable_hash(
        {
            "invocation_kind": invocation_kind,
            "packet_id": packet_id,
            "order": order,
            "kind": kind,
            "source_ref": source_ref,
            "content_hash": content_hash,
        }
    )[:12]
    return f"rtpromptslot:{invocation_kind}:{order}:{kind}:{digest}"


def _stable_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _stable_text_hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(str(value or "").encode("utf-8", errors="ignore")).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
