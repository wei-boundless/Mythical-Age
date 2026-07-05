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
_LOADED_MODULES: set[str] = set()


def snapshot_quality_gate_handler_registry() -> dict[str, Any]:
    return {
        "handlers": dict(_HANDLERS),
        "loaded_modules": set(_LOADED_MODULES),
    }


def restore_quality_gate_handler_registry(snapshot: dict[str, Any]) -> None:
    _HANDLERS.clear()
    _HANDLERS.update(dict(snapshot.get("handlers") or {}))
    _LOADED_MODULES.clear()
    _LOADED_MODULES.update(str(item) for item in set(snapshot.get("loaded_modules") or set()) if str(item))


def register_quality_gate_handler(handler: QualityGateHandler) -> None:
    handler_id = str(handler.handler_id or "").strip()
    if handler_id in _HANDLERS:
        raise ValueError(f"duplicate quality gate handler id: {handler_id}")
    _HANDLERS[handler_id] = handler


def iter_quality_gate_handlers() -> tuple[QualityGateHandler, ...]:
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


def load_quality_gate_handler_module(module_name: str) -> None:
    normalized = str(module_name or "").strip()
    if not normalized or normalized in _LOADED_MODULES:
        return
    module = importlib.import_module(normalized)
    register = getattr(module, "register_quality_gate_handlers", None)
    if not callable(register):
        raise ValueError(f"quality gate handler module has no register_quality_gate_handlers(): {normalized}")
    before = dict(_HANDLERS)
    try:
        register(register_quality_gate_handler)
    except Exception:
        _HANDLERS.clear()
        _HANDLERS.update(before)
        raise
    if _HANDLERS == before:
        raise ValueError(f"quality gate handler module registered no handlers: {normalized}")
    _LOADED_MODULES.add(normalized)


def load_quality_gate_handler_modules(module_names: tuple[str, ...] | list[str]) -> None:
    for module_name in list(module_names or ()):
        load_quality_gate_handler_module(str(module_name or ""))
