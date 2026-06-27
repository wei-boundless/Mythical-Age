from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .contracts import (
    ConversationMemorySnapshot,
    MemoryContextCandidate,
    StateMemoryRestoreCandidate,
    StateMemorySnapshot,
)


MEMORY_LAYER_ALIASES: dict[str, str] = {
    "conversation": "conversation",
    "state": "state",
    "working": "working",
    "working_memory": "working",
    "long_term": "long_term",
    "durable": "long_term",
}
DISCONNECTED_MEMORY_LAYERS: frozenset[str] = frozenset({"task_durable", "task_durable_memory"})
VALID_MEMORY_LAYERS: tuple[str, ...] = ("conversation", "state", "working", "long_term")


@dataclass(slots=True, frozen=True)
class MemoryRuntimeView:
    """Read-only runtime view consumed by harness/context policy."""

    view_id: str
    session_id: str
    conversation_snapshot: ConversationMemorySnapshot | None = None
    state_snapshot: StateMemorySnapshot | None = None
    context_candidates: tuple[MemoryContextCandidate, ...] = ()
    restore_candidates: tuple[StateMemoryRestoreCandidate, ...] = ()
    read_only: bool = True
    memory_write_allowed: bool = False
    authority: str = "memory_runtime_view"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.read_only:
            raise ValueError("MemoryRuntimeView must remain read_only")
        if self.memory_write_allowed:
            raise ValueError("MemoryRuntimeView cannot allow memory writes")
        for candidate in self.context_candidates:
            if candidate.can_override_current_turn:
                raise ValueError("MemoryRuntimeView cannot expose overriding context candidates")
        for candidate in self.restore_candidates:
            if candidate.can_promote_to_current_fact:
                raise ValueError("MemoryRuntimeView cannot expose self-promoting restore candidates")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["conversation_snapshot"] = (
            self.conversation_snapshot.to_dict() if self.conversation_snapshot is not None else None
        )
        payload["state_snapshot"] = self.state_snapshot.to_dict() if self.state_snapshot is not None else None
        payload["context_candidates"] = [item.to_dict() for item in self.context_candidates]
        payload["restore_candidates"] = [item.to_dict() for item in self.restore_candidates]
        return payload


def normalize_memory_layer(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw in DISCONNECTED_MEMORY_LAYERS:
        raise ValueError(f"Memory layer is disconnected from runtime: {raw}")
    normalized = MEMORY_LAYER_ALIASES.get(raw)
    if normalized is None:
        raise ValueError(f"Unknown memory layer: {raw}")
    return normalized


def normalize_memory_layers(values: Any) -> tuple[str, ...]:
    layers: list[str] = []
    seen: set[str] = set()
    for item in list(values or ()):
        layer = normalize_memory_layer(item)
        if not layer or layer in seen:
            continue
        seen.add(layer)
        layers.append(layer)
    return tuple(layers)



