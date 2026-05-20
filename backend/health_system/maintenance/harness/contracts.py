from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class HarnessRunContract:
    run_id: str
    profile: str
    command: list[str]
    output_dir: str
    backend_root: str
    scenario_refs: list[str] = field(default_factory=list)
    timeout_seconds: int = 0
    resource_limits: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "2026-05-20"
    authority: str = "health_system.harness_run_contract"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HarnessProgressEvent:
    event_id: str
    event_type: str
    run_id: str
    status: str
    created_at: float
    message: str = ""
    scenario_ref: str = ""
    turn_ref: str = ""
    artifact_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "health_system.harness_progress_event"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HarnessRunState:
    run_id: str
    profile: str
    status: str
    pid: int = 0
    process_token: str = ""
    command: list[str] = field(default_factory=list)
    output_dir: str = ""
    started_at: float = 0.0
    updated_at: float = 0.0
    ended_at: float = 0.0
    returncode: int | None = None
    heartbeat_at: float = 0.0
    last_progress_at: float = 0.0
    last_progress_event_id: str = ""
    last_artifact_mtime: float = 0.0
    stale_reason: str = ""
    summary: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "2026-05-20"
    authority: str = "health_system.harness_run_state"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HarnessArtifactRecord:
    name: str
    artifact_type: str
    path: str
    relative_ref: str = ""
    producer: str = "health_system.maintenance.harness"
    required: bool = False
    present: bool = False
    checksum: str = ""
    size_bytes: int = 0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HarnessArtifactManifest:
    manifest_id: str
    run_id: str
    artifacts: tuple[HarnessArtifactRecord, ...] = ()
    created_at: float = 0.0
    schema_version: str = "2026-05-20"
    authority: str = "health_system.harness_artifact_manifest"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifacts"] = [item.to_dict() for item in self.artifacts]
        return payload


@dataclass(frozen=True, slots=True)
class HarnessPartialResult:
    run_id: str
    profile: str
    status: str
    summary: dict[str, Any] = field(default_factory=dict)
    completed_scenarios: int = 0
    failed_scenarios: int = 0
    latest_artifact_ref: str = ""
    latest_progress_event_id: str = ""
    updated_at: float = 0.0
    schema_version: str = "2026-05-20"
    authority: str = "health_system.harness_partial_result"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TimingSnapshot:
    started_at: str
    ended_at: str = ""
    duration_ms: float = 0.0
    first_event_ms: float | None = None
    first_token_ms: float | None = None
    done_ms: float | None = None
    event_count: int = 0
    terminal_event: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScenarioResult:
    name: str
    category: str
    passed: bool
    status: str
    summary: str
    timing: TimingSnapshot
    command: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    artifact_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["timing"] = self.timing.to_dict()
        return payload


@dataclass
class IssueEntry:
    id: str
    title: str
    severity: str
    category: str
    summary: str
    command: str = ""
    artifact_paths: list[str] = field(default_factory=list)
    trace_id: str = ""
    trace_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TraceSpan:
    trace_id: str
    stage: str
    status: str
    started_at: str
    ended_at: str
    latency_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunContext:
    run_id: str
    profile: str
    mode: str
    repo_root: str
    backend_root: str
    frontend_root: str
    output_dir: str
    generated_at: str
    python_version: str
    llm_provider: str = ""
    llm_model: str = ""
    langsmith_enabled: bool = False
    trace_backend: str = ""
    trace_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunResult:
    context: RunContext
    results: list[ScenarioResult] = field(default_factory=list)
    issues: list[IssueEntry] = field(default_factory=list)
    traces: list[TraceSpan] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "context": self.context.to_dict(),
            "results": [result.to_dict() for result in self.results],
            "issues": [issue.to_dict() for issue in self.issues],
            "traces": [trace.to_dict() for trace in self.traces],
            "artifacts": dict(self.artifacts),
            "metadata": dict(self.metadata),
        }
