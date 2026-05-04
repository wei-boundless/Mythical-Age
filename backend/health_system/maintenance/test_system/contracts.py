from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


TestRunStatus = Literal["unknown", "running", "passed", "failed", "cancelled"]
TestTurnStatus = Literal["unknown", "passed", "warning", "failed"]
AssertionStatus = Literal["passed", "failed", "unsupported"]


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

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["summary"] = self.summary.to_dict()
        return payload
