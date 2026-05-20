from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


TestRunStatus = Literal["unknown", "running", "passed", "failed", "cancelled", "stale", "detached"]
TestTurnStatus = Literal["unknown", "passed", "warning", "failed"]
AssertionStatus = Literal["passed", "failed", "unsupported"]
RegressionSampleStatus = Literal["candidate", "active", "quarantined", "archived"]
VerificationVerdictStatus = Literal["not_run", "planned", "running", "passed", "failed", "unsupported"]


@dataclass(frozen=True, slots=True)
class TestProfile:
    profile_id: str
    title: str
    description: str
    command_preview: str
    risk: str
    estimated_duration: str
    harness_profile: str = ""
    extra_args: tuple[str, ...] = ()
    requires_confirmation: bool = False
    monitor_owner: str = "orchestration.runtime_loop"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["id"] = self.profile_id
        payload["extra_args"] = list(self.extra_args)
        payload["harness_profile"] = self.harness_profile or self.profile_id
        return payload


@dataclass(frozen=True, slots=True)
class RuntimeLoopMonitorSummary:
    task_run_id: str = ""
    status: str = "unknown"
    terminal_reason: str = ""
    event_count: int = 0
    latest_event_type: str = ""
    event_type_counts: dict[str, int] = field(default_factory=dict)
    operation_gate: dict[str, Any] = field(default_factory=dict)
    tools: dict[str, Any] = field(default_factory=dict)
    commits: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    checkpoints: dict[str, Any] = field(default_factory=dict)
    stages: list[dict[str, Any]] = field(default_factory=list)
    authority: str = "orchestration.runtime_loop_monitor"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AssertionResult:
    expression: str
    status: AssertionStatus
    reason: str = ""
    actual: Any = None

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TestScenarioContract:
    contract_id: str
    title: str
    scenario_id: str
    turn_id: str
    session_alias: str
    user_input: str
    objective: str = ""
    source_kind: str = "long_scenario_turn"
    source_ref: str = ""
    profile: str = "long"
    preconditions: tuple[str, ...] = ()
    assertions: tuple[str, ...] = ()
    expected_tools: tuple[str, ...] = ()
    expected_events: tuple[str, ...] = ()
    evidence_policy: dict[str, Any] = field(default_factory=dict)
    rerun_args: tuple[str, ...] = ()
    schema_version: str = "2026-05-20"
    authority: str = "test_system.scenario_contract"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["preconditions"] = list(self.preconditions)
        payload["assertions"] = list(self.assertions)
        payload["expected_tools"] = list(self.expected_tools)
        payload["expected_events"] = list(self.expected_events)
        payload["rerun_args"] = list(self.rerun_args)
        return payload


@dataclass(frozen=True, slots=True)
class VerificationVerdict:
    status: VerificationVerdictStatus = "not_run"
    reason: str = ""
    run_id: str = ""
    artifact_refs: tuple[str, ...] = ()
    checked_at: float = 0.0
    authority: str = "test_system.verification_verdict"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifact_refs"] = list(self.artifact_refs)
        return payload


@dataclass(frozen=True, slots=True)
class RegressionSample:
    sample_id: str
    title: str
    source_run_id: str
    source_turn_id: str
    source_artifact_path: str
    scenario_id: str
    session_alias: str
    status: RegressionSampleStatus = "candidate"
    failure_summary: str = ""
    observed: str = ""
    expected: str = ""
    task_run_id: str = ""
    problem_node_id: str = ""
    problem_node_label: str = ""
    contract: TestScenarioContract | None = None
    assertion_summary: tuple[dict[str, Any], ...] = ()
    evidence_packet: dict[str, Any] = field(default_factory=dict)
    rerun_command: tuple[str, ...] = ()
    verification: VerificationVerdict = field(default_factory=VerificationVerdict)
    tags: tuple[str, ...] = ()
    created_at: float = 0.0
    updated_at: float = 0.0
    schema_version: str = "2026-05-20"
    authority: str = "test_system.regression_sample"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["contract"] = self.contract.to_dict() if self.contract is not None else None
        payload["assertion_summary"] = [dict(item) for item in self.assertion_summary]
        payload["rerun_command"] = list(self.rerun_command)
        payload["verification"] = self.verification.to_dict()
        payload["tags"] = list(self.tags)
        return payload


@dataclass(frozen=True, slots=True)
class TestTurn:
    turn_id: str
    index: int
    scenario: str
    session_alias: str
    status: TestTurnStatus
    summary: str
    artifact_path: str
    issue_count: int = 0
    assertions: tuple[AssertionResult, ...] = ()
    runtime_loop: RuntimeLoopMonitorSummary = field(default_factory=RuntimeLoopMonitorSummary)
    has_trace: bool = False
    has_prompt_manifest: bool = False
    has_memory_trace: bool = False
    problem_node_id: str = ""
    problem_node_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["assertions"] = [item.to_dict() for item in self.assertions]
        payload["runtime_loop"] = self.runtime_loop.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class TestRunSummary:
    total: int = 0
    passed: int = 0
    failed: int = 0
    warning: int = 0
    first_failure: str = ""
    runtime_loop_count: int = 0
    runtime_loop_failed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TestRunState:
    run_id: str
    profile: str
    status: TestRunStatus
    command: tuple[str, ...] = ()
    output_dir: str = ""
    log_path: str = ""
    started_at: float = 0.0
    ended_at: float = 0.0
    duration_ms: float = 0.0
    returncode: int | None = None
    pid: int | None = None
    summary: TestRunSummary = field(default_factory=TestRunSummary)
    log_tail: str = ""
    heartbeat_at: float = 0.0
    last_progress_at: float = 0.0
    last_progress_event_id: str = ""
    last_artifact_mtime: float = 0.0
    stale_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["command"] = list(self.command)
        payload["summary"] = self.summary.to_dict()
        payload["command_preview"] = " ".join(self.command)
        return payload


@dataclass(frozen=True, slots=True)
class TestArtifactBundle:
    summary: TestRunSummary
    report: str = ""
    trace_tail: str = ""
    log_tail: str = ""
    run_result: dict[str, Any] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)
    runtime_loop: dict[str, Any] = field(default_factory=dict)
    harness_contract: dict[str, Any] = field(default_factory=dict)
    harness_state: dict[str, Any] = field(default_factory=dict)
    artifact_manifest: dict[str, Any] = field(default_factory=dict)
    partial_result: dict[str, Any] = field(default_factory=dict)
    progress_events: list[dict[str, Any]] = field(default_factory=list)
    stuck_diagnosis: dict[str, Any] = field(default_factory=dict)
    evidence_packet: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["summary"] = self.summary.to_dict()
        return payload
