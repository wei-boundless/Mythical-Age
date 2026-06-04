from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .contracts import MemoryContextCandidate, StateMemoryRestoreCandidate
from .layout import durable_memory_namespace_id_for_task_environment
from .runtime_view import MemoryRuntimeView, normalize_memory_layer, normalize_memory_layers


@dataclass(frozen=True, slots=True)
class MemoryRequest:
    request_id: str
    task_id: str
    session_id: str
    agent_id: str
    requested_memory_layers: tuple[str, ...] = ()
    requested_topics: tuple[str, ...] = ()
    task_run_id: str = ""
    graph_id: str = ""
    owner_node_id: str = ""
    node_run_id: str = ""
    run_attempt_id: str = ""
    task_environment_id: str = ""
    turn_environment_snapshot: dict[str, Any] = field(default_factory=dict)
    memory_read_mode: str = "none"
    global_common_allowed: bool = True
    memory_priority: str = "normal"
    allow_long_term_memory: bool = False
    reason: str = ""
    authority: str = "memory_system.memory_request"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["requested_memory_layers"] = list(self.requested_memory_layers)
        payload["requested_topics"] = list(self.requested_topics)
        payload["turn_environment_snapshot"] = dict(self.turn_environment_snapshot)
        return payload


@dataclass(frozen=True, slots=True)
class MemoryScopePolicy:
    policy_id: str
    agent_id: str
    allowed_layers: tuple[str, ...] = ()
    allow_long_term_read: bool = False
    allow_long_term_write: bool = False
    allow_state_restore: bool = True
    allow_working_memory_read: bool = True
    allow_cross_task_memory: bool = False
    writeback_policy: str = "task_default"
    authority: str = "orchestration.memory_scope_policy"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_layers"] = list(self.allowed_layers)
        return payload


@dataclass(frozen=True, slots=True)
class MemoryBundle:
    bundle_id: str
    request_id: str
    session_id: str
    agent_id: str
    runtime_view: MemoryRuntimeView
    context_package: dict[str, Any]
    context_candidates: tuple[MemoryContextCandidate, ...] = ()
    restore_candidates: tuple[StateMemoryRestoreCandidate, ...] = ()
    selected_layers: tuple[str, ...] = ()
    selected_topics: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "memory_system.memory_bundle"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["runtime_view"] = self.runtime_view.to_dict()
        payload["context_candidates"] = [item.to_dict() for item in self.context_candidates]
        payload["restore_candidates"] = [item.to_dict() for item in self.restore_candidates]
        payload["selected_layers"] = list(self.selected_layers)
        payload["selected_topics"] = list(self.selected_topics)
        return payload


@dataclass(slots=True, frozen=True)
class MemoryReadPlan:
    requested_layers: tuple[str, ...] = ()
    allow_long_term: bool = False
    state_read_requested: bool = False
    state_read_mode: str = ""
    requested_topics: tuple[str, ...] = ()
    working_memory_kinds: tuple[str, ...] = ()
    working_memory_semantics: tuple[str, ...] = ()
    working_scope: dict[str, str] = field(default_factory=dict)
    working_limit: int = 20
    note_limit: int = 5
    memory_read_mode: str = "none"
    turn_environment_snapshot: dict[str, Any] = field(default_factory=dict)
    environment_scope: dict[str, Any] = field(default_factory=dict)
    global_common_allowed: bool = True
    main_context: dict[str, Any] = field(default_factory=dict)
    task_summaries: tuple[dict[str, Any], ...] = ()
    session_summary: str = ""
    recently_surfaced_note_ids: tuple[str, ...] = ()
    recent_tools: tuple[str, ...] = ()
    authority: str = "memory_orchestrator.read_plan"

    def wants(self, layer: str) -> bool:
        return normalize_memory_layer(layer) in self.requested_layers

    def diagnostics(self) -> dict[str, Any]:
        working_scope = dict(self.working_scope)
        environment_scope = dict(self.environment_scope)
        return {
            "read_plan_authority": self.authority,
            "requested_memory_layers": list(self.requested_layers),
            "allow_long_term": self.allow_long_term,
            "memory_read_mode": self.memory_read_mode,
            "turn_environment_snapshot": dict(self.turn_environment_snapshot),
            "effective_task_environment_id": environment_scope.get("task_environment_id", ""),
            "read_namespaces": list(environment_scope.get("read_namespaces", ())),
            "environment_scope": environment_scope,
            "global_common_allowed": self.global_common_allowed,
            "state_read_requested": self.state_read_requested,
            "state_read_mode": self.state_read_mode,
            "requested_topics": list(self.requested_topics),
            "session_summary_present": bool(self.session_summary.strip()),
            "task_summary_count": len(self.task_summaries),
            "recent_tool_count": len(self.recent_tools),
            "recently_surfaced_note_count": len(self.recently_surfaced_note_ids),
            "working_memory_task_run_id": working_scope.get("task_run_id", ""),
            "working_memory_scope": {
                "graph_id": working_scope.get("graph_id", ""),
                "owner_node_id": working_scope.get("owner_node_id", ""),
                "node_run_id": working_scope.get("node_run_id", ""),
                "run_attempt_id": working_scope.get("run_attempt_id", ""),
            },
        }


@dataclass(slots=True, frozen=True)
class MemoryCandidatePool:
    conversation_candidates: tuple[MemoryContextCandidate, ...] = ()
    state_candidates: tuple[MemoryContextCandidate, ...] = ()
    working_candidates: tuple[MemoryContextCandidate, ...] = ()
    long_term_candidates: tuple[MemoryContextCandidate, ...] = ()
    restore_candidates: tuple[StateMemoryRestoreCandidate, ...] = ()
    conversation_snapshot: Any | None = None
    state_snapshot: Any | None = None

    @property
    def context_candidates(self) -> tuple[MemoryContextCandidate, ...]:
        return (
            *self.conversation_candidates,
            *self.state_candidates,
            *self.working_candidates,
            *self.long_term_candidates,
        )

    def diagnostics(self) -> dict[str, int]:
        return {
            "conversation_candidate_count": len(self.conversation_candidates),
            "state_candidate_count": len(self.state_candidates),
            "working_candidate_count": len(self.working_candidates),
            "long_term_candidate_count": len(self.long_term_candidates),
            "restore_candidate_count": len(self.restore_candidates),
        }


class MemoryOrchestrator:
    """Builds the explicit read plan for runtime memory supply."""

    def build_read_plan(
        self,
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
        turn_environment_snapshot = _turn_environment_snapshot(profile)
        effective_task_environment_id = _effective_task_environment_id(profile, turn_environment_snapshot)
        global_common_allowed = bool(profile.get("global_common_allowed", True))
        read_namespaces = []
        if effective_task_environment_id:
            read_namespaces.append(durable_memory_namespace_id_for_task_environment(effective_task_environment_id))
        if global_common_allowed:
            read_namespaces.append("global_common")
        memory_read_mode = str(profile.get("memory_read_mode") or ("task_relevant" if "long_term" in requested_layers else "none")).strip()
        return MemoryReadPlan(
            requested_layers=tuple(requested_layers),
            allow_long_term=bool(profile.get("allow_long_term_memory", False)),
            state_read_requested=state_read_requested,
            state_read_mode=str(profile.get("state_read_mode") or ("recall_candidates" if state_read_requested else "")).strip(),
            requested_topics=requested_topics,
            working_memory_kinds=tuple(_normalize_strings(profile.get("working_memory_kinds"))),
            working_memory_semantics=tuple(_normalize_strings(profile.get("working_memory_semantics"))),
            working_scope={
                "task_run_id": str(profile.get("task_run_id") or ""),
                "task_id": str(profile.get("task_id") or ""),
                "graph_id": str(profile.get("graph_id") or ""),
                "owner_node_id": str(profile.get("owner_node_id") or ""),
                "node_run_id": str(profile.get("node_run_id") or ""),
                "run_attempt_id": str(profile.get("run_attempt_id") or ""),
            },
            working_limit=_safe_limit(profile.get("working_memory_limit"), default=20),
            note_limit=effective_note_limit,
            memory_read_mode=memory_read_mode,
            turn_environment_snapshot=turn_environment_snapshot,
            environment_scope={
                "task_environment_id": effective_task_environment_id,
                "environment_kind": str(turn_environment_snapshot.get("environment_kind") or profile.get("environment_kind") or ""),
                "project_id": str(turn_environment_snapshot.get("project_id") or profile.get("project_id") or ""),
                "read_namespaces": tuple(read_namespaces),
            },
            global_common_allowed=global_common_allowed,
            main_context=dict(profile.get("main_context") or {}),
            task_summaries=tuple(
                dict(item)
                for item in list(profile.get("task_summaries") or ())
                if isinstance(item, dict)
            ),
            session_summary=str(profile.get("session_summary") or ""),
            recently_surfaced_note_ids=tuple(_normalize_strings(profile.get("recently_surfaced_note_ids"))),
            recent_tools=tuple(_normalize_strings(profile.get("recent_tools"))),
        )


class MemorySupplier:
    """Fetches memory candidates, but only according to an explicit plan."""

    def fetch_candidates(
        self,
        memory_service: Any,
        *,
        session_id: str,
        plan: MemoryReadPlan,
        query: str | None = None,
        memory_intent: Any | None = None,
        relevant_notes: list[Any] | None = None,
    ) -> MemoryCandidatePool:
        base_candidates = self._base_candidates(memory_service, session_id=session_id, plan=plan)
        long_term_candidates = (
            tuple(
                memory_service.build_long_term_memory_context_candidates(
                    **self._long_term_fetch_kwargs(
                        session_id=session_id,
                        plan=plan,
                        query=query,
                        memory_intent=memory_intent,
                        relevant_notes=relevant_notes,
                    )
                )
            )
            if self._should_fetch_long_term(plan)
            else ()
        )
        return MemoryCandidatePool(
            **base_candidates,
            long_term_candidates=long_term_candidates,
        )

    async def afetch_candidates(
        self,
        memory_service: Any,
        *,
        session_id: str,
        plan: MemoryReadPlan,
        query: str | None = None,
        memory_intent: Any | None = None,
        relevant_notes: list[Any] | None = None,
    ) -> MemoryCandidatePool:
        base_candidates = self._base_candidates(memory_service, session_id=session_id, plan=plan)
        long_term_candidates = (
            tuple(
                await memory_service.abuild_long_term_memory_context_candidates(
                    **self._long_term_fetch_kwargs(
                        session_id=session_id,
                        plan=plan,
                        query=query,
                        memory_intent=memory_intent,
                        relevant_notes=relevant_notes,
                    )
                )
            )
            if self._should_fetch_long_term(plan)
            else ()
        )
        return MemoryCandidatePool(
            **base_candidates,
            long_term_candidates=long_term_candidates,
        )

    def _base_candidates(self, memory_service: Any, *, session_id: str, plan: MemoryReadPlan) -> dict[str, Any]:
        return {
            "conversation_snapshot": memory_service.conversation_memory.load_snapshot(session_id) if plan.wants("conversation") else None,
            "state_snapshot": memory_service.state_memory.load_snapshot(session_id) if plan.state_read_requested else None,
            "conversation_candidates": tuple(memory_service.conversation_memory.context_candidates(session_id)) if plan.wants("conversation") else (),
            "state_candidates": tuple(memory_service.state_memory.context_candidates(session_id)) if plan.state_read_requested else (),
            "working_candidates": tuple(
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
            ) if plan.wants("working") else (),
            "restore_candidates": tuple(memory_service.state_memory.restore_candidates(session_id)) if plan.state_read_requested else (),
        }

    def _should_fetch_long_term(self, plan: MemoryReadPlan) -> bool:
        return plan.allow_long_term and plan.wants("long_term")

    def _long_term_fetch_kwargs(
        self,
        *,
        session_id: str,
        plan: MemoryReadPlan,
        query: str | None,
        memory_intent: Any | None,
        relevant_notes: list[Any] | None,
    ) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "query": query,
            "memory_intent": memory_intent,
            "relevant_notes": relevant_notes,
            "note_limit": plan.note_limit,
            "main_context": plan.main_context,
            "task_summaries": list(plan.task_summaries),
            "session_summary": plan.session_summary,
            "recently_surfaced_note_ids": list(plan.recently_surfaced_note_ids),
            "recent_tools": list(plan.recent_tools),
            "environment_scope": plan.environment_scope,
            "global_common_allowed": plan.global_common_allowed,
        }


def build_memory_runtime_view(
    memory_service: Any,
    *,
    session_id: str,
    query: str | None = None,
    memory_intent: Any | None = None,
    memory_request_profile: dict[str, Any] | None = None,
    relevant_notes: list[Any] | None = None,
    note_limit: int = 5,
    orchestrator: MemoryOrchestrator | None = None,
    supplier: MemorySupplier | None = None,
) -> MemoryRuntimeView:
    read_plan = (orchestrator or MemoryOrchestrator()).build_read_plan(
        memory_request_profile,
        note_limit=note_limit,
    )
    candidate_pool = (supplier or MemorySupplier()).fetch_candidates(
        memory_service,
        session_id=session_id,
        plan=read_plan,
        query=query,
        memory_intent=memory_intent,
        relevant_notes=relevant_notes,
    )
    return _runtime_view_from_candidate_pool(session_id=session_id, read_plan=read_plan, candidate_pool=candidate_pool)


def build_memory_request(
    *,
    task_id: str,
    session_id: str,
    agent_id: str,
    memory_request_profile: dict[str, Any] | None = None,
    reason: str = "",
) -> MemoryRequest:
    profile = dict(memory_request_profile or {})
    requested_layers = normalize_memory_layers(profile.get("requested_memory_layers"))
    requested_topics = _normalize_strings(profile.get("requested_topics"))
    turn_environment_snapshot = _turn_environment_snapshot(profile)
    task_environment_id = _effective_task_environment_id(profile, turn_environment_snapshot)
    return MemoryRequest(
        request_id=f"memreq:{task_id}:{session_id}:{agent_id}",
        task_id=task_id,
        session_id=session_id,
        agent_id=agent_id,
        requested_memory_layers=tuple(requested_layers),
        requested_topics=tuple(requested_topics),
        task_run_id=str(profile.get("task_run_id") or ""),
        graph_id=str(profile.get("graph_id") or ""),
        owner_node_id=str(profile.get("owner_node_id") or ""),
        node_run_id=str(profile.get("node_run_id") or ""),
        run_attempt_id=str(profile.get("run_attempt_id") or ""),
        task_environment_id=task_environment_id,
        turn_environment_snapshot=turn_environment_snapshot,
        memory_read_mode=str(profile.get("memory_read_mode") or ("task_relevant" if "long_term" in requested_layers else "none")),
        global_common_allowed=bool(profile.get("global_common_allowed", True)),
        memory_priority=str(profile.get("memory_priority") or "normal"),
        allow_long_term_memory=bool(profile.get("allow_long_term_memory", False)),
        reason=reason or str(profile.get("memory_scope_hint") or ""),
    )


def build_memory_scope_policy(
    *,
    agent_id: str,
    memory_request_profile: dict[str, Any] | None = None,
) -> MemoryScopePolicy:
    profile = dict(memory_request_profile or {})
    allowed_layers = normalize_memory_layers(profile.get("requested_memory_layers"))
    allow_long_term = bool(profile.get("allow_long_term_memory", False)) or "long_term" in allowed_layers
    return MemoryScopePolicy(
        policy_id=f"memscope:{agent_id}",
        agent_id=agent_id,
        allowed_layers=tuple(allowed_layers),
        allow_long_term_read=allow_long_term,
        allow_long_term_write=False,
        allow_state_restore="state" in allowed_layers,
        allow_working_memory_read="working" in allowed_layers,
        allow_cross_task_memory=False,
        writeback_policy=str(profile.get("writeback_policy") or "task_default"),
    )


async def abuild_memory_runtime_view(
    memory_service: Any,
    *,
    session_id: str,
    query: str | None = None,
    memory_intent: Any | None = None,
    memory_request_profile: dict[str, Any] | None = None,
    relevant_notes: list[Any] | None = None,
    note_limit: int = 5,
    orchestrator: MemoryOrchestrator | None = None,
    supplier: MemorySupplier | None = None,
) -> MemoryRuntimeView:
    read_plan = (orchestrator or MemoryOrchestrator()).build_read_plan(
        memory_request_profile,
        note_limit=note_limit,
    )
    candidate_pool = await (supplier or MemorySupplier()).afetch_candidates(
        memory_service,
        session_id=session_id,
        plan=read_plan,
        query=query,
        memory_intent=memory_intent,
        relevant_notes=relevant_notes,
    )
    return _runtime_view_from_candidate_pool(session_id=session_id, read_plan=read_plan, candidate_pool=candidate_pool)


def _runtime_view_from_candidate_pool(
    *,
    session_id: str,
    read_plan: MemoryReadPlan,
    candidate_pool: MemoryCandidatePool,
) -> MemoryRuntimeView:
    return MemoryRuntimeView(
        view_id=f"memory-runtime:{session_id or 'default'}",
        session_id=session_id,
        conversation_snapshot=candidate_pool.conversation_snapshot,
        state_snapshot=candidate_pool.state_snapshot,
        context_candidates=candidate_pool.context_candidates,
        restore_candidates=candidate_pool.restore_candidates,
        read_only=True,
        memory_write_allowed=False,
        diagnostics={
            **candidate_pool.diagnostics(),
            "memory_write_allowed": False,
            "read_plan": read_plan.diagnostics(),
            **read_plan.diagnostics(),
        },
    )


def apply_memory_scope_policy(request: MemoryRequest, scope_policy: MemoryScopePolicy) -> MemoryRequest:
    allowed = set(scope_policy.allowed_layers)
    requested_layers = [layer for layer in request.requested_memory_layers if layer in allowed]
    allow_long_term = request.allow_long_term_memory and scope_policy.allow_long_term_read
    if not allow_long_term:
        requested_layers = [layer for layer in requested_layers if layer != "long_term"]
    if not scope_policy.allow_working_memory_read:
        requested_layers = [layer for layer in requested_layers if layer != "working"]
    return MemoryRequest(
        request_id=request.request_id,
        task_id=request.task_id,
        session_id=request.session_id,
        agent_id=request.agent_id,
        requested_memory_layers=tuple(requested_layers),
        requested_topics=request.requested_topics,
        task_run_id=request.task_run_id,
        graph_id=request.graph_id,
        owner_node_id=request.owner_node_id,
        node_run_id=request.node_run_id,
        run_attempt_id=request.run_attempt_id,
        task_environment_id=request.task_environment_id,
        turn_environment_snapshot=dict(request.turn_environment_snapshot),
        memory_read_mode=request.memory_read_mode,
        global_common_allowed=request.global_common_allowed,
        memory_priority=request.memory_priority,
        allow_long_term_memory=allow_long_term,
        reason=request.reason,
    )


def build_memory_bundle(
    *,
    request: MemoryRequest,
    runtime_view: MemoryRuntimeView,
    context_policy_result: Any | None = None,
) -> MemoryBundle:
    context_package = {}
    diagnostics = {
        "memory_runtime_view_ref": runtime_view.view_id,
        "context_candidate_count": len(runtime_view.context_candidates),
        "restore_candidate_count": len(runtime_view.restore_candidates),
        "selected_layer_count": len(request.requested_memory_layers),
    }
    if context_policy_result is not None:
        context_package = context_policy_result.to_dict() if hasattr(context_policy_result, "to_dict") else dict(context_policy_result)
        diagnostics["context_policy_attached"] = True
    else:
        diagnostics["context_policy_attached"] = False
    return MemoryBundle(
        bundle_id=f"membundle:{request.task_id}:{request.session_id}:{request.agent_id}",
        request_id=request.request_id,
        session_id=request.session_id,
        agent_id=request.agent_id,
        runtime_view=runtime_view,
        context_package=context_package,
        context_candidates=tuple(runtime_view.context_candidates),
        restore_candidates=tuple(runtime_view.restore_candidates),
        selected_layers=request.requested_memory_layers,
        selected_topics=request.requested_topics,
        diagnostics=diagnostics,
    )


def build_memory_read_plan(
    memory_request_profile: dict[str, Any] | None,
    *,
    note_limit: int = 5,
) -> MemoryReadPlan:
    return MemoryOrchestrator().build_read_plan(memory_request_profile, note_limit=note_limit)


def _turn_environment_snapshot(profile: dict[str, Any]) -> dict[str, Any]:
    snapshot = profile.get("turn_environment_snapshot")
    payload = dict(snapshot) if isinstance(snapshot, dict) else {}
    task_environment = profile.get("task_environment")
    if isinstance(task_environment, dict):
        payload.setdefault(
            "task_environment_id",
            task_environment.get("task_environment_id") or task_environment.get("environment_id") or "",
        )
        payload.setdefault("environment_kind", task_environment.get("environment_kind") or task_environment.get("kind") or "")
        payload.setdefault("project_id", task_environment.get("project_id") or "")
    payload.setdefault("task_environment_id", profile.get("task_environment_id") or profile.get("environment_id") or "")
    payload.setdefault("environment_kind", profile.get("environment_kind") or "")
    payload.setdefault("project_id", profile.get("project_id") or "")
    return {str(key): str(value or "") for key, value in payload.items() if str(value or "").strip()}


def _effective_task_environment_id(profile: dict[str, Any], snapshot: dict[str, Any]) -> str:
    return str(
        snapshot.get("task_environment_id")
        or snapshot.get("environment_id")
        or profile.get("task_environment_id")
        or profile.get("environment_id")
        or ""
    ).strip()


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


