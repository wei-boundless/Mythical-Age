from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .adoption import AdoptionCandidate
from .directives import RuntimeDirectiveCandidate
from .execution_graph import CommitCandidate, CommitType
from .graph_preview import ExecutionGraphPreview
from .plan import OrchestrationPlanPreview


DEFAULT_COMMIT_TYPES: tuple[CommitType, ...] = (
    "session_message",
    "session_memory",
    "durable_memory",
    "task_result",
    "artifact_graph",
    "title",
)


@dataclass(slots=True, frozen=True)
class CommitGatePreview:
    """Preview-only writeback gate.

    This is the final fail-closed boundary before any future session, memory,
    task, artifact, or title writeback. It records denied writeback lanes but
    never grants commit authority.
    """

    gate_id: str
    task_id: str
    plan_ref: str
    execution_graph_preview_ref: str
    adoption_candidate_ref: str
    directive_candidate_refs: tuple[str, ...] = ()
    commit_candidates: tuple[CommitCandidate, ...] = ()
    status: str = "blocked"
    reason: str = "preview_only"
    commit_allowed: bool = False
    preview_only: bool = True
    runtime_executable: bool = False
    authority: str = "commit_gate_preview"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != "commit_gate_preview":
            raise ValueError("CommitGatePreview cannot carry commit authority")
        if self.status != "blocked":
            raise ValueError("CommitGatePreview must stay blocked")
        if self.commit_allowed:
            raise ValueError("CommitGatePreview cannot allow commits")
        if not self.preview_only:
            raise ValueError("CommitGatePreview must remain preview_only")
        if self.runtime_executable:
            raise ValueError("CommitGatePreview cannot be runtime executable")
        for candidate in self.commit_candidates:
            if candidate.allowed:
                raise ValueError("CommitGatePreview only accepts denied commit candidates")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["directive_candidate_refs"] = list(self.directive_candidate_refs)
        payload["commit_candidates"] = [candidate.to_dict() for candidate in self.commit_candidates]
        return payload


@dataclass(slots=True, frozen=True)
class RuntimeCommitGateDecision:
    gate_id: str
    commit_type: CommitType
    commit_candidate: CommitCandidate
    status: str
    reason: str
    commit_allowed: bool = False
    authority: str = "runtime_commit_gate"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != "runtime_commit_gate":
            raise ValueError("RuntimeCommitGateDecision authority must be runtime_commit_gate")
        if self.commit_allowed and self.status != "allowed":
            raise ValueError("Allowed runtime commits must use status=allowed")
        if not self.commit_allowed and self.status == "allowed":
            raise ValueError("Blocked runtime commits cannot use status=allowed")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["commit_candidate"] = self.commit_candidate.to_dict()
        return payload


def build_blocked_commit_gate_preview(
    *,
    plan: OrchestrationPlanPreview,
    graph_preview: ExecutionGraphPreview,
    adoption_candidate: AdoptionCandidate,
    directive_candidates: tuple[RuntimeDirectiveCandidate, ...],
    commit_types: tuple[CommitType, ...] = DEFAULT_COMMIT_TYPES,
) -> CommitGatePreview:
    directive_refs = tuple(candidate.directive_candidate_id for candidate in directive_candidates)
    commit_candidates = tuple(
        CommitCandidate(
            candidate_id=f"commit-candidate:{plan.task_id}:{commit_type}:blocked",
            commit_type=commit_type,
            payload={},
            producer="orchestration.commit_gate_preview",
            allowed=False,
            reason="preview_only",
            refs={
                "plan_ref": plan.plan_id,
                "execution_graph_preview_ref": graph_preview.graph_preview_id,
                "adoption_candidate_ref": adoption_candidate.candidate_id,
                "runtime_directive_enabled": False,
                "runtime_executable": False,
            },
        )
        for commit_type in commit_types
    )
    return CommitGatePreview(
        gate_id=f"commit-gate:{plan.task_id}:preview",
        task_id=plan.task_id,
        plan_ref=plan.plan_id,
        execution_graph_preview_ref=graph_preview.graph_preview_id,
        adoption_candidate_ref=adoption_candidate.candidate_id,
        directive_candidate_refs=directive_refs,
        commit_candidates=commit_candidates,
        status="blocked",
        reason="preview_only",
        commit_allowed=False,
        preview_only=True,
        runtime_executable=False,
        diagnostics={
            "preview_only": True,
            "fail_closed": True,
            "commit_candidate_count": len(commit_candidates),
            "commit_allowed": False,
            "writeback_allowed": False,
            "session_write_allowed": False,
            "memory_write_allowed": False,
            "artifact_write_allowed": False,
            "task_result_write_allowed": False,
            "title_write_allowed": False,
            "runtime_directive_enabled": False,
            "runtime_executable": False,
        },
    )


def build_blocked_runtime_commit_gate(
    *,
    task_id: str,
    plan_ref: str,
    execution_graph_ref: str = "",
    directive_ref: str = "",
    output_response: Any | None = None,
) -> CommitGatePreview:
    canonical_answer = str(getattr(output_response, "canonical_answer", "") or "").strip()
    selected_channel = str(getattr(output_response, "selected_channel", "") or "")
    selected_source = str(getattr(output_response, "selected_source", "") or "")
    persist_policy = str(getattr(output_response, "persist_policy", "") or "do_not_persist")
    commit_candidates = (
        CommitCandidate(
            candidate_id=f"commit-candidate:{task_id}:session_message:runtime-blocked",
            commit_type="session_message",
            payload={
                "role": "assistant",
                "content": canonical_answer,
                "answer_channel": selected_channel,
                "answer_source": selected_source,
                "persist_policy": persist_policy,
            },
            producer="orchestration.runtime_commit_gate",
            allowed=False,
            reason="commit_gate_blocked",
            refs={
                "plan_ref": plan_ref,
                "directive_ref": directive_ref,
                "output_boundary_authority": "AssistantOutputBoundary",
            },
        ),
        CommitCandidate(
            candidate_id=f"commit-candidate:{task_id}:task_result:runtime-blocked",
            commit_type="task_result",
            payload={
                "canonical_state": str(getattr(output_response, "canonical_state", "") or ""),
                "fallback_reason": str(getattr(output_response, "fallback_reason", "") or ""),
            },
            producer="orchestration.runtime_commit_gate",
            allowed=False,
            reason="commit_gate_blocked",
            refs={
                "plan_ref": plan_ref,
                "directive_ref": directive_ref,
            },
        ),
    )
    return CommitGatePreview(
        gate_id=f"commit-gate:{task_id}:runtime-blocked",
        task_id=task_id,
        plan_ref=plan_ref,
        execution_graph_preview_ref=execution_graph_ref,
        adoption_candidate_ref="runtime-directive-adopted:model-only",
        directive_candidate_refs=(directive_ref,) if directive_ref else (),
        commit_candidates=commit_candidates,
        status="blocked",
        reason="commit_gate_blocked",
        commit_allowed=False,
        preview_only=True,
        runtime_executable=False,
        diagnostics={
            "preview_only": True,
            "fail_closed": True,
            "runtime_directive_ref": directive_ref,
            "output_boundary_applied": True,
            "commit_candidate_count": len(commit_candidates),
            "commit_allowed": False,
            "session_write_allowed": False,
            "memory_write_allowed": False,
            "artifact_write_allowed": False,
            "task_result_write_allowed": False,
            "title_write_allowed": False,
        },
    )


def build_user_message_commit_decision(
    *,
    session_id: str,
    content: str,
    task_id: str = "",
    source: str = "api_user_input",
) -> RuntimeCommitGateDecision:
    normalized = str(content or "").strip()
    candidate = CommitCandidate(
        candidate_id=f"commit-candidate:{task_id or session_id}:session_message:user-input",
        commit_type="session_message",
        payload={
            "session_id": str(session_id or ""),
            "role": "user",
            "content": normalized,
        },
        producer="orchestration.runtime_commit_gate",
        allowed=bool(normalized),
        reason="user_input_commit_allowed" if normalized else "empty_user_input_blocked",
        refs={
            "source": source,
            "commit_scope": "inbound_user_message_only",
        },
    )
    return RuntimeCommitGateDecision(
        gate_id=f"commit-gate:{task_id or session_id}:user-message",
        commit_type="session_message",
        commit_candidate=candidate,
        status="allowed" if normalized else "blocked",
        reason=candidate.reason,
        commit_allowed=bool(normalized),
        diagnostics={
            "session_id": str(session_id or ""),
            "role": "user",
            "assistant_write_allowed": False,
            "memory_write_allowed": False,
            "artifact_write_allowed": False,
            "task_result_write_allowed": False,
        },
    )


def build_task_run_final_commit_decision(
    *,
    task_run_id: str,
    task_id: str,
    terminal_reason: str,
    final_content_chars: int = 0,
    source: str = "orchestration.task_run_loop",
) -> RuntimeCommitGateDecision:
    candidate = CommitCandidate(
        candidate_id=f"commit-candidate:{task_run_id}:task_result:final",
        commit_type="task_result",
        payload={
            "task_run_id": str(task_run_id or ""),
            "task_id": str(task_id or ""),
            "terminal_reason": str(terminal_reason or ""),
            "final_content_chars": int(final_content_chars or 0),
        },
        producer="orchestration.runtime_commit_gate",
        allowed=True,
        reason="task_run_final_record_allowed",
        refs={
            "source": source,
            "commit_scope": "task_run_status_and_final_record_only",
        },
    )
    return RuntimeCommitGateDecision(
        gate_id=f"commit-gate:{task_run_id}:task-result-final",
        commit_type="task_result",
        commit_candidate=candidate,
        status="allowed",
        reason=candidate.reason,
        commit_allowed=True,
        diagnostics={
            "task_run_status_write_allowed": True,
            "final_answer_record_allowed": True,
            "assistant_session_write_allowed": False,
            "memory_write_allowed": False,
            "artifact_write_allowed": False,
            "filesystem_write_allowed": False,
        },
    )


def build_assistant_session_message_commit_decision(
    *,
    session_id: str,
    task_run_id: str,
    task_id: str,
    content: str,
    answer_channel: str = "",
    answer_source: str = "",
    answer_canonical_state: str = "",
    answer_persist_policy: str = "",
    answer_finalization_policy: str = "",
    answer_fallback_reason: str = "",
    source: str = "orchestration.task_run_loop",
) -> RuntimeCommitGateDecision:
    normalized = str(content or "").strip()
    candidate = CommitCandidate(
        candidate_id=f"commit-candidate:{task_run_id}:session_message:assistant-final",
        commit_type="session_message",
        payload={
            "session_id": str(session_id or ""),
            "task_run_id": str(task_run_id or ""),
            "task_id": str(task_id or ""),
            "role": "assistant",
            "content": normalized,
            "answer_channel": str(answer_channel or ""),
            "answer_source": str(answer_source or ""),
            "answer_canonical_state": str(answer_canonical_state or ""),
            "answer_persist_policy": str(answer_persist_policy or ""),
            "answer_finalization_policy": str(answer_finalization_policy or ""),
            "answer_fallback_reason": str(answer_fallback_reason or ""),
        },
        producer="orchestration.runtime_commit_gate",
        allowed=bool(normalized),
        reason="assistant_session_message_allowed" if normalized else "empty_assistant_message_blocked",
        refs={
            "source": source,
            "commit_scope": "assistant_final_message_only",
        },
    )
    return RuntimeCommitGateDecision(
        gate_id=f"commit-gate:{task_run_id}:assistant-session-message",
        commit_type="session_message",
        commit_candidate=candidate,
        status="allowed" if normalized else "blocked",
        reason=candidate.reason,
        commit_allowed=bool(normalized),
        diagnostics={
            "session_id": str(session_id or ""),
            "task_run_id": str(task_run_id or ""),
            "assistant_session_write_allowed": bool(normalized),
            "task_run_status_write_allowed": False,
            "memory_write_allowed": False,
            "artifact_write_allowed": False,
            "filesystem_write_allowed": False,
        },
    )
