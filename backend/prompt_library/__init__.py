from __future__ import annotations

from .default_resources import list_default_prompt_resources
from .assembly import PromptAssemblyService
from .manifest import RuntimePromptManifest, build_runtime_prompt_manifest
from .models import (
    PromptAssemblyPlan,
    PromptAssemblyPlanItem,
    PromptAssemblyRequest,
    PromptAssemblyResult,
    PromptPack,
    PromptResource,
    PromptSection,
    PromptSelectionContext,
)
from .packs import default_pack_ref_for_invocation, list_builtin_prompt_packs, list_builtin_runtime_prompt_resources
from .registry import PromptLibraryRegistry
from .selector import PromptSelector, build_prompt_selection_context

__all__ = [
    "list_default_prompt_resources",
    "list_builtin_runtime_prompt_resources",
    "list_builtin_prompt_packs",
    "default_pack_ref_for_invocation",
    "PromptLibraryRegistry",
    "PromptAssemblyService",
    "PromptSelector",
    "PromptAssemblyPlan",
    "PromptAssemblyPlanItem",
    "PromptAssemblyRequest",
    "PromptAssemblyResult",
    "PromptPack",
    "PromptSection",
    "PromptResource",
    "PromptSelectionContext",
    "RuntimePromptManifest",
    "build_runtime_prompt_manifest",
    "assemble_runtime_prompt_contract",
    "assemble_runtime_prompt_sections",
    "build_prompt_manifest_validation",
    "build_prompt_selection_context",
]


def assemble_runtime_prompt_contract(*args, **kwargs):
    from .assembler import assemble_runtime_prompt_contract as _assemble_runtime_prompt_contract

    return _assemble_runtime_prompt_contract(*args, **kwargs)


def assemble_runtime_prompt_sections(*args, **kwargs):
    from .runtime_sections import assemble_runtime_prompt_sections as _assemble_runtime_prompt_sections

    return _assemble_runtime_prompt_sections(*args, **kwargs)


def build_prompt_manifest_validation(*args, **kwargs):
    from .manifest_validation import build_prompt_manifest_validation as _build_prompt_manifest_validation

    return _build_prompt_manifest_validation(*args, **kwargs)


