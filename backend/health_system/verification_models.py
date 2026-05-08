from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

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
