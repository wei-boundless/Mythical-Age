from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .models import PromptSet
from .registry import PromptLibraryRegistry


@dataclass(frozen=True, slots=True)
class PromptSetResolution:
    requested_refs: tuple[str, ...]
    prompt_sets: tuple[PromptSet, ...]
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_library.prompt_set_resolver"

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_refs": list(self.requested_refs),
            "resolved_prompt_sets": [item.prompt_set_id for item in self.prompt_sets],
            "diagnostics": dict(self.diagnostics),
            "authority": self.authority,
        }


class PromptSetResolver:
    def __init__(self, registry: PromptLibraryRegistry) -> None:
        self._registry = registry

    def resolve(self, prompt_set_refs: tuple[str, ...] | list[str]) -> PromptSetResolution:
        requested_refs = _dedupe(tuple(str(item).strip() for item in tuple(prompt_set_refs or ()) if str(item).strip()))
        state = _PromptSetResolutionState(requested_refs=requested_refs)
        for ref in requested_refs:
            self._visit(ref, state=state, chain=())
        diagnostics = {
            "inheritance_graph": {key: list(value) for key, value in sorted(state.inheritance_graph.items())},
            "resolved_paths": [list(path) for path in state.resolved_paths],
            "cycles": [dict(item) for item in state.cycles],
            "missing_prompt_sets": [dict(item) for item in state.missing_prompt_sets],
            "duplicate_prompt_set_paths": [dict(item) for item in state.duplicate_paths],
            "rejected_prompt_sets": [
                *(dict(item) for item in state.missing_prompt_sets),
                *(dict(item) for item in state.cycles),
            ],
            "resolution_id": f"promptsetres:{_digest({'requested_refs': requested_refs, 'resolved': [item.prompt_set_id for item in state.resolved]})}",
        }
        return PromptSetResolution(
            requested_refs=requested_refs,
            prompt_sets=tuple(state.resolved),
            diagnostics=diagnostics,
        )

    def _visit(self, ref: str, *, state: "_PromptSetResolutionState", chain: tuple[str, ...]) -> None:
        normalized_ref = str(ref or "").strip()
        if not normalized_ref:
            return
        next_path = (*chain, normalized_ref)
        if normalized_ref in chain:
            cycle_start = chain.index(normalized_ref)
            cycle = (*chain[cycle_start:], normalized_ref)
            state.cycles.append(
                {
                    "prompt_set_ref": normalized_ref,
                    "reason": "prompt_set_extends_cycle",
                    "cycle": list(cycle),
                    "path": list(next_path),
                    "resolution": "cycle_parent_edge_skipped",
                }
            )
            return
        if normalized_ref in state.resolved_refs:
            state.duplicate_paths.append(
                {
                    "prompt_set_ref": normalized_ref,
                    "reason": "prompt_set_already_resolved",
                    "path": list(next_path),
                    "resolution": "duplicate_ref_reused_from_first_resolution",
                }
            )
            return
        prompt_set = self._registry.get_prompt_set(normalized_ref)
        if prompt_set is None:
            state.missing_prompt_sets.append(
                {
                    "prompt_set_ref": normalized_ref,
                    "reason": "prompt_set_not_found_or_inactive",
                    "path": list(next_path),
                }
            )
            state.inheritance_graph.setdefault(normalized_ref, ())
            return
        state.inheritance_graph[normalized_ref] = tuple(prompt_set.extends)
        for parent_ref in prompt_set.extends:
            self._visit(parent_ref, state=state, chain=next_path)
        state.resolved_refs.add(normalized_ref)
        state.resolved.append(prompt_set)
        state.resolved_paths.append(next_path)


@dataclass(slots=True)
class _PromptSetResolutionState:
    requested_refs: tuple[str, ...]
    resolved: list[PromptSet] = field(default_factory=list)
    resolved_refs: set[str] = field(default_factory=set)
    inheritance_graph: dict[str, tuple[str, ...]] = field(default_factory=dict)
    resolved_paths: list[tuple[str, ...]] = field(default_factory=list)
    cycles: list[dict[str, Any]] = field(default_factory=list)
    missing_prompt_sets: list[dict[str, Any]] = field(default_factory=list)
    duplicate_paths: list[dict[str, Any]] = field(default_factory=list)


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return tuple(result)


def _digest(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]
