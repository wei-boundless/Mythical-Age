from __future__ import annotations

from typing import Any

from .context import ObservabilityContext, coerce_observability_context, observability_payload, runtime_trace_payload
from .lifecycle import RuntimeObservabilityLifecycle
from .query import RuntimeObservabilityQuery
from .sinks import RuntimeEventLogSink, RuntimeFactSink, RuntimeTraceSink


class RuntimeObservabilityRecorder:
    authority = "runtime.observability.recorder"

    def __init__(
        self,
        *,
        event_sink: RuntimeEventLogSink,
        trace_sink: RuntimeTraceSink,
        fact_sink: RuntimeFactSink,
    ) -> None:
        self.event_sink = event_sink
        self.trace_sink = trace_sink
        self.fact_sink = fact_sink

    def start_run(self, *, run_kind: str, **kwargs: Any) -> ObservabilityContext | None:
        return self.trace_sink.start_run(run_kind=run_kind, **kwargs)

    def finish_run(self, context: Any, *, status: str, **kwargs: Any) -> Any | None:
        return self.trace_sink.finish_run(context, status=status, **kwargs)

    def start_span(self, context: Any, *, name: str, **kwargs: Any) -> ObservabilityContext | None:
        return self.trace_sink.start_span(context, name=name, **kwargs)

    def finish_span(self, context: Any, **kwargs: Any) -> Any | None:
        return self.trace_sink.finish_span(context, **kwargs)

    def record_event(self, context: Any, *, name: str, **kwargs: Any) -> Any | None:
        return self.trace_sink.record_event(context, name=name, **kwargs)

    def record_runtime_event(
        self,
        run_id: str,
        event_type: Any,
        *,
        payload: dict[str, Any] | None = None,
        refs: dict[str, Any] | None = None,
    ) -> Any | None:
        return self.event_sink.append_recovery_event(run_id, event_type, payload=payload, refs=refs)

    def record_fact(self, **kwargs: Any) -> Any | None:
        return self.fact_sink.record_fact(**kwargs)

    def context_payload(self, context: Any) -> dict[str, Any]:
        return observability_payload(coerce_observability_context(context))

    def runtime_trace_payload(self, context: Any) -> dict[str, Any]:
        return runtime_trace_payload(coerce_observability_context(context))

    def trace_context_from_payload(self, payload: dict[str, Any]) -> ObservabilityContext | None:
        return coerce_observability_context(payload)


class RuntimeObservabilityKernel:
    authority = "runtime.observability.kernel"

    def __init__(self, *, event_log: Any | None, trace_service: Any | None, fact_ledger: Any | None) -> None:
        self.event_sink = RuntimeEventLogSink(event_log)
        self.trace_sink = RuntimeTraceSink(trace_service)
        self.fact_sink = RuntimeFactSink(fact_ledger)
        self.recorder = RuntimeObservabilityRecorder(
            event_sink=self.event_sink,
            trace_sink=self.trace_sink,
            fact_sink=self.fact_sink,
        )
        self.query = RuntimeObservabilityQuery(trace_sink=self.trace_sink, fact_sink=self.fact_sink)
        self.lifecycle = RuntimeObservabilityLifecycle(
            event_sink=self.event_sink,
            trace_sink=self.trace_sink,
            fact_sink=self.fact_sink,
        )

    def start_run(self, **kwargs: Any) -> ObservabilityContext | None:
        return self.recorder.start_run(**kwargs)

    def finish_run(self, context: Any, **kwargs: Any) -> Any | None:
        return self.recorder.finish_run(context, **kwargs)

    def start_span(self, context: Any, **kwargs: Any) -> ObservabilityContext | None:
        return self.recorder.start_span(context, **kwargs)

    def finish_span(self, context: Any, **kwargs: Any) -> Any | None:
        return self.recorder.finish_span(context, **kwargs)

    def record_event(self, context: Any, **kwargs: Any) -> Any | None:
        return self.recorder.record_event(context, **kwargs)

    def record_runtime_event(self, *args: Any, **kwargs: Any) -> Any | None:
        return self.recorder.record_runtime_event(*args, **kwargs)

    def record_fact(self, **kwargs: Any) -> Any | None:
        return self.recorder.record_fact(**kwargs)

    def context_payload(self, context: Any) -> dict[str, Any]:
        return self.recorder.context_payload(context)

    def runtime_trace_payload(self, context: Any) -> dict[str, Any]:
        return self.recorder.runtime_trace_payload(context)

    def trace_context_from_payload(self, payload: dict[str, Any]) -> ObservabilityContext | None:
        return self.recorder.trace_context_from_payload(payload)
