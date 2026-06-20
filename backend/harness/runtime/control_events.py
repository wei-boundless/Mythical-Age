from __future__ import annotations

from dataclasses import asdict, dataclass, field
import time
import uuid
from typing import Any, Literal

from .agent_scope import AgentRunScope


RuntimeSignalVisibility = Literal["runtime_private", "model_visible", "public_projectable"]
RuntimeSignalConsumptionState = Literal["pending", "observed", "consumed", "terminal"]


@dataclass(frozen=True, slots=True)
class RuntimeSignalScope:
    session_id: str = ""
    agent_run_id: str = ""
    run_cell_id: str = ""
    turn_id: str = ""
    turn_run_id: str = ""
    task_run_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RuntimeSignalEnvelope:
    signal_id: str
    signal_type: str
    scope: RuntimeSignalScope
    source_authority: str
    payload: dict[str, Any] = field(default_factory=dict)
    visibility: RuntimeSignalVisibility = "runtime_private"
    consumption_state: RuntimeSignalConsumptionState = "pending"
    consumed_by: str = ""
    causation_id: str = ""
    correlation_id: str = ""
    created_at: float = 0.0
    authority: str = "harness.runtime.control_signal"

    def __post_init__(self) -> None:
        if self.authority != "harness.runtime.control_signal":
            raise ValueError("RuntimeSignalEnvelope authority must be harness.runtime.control_signal")
        if not self.signal_id:
            raise ValueError("RuntimeSignalEnvelope requires signal_id")
        if not self.signal_type:
            raise ValueError("RuntimeSignalEnvelope requires signal_type")
        if not self.source_authority:
            raise ValueError("RuntimeSignalEnvelope requires source_authority")

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "signal_type": self.signal_type,
            "scope": self.scope.to_dict(),
            "source_authority": self.source_authority,
            "payload": dict(self.payload or {}),
            "visibility": self.visibility,
            "consumption_state": self.consumption_state,
            "consumed_by": self.consumed_by,
            "causation_id": self.causation_id,
            "correlation_id": self.correlation_id,
            "created_at": self.created_at,
            "authority": self.authority,
        }


def signal_scope_from_agent_scope(scope: AgentRunScope | None = None, **overrides: Any) -> RuntimeSignalScope:
    base = scope.to_dict() if isinstance(scope, AgentRunScope) else {}
    return RuntimeSignalScope(
        session_id=str(overrides.get("session_id") or base.get("session_id") or ""),
        agent_run_id=str(overrides.get("agent_run_id") or base.get("agent_run_id") or ""),
        run_cell_id=str(overrides.get("run_cell_id") or base.get("run_cell_id") or ""),
        turn_id=str(overrides.get("turn_id") or base.get("turn_id") or ""),
        turn_run_id=str(overrides.get("turn_run_id") or base.get("turn_run_id") or ""),
        task_run_id=str(overrides.get("task_run_id") or base.get("task_run_id") or ""),
    )


def build_runtime_signal_envelope(
    *,
    signal_type: str,
    scope: RuntimeSignalScope,
    source_authority: str,
    payload: dict[str, Any] | None = None,
    visibility: RuntimeSignalVisibility = "runtime_private",
    consumption_state: RuntimeSignalConsumptionState = "pending",
    consumed_by: str = "",
    causation_id: str = "",
    correlation_id: str = "",
    signal_id: str = "",
    created_at: float | None = None,
) -> RuntimeSignalEnvelope:
    normalized_signal_type = str(signal_type or "").strip()
    return RuntimeSignalEnvelope(
        signal_id=str(signal_id or "").strip() or f"rtsig:{normalized_signal_type}:{uuid.uuid4().hex[:16]}",
        signal_type=normalized_signal_type,
        scope=scope,
        source_authority=str(source_authority or "").strip(),
        payload=dict(payload or {}),
        visibility=visibility,
        consumption_state=consumption_state,
        consumed_by=str(consumed_by or "").strip(),
        causation_id=str(causation_id or "").strip(),
        correlation_id=str(correlation_id or "").strip(),
        created_at=time.time() if created_at is None else float(created_at or 0.0),
    )


def runtime_signal_from_event_payload(payload: dict[str, Any]) -> RuntimeSignalEnvelope | None:
    envelope = dict(payload.get("signal") or payload or {})
    if not envelope:
        return None
    scope_payload = dict(envelope.get("scope") or {})
    try:
        return RuntimeSignalEnvelope(
            signal_id=str(envelope.get("signal_id") or ""),
            signal_type=str(envelope.get("signal_type") or ""),
            scope=RuntimeSignalScope(
                session_id=str(scope_payload.get("session_id") or ""),
                agent_run_id=str(scope_payload.get("agent_run_id") or ""),
                run_cell_id=str(scope_payload.get("run_cell_id") or ""),
                turn_id=str(scope_payload.get("turn_id") or ""),
                turn_run_id=str(scope_payload.get("turn_run_id") or ""),
                task_run_id=str(scope_payload.get("task_run_id") or ""),
            ),
            source_authority=str(envelope.get("source_authority") or ""),
            payload=dict(envelope.get("payload") or {}),
            visibility=str(envelope.get("visibility") or "runtime_private"),  # type: ignore[arg-type]
            consumption_state=str(envelope.get("consumption_state") or "pending"),  # type: ignore[arg-type]
            consumed_by=str(envelope.get("consumed_by") or ""),
            causation_id=str(envelope.get("causation_id") or ""),
            correlation_id=str(envelope.get("correlation_id") or ""),
            created_at=float(envelope.get("created_at") or 0.0),
            authority=str(envelope.get("authority") or "harness.runtime.control_signal"),
        )
    except (TypeError, ValueError):
        return None
