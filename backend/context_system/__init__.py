from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

__all__ = [
    "BundleItem",
    "CompactResult",
    "ContextBudget",
    "ContextBudgetPreset",
    "ContextCandidateDecision",
    "ContextCompactor",
    "ContextController",
    "ContextControllerResult",
    "ContextPackage",
    "ContextPolicyResult",
    "ContextProjection",
    "ContextResolver",
    "TurnBinding",
    "EvidenceSummary",
    "MainContextState",
    "MemoryContextPolicy",
    "PressureLevel",
    "ResolvedBinding",
    "SealedContextLedgerEntry",
    "SealedContextReceipt",
    "SemanticCompactionRequest",
    "TaskSummaryRef",
    "build_context_package_result",
    "get_context_budget_preset",
    "list_context_budget_presets",
    "normalize_context_budget_preset_id",
    "projection_from_bundle_answer",
    "projection_from_file_work",
]

_EXPORTS = {
    "BundleItem": ("context_system.current_turn.turn_binding", "BundleItem"),
    "CompactResult": ("context_system.compaction.compactor", "CompactResult"),
    "ContextBudget": ("context_system.models.context_models", "ContextBudget"),
    "ContextBudgetPreset": ("context_system.budget.presets", "ContextBudgetPreset"),
    "ContextCandidateDecision": ("context_system.policy.contracts", "ContextCandidateDecision"),
    "ContextCompactor": ("context_system.compaction.compactor", "ContextCompactor"),
    "ContextController": ("context_system.packaging.controller", "ContextController"),
    "ContextControllerResult": ("context_system.models.context_models", "ContextControllerResult"),
    "ContextPackage": ("context_system.models.context_models", "ContextPackage"),
    "ContextPolicyResult": ("context_system.policy.contracts", "ContextPolicyResult"),
    "ContextProjection": ("context_system.projection.projection", "ContextProjection"),
    "ContextResolver": ("context_system.resolution.resolver", "ContextResolver"),
    "TurnBinding": ("context_system.current_turn.turn_binding", "TurnBinding"),
    "EvidenceSummary": ("context_system.policy.runtime_models", "EvidenceSummary"),
    "MainContextState": ("context_system.policy.runtime_models", "MainContextState"),
    "MemoryContextPolicy": ("context_system.policy.package_builder", "MemoryContextPolicy"),
    "PressureLevel": ("context_system.models.context_models", "PressureLevel"),
    "ResolvedBinding": ("context_system.current_turn.turn_binding", "ResolvedBinding"),
    "SealedContextLedgerEntry": ("context_system.models.context_models", "SealedContextLedgerEntry"),
    "SealedContextReceipt": ("context_system.models.context_models", "SealedContextReceipt"),
    "SemanticCompactionRequest": ("context_system.compaction.compactor", "SemanticCompactionRequest"),
    "TaskSummaryRef": ("context_system.policy.runtime_models", "TaskSummaryRef"),
    "build_context_package_result": ("context_system.policy.package_builder", "build_context_package_result"),
    "get_context_budget_preset": ("context_system.budget.presets", "get_context_budget_preset"),
    "list_context_budget_presets": ("context_system.budget.presets", "list_context_budget_presets"),
    "normalize_context_budget_preset_id": ("context_system.budget.presets", "normalize_context_budget_preset_id"),
    "projection_from_bundle_answer": ("context_system.projection.projection", "projection_from_bundle_answer"),
    "projection_from_file_work": ("context_system.projection.projection", "projection_from_file_work"),
}

if TYPE_CHECKING:
    from context_system.budget.presets import (
        ContextBudgetPreset,
        get_context_budget_preset,
        list_context_budget_presets,
        normalize_context_budget_preset_id,
    )
    from context_system.compaction.compactor import CompactResult, ContextCompactor, SemanticCompactionRequest
    from context_system.current_turn.turn_binding import BundleItem, TurnBinding, ResolvedBinding
    from context_system.models.context_models import (
        ContextBudget,
        ContextControllerResult,
        ContextPackage,
        PressureLevel,
        SealedContextLedgerEntry,
        SealedContextReceipt,
    )
    from context_system.packaging.controller import ContextController
    from context_system.policy import (
        ContextCandidateDecision,
        ContextPolicyResult,
        EvidenceSummary,
        MainContextState,
        MemoryContextPolicy,
        TaskSummaryRef,
        build_context_package_result,
    )
    from context_system.projection.projection import (
        ContextProjection,
        projection_from_bundle_answer,
        projection_from_file_work,
    )
    from context_system.resolution.resolver import ContextResolver


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


