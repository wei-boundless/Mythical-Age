from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Callable


RevisionRejectionSignalCallable = Callable[..., bool | dict[str, Any] | None]
RevisionRequeuePatchCallable = Callable[..., dict[str, Any] | None]


@dataclass(frozen=True, slots=True)
class RevisionRejectionSignalHandler:
    handler_id: str
    source_result_requests_revision: RevisionRejectionSignalCallable
    priority: int = 1000

    def __post_init__(self) -> None:
        if not str(self.handler_id or "").strip():
            raise ValueError("RevisionRejectionSignalHandler requires handler_id")
        if not callable(self.source_result_requests_revision):
            raise ValueError("RevisionRejectionSignalHandler requires callable source_result_requests_revision")


@dataclass(frozen=True, slots=True)
class RevisionRequeuePatchHandler:
    handler_id: str
    build_revision_requeue_patch: RevisionRequeuePatchCallable
    priority: int = 1000

    def __post_init__(self) -> None:
        if not str(self.handler_id or "").strip():
            raise ValueError("RevisionRequeuePatchHandler requires handler_id")
        if not callable(self.build_revision_requeue_patch):
            raise ValueError("RevisionRequeuePatchHandler requires callable build_revision_requeue_patch")


_HANDLERS: dict[str, RevisionRejectionSignalHandler] = {}
_PATCH_HANDLERS: dict[str, RevisionRequeuePatchHandler] = {}
_DEFAULT_MODULES_LOADED = False
_DEFAULT_MODULES = (
    "task_system.writing_graphs.revision_signal_handlers",
)


def register_revision_rejection_signal_handler(handler: RevisionRejectionSignalHandler) -> None:
    _HANDLERS[handler.handler_id] = handler


def register_revision_requeue_patch_handler(handler: RevisionRequeuePatchHandler) -> None:
    _PATCH_HANDLERS[handler.handler_id] = handler


def iter_revision_rejection_signal_handlers() -> tuple[RevisionRejectionSignalHandler, ...]:
    _ensure_default_modules_loaded()
    return tuple(sorted(_HANDLERS.values(), key=lambda handler: (handler.priority, handler.handler_id)))


def iter_revision_requeue_patch_handlers() -> tuple[RevisionRequeuePatchHandler, ...]:
    _ensure_default_modules_loaded()
    return tuple(sorted(_PATCH_HANDLERS.values(), key=lambda handler: (handler.priority, handler.handler_id)))


def source_result_revision_signal(*, source_result: dict[str, Any]) -> dict[str, Any]:
    for handler in iter_revision_rejection_signal_handlers():
        decision = handler.source_result_requests_revision(source_result=dict(source_result or {}))
        if decision is None:
            continue
        if isinstance(decision, dict):
            return {
                **dict(decision),
                "requests_revision": bool(dict(decision).get("requests_revision", False)),
                "handler_id": handler.handler_id,
            }
        return {
            "requests_revision": bool(decision),
            "handler_id": handler.handler_id,
            "authority": "graph_system.revision_signal_registry.boolean_decision",
        }
    return {}


def source_result_requests_revision(*, source_result: dict[str, Any]) -> bool:
    return bool(source_result_revision_signal(source_result=source_result).get("requests_revision", False))


def build_revision_requeue_patch(
    *,
    graph_config: Any,
    state: Any,
    target_node_ids: tuple[str, ...],
    revision_sources: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    for handler in iter_revision_requeue_patch_handlers():
        patch = handler.build_revision_requeue_patch(
            graph_config=graph_config,
            state=state,
            target_node_ids=target_node_ids,
            revision_sources=revision_sources,
        )
        if patch:
            return {
                **dict(patch),
                "handler_id": handler.handler_id,
            }
    return {}


def _ensure_default_modules_loaded() -> None:
    global _DEFAULT_MODULES_LOADED
    if _DEFAULT_MODULES_LOADED:
        return
    _DEFAULT_MODULES_LOADED = True
    for module_name in _DEFAULT_MODULES:
        module = importlib.import_module(module_name)
        register = getattr(module, "register_revision_rejection_signal_handlers", None)
        if callable(register):
            register(register_revision_rejection_signal_handler)
        patch_register = getattr(module, "register_revision_requeue_patch_handlers", None)
        if callable(patch_register):
            patch_register(register_revision_requeue_patch_handler)
