from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

__all__ = [
    "MemoryBundle",
    "MemoryContextCandidate",
    "MemoryFacade",
    "MemoryHeader",
    "MemoryNote",
    "MemoryRequest",
    "MemoryRuntimeView",
    "MemoryScopePolicy",
    "WorkingMemoryPolicyProfile",
    "build_memory_bundle",
    "build_memory_request",
    "build_memory_scope_policy",
]

_EXPORTS = {
    "MemoryBundle": ("memory_system.runtime_supply", "MemoryBundle"),
    "MemoryContextCandidate": ("memory_system.contracts", "MemoryContextCandidate"),
    "MemoryFacade": ("memory_system.facade", "MemoryFacade"),
    "MemoryHeader": ("memory_system.manifest_scan", "MemoryHeader"),
    "MemoryNote": ("memory_system.storage.models", "MemoryNote"),
    "MemoryRequest": ("memory_system.runtime_supply", "MemoryRequest"),
    "MemoryRuntimeView": ("memory_system.runtime_view", "MemoryRuntimeView"),
    "MemoryScopePolicy": ("memory_system.runtime_supply", "MemoryScopePolicy"),
    "WorkingMemoryPolicyProfile": ("memory_system.working_memory_models", "WorkingMemoryPolicyProfile"),
    "build_memory_bundle": ("memory_system.runtime_supply", "build_memory_bundle"),
    "build_memory_request": ("memory_system.runtime_supply", "build_memory_request"),
    "build_memory_scope_policy": ("memory_system.runtime_supply", "build_memory_scope_policy"),
}

if TYPE_CHECKING:
    from .contracts import MemoryContextCandidate
    from .facade import MemoryFacade
    from .manifest_scan import MemoryHeader
    from .runtime_view import MemoryRuntimeView
    from .runtime_supply import (
        MemoryBundle,
        MemoryRequest,
        MemoryScopePolicy,
        build_memory_bundle,
        build_memory_request,
        build_memory_scope_policy,
    )
    from .storage.models import MemoryNote
    from .working_memory_models import WorkingMemoryPolicyProfile


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


