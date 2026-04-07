from __future__ import annotations

from typing import Any

__all__ = [
    "CompactResult",
    "ContextBudget",
    "ContextCompactor",
    "ContextController",
    "ContextControllerResult",
    "ContextPackage",
]


def __getattr__(name: str) -> Any:
    if name in {"CompactResult", "ContextCompactor"}:
        from .context_compactor import CompactResult, ContextCompactor

        mapping = {
            "CompactResult": CompactResult,
            "ContextCompactor": ContextCompactor,
        }
        return mapping[name]

    if name in {"ContextBudget", "ContextControllerResult", "ContextPackage"}:
        from .context_models import ContextBudget, ContextControllerResult, ContextPackage

        mapping = {
            "ContextBudget": ContextBudget,
            "ContextControllerResult": ContextControllerResult,
            "ContextPackage": ContextPackage,
        }
        return mapping[name]

    if name == "ContextController":
        from .context_controller import ContextController

        return ContextController

    raise AttributeError(name)

