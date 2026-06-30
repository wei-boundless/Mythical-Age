from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

__all__ = [
    "EvidenceSummary",
    "MainContextState",
    "TurnContextCandidateDecision",
    "TurnContextPolicyResult",
    "TurnMemoryContextPolicy",
    "ContextSelectionReceiptEntry",
    "ContextSelectionReceipt",
    "TaskSummaryRef",
    "build_turn_context_package_result",
]

_EXPORTS = {
    "EvidenceSummary": ("context_system.policy.runtime_models", "EvidenceSummary"),
    "MainContextState": ("context_system.policy.runtime_models", "MainContextState"),
    "TurnContextCandidateDecision": ("context_system.policy.contracts", "TurnContextCandidateDecision"),
    "TurnContextPolicyResult": ("context_system.policy.contracts", "TurnContextPolicyResult"),
    "TurnMemoryContextPolicy": ("context_system.policy.package_builder", "TurnMemoryContextPolicy"),
    "ContextSelectionReceiptEntry": ("context_system.models.context_models", "ContextSelectionReceiptEntry"),
    "ContextSelectionReceipt": ("context_system.models.context_models", "ContextSelectionReceipt"),
    "TaskSummaryRef": ("context_system.policy.runtime_models", "TaskSummaryRef"),
    "build_turn_context_package_result": ("context_system.policy.package_builder", "build_turn_context_package_result"),
}

if TYPE_CHECKING:
    from context_system.policy.contracts import TurnContextCandidateDecision, TurnContextPolicyResult
    from context_system.policy.package_builder import TurnMemoryContextPolicy, build_turn_context_package_result
    from context_system.policy.runtime_models import EvidenceSummary, MainContextState, TaskSummaryRef
    from context_system.models.context_models import ContextSelectionReceiptEntry, ContextSelectionReceipt


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


