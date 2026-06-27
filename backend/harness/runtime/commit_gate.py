from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


CommitType = Literal[
    "session_message",
    "session_memory",
    "durable_memory",
    "task_result",
    "artifact_graph",
    "artifact_output",
    "memory_output",
    "file_output",
    "title",
]


@dataclass(slots=True, frozen=True)
class CommitCandidate:
    """Writeback request. It is denied until the harness commit gate explicitly allows it."""

    candidate_id: str
    commit_type: CommitType
    payload: dict[str, Any] = field(default_factory=dict)
    producer: str = ""
    allowed: bool = False
    reason: str = "pending_commit_gate"
    refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_COMMIT_TYPES: tuple[CommitType, ...] = (
    "session_message",
    "session_memory",
    "durable_memory",
    "task_result",
    "artifact_graph",
    "artifact_output",
    "memory_output",
    "file_output",
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
    authority: str = "harness.output_commit"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != "harness.output_commit":
            raise ValueError("RuntimeCommitGateDecision authority must be harness.output_commit")
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
            producer="harness.output_commit",
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
            producer="harness.output_commit",
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
        producer="harness.output_commit",
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
        producer="harness.output_commit",
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


def build_task_run_staged_output_commit_decision(
    *,
    task_run_id: str,
    session_id: str = "",
    output_kind: str,
    output_refs: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    execution_isolation: dict[str, Any] | None = None,
    capsule: Any | None = None,
    source: str = "harness.task_executor",
) -> RuntimeCommitGateDecision:
    isolation = dict(execution_isolation or {})
    capsule_payload = _capsule_payload(capsule)
    proof = {
        "capsule_id": str(isolation.get("capsule_id") or capsule_payload.get("capsule_id") or "").strip(),
        "lease_id": str(isolation.get("lease_id") or capsule_payload.get("lease_id") or "").strip(),
        "task_thread_id": str(isolation.get("task_thread_id") or capsule_payload.get("task_thread_id") or "").strip(),
        "task_group_id": str(isolation.get("task_group_id") or capsule_payload.get("task_group_id") or "").strip(),
        "permission_fingerprint": str(isolation.get("permission_fingerprint") or capsule_payload.get("permission_fingerprint") or "").strip(),
        "resource_lock_refs": [
            str(item)
            for item in list(isolation.get("resource_lock_refs") or capsule_payload.get("resource_lock_refs") or [])
            if str(item)
        ],
    }
    normalized_kind = str(output_kind or "").strip()
    commit_type = _staged_output_commit_type(normalized_kind)
    refs = [dict(item) for item in list(output_refs or []) if isinstance(item, dict)]
    allowed, reason = _staged_output_commit_verdict(
        normalized_kind,
        proof=proof,
        isolation=isolation,
        capsule_payload=capsule_payload,
    )
    candidate = CommitCandidate(
        candidate_id=f"commit-candidate:{task_run_id}:{commit_type}:{normalized_kind or 'output'}",
        commit_type=commit_type,
        payload={
            "task_run_id": str(task_run_id or ""),
            "session_id": str(session_id or ""),
            "output_kind": normalized_kind,
            "output_refs": refs,
            "output_ref_count": len(refs),
            "commit_state": "staged" if allowed else "blocked",
            "capsule_id": proof["capsule_id"],
            "task_thread_id": proof["task_thread_id"],
            "task_group_id": proof["task_group_id"],
        },
        producer="harness.output_commit",
        allowed=allowed,
        reason=reason,
        refs={
            "source": source,
            "commit_scope": "task_thread_staged_output",
            "capsule_ref": proof["capsule_id"],
            "task_thread_ref": proof["task_thread_id"],
        },
    )
    return RuntimeCommitGateDecision(
        gate_id=f"commit-gate:{task_run_id}:{normalized_kind or 'output'}",
        commit_type=commit_type,
        commit_candidate=candidate,
        status="allowed" if allowed else "blocked",
        reason=reason,
        commit_allowed=allowed,
        diagnostics={
            "task_run_id": str(task_run_id or ""),
            "session_id": str(session_id or ""),
            "output_kind": normalized_kind,
            "output_ref_count": len(refs),
            "capsule_id": proof["capsule_id"],
            "lease_id": proof["lease_id"],
            "task_thread_id": proof["task_thread_id"],
            "task_group_id": proof["task_group_id"],
            "resource_lock_refs": list(proof["resource_lock_refs"]),
            "permission_fingerprint": proof["permission_fingerprint"],
            "commit_policy": dict(capsule_payload.get("commit_policy") or isolation.get("commit_policy") or {}),
            "capsule_status": str(capsule_payload.get("status") or ""),
            "staged_output_allowed": allowed,
            "artifact_write_allowed": allowed and commit_type == "artifact_output",
            "memory_write_allowed": allowed and commit_type == "memory_output",
            "filesystem_write_allowed": allowed and commit_type == "file_output",
            "session_write_allowed": False,
            "canonical_workspace_write_allowed": False,
            "canonical_memory_write_allowed": False,
            "authority": "harness.output_commit.staged_output",
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
    control_only_channel = normalized_channel in {
        "active_work_control",
        "opening_judgment",
        "harness_fail_closed",
        "runtime_control",
        "task_control",
    }
    replacement_stop = normalized_terminal_reason == "user_aborted" and source == "harness.loop.task_executor.replacement_stop"
    is_missing_fallback = (
        normalized_state == "missing_answer"
        or normalized_persist_policy == "do_not_persist"
    )

    allowed = (
        bool(normalized)
        and bool(normalized_turn_id)
        and not is_missing_fallback
        and not control_only_channel
        and not replacement_stop
    )
    reason = "assistant_session_message_allowed"
    if not normalized:
        reason = "empty_assistant_message_blocked"
    elif not normalized_turn_id:
        reason = "assistant_session_message_missing_turn_id"
    elif control_only_channel:
        reason = "control_channel_not_committable"
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
        producer="harness.output_commit",
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
            "answer_protocol_metadata_present": bool(normalized_leak_flags),
            "answer_protocol_flags": list(normalized_leak_flags),
        },
    )


def _staged_output_commit_type(output_kind: str) -> CommitType:
    if output_kind.startswith("memory"):
        return "memory_output"
    if output_kind.startswith("file"):
        return "file_output"
    return "artifact_output"


def _staged_output_commit_verdict(
    output_kind: str,
    *,
    proof: dict[str, Any],
    isolation: dict[str, Any],
    capsule_payload: dict[str, Any],
) -> tuple[bool, str]:
    missing = [
        key
        for key in ("capsule_id", "lease_id", "task_thread_id", "permission_fingerprint", "resource_lock_refs")
        if not proof.get(key)
    ]
    if missing:
        return False, "execution_capsule_required_for_staged_output_commit"
    if not capsule_payload:
        return False, "execution_capsule_not_found"
    if str(capsule_payload.get("status") or "") != "active":
        return False, "execution_capsule_not_active"
    for key in ("capsule_id", "lease_id", "task_thread_id", "permission_fingerprint"):
        expected = str(capsule_payload.get(key) or "").strip()
        if expected and expected != str(proof.get(key) or "").strip():
            return False, f"execution_capsule_{key}_mismatch"
    capsule_locks = {str(item) for item in list(capsule_payload.get("resource_lock_refs") or []) if str(item)}
    if not set(proof["resource_lock_refs"]).issubset(capsule_locks):
        return False, "execution_capsule_resource_lock_ref_mismatch"
    policy = dict(capsule_payload.get("commit_policy") or isolation.get("commit_policy") or {})
    if output_kind in {"artifact", "artifact_staged", "artifact_output"}:
        return _policy_allows(policy, key="artifact_outputs", allowed_values={"staged", "candidate_only"}, default="staged")
    if output_kind in {"memory", "memory_candidate", "memory_output"}:
        return _policy_allows(policy, key="memory_outputs", allowed_values={"candidate_only", "staged"}, default="candidate_only")
    if output_kind in {"memory_commit", "canonical_memory"}:
        return _policy_allows(policy, key="memory_outputs", allowed_values={"commit_gate", "canonical_commit_allowed"}, default="candidate_only")
    if output_kind in {"file", "file_staged", "file_output", "changeset"}:
        return _policy_allows(policy, key="file_outputs", allowed_values={"changeset_required", "staged"}, default="changeset_required")
    return False, "unsupported_staged_output_kind"


def _policy_allows(
    policy: dict[str, Any],
    *,
    key: str,
    allowed_values: set[str],
    default: str,
) -> tuple[bool, str]:
    value = str(policy.get(key) or default).strip()
    if value in allowed_values:
        return True, "task_thread_staged_output_allowed"
    return False, f"commit_policy_blocks_{key}:{value or 'empty'}"


def _capsule_payload(capsule: Any | None) -> dict[str, Any]:
    if capsule is None:
        return {}
    if isinstance(capsule, dict):
        data = dict(capsule)
    elif hasattr(capsule, "to_dict"):
        data = dict(capsule.to_dict())
    else:
        data = {
            "capsule_id": getattr(capsule, "capsule_id", ""),
            "lease_id": getattr(capsule, "lease_id", ""),
            "task_thread_id": getattr(capsule, "task_thread_id", ""),
            "task_group_id": getattr(capsule, "task_group_id", ""),
            "resource_lock_refs": list(getattr(capsule, "resource_lock_refs", ()) or ()),
            "permission_fingerprint": getattr(capsule, "permission_fingerprint", ""),
            "commit_policy": dict(getattr(capsule, "commit_policy", {}) or {}),
            "status": getattr(capsule, "status", ""),
        }
    data["resource_lock_refs"] = [str(item) for item in list(data.get("resource_lock_refs") or []) if str(item)]
    data["commit_policy"] = dict(data.get("commit_policy") or {})
    return data
