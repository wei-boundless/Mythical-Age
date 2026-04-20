from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from structured_memory import ExactMemoryMatch, MemoryManager, find_exact_memory_matches


@dataclass(slots=True)
class DurableSelectionResult:
    exact_matches: list[ExactMemoryMatch]
    relevant_notes: list[Any]
    manifest_lines: str


class RelevantMemorySelector:
    def __init__(self, memory_manager: MemoryManager) -> None:
        self.memory_manager = memory_manager

    def select_exact(
        self,
        query: str | None,
        memory_intent: Any | None,
        *,
        note_limit: int,
    ) -> list[ExactMemoryMatch]:
        if (
            not query
            or memory_intent is None
            or bool(getattr(memory_intent, "ignore_memory", False))
            or not _should_consider_durable_query(memory_intent)
        ):
            return []
        return find_exact_memory_matches(
            self.memory_manager.root_dir,
            query,
            preferred_types=list(getattr(memory_intent, "preferred_types", []) or []),
            limit=min(3, note_limit),
        )

    def select_relevant(
        self,
        query: str,
        *,
        preferred_types: list[str] | None = None,
        preferred_classes: list[str] | None = None,
        limit: int = 3,
        exclude_filenames: set[str] | None = None,
    ) -> list[Any]:
        return self.memory_manager.select_relevant_notes(
            query,
            preferred_types=preferred_types or [],
            preferred_classes=preferred_classes or [],
            limit=limit,
            exclude_filenames=exclude_filenames or set(),
        )

    def build_manifest_fallback(self, *, limit: int = 5) -> str:
        manifest = self.memory_manager.build_manifest(limit=limit).strip()
        if not manifest:
            return ""
        return f"## Durable Memory Manifest\n{manifest}"


def _should_consider_durable_query(memory_intent: Any | None) -> bool:
    if memory_intent is None:
        return False
    if bool(getattr(memory_intent, "explicit_read_inventory", False)):
        return True
    if str(getattr(memory_intent, "intent", "") or "") == "memory_read_signal":
        return True
    if list(getattr(memory_intent, "preferred_types", []) or []):
        return True
    if list(getattr(memory_intent, "preferred_memory_classes", []) or []):
        return True
    return getattr(memory_intent, "memory_read_mode", "none") == "durable_exact"
