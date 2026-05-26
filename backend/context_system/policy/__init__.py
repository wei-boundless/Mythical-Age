from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

__all__ = [
    "ContextCandidateDecision",
    "ContextPolicyResult",
    "EvidenceSummary",
    "MainContextState",
    "MemoryContextPolicy",
    "SealedContextLedgerEntry",
    "SealedContextReceipt",
    "TaskSummaryRef",
    "build_context_package_result",
]

_EXPORTS = {
    "ContextCandidateDecision": ("context_system.policy.contracts", "ContextCandidateDecision"),
    "ContextPolicyResult": ("context_system.policy.contracts", "ContextPolicyResult"),
    "EvidenceSummary": ("context_system.policy.runtime_models", "EvidenceSummary"),
    "MainContextState": ("context_system.policy.runtime_models", "MainContextState"),
    "MemoryContextPolicy": ("context_system.policy.package_builder", "MemoryContextPolicy"),
    "SealedContextLedgerEntry": ("context_system.models.context_models", "SealedContextLedgerEntry"),
    "SealedContextReceipt": ("context_system.models.context_models", "SealedContextReceipt"),
    "TaskSummaryRef": ("context_system.policy.runtime_models", "TaskSummaryRef"),
    "build_context_package_result": ("context_system.policy.package_builder", "build_context_package_result"),
}

if TYPE_CHECKING:
    from context_system.policy.contracts import ContextCandidateDecision, ContextPolicyResult
    from context_system.policy.package_builder import MemoryContextPolicy, build_context_package_result
    from context_system.policy.runtime_models import EvidenceSummary, MainContextState, TaskSummaryRef
    from context_system.models.context_models import SealedContextLedgerEntry, SealedContextReceipt


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
