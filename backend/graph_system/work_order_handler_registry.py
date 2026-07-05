from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Callable

from .models import ExecutableGraphConfig, GraphNodeWorkOrder


DeterministicWorkOrderCallable = Callable[..., "DeterministicWorkOrderResult | None"]


@dataclass(frozen=True, slots=True)
class DeterministicWorkOrderResult:
    executor_result: dict[str, Any]
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DeterministicWorkOrderHandler:
    handler_id: str
    handle: DeterministicWorkOrderCallable
    priority: int = 1000

    def __post_init__(self) -> None:
        if not str(self.handler_id or "").strip():
            raise ValueError("DeterministicWorkOrderHandler requires handler_id")
        if not callable(self.handle):
            raise ValueError("DeterministicWorkOrderHandler requires callable handle")


_HANDLERS: dict[str, DeterministicWorkOrderHandler] = {}
_LOADED_MODULES: set[str] = set()


def snapshot_deterministic_work_order_handler_registry() -> dict[str, Any]:
    return {
        "handlers": dict(_HANDLERS),
        "loaded_modules": set(_LOADED_MODULES),
    }


def restore_deterministic_work_order_handler_registry(snapshot: dict[str, Any]) -> None:
    _HANDLERS.clear()
    _HANDLERS.update(dict(snapshot.get("handlers") or {}))
    _LOADED_MODULES.clear()
    _LOADED_MODULES.update(str(item) for item in set(snapshot.get("loaded_modules") or set()) if str(item))


def register_deterministic_work_order_handler(handler: DeterministicWorkOrderHandler) -> None:
    handler_id = str(handler.handler_id or "").strip()
    if handler_id in _HANDLERS:
        raise ValueError(f"duplicate deterministic work order handler id: {handler_id}")
    _HANDLERS[handler_id] = handler


def iter_deterministic_work_order_handlers() -> tuple[DeterministicWorkOrderHandler, ...]:
    return tuple(sorted(_HANDLERS.values(), key=lambda handler: (handler.priority, handler.handler_id)))


def handle_deterministic_work_order(
    *,
    graph_config: ExecutableGraphConfig,
    work_order: GraphNodeWorkOrder,
) -> DeterministicWorkOrderResult | None:
    for handler in iter_deterministic_work_order_handlers():
        result = handler.handle(graph_config=graph_config, work_order=work_order)
        if result is not None:
            return result
    return None


def load_deterministic_work_order_handler_module(module_name: str) -> None:
    normalized = str(module_name or "").strip()
    if not normalized or normalized in _LOADED_MODULES:
        return
    module = importlib.import_module(normalized)
    register = getattr(module, "register_deterministic_work_order_handlers", None)
    if not callable(register):
        raise ValueError(f"deterministic work order handler module has no register_deterministic_work_order_handlers(): {normalized}")
    before = dict(_HANDLERS)
    try:
        register(register_deterministic_work_order_handler)
    except Exception:
        _HANDLERS.clear()
        _HANDLERS.update(before)
        raise
    if _HANDLERS == before:
        raise ValueError(f"deterministic work order handler module registered no handlers: {normalized}")
    _LOADED_MODULES.add(normalized)


def load_deterministic_work_order_handler_modules(module_names: tuple[str, ...] | list[str]) -> None:
    for module_name in list(module_names or ()):
        load_deterministic_work_order_handler_module(str(module_name or ""))
