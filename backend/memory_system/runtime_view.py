from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .contracts import (
    ConversationMemorySnapshot,
    LongTermMemoryRecord,
    MemoryContextCandidate,
    MemoryWriteCandidate,
    StateMemoryRestoreCandidate,
    StateMemorySnapshot,
)


@dataclass(slots=True, frozen=True)
class MemoryRuntimeView:
    """Read-only runtime view consumed by orchestration/context policy."""

    view_id: str
    session_id: str
    conversation_snapshot: ConversationMemorySnapshot | None = None
    state_snapshot: StateMemorySnapshot | None = None
    long_term_records: tuple[LongTermMemoryRecord, ...] = ()
    context_candidates: tuple[MemoryContextCandidate, ...] = ()
    restore_candidates: tuple[StateMemoryRestoreCandidate, ...] = ()
    write_candidates: tuple[MemoryWriteCandidate, ...] = ()
    preview_only: bool = True
    memory_write_allowed: bool = False
    authority: str = "memory_runtime_view"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.preview_only:
            raise ValueError("MemoryRuntimeView must remain preview_only")
        if self.memory_write_allowed:
            raise ValueError("MemoryRuntimeView cannot allow memory writes")
        for candidate in self.context_candidates:
            if candidate.can_override_current_turn:
                raise ValueError("MemoryRuntimeView cannot expose overriding context candidates")
        for candidate in self.restore_candidates:
            if candidate.can_promote_to_current_fact:
                raise ValueError("MemoryRuntimeView cannot expose self-promoting restore candidates")
        for candidate in self.write_candidates:
            if candidate.authority != "candidate_only":
                raise ValueError("MemoryRuntimeView only accepts candidate-only write candidates")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["conversation_snapshot"] = (
            self.conversation_snapshot.to_dict() if self.conversation_snapshot is not None else None
        )
        payload["state_snapshot"] = self.state_snapshot.to_dict() if self.state_snapshot is not None else None
        payload["long_term_records"] = [item.to_dict() for item in self.long_term_records]
        payload["context_candidates"] = [item.to_dict() for item in self.context_candidates]
        payload["restore_candidates"] = [item.to_dict() for item in self.restore_candidates]
        payload["write_candidates"] = [item.to_dict() for item in self.write_candidates]
        return payload


def build_memory_runtime_view(
    memory_facade: Any,
    *,
    session_id: str,
    query: str | None = None,
    memory_intent: Any | None = None,
    relevant_notes: list[Any] | None = None,
    note_limit: int = 5,
) -> MemoryRuntimeView:
    conversation_snapshot = _call(memory_facade, "build_conversation_memory_snapshot", session_id)
    state_snapshot = _call(memory_facade, "build_state_memory_snapshot", session_id)
    conversation_candidates = tuple(_call(memory_facade, "build_conversation_memory_context_candidates", session_id) or ())
    state_candidates = tuple(_call(memory_facade, "build_state_memory_context_candidates", session_id) or ())
    restore_candidates = tuple(_call(memory_facade, "build_state_memory_restore_candidates", session_id) or ())
    long_term_records = tuple(_call_kwargs(memory_facade, "build_long_term_memory_records", limit=note_limit) or ())
    long_term_candidates = tuple(
        _call_kwargs(
            memory_facade,
            "build_long_term_memory_context_candidates",
            session_id=session_id,
            query=query,
            memory_intent=memory_intent,
            relevant_notes=relevant_notes,
            note_limit=note_limit,
        )
        or ()
    )
    context_candidates = (*conversation_candidates, *state_candidates, *long_term_candidates)
    return MemoryRuntimeView(
        view_id=f"memory-runtime:{session_id or 'default'}",
        session_id=session_id,
        conversation_snapshot=conversation_snapshot,
        state_snapshot=state_snapshot,
        long_term_records=long_term_records,
        context_candidates=context_candidates,
        restore_candidates=restore_candidates,
        write_candidates=(),
        preview_only=True,
        memory_write_allowed=False,
        diagnostics={
            "conversation_candidate_count": len(conversation_candidates),
            "state_candidate_count": len(state_candidates),
            "long_term_candidate_count": len(long_term_candidates),
            "restore_candidate_count": len(restore_candidates),
            "long_term_record_count": len(long_term_records),
            "memory_write_allowed": False,
        },
    )


def _call(target: Any, method_name: str, *args: Any) -> Any:
    method = getattr(target, method_name, None)
    if not callable(method):
        return None
    return method(*args)


def _call_kwargs(target: Any, method_name: str, **kwargs: Any) -> Any:
    method = getattr(target, method_name, None)
    if not callable(method):
        return None
    return method(**kwargs)
