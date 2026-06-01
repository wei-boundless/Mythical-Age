from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ObservationRecord:
    observation_id: str
    source: str
    packet_ref: str
    action_request_ref: str = ""
    execution_context_ref: str = ""
    receipt_ref: str = ""
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: float = 0.0
    authority: str = "harness.loop.observation"

    def __post_init__(self) -> None:
        if self.authority != "harness.loop.observation":
            raise ValueError("ObservationRecord authority must be harness.loop.observation")
        if not self.observation_id:
            raise ValueError("ObservationRecord requires observation_id")
        if not self.packet_ref:
            raise ValueError("ObservationRecord requires packet_ref")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_observation_record(
    *,
    source: str,
    packet_ref: str,
    action_request_ref: str = "",
    execution_context_ref: str = "",
    receipt_ref: str = "",
    summary: str = "",
    payload: dict[str, Any] | None = None,
    error: str = "",
) -> ObservationRecord:
    return ObservationRecord(
        observation_id=f"obs:{uuid.uuid4().hex[:12]}",
        source=str(source or ""),
        packet_ref=packet_ref,
        action_request_ref=action_request_ref,
        execution_context_ref=execution_context_ref,
        receipt_ref=receipt_ref,
        summary=str(summary or ""),
        payload=dict(payload or {}),
        error=str(error or ""),
        created_at=time.time(),
    )


def structured_error_from_exception(exc: Exception) -> dict[str, Any]:
    payload = getattr(exc, "structured_error", None)
    if not isinstance(payload, dict):
        return {}
    return {
        key: value
        for key, value in {
            "code": str(payload.get("code") or payload.get("error_code") or "tool_error"),
            "message": str(payload.get("message") or str(exc) or ""),
            "retryable": payload.get("retryable") if isinstance(payload.get("retryable"), bool) else True,
            "origin": str(payload.get("origin") or "tool_provider"),
            "status_code": payload.get("status_code") if isinstance(payload.get("status_code"), int) else None,
        }.items()
        if value not in ("", None)
    }
