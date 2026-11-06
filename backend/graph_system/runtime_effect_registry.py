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
_LOADED_MODULES: set[str] = set()


def snapshot_runtime_algorithm_effect_registry() -> dict[str, Any]:
    return {
        "handlers": dict(_HANDLERS),
        "loaded_modules": set(_LOADED_MODULES),
    }


def restore_runtime_algorithm_effect_registry(snapshot: dict[str, Any]) -> None:
    _HANDLERS.clear()
    _HANDLERS.update(dict(snapshot.get("handlers") or {}))
    _LOADED_MODULES.clear()
    _LOADED_MODULES.update(str(item) for item in set(snapshot.get("loaded_modules") or set()) if str(item))


def register_runtime_algorithm_effect_handler(handler: RuntimeAlgorithmEffectHandler) -> None:
    effect_kind = str(handler.effect_kind or "").strip()
    if effect_kind in _HANDLERS:
        raise ValueError(f"duplicate runtime algorithm effect handler kind: {effect_kind}")
    _HANDLERS[effect_kind] = handler


def iter_runtime_algorithm_effect_handlers() -> tuple[RuntimeAlgorithmEffectHandler, ...]:
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


def load_runtime_algorithm_effect_module(module_name: str) -> None:
    normalized = str(module_name or "").strip()
    if not normalized or normalized in _LOADED_MODULES:
        return
    module = importlib.import_module(normalized)
    register = getattr(module, "register_runtime_algorithm_effect_handlers", None)
    if not callable(register):
        raise ValueError(f"runtime algorithm effect module has no register_runtime_algorithm_effect_handlers(): {normalized}")
    before = dict(_HANDLERS)
    try:
        register(register_runtime_algorithm_effect_handler)
    except Exception:
        _HANDLERS.clear()
        _HANDLERS.update(before)
        raise
    if _HANDLERS == before:
        raise ValueError(f"runtime algorithm effect module registered no handlers: {normalized}")
    _LOADED_MODULES.add(normalized)


def load_runtime_algorithm_effect_modules(module_names: tuple[str, ...] | list[str]) -> None:
    for module_name in list(module_names or ()):
        load_runtime_algorithm_effect_module(str(module_name or ""))


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
