from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


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
