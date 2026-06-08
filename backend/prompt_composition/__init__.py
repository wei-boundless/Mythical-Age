from __future__ import annotations

from .fragments import build_content_fragments_from_message_specs, build_content_fragments_from_model_messages
from .manifest import build_shadow_prompt_composition_manifest
from .message_specs import build_model_message_spec, message_spec_content_source
from .models import (
    PromptCompositionGraph,
    PromptCompositionContentFragment,
    PromptCompositionLayerInput,
    PromptCompositionManifest,
    PromptCompositionMessageProjection,
    PromptCompositionPlan,
    PromptCompositionSegmentBinding,
    PromptCompositionSlot,
)
from .renderer import PromptCompositionRenderResult, render_model_messages_from_projection
from .runtime_fragments import (
    PromptCompositionRuntimeFragment,
    build_runtime_payload_message_spec,
    render_runtime_payload_fragment,
)
from .section_renderer import (
    render_agent_prompt_instruction,
    render_environment_instruction,
    render_personality_prompt_instruction,
    render_prompt_contract_instruction,
)

__all__ = [
    "PromptCompositionGraph",
    "PromptCompositionContentFragment",
    "PromptCompositionLayerInput",
    "PromptCompositionManifest",
    "PromptCompositionMessageProjection",
    "PromptCompositionPlan",
    "PromptCompositionRenderResult",
    "PromptCompositionRuntimeFragment",
    "PromptCompositionSegmentBinding",
    "PromptCompositionSlot",
    "build_content_fragments_from_model_messages",
    "build_content_fragments_from_message_specs",
    "build_model_message_spec",
    "build_runtime_payload_message_spec",
    "build_shadow_prompt_composition_manifest",
    "message_spec_content_source",
    "render_agent_prompt_instruction",
    "render_environment_instruction",
    "render_model_messages_from_projection",
    "render_personality_prompt_instruction",
    "render_prompt_contract_instruction",
    "render_runtime_payload_fragment",
]
