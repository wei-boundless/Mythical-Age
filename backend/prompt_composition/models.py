from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PromptCompositionLayerInput:
    layer_id: str
    slot_layer: str
    assembly: Any | None = None
    message_kinds: tuple[str, ...] = ()
    target_role: str = "system"
    lifecycle: str = ""
    required: bool = True
    source_kind: str = "registered_prompt"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "layer_id", str(self.layer_id or "").strip())
        object.__setattr__(self, "slot_layer", str(self.slot_layer or self.layer_id or "unknown").strip())
        object.__setattr__(
            self,
            "message_kinds",
            tuple(str(item).strip() for item in tuple(self.message_kinds or ()) if str(item).strip()),
        )


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
class PromptCompositionManifest:
    manifest_id: str
    invocation_kind: str
    packet_id: str
    shadow_mode: bool
    plan: PromptCompositionPlan
    graph: PromptCompositionGraph
    segment_bindings: tuple[PromptCompositionSegmentBinding, ...] = ()
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
            "coverage": dict(self.coverage),
            "diagnostics": dict(self.diagnostics),
            "authority": self.authority,
        }
