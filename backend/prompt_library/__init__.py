from __future__ import annotations

from .default_resources import list_default_prompt_resources
from .models import PromptAssemblyPlan, PromptAssemblyPlanItem, PromptResource, PromptSelectionContext
from .registry import PromptLibraryRegistry
from .selector import PromptSelector, build_prompt_selection_context

__all__ = [
    "list_default_prompt_resources",
    "PromptLibraryRegistry",
    "PromptSelector",
    "PromptAssemblyPlan",
    "PromptAssemblyPlanItem",
    "PromptResource",
    "PromptSelectionContext",
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


