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
_LOADED_MODULES: set[str] = set()


def snapshot_revision_signal_handler_registry() -> dict[str, Any]:
    return {
        "handlers": dict(_HANDLERS),
        "patch_handlers": dict(_PATCH_HANDLERS),
        "loaded_modules": set(_LOADED_MODULES),
    }


def restore_revision_signal_handler_registry(snapshot: dict[str, Any]) -> None:
    _HANDLERS.clear()
    _HANDLERS.update(dict(snapshot.get("handlers") or {}))
    _PATCH_HANDLERS.clear()
    _PATCH_HANDLERS.update(dict(snapshot.get("patch_handlers") or {}))
    _LOADED_MODULES.clear()
    _LOADED_MODULES.update(str(item) for item in set(snapshot.get("loaded_modules") or set()) if str(item))


def register_revision_rejection_signal_handler(handler: RevisionRejectionSignalHandler) -> None:
    handler_id = str(handler.handler_id or "").strip()
    if handler_id in _HANDLERS:
        raise ValueError(f"duplicate revision rejection signal handler id: {handler_id}")
    _HANDLERS[handler_id] = handler


def register_revision_requeue_patch_handler(handler: RevisionRequeuePatchHandler) -> None:
    handler_id = str(handler.handler_id or "").strip()
    if handler_id in _PATCH_HANDLERS:
        raise ValueError(f"duplicate revision requeue patch handler id: {handler_id}")
    _PATCH_HANDLERS[handler_id] = handler


def iter_revision_rejection_signal_handlers() -> tuple[RevisionRejectionSignalHandler, ...]:
    return tuple(sorted(_HANDLERS.values(), key=lambda handler: (handler.priority, handler.handler_id)))


def iter_revision_requeue_patch_handlers() -> tuple[RevisionRequeuePatchHandler, ...]:
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


def load_revision_signal_handler_module(module_name: str) -> None:
    normalized = str(module_name or "").strip()
    if not normalized or normalized in _LOADED_MODULES:
        return
    module = importlib.import_module(normalized)
    register = getattr(module, "register_revision_rejection_signal_handlers", None)
    patch_register = getattr(module, "register_revision_requeue_patch_handlers", None)
    if not callable(register) and not callable(patch_register):
        raise ValueError(
            "revision signal handler module has no register_revision_rejection_signal_handlers() "
            f"or register_revision_requeue_patch_handlers(): {normalized}"
        )
    before_handlers = dict(_HANDLERS)
    before_patch_handlers = dict(_PATCH_HANDLERS)
    try:
        if callable(register):
            register(register_revision_rejection_signal_handler)
        if callable(patch_register):
            patch_register(register_revision_requeue_patch_handler)
    except Exception:
        _HANDLERS.clear()
        _HANDLERS.update(before_handlers)
        _PATCH_HANDLERS.clear()
        _PATCH_HANDLERS.update(before_patch_handlers)
        raise
    if _HANDLERS == before_handlers and _PATCH_HANDLERS == before_patch_handlers:
        raise ValueError(f"revision signal handler module registered no handlers: {normalized}")
    _LOADED_MODULES.add(normalized)


def load_revision_signal_handler_modules(module_names: tuple[str, ...] | list[str]) -> None:
    for module_name in list(module_names or ()):
        load_revision_signal_handler_module(str(module_name or ""))
