from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class HealthVerificationRun:
    verification_run_id: str
    source_run_ref: str
    profile: str
    status: str
    verdict: str
    summary: dict[str, Any] = field(default_factory=dict)
    artifact_refs: tuple[str, ...] = ()
    issue_refs: tuple[str, ...] = ()
    scenario_refs: tuple[str, ...] = ()
    started_at: float = 0.0
    finished_at: float = 0.0
    authority: str = "health_system.verification_run"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("artifact_refs", "issue_refs", "scenario_refs"):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True, slots=True)
class RegressionGateDecision:
    gate_decision_id: str
    profile: str
    passed: bool
    total: int
    failed: int
    blocker_refs: tuple[str, ...] = ()
    result_refs: tuple[str, ...] = ()
    summary: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "health_system.regression_gate_decision"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blocker_refs"] = list(payload["blocker_refs"])
        payload["result_refs"] = list(payload["result_refs"])
        return payload
