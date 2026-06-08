from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


TRACE_RUN_AUTHORITY = "runtime.trace.run"
TRACE_SPAN_AUTHORITY = "runtime.trace.span"
TRACE_EVENT_AUTHORITY = "runtime.trace.event"


@dataclass(frozen=True, slots=True)
class TraceContext:
    trace_id: str
    span_id: str = ""
    scope: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, Any] = field(default_factory=dict)

    def child(self, *, span_id: str, refs: dict[str, Any] | None = None) -> "TraceContext":
        return TraceContext(
            trace_id=self.trace_id,
            span_id=span_id,
            scope=dict(self.scope),
            refs={**dict(self.refs or {}), **dict(refs or {})},
        )


@dataclass(frozen=True, slots=True)
class RuntimeTraceRun:
    trace_id: str
    run_kind: str
    root_run_id: str = ""
    scope: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "running"
    terminal_reason: str = ""
    started_at: float = 0.0
    ended_at: float = 0.0
    idempotency_key: str = ""
    tombstoned: bool = False
    deleted_at: float = 0.0
    authority: str = TRACE_RUN_AUTHORITY

    def __post_init__(self) -> None:
        if self.authority != TRACE_RUN_AUTHORITY:
            raise ValueError("RuntimeTraceRun authority must be runtime.trace.run")
        if not self.trace_id:
            raise ValueError("RuntimeTraceRun requires trace_id")
        if not self.run_kind:
            raise ValueError("RuntimeTraceRun requires run_kind")
        if not self.idempotency_key:
            object.__setattr__(self, "idempotency_key", self.trace_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RuntimeTraceRun":
        data = dict(payload or {})
        return cls(
            trace_id=str(data.get("trace_id") or ""),
            run_kind=str(data.get("run_kind") or ""),
            root_run_id=str(data.get("root_run_id") or ""),
            scope=dict(data.get("scope") or {}),
            refs=dict(data.get("refs") or {}),
            attributes=dict(data.get("attributes") or {}),
            status=str(data.get("status") or "running"),
            terminal_reason=str(data.get("terminal_reason") or ""),
            started_at=float(data.get("started_at") or 0.0),
            ended_at=float(data.get("ended_at") or 0.0),
            idempotency_key=str(data.get("idempotency_key") or data.get("trace_id") or ""),
            tombstoned=bool(data.get("tombstoned", False)),
            deleted_at=float(data.get("deleted_at") or 0.0),
            authority=str(data.get("authority") or TRACE_RUN_AUTHORITY),
        )


@dataclass(frozen=True, slots=True)
class RuntimeTraceSpan:
    trace_id: str
    span_id: str
    name: str
    parent_span_id: str = ""
    span_kind: str = "internal"
    scope: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "running"
    error: dict[str, Any] = field(default_factory=dict)
    started_at: float = 0.0
    ended_at: float = 0.0
    idempotency_key: str = ""
    tombstoned: bool = False
    deleted_at: float = 0.0
    authority: str = TRACE_SPAN_AUTHORITY

    def __post_init__(self) -> None:
        if self.authority != TRACE_SPAN_AUTHORITY:
            raise ValueError("RuntimeTraceSpan authority must be runtime.trace.span")
        if not self.trace_id:
            raise ValueError("RuntimeTraceSpan requires trace_id")
        if not self.span_id:
            raise ValueError("RuntimeTraceSpan requires span_id")
        if not self.name:
            raise ValueError("RuntimeTraceSpan requires name")
        if not self.idempotency_key:
            object.__setattr__(self, "idempotency_key", self.span_id)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["latency_ms"] = latency_ms(self.started_at, self.ended_at)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RuntimeTraceSpan":
        data = dict(payload or {})
        return cls(
            trace_id=str(data.get("trace_id") or ""),
            span_id=str(data.get("span_id") or ""),
            name=str(data.get("name") or ""),
            parent_span_id=str(data.get("parent_span_id") or ""),
            span_kind=str(data.get("span_kind") or "internal"),
            scope=dict(data.get("scope") or {}),
            refs=dict(data.get("refs") or {}),
            attributes=dict(data.get("attributes") or {}),
            status=str(data.get("status") or "running"),
            error=dict(data.get("error") or {}),
            started_at=float(data.get("started_at") or 0.0),
            ended_at=float(data.get("ended_at") or 0.0),
            idempotency_key=str(data.get("idempotency_key") or data.get("span_id") or ""),
            tombstoned=bool(data.get("tombstoned", False)),
            deleted_at=float(data.get("deleted_at") or 0.0),
            authority=str(data.get("authority") or TRACE_SPAN_AUTHORITY),
        )


@dataclass(frozen=True, slots=True)
class RuntimeTraceEvent:
    trace_id: str
    event_id: str
    name: str
    span_id: str = ""
    scope: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    idempotency_key: str = ""
    tombstoned: bool = False
    deleted_at: float = 0.0
    authority: str = TRACE_EVENT_AUTHORITY

    def __post_init__(self) -> None:
        if self.authority != TRACE_EVENT_AUTHORITY:
            raise ValueError("RuntimeTraceEvent authority must be runtime.trace.event")
        if not self.trace_id:
            raise ValueError("RuntimeTraceEvent requires trace_id")
        if not self.event_id:
            raise ValueError("RuntimeTraceEvent requires event_id")
        if not self.name:
            raise ValueError("RuntimeTraceEvent requires name")
        if not self.idempotency_key:
            object.__setattr__(self, "idempotency_key", self.event_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RuntimeTraceEvent":
        data = dict(payload or {})
        return cls(
            trace_id=str(data.get("trace_id") or ""),
            event_id=str(data.get("event_id") or ""),
            name=str(data.get("name") or ""),
            span_id=str(data.get("span_id") or ""),
            scope=dict(data.get("scope") or {}),
            refs=dict(data.get("refs") or {}),
            attributes=dict(data.get("attributes") or {}),
            created_at=float(data.get("created_at") or 0.0),
            idempotency_key=str(data.get("idempotency_key") or data.get("event_id") or ""),
            tombstoned=bool(data.get("tombstoned", False)),
            deleted_at=float(data.get("deleted_at") or 0.0),
            authority=str(data.get("authority") or TRACE_EVENT_AUTHORITY),
        )


def latency_ms(started_at: float, ended_at: float) -> float:
    if not started_at or not ended_at:
        return 0.0
    return round(max(0.0, float(ended_at) - float(started_at)) * 1000.0, 2)
