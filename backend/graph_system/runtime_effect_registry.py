from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


RuntimeAlgorithmEffectCallable = Callable[..., dict[str, Any] | None]


@dataclass(frozen=True, slots=True)
class RuntimeAlgorithmEffectHandler:
    effect_kind: str
    handle: RuntimeAlgorithmEffectCallable
    priority: int = 1000

    def __post_init__(self) -> None:
        if not str(self.effect_kind or "").strip():
            raise ValueError("RuntimeAlgorithmEffectHandler requires effect_kind")
        if not callable(self.handle):
            raise ValueError("RuntimeAlgorithmEffectHandler requires callable handle")


_HANDLERS: dict[str, RuntimeAlgorithmEffectHandler] = {}
_DEFAULT_MODULES_LOADED = False
_DEFAULT_MODULES = (
    "project_network_tasks.runtime_effects",
)


def register_runtime_algorithm_effect_handler(handler: RuntimeAlgorithmEffectHandler) -> None:
    _HANDLERS[handler.effect_kind] = handler


def iter_runtime_algorithm_effect_handlers() -> tuple[RuntimeAlgorithmEffectHandler, ...]:
    _ensure_default_modules_loaded()
    return tuple(sorted(_HANDLERS.values(), key=lambda handler: (handler.priority, handler.effect_kind)))


def handle_runtime_algorithm_effects(
    *,
    effect_requests: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    graph_config: Any,
    graph_state: Any,
    node_result: Any,
    backend_dir: str | Path,
) -> dict[str, Any]:
    receipts: list[dict[str, Any]] = []
    handlers = {handler.effect_kind: handler for handler in iter_runtime_algorithm_effect_handlers()}
    for request in [dict(item) for item in list(effect_requests or []) if isinstance(item, dict)]:
        effect_kind = str(request.get("effect_kind") or "").strip()
        handler = handlers.get(effect_kind)
        if handler is None:
            receipts.append(_unsupported_effect_receipt(request))
            continue
        try:
            receipt = handler.handle(
                request=request,
                graph_config=graph_config,
                graph_state=graph_state,
                node_result=node_result,
                backend_dir=Path(backend_dir),
            )
        except Exception as exc:  # pragma: no cover - defensive boundary; CLI smoke checks cover success path.
            receipt = {
                "effect_kind": effect_kind,
                "status": "failed",
                "reason": type(exc).__name__,
                "detail": str(exc),
                "required": bool(request.get("required", False)),
                "authority": "graph_system.runtime_effect_registry.handler_exception",
            }
        receipts.append(dict(receipt or _default_handler_receipt(request)))
    return {
        "receipts": receipts,
        "authority": "graph_system.runtime_effect_registry",
    }


def _ensure_default_modules_loaded() -> None:
    global _DEFAULT_MODULES_LOADED
    if _DEFAULT_MODULES_LOADED:
        return
    _DEFAULT_MODULES_LOADED = True
    for module_name in _DEFAULT_MODULES:
        module = importlib.import_module(module_name)
        register = getattr(module, "register_runtime_algorithm_effect_handlers", None)
        if callable(register):
            register(register_runtime_algorithm_effect_handler)


def _unsupported_effect_receipt(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "effect_kind": str(request.get("effect_kind") or ""),
        "status": "failed" if bool(request.get("required", False)) else "skipped",
        "reason": "unsupported_runtime_algorithm_effect",
        "required": bool(request.get("required", False)),
        "authority": "graph_system.runtime_effect_registry.unsupported",
    }


def _default_handler_receipt(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "effect_kind": str(request.get("effect_kind") or ""),
        "status": "failed" if bool(request.get("required", False)) else "skipped",
        "reason": "effect_handler_returned_no_receipt",
        "required": bool(request.get("required", False)),
        "authority": "graph_system.runtime_effect_registry.default_receipt",
    }
