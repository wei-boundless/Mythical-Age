from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Callable


MemoryCandidatePayloadCallable = Callable[..., dict[str, Any] | None]


@dataclass(frozen=True, slots=True)
class MemoryCandidatePayloadHandler:
    handler_id: str
    augment_candidate_source_payload: MemoryCandidatePayloadCallable
    priority: int = 1000

    def __post_init__(self) -> None:
        if not str(self.handler_id or "").strip():
            raise ValueError("MemoryCandidatePayloadHandler requires handler_id")
        if not callable(self.augment_candidate_source_payload):
            raise ValueError("MemoryCandidatePayloadHandler requires callable augment_candidate_source_payload")


_HANDLERS: dict[str, MemoryCandidatePayloadHandler] = {}
_LOADED_MODULES: set[str] = set()


def snapshot_memory_candidate_payload_handler_registry() -> dict[str, Any]:
    return {
        "handlers": dict(_HANDLERS),
        "loaded_modules": set(_LOADED_MODULES),
    }


def restore_memory_candidate_payload_handler_registry(snapshot: dict[str, Any]) -> None:
    _HANDLERS.clear()
    _HANDLERS.update(dict(snapshot.get("handlers") or {}))
    _LOADED_MODULES.clear()
    _LOADED_MODULES.update(str(item) for item in set(snapshot.get("loaded_modules") or set()) if str(item))


def register_memory_candidate_payload_handler(handler: MemoryCandidatePayloadHandler) -> None:
    handler_id = str(handler.handler_id or "").strip()
    if handler_id in _HANDLERS:
        raise ValueError(f"duplicate memory candidate handler id: {handler_id}")
    _HANDLERS[handler_id] = handler


def iter_memory_candidate_payload_handlers() -> tuple[MemoryCandidatePayloadHandler, ...]:
    return tuple(sorted(_HANDLERS.values(), key=lambda handler: (handler.priority, handler.handler_id)))


def augment_candidate_source_payload(*, task_execution_payload: dict[str, Any], base_payload: dict[str, Any]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for handler in iter_memory_candidate_payload_handlers():
        contribution = handler.augment_candidate_source_payload(
            task_execution_payload=dict(task_execution_payload or {}),
            base_payload={**dict(base_payload or {}), **patch},
        )
        if contribution:
            patch.update(dict(contribution))
    return patch


def load_memory_candidate_payload_handler_module(module_name: str) -> None:
    normalized = str(module_name or "").strip()
    if not normalized or normalized in _LOADED_MODULES:
        return
    module = importlib.import_module(normalized)
    register = getattr(module, "register_memory_candidate_payload_handlers", None)
    if not callable(register):
        raise ValueError(f"memory candidate handler module has no register_memory_candidate_payload_handlers(): {normalized}")
    before = dict(_HANDLERS)
    try:
        register(register_memory_candidate_payload_handler)
    except Exception:
        _HANDLERS.clear()
        _HANDLERS.update(before)
        raise
    if _HANDLERS == before:
        raise ValueError(f"memory candidate handler module registered no handlers: {normalized}")
    _LOADED_MODULES.add(normalized)


def load_memory_candidate_payload_handler_modules(module_names: tuple[str, ...] | list[str]) -> None:
    for module_name in list(module_names or ()):
        load_memory_candidate_payload_handler_module(str(module_name or ""))
