from __future__ import annotations

from .models import GraphNodeTaskBinding, binding_from_work_order_payload
from .repository import GraphNodeTaskBindingRepository

__all__ = [
    "GraphNodeTaskBinding",
    "GraphNodeTaskBindingRepository",
    "GraphNodeTaskBindingService",
    "GraphNodeTaskPreparation",
    "GraphNodeTaskResultProjection",
    "binding_from_work_order_payload",
]


def __getattr__(name: str) -> object:
    if name in {"GraphNodeTaskBindingService", "GraphNodeTaskPreparation", "GraphNodeTaskResultProjection"}:
        from .service import GraphNodeTaskBindingService, GraphNodeTaskPreparation, GraphNodeTaskResultProjection

        exports = {
            "GraphNodeTaskBindingService": GraphNodeTaskBindingService,
            "GraphNodeTaskPreparation": GraphNodeTaskPreparation,
            "GraphNodeTaskResultProjection": GraphNodeTaskResultProjection,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
