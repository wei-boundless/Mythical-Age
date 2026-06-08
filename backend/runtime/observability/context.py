from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from runtime.trace import TraceContext


@dataclass(frozen=True, slots=True)
class ObservabilityContext:
    trace_id: str
    span_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    turn_run_id: str = ""
    task_run_id: str = ""
    graph_run_id: str = ""
    graph_id: str = ""
    node_id: str = ""
    work_order_id: str = ""
    runtime_run_id: str = ""
    runtime_event_id: str = ""
    execution_id: str = ""
    usage_id: str = ""
    artifact_ref: str = ""
    refs: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _compact(asdict(self))

    def to_trace_context(self) -> TraceContext:
        scope = {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "turn_run_id": self.turn_run_id,
            "task_run_id": self.task_run_id,
            "graph_run_id": self.graph_run_id,
            "graph_id": self.graph_id,
            "node_id": self.node_id,
            "work_order_id": self.work_order_id,
            **dict(self.attributes.get("scope") or {}),
        }
        refs = {
            "runtime_run_id": self.runtime_run_id,
            "runtime_event_id": self.runtime_event_id,
            "execution_id": self.execution_id,
            "usage_id": self.usage_id,
            "artifact_ref": self.artifact_ref,
            **dict(self.refs or {}),
        }
        return TraceContext(
            trace_id=self.trace_id,
            span_id=self.span_id,
            scope=_compact(scope),
            refs=_compact(refs),
        )

    @classmethod
    def from_trace_context(cls, context: TraceContext, *, attributes: dict[str, Any] | None = None) -> "ObservabilityContext":
        scope = dict(getattr(context, "scope", {}) or {})
        refs = dict(getattr(context, "refs", {}) or {})
        return cls(
            trace_id=str(getattr(context, "trace_id", "") or ""),
            span_id=str(getattr(context, "span_id", "") or ""),
            session_id=str(scope.get("session_id") or refs.get("session_id") or ""),
            turn_id=str(scope.get("turn_id") or refs.get("turn_id") or ""),
            turn_run_id=str(scope.get("turn_run_id") or refs.get("turn_run_id") or ""),
            task_run_id=str(scope.get("task_run_id") or refs.get("task_run_id") or ""),
            graph_run_id=str(scope.get("graph_run_id") or refs.get("graph_run_id") or ""),
            graph_id=str(scope.get("graph_id") or refs.get("graph_id") or ""),
            node_id=str(scope.get("node_id") or refs.get("node_id") or ""),
            work_order_id=str(scope.get("work_order_id") or refs.get("work_order_id") or ""),
            runtime_run_id=str(refs.get("runtime_run_id") or refs.get("run_id") or ""),
            runtime_event_id=str(refs.get("runtime_event_id") or ""),
            execution_id=str(refs.get("execution_id") or ""),
            usage_id=str(refs.get("usage_id") or ""),
            artifact_ref=str(refs.get("artifact_ref") or ""),
            refs=_compact(refs),
            attributes=_compact(attributes or {}),
        )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ObservabilityContext":
        data = dict(payload or {})
        if "runtime_observability" in data and isinstance(data.get("runtime_observability"), dict):
            data = dict(data.get("runtime_observability") or {})
        elif "observability" in data and isinstance(data.get("observability"), dict):
            data = dict(data.get("observability") or {})
        elif "runtime_trace" in data and isinstance(data.get("runtime_trace"), dict):
            trace = dict(data.get("runtime_trace") or {})
            return cls.from_trace_context(
                TraceContext(
                    trace_id=str(trace.get("trace_id") or ""),
                    span_id=str(trace.get("span_id") or ""),
                    scope=dict(trace.get("scope") or {}),
                    refs=dict(trace.get("refs") or {}),
                )
            )
        return cls(
            trace_id=str(data.get("trace_id") or ""),
            span_id=str(data.get("span_id") or ""),
            session_id=str(data.get("session_id") or ""),
            turn_id=str(data.get("turn_id") or ""),
            turn_run_id=str(data.get("turn_run_id") or ""),
            task_run_id=str(data.get("task_run_id") or ""),
            graph_run_id=str(data.get("graph_run_id") or ""),
            graph_id=str(data.get("graph_id") or ""),
            node_id=str(data.get("node_id") or ""),
            work_order_id=str(data.get("work_order_id") or ""),
            runtime_run_id=str(data.get("runtime_run_id") or ""),
            runtime_event_id=str(data.get("runtime_event_id") or ""),
            execution_id=str(data.get("execution_id") or ""),
            usage_id=str(data.get("usage_id") or ""),
            artifact_ref=str(data.get("artifact_ref") or ""),
            refs=_compact(dict(data.get("refs") or {})),
            attributes=_compact(dict(data.get("attributes") or {})),
        )

    def child(self, *, span_id: str, refs: dict[str, Any] | None = None, attributes: dict[str, Any] | None = None) -> "ObservabilityContext":
        return ObservabilityContext(
            **{
                **self.to_dict(),
                "span_id": str(span_id or ""),
                "refs": {**dict(self.refs or {}), **dict(refs or {})},
                "attributes": {**dict(self.attributes or {}), **dict(attributes or {})},
            }
        )


def coerce_observability_context(value: Any) -> ObservabilityContext | None:
    if value is None:
        return None
    if isinstance(value, ObservabilityContext):
        return value
    if isinstance(value, TraceContext):
        return ObservabilityContext.from_trace_context(value)
    if isinstance(value, dict):
        context = ObservabilityContext.from_payload(value)
        return context if context.trace_id else None
    return None


def runtime_trace_payload(context: ObservabilityContext | TraceContext | None) -> dict[str, Any]:
    resolved = coerce_observability_context(context)
    if resolved is None:
        return {}
    trace_context = resolved.to_trace_context()
    return {
        "trace_id": trace_context.trace_id,
        "span_id": trace_context.span_id,
        "scope": dict(trace_context.scope or {}),
        "refs": dict(trace_context.refs or {}),
    }


def observability_payload(context: ObservabilityContext | TraceContext | None) -> dict[str, Any]:
    resolved = coerce_observability_context(context)
    if resolved is None:
        return {}
    return {
        "runtime_observability": resolved.to_dict(),
        "runtime_trace": runtime_trace_payload(resolved),
    }


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in dict(payload or {}).items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, str):
            result[str(key)] = value[:1200]
        elif isinstance(value, (bool, int, float)):
            result[str(key)] = value
        elif isinstance(value, dict):
            nested = _compact(value)
            if nested:
                result[str(key)] = nested
        elif isinstance(value, (list, tuple)):
            items = list(value)[:20]
            if items:
                result[str(key)] = items
        else:
            result[str(key)] = str(value)[:400]
    return result
