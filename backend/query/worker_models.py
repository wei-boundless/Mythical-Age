from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from query.evidence_models import BindingCandidate, EvidenceArtifact, EvidenceEnvelope


WorkerRoute = Literal["none", "retrieval", "pdf", "structured_data", "evidence_orchestrator"]
WorkerStatus = Literal["ok", "degraded", "clarify", "error"]


@dataclass(frozen=True, slots=True)
class WorkerRequest:
    request_id: str
    session_id: str = ""
    query: str = ""
    worker_route: WorkerRoute = "none"
    task_frame: dict[str, Any] = field(default_factory=dict)
    bindings: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    artifact_refs: list[str] = field(default_factory=list)
    evidence_policy: dict[str, Any] = field(default_factory=dict)
    target_handle_kind: str = "none"
    target_handle_id: str = ""
    upstream_object_handle_ids: list[str] = field(default_factory=list)
    upstream_result_handle_ids: list[str] = field(default_factory=list)
    owner_task_id: str = ""
    arbitration_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CanonicalResult:
    result_kind: str
    ok: bool
    answer: str
    evidence_refs: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    bindings: dict[str, Any] = field(default_factory=dict)
    projection_policy: str = "do_not_persist"
    degraded_reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    object_handle_ids: list[str] = field(default_factory=list)
    result_handle_ids: list[str] = field(default_factory=list)
    primary_result_handle_id: str = ""
    degraded_reason_typed: str = ""
    presentation_hints: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WorkerResult:
    worker_name: str
    status: WorkerStatus = "ok"
    evidence_envelope: EvidenceEnvelope | None = None
    artifact_updates: list[EvidenceArtifact] = field(default_factory=list)
    canonical_result: CanonicalResult | None = None
    binding_candidates: list[BindingCandidate] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    emitted_object_handles: list[dict[str, Any]] = field(default_factory=list)
    emitted_result_handles: list[dict[str, Any]] = field(default_factory=list)
    binding_owner_task_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_name": self.worker_name,
            "status": self.status,
            "evidence_envelope": self.evidence_envelope.to_dict() if self.evidence_envelope is not None else None,
            "artifact_updates": [item.to_dict() for item in self.artifact_updates],
            "canonical_result": self.canonical_result.to_dict() if self.canonical_result is not None else None,
            "binding_candidates": [item.to_dict() for item in self.binding_candidates],
            "diagnostics": dict(self.diagnostics),
            "emitted_object_handles": [dict(item) for item in self.emitted_object_handles],
            "emitted_result_handles": [dict(item) for item in self.emitted_result_handles],
            "binding_owner_task_id": self.binding_owner_task_id,
        }


@dataclass(frozen=True, slots=True)
class WorkerExecutionPlan:
    worker_route: WorkerRoute = "none"
    request: WorkerRequest | None = None
    expected_result: Literal["evidence", "canonical", "clarification"] = "evidence"
    artifact_refs: list[str] = field(default_factory=list)
    candidate_refs: list[str] = field(default_factory=list)
    fallback_execution_kind: Literal["agent", "direct_tool", "none"] = "agent"
    cutover_mode: Literal["shadow", "primary", "disabled"] = "primary"

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_route": self.worker_route,
            "request": self.request.to_dict() if self.request is not None else None,
            "expected_result": self.expected_result,
            "artifact_refs": list(self.artifact_refs),
            "candidate_refs": list(self.candidate_refs),
            "fallback_execution_kind": self.fallback_execution_kind,
            "cutover_mode": self.cutover_mode,
        }
