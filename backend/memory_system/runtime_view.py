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
    memory_request_profile: dict[str, Any] | None = None,
    relevant_notes: list[Any] | None = None,
    note_limit: int = 5,
) -> MemoryRuntimeView:
    profile = dict(memory_request_profile or {})
    profile_provided = bool(profile)
    requested_layers = {
        str(item).strip()
        for item in list(profile.get("requested_memory_layers") or [])
        if str(item).strip()
    }
    allow_long_term = bool(profile.get("allow_long_term_memory", False)) or not profile_provided
    requested_topics = [
        str(item).strip()
        for item in list(profile.get("requested_topics") or [])
        if str(item).strip()
    ]
    requested_kinds = [
        str(item).strip()
        for item in list(profile.get("working_memory_kinds") or [])
        if str(item).strip()
    ]
    requested_semantics = [
        str(item).strip()
        for item in list(profile.get("working_memory_semantics") or [])
        if str(item).strip()
    ]
    task_durable_kinds = [
        str(item).strip()
        for item in list(profile.get("task_durable_memory_kinds") or profile.get("task_durable_kinds") or [])
        if str(item).strip()
    ]
    task_durable_semantics = [
        str(item).strip()
        for item in list(profile.get("task_durable_memory_semantics") or profile.get("task_durable_semantics") or [])
        if str(item).strip()
    ]
    effective_note_limit = int(note_limit or 5)
    if requested_topics:
        effective_note_limit = max(effective_note_limit, min(len(requested_topics) + 2, 8))
    conversation_snapshot = _call(memory_facade, "build_conversation_memory_snapshot", session_id)
    state_snapshot = _call(memory_facade, "build_state_memory_snapshot", session_id)
    conversation_candidates = tuple(_call(memory_facade, "build_conversation_memory_context_candidates", session_id) or ()) if "conversation" in requested_layers else ()
    state_candidates = tuple(_call(memory_facade, "build_state_memory_context_candidates", session_id) or ()) if not requested_layers or "state" in requested_layers else ()
    working_candidates = tuple(
        _call_kwargs(
            memory_facade,
            "build_working_memory_context_candidates",
            task_run_id=str(profile.get("task_run_id") or ""),
            task_id=str(profile.get("task_id") or ""),
            graph_id=str(profile.get("graph_id") or ""),
            owner_node_id=str(profile.get("owner_node_id") or ""),
            node_run_id=str(profile.get("node_run_id") or ""),
            run_attempt_id=str(profile.get("run_attempt_id") or ""),
            requested_kinds=requested_kinds,
            requested_semantics=requested_semantics,
            limit=int(profile.get("working_memory_limit") or 20),
        )
        or ()
    ) if ("working" in requested_layers or not requested_layers) else ()
    task_durable_candidates = tuple(
        _call_kwargs(
            memory_facade,
            "build_task_durable_memory_context_candidates",
            namespace_id=str(profile.get("task_durable_namespace_id") or profile.get("namespace_id") or ""),
            task_family=str(profile.get("task_family") or ""),
            domain_id=str(profile.get("domain_id") or ""),
            task_id=str(profile.get("task_id") or ""),
            graph_id=str(profile.get("graph_id") or ""),
            project_id=str(profile.get("project_id") or ""),
            artifact_namespace=str(profile.get("artifact_namespace") or ""),
            requested_kinds=task_durable_kinds,
            requested_semantics=task_durable_semantics,
            limit=int(profile.get("task_durable_memory_limit") or profile.get("task_durable_limit") or 20),
        )
        or ()
    ) if ("task_durable" in requested_layers or "task_durable_memory" in requested_layers) else ()
    restore_candidates = tuple(_call(memory_facade, "build_state_memory_restore_candidates", session_id) or ()) if not requested_layers or "state" in requested_layers else ()
    long_term_records = tuple(
        _call_kwargs(memory_facade, "build_long_term_memory_records", limit=effective_note_limit) or ()
    ) if allow_long_term and ("long_term" in requested_layers or not requested_layers) else ()
    long_term_candidates = tuple(
        _call_kwargs(
            memory_facade,
            "build_long_term_memory_context_candidates",
            session_id=session_id,
            query=query,
            memory_intent=memory_intent,
            relevant_notes=relevant_notes,
            note_limit=effective_note_limit,
        )
        or ()
    ) if allow_long_term and ("long_term" in requested_layers or not requested_layers) else ()
    context_candidates = (*conversation_candidates, *state_candidates, *working_candidates, *task_durable_candidates, *long_term_candidates)
    return MemoryRuntimeView(
        view_id=f"memory-runtime:{session_id or 'default'}",
        session_id=session_id,
        conversation_snapshot=conversation_snapshot,
        state_snapshot=state_snapshot,
        long_term_records=long_term_records,
        context_candidates=context_candidates,
        restore_candidates=restore_candidates,
        write_candidates=(),
        read_only=True,
        memory_write_allowed=False,
        diagnostics={
            "conversation_candidate_count": len(conversation_candidates),
            "state_candidate_count": len(state_candidates),
            "working_candidate_count": len(working_candidates),
            "task_durable_candidate_count": len(task_durable_candidates),
            "long_term_candidate_count": len(long_term_candidates),
            "restore_candidate_count": len(restore_candidates),
            "long_term_record_count": len(long_term_records),
            "memory_write_allowed": False,
            "requested_memory_layers": list(requested_layers),
            "requested_topics": requested_topics,
            "working_memory_task_run_id": str(profile.get("task_run_id") or ""),
            "working_memory_scope": {
                "graph_id": str(profile.get("graph_id") or ""),
                "owner_node_id": str(profile.get("owner_node_id") or ""),
                "node_run_id": str(profile.get("node_run_id") or ""),
                "run_attempt_id": str(profile.get("run_attempt_id") or ""),
            },
            "task_durable_memory_scope": {
                "namespace_id": str(profile.get("task_durable_namespace_id") or profile.get("namespace_id") or ""),
                "task_family": str(profile.get("task_family") or ""),
                "domain_id": str(profile.get("domain_id") or ""),
                "task_id": str(profile.get("task_id") or ""),
                "graph_id": str(profile.get("graph_id") or ""),
                "project_id": str(profile.get("project_id") or ""),
                "artifact_namespace": str(profile.get("artifact_namespace") or ""),
            },
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
