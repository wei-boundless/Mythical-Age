from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import PromptCompositionLayerInput, PromptCompositionPlan, PromptCompositionSlot


def build_prompt_composition_plan(
    *,
    invocation_kind: str,
    packet_id: str,
    layers: tuple[PromptCompositionLayerInput, ...],
    dynamic_fragment_refs: tuple[str, ...] = (),
    volatile_state_refs: tuple[str, ...] = (),
    diagnostics: dict[str, Any] | None = None,
) -> PromptCompositionPlan:
    slots: list[PromptCompositionSlot] = []
    rejected_refs: list[dict[str, Any]] = []
    order = 1
    for layer in layers:
        assembly = layer.assembly
        sections = tuple(getattr(assembly, "sections", ()) or ())
        rejected_refs.extend(dict(item) for item in tuple(getattr(assembly, "rejected_refs", ()) or ()))
        prompt_pack_refs = tuple(str(item).strip() for item in tuple(getattr(assembly, "prompt_pack_refs", ()) or ()) if str(item).strip())
        for section in sections:
            prompt_ref = str(getattr(section, "prompt_ref", "") or "").strip()
            source_ref = str(getattr(section, "source_ref", "") or "").strip()
            cache_scope = str(getattr(section, "cache_scope", "") or "static").strip()
            content = str(getattr(section, "content", "") or "")
            slot = PromptCompositionSlot(
                slot_id=_slot_id(
                    invocation_kind=invocation_kind,
                    layer=layer.slot_layer,
                    order=order,
                    source_ref=prompt_ref or source_ref or str(getattr(section, "section_id", "") or ""),
                ),
                invocation_kind=str(invocation_kind or ""),
                layer=layer.slot_layer,
                slot_kind=_slot_kind_from_section(section),
                target_role=layer.target_role,
                lifecycle=layer.lifecycle or _lifecycle_from_cache_scope(cache_scope, layer.slot_layer),
                cache_scope=cache_scope,
                cache_role=_cache_role_from_cache_scope(cache_scope),
                prefix_tier=_prefix_tier_from_cache_scope(cache_scope, layer.slot_layer),
                source_kind=layer.source_kind,
                source_ref=source_ref,
                prompt_ref=prompt_ref,
                prompt_pack_refs=prompt_pack_refs,
                section_id=str(getattr(section, "section_id", "") or ""),
                title=str(getattr(section, "title", "") or ""),
                content_hash=_stable_text_hash(content),
                order=order,
                required=layer.required,
                message_kinds=layer.message_kinds,
                metadata={
                    **dict(getattr(section, "metadata", {}) or {}),
                    **dict(layer.metadata or {}),
                    "assembly_id": str(getattr(assembly, "assembly_id", "") or ""),
                    "source_layer_id": layer.layer_id,
                },
            )
            slots.append(slot)
            order += 1
    seed = {
        "invocation_kind": invocation_kind,
        "packet_id": packet_id,
        "slots": [
            {
                "slot_id": slot.slot_id,
                "prompt_ref": slot.prompt_ref,
                "source_ref": slot.source_ref,
                "layer": slot.layer,
                "content_hash": slot.content_hash,
            }
            for slot in slots
        ],
        "dynamic_fragment_refs": list(dynamic_fragment_refs),
        "volatile_state_refs": list(volatile_state_refs),
    }
    digest = _stable_hash(seed)[:16]
    return PromptCompositionPlan(
        plan_id=f"pcplan:{digest}",
        invocation_kind=str(invocation_kind or ""),
        packet_id=str(packet_id or ""),
        slots=tuple(slots),
        rejected_refs=tuple(rejected_refs),
        dynamic_fragment_refs=tuple(str(item).strip() for item in tuple(dynamic_fragment_refs or ()) if str(item).strip()),
        volatile_state_refs=tuple(str(item).strip() for item in tuple(volatile_state_refs or ()) if str(item).strip()),
        diagnostics={
            **dict(diagnostics or {}),
            "layer_count": len(layers),
            "registered_slot_count": len(slots),
            "authority": "prompt_composition.planner",
        },
    )


def _slot_kind_from_section(section: Any) -> str:
    category = str(getattr(section, "category", "") or "").strip()
    subtype = str(getattr(section, "subtype", "") or "").strip()
    resource_type = str(dict(getattr(section, "metadata", {}) or {}).get("resource_type") or "").strip()
    return resource_type or ".".join(part for part in (category, subtype) if part) or "prompt_section"


def _lifecycle_from_cache_scope(cache_scope: str, layer: str) -> str:
    scope = str(cache_scope or "").strip()
    normalized_layer = str(layer or "").strip()
    if scope in {"static", "global"}:
        return "global_static" if normalized_layer == "global_static" else f"{normalized_layer}_stable"
    if scope in {"static_environment"}:
        return "environment_stable"
    if scope in {"session", "session_stable"}:
        return "session_stable"
    if scope in {"task", "task_stable"}:
        return "task_stable"
    if scope in {"none", "volatile"}:
        return "runtime_dynamic"
    return normalized_layer or "unknown"


def _cache_role_from_cache_scope(cache_scope: str) -> str:
    scope = str(cache_scope or "").strip()
    if scope in {"static", "global", "static_environment"}:
        return "cacheable_prefix"
    if scope in {"session", "session_stable", "task", "task_stable"}:
        return "session_stable"
    return "volatile"


def _prefix_tier_from_cache_scope(cache_scope: str, layer: str) -> str:
    scope = str(cache_scope or "").strip()
    normalized_layer = str(layer or "").strip()
    if scope in {"static", "global"} and normalized_layer == "global_static":
        return "provider_global"
    if scope in {"static", "static_environment", "session", "session_stable"}:
        return "session"
    if scope in {"task", "task_stable"}:
        return "task"
    return "volatile"


def _slot_id(*, invocation_kind: str, layer: str, order: int, source_ref: str) -> str:
    digest = _stable_hash({"invocation_kind": invocation_kind, "layer": layer, "order": order, "source_ref": source_ref})[:12]
    return f"pcslot:{invocation_kind}:{layer}:{order}:{digest}"


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
