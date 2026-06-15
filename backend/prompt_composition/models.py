from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PromptCompositionSlot:
    slot_id: str
    invocation_kind: str
    layer: str
    slot_kind: str
    target_role: str
    lifecycle: str
    cache_scope: str
    cache_role: str
    prefix_tier: str
    source_kind: str
    source_ref: str = ""
    prompt_ref: str = ""
    prompt_pack_refs: tuple[str, ...] = ()
    section_id: str = ""
    title: str = ""
    content_hash: str = ""
    order: int = 100
    required: bool = True
    model_visible: bool = True
    message_kinds: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_composition.slot"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["prompt_pack_refs"] = list(self.prompt_pack_refs)
        payload["message_kinds"] = list(self.message_kinds)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class PromptCompositionPlan:
    plan_id: str
    invocation_kind: str
    packet_id: str
    slots: tuple[PromptCompositionSlot, ...] = ()
    rejected_refs: tuple[dict[str, Any], ...] = ()
    dynamic_fragment_refs: tuple[str, ...] = ()
    volatile_state_refs: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_composition.plan"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["slots"] = [slot.to_dict() for slot in self.slots]
        payload["rejected_refs"] = [dict(item) for item in self.rejected_refs]
        payload["dynamic_fragment_refs"] = list(self.dynamic_fragment_refs)
        payload["volatile_state_refs"] = list(self.volatile_state_refs)
        payload["diagnostics"] = dict(self.diagnostics)
        return payload


@dataclass(frozen=True, slots=True)
class RuntimePromptSlot:
    slot_id: str
    invocation_kind: str
    packet_id: str
    order: int
    layer: str
    slot_kind: str
    target_role: str
    source_kind: str
    source_ref: str
    cache_scope: str
    cache_role: str
    cache_tier: str
    dynamic_tier: str
    compression_role: str
    authority_class: str
    render_contract: dict[str, Any] = field(default_factory=dict)
    message_spec: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    model_visible: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_composition.runtime_prompt_slot"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["render_contract"] = dict(self.render_contract)
        payload["message_spec"] = dict(self.message_spec)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class RuntimePromptSlotPlan:
    plan_id: str
    invocation_kind: str
    packet_id: str
    slots: tuple[RuntimePromptSlot, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_composition.runtime_prompt_slot_plan"

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "invocation_kind": self.invocation_kind,
            "packet_id": self.packet_id,
            "slots": [slot.to_dict() for slot in self.slots],
            "diagnostics": dict(self.diagnostics),
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class RuntimeContextLoadEntry:
    load_entry_id: str
    load_plan_id: str
    invocation_kind: str
    packet_id: str
    load_phase: str
    phase_order: int
    load_order: int
    slot_id: str
    slot_layer: str
    slot_kind: str
    target_role: str
    source_kind: str
    source_ref: str
    cache_tier: str
    dynamic_tier: str
    authority_class: str
    render_contract: dict[str, Any] = field(default_factory=dict)
    message_spec: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_composition.runtime_context_load_entry"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["render_contract"] = dict(self.render_contract)
        payload["message_spec"] = dict(self.message_spec)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class RuntimeContextLoadPlan:
    plan_id: str
    invocation_kind: str
    packet_id: str
    entries: tuple[RuntimeContextLoadEntry, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_composition.runtime_context_load_plan"

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "invocation_kind": self.invocation_kind,
            "packet_id": self.packet_id,
            "entries": [entry.to_dict() for entry in self.entries],
            "diagnostics": dict(self.diagnostics),
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class PromptCompositionGraph:
    graph_id: str
    plan_id: str
    nodes: tuple[dict[str, Any], ...] = ()
    edges: tuple[dict[str, Any], ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_composition.graph"

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "plan_id": self.plan_id,
            "nodes": [dict(item) for item in self.nodes],
            "edges": [dict(item) for item in self.edges],
            "diagnostics": dict(self.diagnostics),
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class PromptCompositionSegmentBinding:
    segment_id: str
    kind: str
    source_ref: str
    model_message_index: int
    transport_location: str = "messages"
    cache_role: str = "volatile"
    prefix_tier: str = "volatile"
    bound_slot_ids: tuple[str, ...] = ()
    binding_status: str = "unmapped"
    binding_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_composition.segment_binding"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["bound_slot_ids"] = list(self.bound_slot_ids)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class PromptCompositionMessageProjection:
    segment_id: str
    kind: str
    source_ref: str
    ordinal: int
    model_message_index: int
    model_message_role: str
    cache_role: str = "volatile"
    prefix_tier: str = "volatile"
    content_hash: str = ""
    model_message_hash: str = ""
    binding_status: str = "unmapped"
    bound_slot_ids: tuple[str, ...] = ()
    authority: str = "prompt_composition.message_projection"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["bound_slot_ids"] = list(self.bound_slot_ids)
        return payload


@dataclass(frozen=True, slots=True)
class PromptCompositionContentFragment:
    segment_id: str
    kind: str
    source_ref: str
    ordinal: int
    model_message_index: int
    model_message_role: str
    content_hash: str = ""
    model_message_hash: str = ""
    model_message: dict[str, Any] = field(default_factory=dict)
    content_source: str = "runtime_sanitized_model_message"
    materialized_from: str = "sanitized_model_message"
    authority: str = "prompt_composition.content_fragment"

    def to_model_message(self) -> dict[str, Any]:
        return dict(self.model_message)

    def to_diagnostic_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "kind": self.kind,
            "source_ref": self.source_ref,
            "ordinal": self.ordinal,
            "model_message_index": self.model_message_index,
            "model_message_role": self.model_message_role,
            "content_hash": self.content_hash,
            "model_message_hash": self.model_message_hash,
            "content_source": self.content_source,
            "materialized_from": self.materialized_from,
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class PromptCompositionManifest:
    manifest_id: str
    invocation_kind: str
    packet_id: str
    shadow_mode: bool
    plan: PromptCompositionPlan
    graph: PromptCompositionGraph
    segment_bindings: tuple[PromptCompositionSegmentBinding, ...] = ()
    message_projection: tuple[PromptCompositionMessageProjection, ...] = ()
    coverage: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_composition.manifest"

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "invocation_kind": self.invocation_kind,
            "packet_id": self.packet_id,
            "shadow_mode": self.shadow_mode,
            "plan": self.plan.to_dict(),
            "graph": self.graph.to_dict(),
            "segment_bindings": [item.to_dict() for item in self.segment_bindings],
            "message_projection": [item.to_dict() for item in self.message_projection],
            "coverage": dict(self.coverage),
            "diagnostics": dict(self.diagnostics),
            "authority": self.authority,
        }
