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
    graph_id: str = ""
    entry_node_id: str = ""
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
    task_mode: str
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
    task_mode: str
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
    test_run_ref: str = ""
    verification_run_ref: str = ""
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
    test_run_ref: str = ""
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


@dataclass(frozen=True, slots=True)
class HealthTestScenario:
    scenario_id: str
    title: str
    category: str
    owner_system: str
    required_flows: tuple[str, ...] = ()
    expected_invariants: dict[str, Any] = field(default_factory=dict)
    default_enabled: bool = True
    source_test_refs: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_flows"] = list(self.required_flows)
        payload["source_test_refs"] = list(self.source_test_refs)
        payload["tags"] = list(self.tags)
        return payload


@dataclass(frozen=True, slots=True)
class HealthTestRun:
    health_test_run_id: str
    command_ref: str
    test_system_run_ref: str
    profile: str
    scenario_refs: tuple[str, ...] = ()
    status: str = "unknown"
    verdict: str = "unknown"
    artifact_refs: tuple[str, ...] = ()
    issue_refs: tuple[str, ...] = ()
    report_refs: tuple[str, ...] = ()
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("scenario_refs", "artifact_refs", "issue_refs", "report_refs"):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True, slots=True)
class VerificationProfile:
    profile_id: str
    layer: str
    purpose: str
    case_refs: tuple[str, ...] = ()
    harness_profile: str = ""
    default_timeout_sec: int = 0
    required_artifacts: tuple[str, ...] = ()
    cutover_required: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "health_system.verification_profile"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["case_refs"] = list(payload["case_refs"])
        payload["required_artifacts"] = list(payload["required_artifacts"])
        return payload


@dataclass(frozen=True, slots=True)
class VerificationArtifact:
    name: str
    artifact_type: str
    path: str
    relative_ref: str = ""
    producer: str = ""
    required: bool = False
    present: bool = False
    checksum: str = ""
    size_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VerificationArtifactManifest:
    manifest_id: str
    verification_run_id: str
    schema_version: str = "2026-05-08"
    artifacts: tuple[VerificationArtifact, ...] = ()
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "health_system.verification_artifact_manifest"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifacts"] = [item.to_dict() for item in self.artifacts]
        return payload


@dataclass(frozen=True, slots=True)
class VerificationRun:
    verification_run_id: str
    profile_id: str
    status: str
    command_ref: str = ""
    source_run_ref: str = ""
    process_ref: str = ""
    output_dir: str = ""
    log_path: str = ""
    artifact_manifest_ref: str = ""
    summary: dict[str, Any] = field(default_factory=dict)
    artifact_refs: tuple[str, ...] = ()
    issue_refs: tuple[str, ...] = ()
    report_refs: tuple[str, ...] = ()
    trace_refs: tuple[str, ...] = ()
    started_at: float = 0.0
    ended_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "health_system.verification_run"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("artifact_refs", "issue_refs", "report_refs", "trace_refs"):
            payload[key] = list(payload[key])
        return payload
