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
    "task_durable": "task_durable",
    "task_durable_memory": "task_durable",
    "long_term": "long_term",
    "durable": "long_term",
}
VALID_MEMORY_LAYERS: tuple[str, ...] = ("conversation", "state", "working", "task_durable", "long_term")


@dataclass(slots=True, frozen=True)
class MemoryReadPlan:
    requested_layers: tuple[str, ...] = ()
    allow_long_term: bool = False
    state_read_requested: bool = False
    state_read_mode: str = ""
    requested_topics: tuple[str, ...] = ()
    working_memory_kinds: tuple[str, ...] = ()
    working_memory_semantics: tuple[str, ...] = ()
    task_durable_kinds: tuple[str, ...] = ()
    task_durable_semantics: tuple[str, ...] = ()
    working_scope: dict[str, str] = field(default_factory=dict)
    task_durable_scope: dict[str, str] = field(default_factory=dict)
    working_limit: int = 20
    task_durable_limit: int = 20
    note_limit: int = 5

    def wants(self, layer: str) -> bool:
        return normalize_memory_layer(layer) in self.requested_layers

    def diagnostics(self) -> dict[str, Any]:
        return {
            "requested_memory_layers": list(self.requested_layers),
            "state_read_requested": self.state_read_requested,
            "state_read_mode": self.state_read_mode,
            "requested_topics": list(self.requested_topics),
            "working_memory_task_run_id": self.working_scope["task_run_id"],
            "working_memory_scope": {
                "graph_id": self.working_scope["graph_id"],
                "owner_node_id": self.working_scope["owner_node_id"],
                "node_run_id": self.working_scope["node_run_id"],
                "run_attempt_id": self.working_scope["run_attempt_id"],
            },
            "task_durable_memory_scope": dict(self.task_durable_scope),
        }


@dataclass(slots=True, frozen=True)
class MemoryRuntimeView:
    """Read-only runtime view consumed by orchestration/context policy."""

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


def build_memory_runtime_view(
    memory_service: Any,
    *,
    session_id: str,
    query: str | None = None,
    memory_intent: Any | None = None,
    memory_request_profile: dict[str, Any] | None = None,
    relevant_notes: list[Any] | None = None,
    note_limit: int = 5,
) -> MemoryRuntimeView:
    plan = build_memory_read_plan(memory_request_profile, note_limit=note_limit)
    conversation_snapshot = memory_service.conversation_memory.load_snapshot(session_id) if plan.wants("conversation") else None
    state_snapshot = memory_service.state_memory.load_snapshot(session_id) if plan.state_read_requested else None
    conversation_candidates = (
        tuple(memory_service.conversation_memory.context_candidates(session_id))
        if plan.wants("conversation")
        else ()
    )
    state_candidates = (
        tuple(memory_service.state_memory.context_candidates(session_id))
        if plan.state_read_requested
        else ()
    )
    working_candidates = (
        tuple(
            memory_service.working_memory.context_candidates(
                task_run_id=plan.working_scope["task_run_id"],
                task_id=plan.working_scope["task_id"],
                graph_id=plan.working_scope["graph_id"],
                owner_node_id=plan.working_scope["owner_node_id"],
                node_run_id=plan.working_scope["node_run_id"],
                run_attempt_id=plan.working_scope["run_attempt_id"],
                requested_kinds=plan.working_memory_kinds,
                requested_semantics=plan.working_memory_semantics,
                limit=plan.working_limit,
            )
        )
        if plan.wants("working")
        else ()
    )
    task_durable_candidates = (
        tuple(
            memory_service.task_durable_memory.context_candidates(
                namespace_id=plan.task_durable_scope["namespace_id"],
                domain_id=plan.task_durable_scope["domain_id"],
                task_id=plan.task_durable_scope["task_id"],
                graph_id=plan.task_durable_scope["graph_id"],
                project_id=plan.task_durable_scope["project_id"],
                artifact_namespace=plan.task_durable_scope["artifact_namespace"],
                requested_kinds=plan.task_durable_kinds,
                requested_semantics=plan.task_durable_semantics,
                limit=plan.task_durable_limit,
            )
        )
        if plan.wants("task_durable") and memory_service.task_durable_memory is not None
        else ()
    )
    restore_candidates = (
        tuple(memory_service.state_memory.restore_candidates(session_id))
        if plan.state_read_requested
        else ()
    )
    long_term_candidates = (
        tuple(
            memory_service.build_long_term_memory_context_candidates(
            session_id=session_id,
            query=query,
            memory_intent=memory_intent,
            relevant_notes=relevant_notes,
            note_limit=plan.note_limit,
        )
        )
        if plan.allow_long_term and plan.wants("long_term")
        else ()
    )
    context_candidates = (*conversation_candidates, *state_candidates, *working_candidates, *task_durable_candidates, *long_term_candidates)
    return MemoryRuntimeView(
        view_id=f"memory-runtime:{session_id or 'default'}",
        session_id=session_id,
        conversation_snapshot=conversation_snapshot,
        state_snapshot=state_snapshot,
        context_candidates=context_candidates,
        restore_candidates=restore_candidates,
        read_only=True,
        memory_write_allowed=False,
        diagnostics={
            "conversation_candidate_count": len(conversation_candidates),
            "state_candidate_count": len(state_candidates),
            "working_candidate_count": len(working_candidates),
            "task_durable_candidate_count": len(task_durable_candidates),
            "long_term_candidate_count": len(long_term_candidates),
            "restore_candidate_count": len(restore_candidates),
            "memory_write_allowed": False,
            **plan.diagnostics(),
        },
    )


def build_memory_read_plan(
    memory_request_profile: dict[str, Any] | None,
    *,
    note_limit: int = 5,
) -> MemoryReadPlan:
    profile = dict(memory_request_profile or {})
    requested_layers = normalize_memory_layers(profile.get("requested_memory_layers"))
    requested_topics = tuple(_normalize_strings(profile.get("requested_topics")))
    effective_note_limit = int(note_limit or 5)
    if requested_topics:
        effective_note_limit = max(effective_note_limit, min(len(requested_topics) + 2, 8))
    state_read_requested = "state" in requested_layers
    return MemoryReadPlan(
        requested_layers=tuple(requested_layers),
        allow_long_term=bool(profile.get("allow_long_term_memory", False)),
        state_read_requested=state_read_requested,
        state_read_mode=str(profile.get("state_read_mode") or ("recall_candidates" if state_read_requested else "")).strip(),
        requested_topics=requested_topics,
        working_memory_kinds=tuple(_normalize_strings(profile.get("working_memory_kinds"))),
        working_memory_semantics=tuple(_normalize_strings(profile.get("working_memory_semantics"))),
        task_durable_kinds=tuple(
            _normalize_strings(profile.get("task_durable_memory_kinds") or profile.get("task_durable_kinds"))
        ),
        task_durable_semantics=tuple(
            _normalize_strings(profile.get("task_durable_memory_semantics") or profile.get("task_durable_semantics"))
        ),
        working_scope={
            "task_run_id": str(profile.get("task_run_id") or ""),
            "task_id": str(profile.get("task_id") or ""),
            "graph_id": str(profile.get("graph_id") or ""),
            "owner_node_id": str(profile.get("owner_node_id") or ""),
            "node_run_id": str(profile.get("node_run_id") or ""),
            "run_attempt_id": str(profile.get("run_attempt_id") or ""),
        },
        task_durable_scope={
            "namespace_id": str(profile.get("task_durable_namespace_id") or profile.get("namespace_id") or ""),
            "domain_id": str(profile.get("domain_id") or ""),
            "task_id": str(profile.get("task_id") or ""),
            "graph_id": str(profile.get("graph_id") or ""),
            "project_id": str(profile.get("project_id") or ""),
            "artifact_namespace": str(profile.get("artifact_namespace") or ""),
        },
        working_limit=_safe_limit(profile.get("working_memory_limit"), default=20),
        task_durable_limit=_safe_limit(profile.get("task_durable_memory_limit") or profile.get("task_durable_limit"), default=20),
        note_limit=effective_note_limit,
    )


def normalize_memory_layer(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
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


def _normalize_strings(values: Any) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in list(values or ()):
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _safe_limit(value: Any, *, default: int) -> int:
    try:
        return max(1, min(int(value or default), 1000))
    except (TypeError, ValueError):
        return default
