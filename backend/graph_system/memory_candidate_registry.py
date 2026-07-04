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
_DEFAULT_MODULES_LOADED = False
_DEFAULT_MODULES = (
    "task_system.writing_graphs.memory_candidate_handlers",
)


def register_memory_candidate_payload_handler(handler: MemoryCandidatePayloadHandler) -> None:
    _HANDLERS[handler.handler_id] = handler


def iter_memory_candidate_payload_handlers() -> tuple[MemoryCandidatePayloadHandler, ...]:
    _ensure_default_modules_loaded()
    return tuple(sorted(_HANDLERS.values(), key=lambda handler: (handler.priority, handler.handler_id)))


def augment_candidate_source_payload(*, task_run_payload: dict[str, Any], base_payload: dict[str, Any]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for handler in iter_memory_candidate_payload_handlers():
        contribution = handler.augment_candidate_source_payload(
            task_run_payload=dict(task_run_payload or {}),
            base_payload={**dict(base_payload or {}), **patch},
        )
        if contribution:
            patch.update(dict(contribution))
    return patch


def _ensure_default_modules_loaded() -> None:
    global _DEFAULT_MODULES_LOADED
    if _DEFAULT_MODULES_LOADED:
        return
    _DEFAULT_MODULES_LOADED = True
    for module_name in _DEFAULT_MODULES:
        module = importlib.import_module(module_name)
        register = getattr(module, "register_memory_candidate_payload_handlers", None)
        if callable(register):
            register(register_memory_candidate_payload_handler)
