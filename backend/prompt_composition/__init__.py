from __future__ import annotations

from .fragments import build_content_fragments_from_message_specs, build_content_fragments_from_model_messages
from .context_envelope import (
    CONTEXT_FRAGMENT_PROTOCOL,
    CONTEXT_FRAGMENT_TAG,
    is_context_fragment,
    parse_context_fragment_payload,
    parse_context_fragments,
    render_context_fragment,
    render_text_context_fragment,
)
from .manifest import build_runtime_slot_prompt_composition_manifest
from .message_specs import build_model_message_spec, message_spec_content_source
from .assembly_plan import PromptAssemblyPlan, PromptAssemblySlot, build_prompt_assembly_plan
from .materializer import PromptMaterializedPacket, materialize_prompt_packet
from .models import (
    PromptCompositionGraph,
    PromptCompositionContentFragment,
    PromptCompositionManifest,
    PromptCompositionMessageProjection,
    PromptCompositionPlan,
    PromptCompositionSegmentBinding,
    PromptCompositionSlot,
    RuntimePromptSource,
    RuntimePromptSourceManifest,
    RuntimeContextLoadEntry,
    RuntimeContextLoadPlan,
    RuntimePromptSlot,
    RuntimePromptSlotPlan,
)
from .renderer import PromptCompositionRenderResult, render_model_messages_from_projection
from .runtime_context_load_plan import build_runtime_context_load_plan, materialize_runtime_context_load_plan
from .runtime_fragments import (
    PromptCompositionRuntimeFragment,
    build_runtime_payload_message_spec,
    render_runtime_payload_fragment,
)
from .source_bundle import PromptSource, PromptSourceBundle, build_prompt_source_bundle
from .runtime_sources import build_runtime_prompt_source_manifest, materialize_runtime_prompt_sources
from .runtime_slot_plan import (
    build_runtime_prompt_slot_plan,
    composition_slots_from_runtime_slot_plan,
)
from .section_renderer import (
    render_agent_prompt_instruction,
    render_environment_instruction,
    render_lifecycle_instruction,
    render_personality_prompt_instruction,
    render_prompt_contract_instruction,
)

__all__ = [
    "PromptCompositionGraph",
    "PromptCompositionContentFragment",
    "PromptCompositionManifest",
    "PromptCompositionMessageProjection",
    "PromptCompositionPlan",
    "PromptCompositionRenderResult",
    "PromptCompositionRuntimeFragment",
    "PromptCompositionSegmentBinding",
    "PromptCompositionSlot",
    "PromptAssemblyPlan",
    "PromptAssemblySlot",
    "PromptMaterializedPacket",
    "PromptSource",
    "PromptSourceBundle",
    "CONTEXT_FRAGMENT_PROTOCOL",
    "CONTEXT_FRAGMENT_TAG",
    "RuntimePromptSource",
    "RuntimePromptSourceManifest",
    "RuntimeContextLoadEntry",
    "RuntimeContextLoadPlan",
    "RuntimePromptSlot",
    "RuntimePromptSlotPlan",
    "build_content_fragments_from_model_messages",
    "build_content_fragments_from_message_specs",
    "build_model_message_spec",
    "build_prompt_assembly_plan",
    "build_prompt_source_bundle",
    "build_runtime_context_load_plan",
    "build_runtime_prompt_source_manifest",
    "build_runtime_prompt_slot_plan",
    "build_runtime_payload_message_spec",
    "build_runtime_slot_prompt_composition_manifest",
    "composition_slots_from_runtime_slot_plan",
    "is_context_fragment",
    "materialize_runtime_context_load_plan",
    "materialize_runtime_prompt_sources",
    "materialize_prompt_packet",
    "message_spec_content_source",
    "parse_context_fragment_payload",
    "parse_context_fragments",
    "render_agent_prompt_instruction",
    "render_environment_instruction",
    "render_lifecycle_instruction",
    "render_model_messages_from_projection",
    "render_personality_prompt_instruction",
    "render_prompt_contract_instruction",
    "render_context_fragment",
    "render_runtime_payload_fragment",
    "render_text_context_fragment",
]
