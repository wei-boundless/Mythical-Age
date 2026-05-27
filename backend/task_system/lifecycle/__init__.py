"""Task lifecycle services."""

from __future__ import annotations

from typing import Any


__all__ = [
    "InMemoryTaskLifecycleStore",
    "TaskLifecycleCreation",
    "TaskLifecycleFactory",
    "TaskLifecycleRegistry",
    "TaskLifecycleStore",
]


def __getattr__(name: str) -> Any:
    if name in {"TaskLifecycleCreation", "TaskLifecycleFactory"}:
        from .factory import TaskLifecycleCreation, TaskLifecycleFactory

        return {
            "TaskLifecycleCreation": TaskLifecycleCreation,
            "TaskLifecycleFactory": TaskLifecycleFactory,
        }[name]
    if name == "TaskLifecycleRegistry":
        from .registry import TaskLifecycleRegistry

        return TaskLifecycleRegistry
    if name in {"InMemoryTaskLifecycleStore", "TaskLifecycleStore"}:
        from .repository import InMemoryTaskLifecycleStore, TaskLifecycleStore

        return {
            "InMemoryTaskLifecycleStore": InMemoryTaskLifecycleStore,
            "TaskLifecycleStore": TaskLifecycleStore,
        }[name]
    raise AttributeError(name)
