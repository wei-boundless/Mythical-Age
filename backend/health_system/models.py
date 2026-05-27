from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class HealthTaskRequest:
    request_id: str
    issue_id: str
    task_kind: str
    task_id: str
    flow_id: str
    required_evidence_refs: tuple[str, ...] = ()
    requested_by: str = ""
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "health_system.task_request"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_evidence_refs"] = list(self.required_evidence_refs)
        return payload


@dataclass(frozen=True, slots=True)
class HealthIssue:
    issue_id: str
    title: str
    owner_system: str
    severity: str
    status: str
    source: str
    conversation_ref: str = ""
    runtime_trace_refs: tuple[str, ...] = ()
    prompt_manifest_refs: tuple[str, ...] = ()
    memory_refs: tuple[str, ...] = ()
    assertion_refs: tuple[str, ...] = ()
    duplicate_of: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("runtime_trace_refs", "prompt_manifest_refs", "memory_refs", "assertion_refs"):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True, slots=True)
class HealthAgentRun:
    run_id: str
    request_id: str
    issue_id: str
    task_run_id: str
    agent_id: str
    agent_profile_id: str
    runtime_lane: str
    health_action: str
    workflow_id: str
    projection_id: str
    prompt_manifest_id: str
    status: str
    terminal_reason: str
    admission_status: str = ""
    blocked_reasons: tuple[str, ...] = ()
    report_refs: tuple[str, ...] = ()
    trace_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    result_ref: str = ""
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("blocked_reasons", "report_refs", "trace_refs", "artifact_refs"):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True, slots=True)
class ProblemNode:
    node_id: str
    issue_id: str
    system: str
    stage: str
    evidence_refs: tuple[str, ...] = ()
    diagnosis: str = ""
    confidence: float = 0.0
    suggested_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_refs"] = list(self.evidence_refs)
        return payload


@dataclass(frozen=True, slots=True)
class HealthManagementCommand:
    command_id: str
    command_type: str
    initiator_type: str
    initiator_ref: str
    requested_by: str
    source: str
    conversation_session_ref: str
    target_scope: str
    target_ref: str
    health_action: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HealthManagementReceipt:
    receipt_id: str
    command_ref: str
    accepted: bool
    status: str
    health_issue_ref: str = ""
    health_run_ref: str = ""
    report_ref: str = ""
    admission_status: str = ""
    run_status: str = ""
    blocked_reasons: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blocked_reasons"] = list(self.blocked_reasons)
        return payload


@dataclass(frozen=True, slots=True)
class HealthReport:
    report_id: str
    report_type: str
    issue_ref: str = ""
    command_ref: str = ""
    agent_run_ref: str = ""
    evidence_refs: tuple[str, ...] = ()
    verdict: str = "unknown"
    severity: str = "medium"
    summary: str = ""
    recommended_actions: tuple[str, ...] = ()
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_refs"] = list(self.evidence_refs)
        payload["recommended_actions"] = list(self.recommended_actions)
        return payload


@dataclass(frozen=True, slots=True)
class HealthAgentConversationSession:
    session_id: str
    agent_id: str
    agent_profile_id: str
    workflow_id: str
    runtime_lane: str
    active_issue_ref: str = ""
    active_run_ref: str = ""
    command_refs: tuple[str, ...] = ()
    status: str = "active"
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["command_refs"] = list(self.command_refs)
        return payload


@dataclass(frozen=True, slots=True)
class HealthAgentConversationMessage:
    message_id: str
    session_id: str
    role: str
    content: str
    command_ref: str = ""
    receipt_ref: str = ""
    report_ref: str = ""
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


