from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ContextCandidate:
    candidate_id: str
    kind: str
    source: str
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["payload"] = dict(self.payload or {})
        return payload


@dataclass(frozen=True, slots=True)
class ContextCandidates:
    candidates_id: str
    candidates: tuple[ContextCandidate, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "agent_runtime.context_candidates"

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates_id": self.candidates_id,
            "candidates": [item.to_dict() for item in self.candidates],
            "diagnostics": dict(self.diagnostics or {}),
            "authority": self.authority,
        }


def build_context_candidates(
    *,
    request_facts: dict[str, Any],
    continuation_candidates: list[Any] | None = None,
    memory_runtime_view: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
) -> ContextCandidates:
    facts = dict(request_facts or {})
    candidates: list[ContextCandidate] = []
    for index, item in enumerate(list(continuation_candidates or []), start=1):
        payload = item.to_dict() if hasattr(item, "to_dict") else dict(item or {})
        candidates.append(
            ContextCandidate(
                candidate_id=str(payload.get("candidate_id") or f"context-candidate:continuation:{index}"),
                kind="continuation",
                source="continuation_candidate_collector",
                summary=str(payload.get("summary") or payload.get("title") or ""),
                payload=payload,
                confidence=float(payload.get("confidence") or 0.0),
            )
        )
    memory = dict(memory_runtime_view or {})
    if memory:
        candidates.append(
            ContextCandidate(
                candidate_id=str(memory.get("view_id") or "context-candidate:memory"),
                kind="memory_runtime_view",
                source="memory_facade",
                summary="Memory runtime view is available.",
                payload=memory,
                confidence=0.5,
            )
        )
    current = dict(current_turn_context or {})
    selected_task = str(current.get("selected_task_id") or current.get("task_id") or current.get("specific_task_id") or "").strip()
    if selected_task:
        candidates.append(
            ContextCandidate(
                candidate_id=f"context-candidate:selected-task:{selected_task}",
                kind="explicit_task_selection",
                source="current_turn_context",
                summary=f"Explicit selected task: {selected_task}",
                payload={"selected_task_id": selected_task},
                confidence=1.0,
            )
        )
    return ContextCandidates(
        candidates_id=f"context-candidates:{facts.get('facts_id') or 'runtime'}",
        candidates=tuple(candidates),
        diagnostics={"candidate_only": True, "does_not_decide_current_turn": True},
    )
