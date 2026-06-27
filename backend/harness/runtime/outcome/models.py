from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


RunOutcomeStatus = Literal["completed", "partial", "blocked", "failed", "aborted"]
EvidenceConfidence = Literal["none", "claimed", "observed", "verified"]


@dataclass(frozen=True, slots=True)
class RunOutcome:
    outcome_id: str
    task_run_id: str
    task_id: str
    execution_runtime_kind: str
    source: str
    status: RunOutcomeStatus
    completed: bool
    terminal_reason: str
    user_visible_status: str
    summary: str = ""
    evidence_confidence: EvidenceConfidence = "none"
    verification_passed: bool = False
    completion_allowed: bool = False
    completion_judgment_ref: str = ""
    verification_ref: str = ""
    evidence_packet_ref: str = ""
    satisfied_deliverables: tuple[str, ...] = ()
    missing_deliverables: tuple[str, ...] = ()
    unsatisfied_obligations: tuple[str, ...] = ()
    missing_output_paths: tuple[str, ...] = ()
    unsupported_claims: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    changed_files: tuple[str, ...] = ()
    verification_refs: tuple[str, ...] = ()
    observation_refs: tuple[str, ...] = ()
    resume_recommended: bool = False
    resume_reason: str = ""
    next_required_actions: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.run_outcome"

    def __post_init__(self) -> None:
        if self.authority != "harness.runtime.run_outcome":
            raise ValueError("RunOutcome authority must be harness.runtime.run_outcome")
        if not self.outcome_id:
            raise ValueError("RunOutcome requires outcome_id")
        if not self.task_run_id:
            raise ValueError("RunOutcome requires task_run_id")
        if self.completed != (self.status == "completed"):
            raise ValueError("RunOutcome.completed must match status == completed")
        if self.completed and not self.completion_allowed:
            raise ValueError("completed RunOutcome requires completion_allowed")
        if self.completed and not self.verification_passed:
            raise ValueError("completed RunOutcome requires verification_passed")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "satisfied_deliverables",
            "missing_deliverables",
            "unsatisfied_obligations",
            "missing_output_paths",
            "unsupported_claims",
            "limitations",
            "artifact_refs",
            "changed_files",
            "verification_refs",
            "observation_refs",
            "next_required_actions",
        ):
            payload[key] = list(getattr(self, key))
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


