from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


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
    result_ref: str = ""
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
