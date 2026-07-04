from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Callable

from .models import ExecutableGraphConfig, GraphNodeWorkOrder


QualityGateCallable = Callable[..., dict[str, Any] | None]


@dataclass(frozen=True, slots=True)
class QualityGateHandler:
    handler_id: str
    evaluate: QualityGateCallable
    priority: int = 1000

    def __post_init__(self) -> None:
        if not str(self.handler_id or "").strip():
            raise ValueError("QualityGateHandler requires handler_id")
        if not callable(self.evaluate):
            raise ValueError("QualityGateHandler requires callable evaluate")


_HANDLERS: dict[str, QualityGateHandler] = {}
_DEFAULT_MODULES_LOADED = False
_DEFAULT_MODULES = (
    "task_system.writing_graphs.quality_gate_handlers",
)


def register_quality_gate_handler(handler: QualityGateHandler) -> None:
    _HANDLERS[handler.handler_id] = handler


def iter_quality_gate_handlers() -> tuple[QualityGateHandler, ...]:
    _ensure_default_modules_loaded()
    return tuple(sorted(_HANDLERS.values(), key=lambda handler: (handler.priority, handler.handler_id)))


def evaluate_node_quality_acceptance(
    *,
    graph_config: ExecutableGraphConfig,
    work_order: GraphNodeWorkOrder,
    final_answer: str,
    artifact_refs: list[dict[str, Any]],
    result_status: str,
) -> dict[str, Any]:
    for handler in iter_quality_gate_handlers():
        acceptance = handler.evaluate(
            graph_config=graph_config,
            work_order=work_order,
            final_answer=final_answer,
            artifact_refs=artifact_refs,
            result_status=result_status,
        )
        if acceptance:
            return dict(acceptance)
    return {}


def _ensure_default_modules_loaded() -> None:
    global _DEFAULT_MODULES_LOADED
    if _DEFAULT_MODULES_LOADED:
        return
    _DEFAULT_MODULES_LOADED = True
    for module_name in _DEFAULT_MODULES:
        module = importlib.import_module(module_name)
        register = getattr(module, "register_quality_gate_handlers", None)
        if callable(register):
            register(register_quality_gate_handler)
