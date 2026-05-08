from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .contracts import MemoryContextCandidate, MemoryWriteCandidate, StateMemoryRestoreCandidate
from .runtime_view import MemoryRuntimeView


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
    memory_priority: str = "normal"
    allow_long_term_memory: bool = False
    reason: str = ""
    authority: str = "memory_system.memory_request"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["requested_memory_layers"] = list(self.requested_memory_layers)
        payload["requested_topics"] = list(self.requested_topics)
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
    allow_task_durable_memory_read: bool = False
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


@dataclass(frozen=True, slots=True)
class MemoryWritebackProposal:
    proposal_id: str
    session_id: str
    task_id: str
    target_layers: tuple[str, ...] = ()
    write_candidates: tuple[MemoryWriteCandidate, ...] = ()
    adopted: bool = False
    authority: str = "memory_system.memory_writeback_proposal"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.adopted:
            raise ValueError("MemoryWritebackProposal cannot self-adopt")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["target_layers"] = list(self.target_layers)
        payload["write_candidates"] = [item.to_dict() for item in self.write_candidates]
        return payload


def build_memory_request(
    *,
    task_id: str,
    session_id: str,
    agent_id: str,
    memory_request_profile: dict[str, Any] | None = None,
    reason: str = "",
) -> MemoryRequest:
    profile = dict(memory_request_profile or {})
    requested_layers = _normalize_strings(profile.get("requested_memory_layers"))
    requested_topics = _normalize_strings(profile.get("requested_topics"))
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
    allowed_layers = _normalize_strings(profile.get("requested_memory_layers")) or ["conversation", "state"]
    allow_long_term = bool(profile.get("allow_long_term_memory", False)) or "long_term" in allowed_layers
    allow_task_durable = "task_durable" in allowed_layers or "task_durable_memory" in allowed_layers
    return MemoryScopePolicy(
        policy_id=f"memscope:{agent_id}",
        agent_id=agent_id,
        allowed_layers=tuple(allowed_layers),
        allow_long_term_read=allow_long_term,
        allow_long_term_write=False,
        allow_state_restore="state" in allowed_layers or not allowed_layers,
        allow_working_memory_read="working" in allowed_layers or not allowed_layers,
        allow_task_durable_memory_read=allow_task_durable,
        allow_cross_task_memory=False,
        writeback_policy=str(profile.get("writeback_policy") or "task_default"),
    )


def apply_memory_scope_policy(request: MemoryRequest, scope_policy: MemoryScopePolicy) -> MemoryRequest:
    allowed = set(scope_policy.allowed_layers)
    requested_layers = [layer for layer in request.requested_memory_layers if layer in allowed]
    allow_long_term = request.allow_long_term_memory and scope_policy.allow_long_term_read
    if not allow_long_term:
        requested_layers = [layer for layer in requested_layers if layer != "long_term"]
    if not scope_policy.allow_working_memory_read:
        requested_layers = [layer for layer in requested_layers if layer != "working"]
    if not scope_policy.allow_task_durable_memory_read:
        requested_layers = [layer for layer in requested_layers if layer not in {"task_durable", "task_durable_memory"}]
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


def build_memory_writeback_proposal(
    *,
    session_id: str,
    task_id: str,
    write_candidates: list[MemoryWriteCandidate] | tuple[MemoryWriteCandidate, ...] | None = None,
) -> MemoryWritebackProposal:
    candidates = tuple(write_candidates or ())
    target_layers = tuple(_normalize_strings([candidate.target_layer for candidate in candidates]))
    return MemoryWritebackProposal(
        proposal_id=f"memwrite:{task_id}:{session_id}",
        session_id=session_id,
        task_id=task_id,
        target_layers=target_layers,
        write_candidates=candidates,
        adopted=False,
        diagnostics={
            "write_candidate_count": len(candidates),
            "candidate_only": True,
        },
    )


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
