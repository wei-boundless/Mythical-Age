from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .execution_graph import CommitCandidate, CommitType


DEFAULT_COMMIT_TYPES: tuple[CommitType, ...] = (
    "session_message",
    "session_memory",
    "durable_memory",
    "task_result",
    "artifact_graph",
    "title",
)


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
        diagnostic_candidates = dict(self.diagnostics).get("commit_candidates")
        if isinstance(diagnostic_candidates, list):
            payload["commit_candidates"] = diagnostic_candidates
        return payload


def build_blocked_runtime_commit_gate(
    *,
    task_id: str,
    plan_ref: str,
    execution_graph_ref: str = "",
    directive_ref: str = "",
    output_response: Any | None = None,
) -> RuntimeCommitGateDecision:
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
    return RuntimeCommitGateDecision(
        gate_id=f"commit-gate:{task_id}:runtime-blocked",
        commit_type="session_message",
        commit_candidate=commit_candidates[0],
        status="blocked",
        reason="commit_gate_blocked",
        commit_allowed=False,
        diagnostics={
            "fail_closed": True,
            "runtime_directive_ref": directive_ref,
            "plan_ref": plan_ref,
            "execution_graph_ref": execution_graph_ref,
            "output_boundary_applied": True,
            "commit_candidate_count": len(commit_candidates),
            "commit_candidates": [candidate.to_dict() for candidate in commit_candidates],
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
    task_spec_ref: str = "",
    template_id: str = "",
    task_result: dict[str, Any] | None = None,
    source: str = "harness.agent_loop",
) -> RuntimeCommitGateDecision:
    payload = {
        "task_run_id": str(task_run_id or ""),
        "task_id": str(task_id or ""),
        "task_spec_ref": str(task_spec_ref or ""),
        "template_id": str(template_id or ""),
        "terminal_reason": str(terminal_reason or ""),
        "final_content_chars": int(final_content_chars or 0),
    }
    if isinstance(task_result, dict) and task_result:
        payload["task_result"] = dict(task_result)
    candidate = CommitCandidate(
        candidate_id=f"commit-candidate:{task_run_id}:task_result:final",
        commit_type="task_result",
        payload=payload,
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
    turn_id: str = "",
    content: str,
    answer_channel: str = "",
    answer_source: str = "",
    answer_canonical_state: str = "",
    answer_persist_policy: str = "",
    answer_finalization_policy: str = "",
    answer_fallback_reason: str = "",
    answer_selected_channel: str = "",
    answer_selected_source: str = "",
    answer_leak_flags: list[str] | tuple[str, ...] | None = None,
    completion_state: str = "",
    terminal_reason: str = "",
    timeout_seconds: str = "",
    partial_delta_count: str = "",
    source: str = "harness.agent_loop",
) -> RuntimeCommitGateDecision:
    normalized = str(content or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    normalized_channel = str(answer_channel or "").strip()
    normalized_state = str(answer_canonical_state or "").strip()
    normalized_persist_policy = str(answer_persist_policy or "").strip()
    normalized_terminal_reason = str(terminal_reason or "").strip()
    normalized_leak_flags = [
        str(flag or "").strip()
        for flag in list(answer_leak_flags or [])
        if str(flag or "").strip()
    ]
    answer_leak_blocked = bool(normalized_leak_flags)
    control_only_channel = normalized_channel in {
        "active_work_control",
        "opening_judgment",
        "orchestration_fail_closed",
        "runtime_control",
        "task_control",
    }
    debug_only_output = normalized_persist_policy == "persist_debug_only" or normalized_state == "progress_only"
    replacement_stop = normalized_terminal_reason == "user_aborted" and source == "harness.loop.task_executor.replacement_stop"
    is_missing_fallback = (
        normalized_state == "missing_answer"
        or normalized_persist_policy == "do_not_persist"
    )
    allowed = (
        bool(normalized)
        and bool(normalized_turn_id)
        and not is_missing_fallback
        and not debug_only_output
        and not control_only_channel
        and not replacement_stop
        and not answer_leak_blocked
    )
    reason = "assistant_session_message_allowed"
    if not normalized:
        reason = "empty_assistant_message_blocked"
    elif not normalized_turn_id:
        reason = "assistant_session_message_missing_turn_id"
    elif answer_leak_blocked:
        reason = "answer_leak_not_committable"
    elif control_only_channel:
        reason = "control_channel_not_committable"
    elif debug_only_output:
        reason = "debug_only_output_not_committable"
    elif is_missing_fallback:
        reason = "missing_answer_not_committable"
    elif replacement_stop:
        reason = "replacement_stop_closeout_not_committable"
    candidate = CommitCandidate(
        candidate_id=f"commit-candidate:{task_run_id}:session_message:assistant-final",
        commit_type="session_message",
        payload={
            "session_id": str(session_id or ""),
            "task_run_id": str(task_run_id or ""),
            "task_id": str(task_id or ""),
            "turn_id": normalized_turn_id,
            "role": "assistant",
            "content": normalized,
            "answer_channel": normalized_channel,
            "answer_source": str(answer_source or ""),
            "answer_canonical_state": normalized_state,
            "answer_persist_policy": normalized_persist_policy,
            "answer_finalization_policy": str(answer_finalization_policy or ""),
            "answer_fallback_reason": str(answer_fallback_reason or ""),
            "answer_selected_channel": str(answer_selected_channel or ""),
            "answer_selected_source": str(answer_selected_source or ""),
            "answer_leak_flags": list(normalized_leak_flags),
            "completion_state": str(completion_state or ""),
            "terminal_reason": normalized_terminal_reason,
            "timeout_seconds": str(timeout_seconds or ""),
            "partial_delta_count": str(partial_delta_count or ""),
        },
        producer="orchestration.runtime_commit_gate",
        allowed=allowed,
        reason=reason,
        refs={
            "source": source,
            "commit_scope": "assistant_final_message_only",
        },
    )
    return RuntimeCommitGateDecision(
        gate_id=f"commit-gate:{task_run_id}:assistant-session-message",
        commit_type="session_message",
        commit_candidate=candidate,
        status="allowed" if allowed else "blocked",
        reason=candidate.reason,
        commit_allowed=allowed,
        diagnostics={
            "session_id": str(session_id or ""),
            "task_run_id": str(task_run_id or ""),
            "turn_id": normalized_turn_id,
            "assistant_session_write_allowed": allowed,
            "task_run_status_write_allowed": False,
            "memory_write_allowed": False,
            "artifact_write_allowed": False,
            "filesystem_write_allowed": False,
            "replacement_stop": replacement_stop,
            "answer_leak_blocked": answer_leak_blocked,
            "answer_leak_flags": list(normalized_leak_flags),
        },
    )


