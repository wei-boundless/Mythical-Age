from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ExecutionObligation:
    obligation_id: str
    user_goal: str
    required_reads: tuple[dict[str, Any], ...] = ()
    required_writes: tuple[dict[str, Any], ...] = ()
    required_commands: tuple[dict[str, Any], ...] = ()
    required_deliverables: tuple[str, ...] = ()
    required_verifications: tuple[dict[str, Any], ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    confidence: float = 0.0
    extraction_evidence: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.execution_obligation"

    def __post_init__(self) -> None:
        if self.authority != "runtime.execution_obligation":
            raise ValueError("ExecutionObligation authority must be runtime.execution_obligation")
        if not self.obligation_id:
            raise ValueError("ExecutionObligation requires obligation_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_reads"] = [dict(item) for item in self.required_reads]
        payload["required_writes"] = [dict(item) for item in self.required_writes]
        payload["required_commands"] = [dict(item) for item in self.required_commands]
        payload["required_deliverables"] = list(self.required_deliverables)
        payload["required_verifications"] = [dict(item) for item in self.required_verifications]
        payload["forbidden_actions"] = list(self.forbidden_actions)
        return payload


def execution_obligation_from_payload(payload: dict[str, Any] | None) -> ExecutionObligation | None:
    item = dict(payload or {})
    if not item:
        return None
    try:
        return ExecutionObligation(
            obligation_id=str(item.get("obligation_id") or ""),
            user_goal=str(item.get("user_goal") or ""),
            required_reads=tuple(dict(value) for value in list(item.get("required_reads") or []) if isinstance(value, dict)),
            required_writes=tuple(dict(value) for value in list(item.get("required_writes") or []) if isinstance(value, dict)),
            required_commands=tuple(dict(value) for value in list(item.get("required_commands") or []) if isinstance(value, dict)),
            required_deliverables=tuple(
                str(value).strip() for value in list(item.get("required_deliverables") or []) if str(value).strip()
            ),
            required_verifications=tuple(
                dict(value) for value in list(item.get("required_verifications") or []) if isinstance(value, dict)
            ),
            forbidden_actions=tuple(
                str(value).strip() for value in list(item.get("forbidden_actions") or []) if str(value).strip()
            ),
            confidence=float(item.get("confidence") or 0.0),
            extraction_evidence=dict(item.get("extraction_evidence") or {}),
        )
    except (TypeError, ValueError):
        return None
