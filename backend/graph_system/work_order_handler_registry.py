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
_DEFAULT_MODULES_LOADED = False
_DEFAULT_MODULES = (
    "task_system.writing_graphs.work_order_handlers",
)


def register_deterministic_work_order_handler(handler: DeterministicWorkOrderHandler) -> None:
    _HANDLERS[handler.handler_id] = handler


def iter_deterministic_work_order_handlers() -> tuple[DeterministicWorkOrderHandler, ...]:
    _ensure_default_modules_loaded()
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


def _ensure_default_modules_loaded() -> None:
    global _DEFAULT_MODULES_LOADED
    if _DEFAULT_MODULES_LOADED:
        return
    _DEFAULT_MODULES_LOADED = True
    for module_name in _DEFAULT_MODULES:
        module = importlib.import_module(module_name)
        register = getattr(module, "register_deterministic_work_order_handlers", None)
        if callable(register):
            register(register_deterministic_work_order_handler)
