from __future__ import annotations

from typing import Any

from runtime.trace import TraceContext

from .context import ObservabilityContext, coerce_observability_context


class RuntimeTraceSink:
    def __init__(self, trace_service: Any | None) -> None:
        self.trace_service = trace_service

    def start_run(self, **kwargs: Any) -> ObservabilityContext | None:
        starter = getattr(self.trace_service, "start_trace", None)
        if not callable(starter):
            return None
        context = starter(**kwargs)
        return ObservabilityContext.from_trace_context(context)

    def finish_run(self, context: Any, **kwargs: Any) -> Any | None:
        resolved = _trace_context(context)
        finisher = getattr(self.trace_service, "finish_trace", None)
        if resolved is None or not callable(finisher):
            return None
        return finisher(resolved, **kwargs)

    def start_span(self, context: Any, **kwargs: Any) -> ObservabilityContext | None:
        resolved = _trace_context(context)
        starter = getattr(self.trace_service, "start_span", None)
        if resolved is None or not callable(starter):
            return None
        span = starter(resolved, **kwargs)
        return ObservabilityContext.from_trace_context(span)

    def finish_span(self, context: Any, **kwargs: Any) -> Any | None:
        resolved = _trace_context(context)
        finisher = getattr(self.trace_service, "finish_span", None)
        if resolved is None or not callable(finisher):
            return None
        return finisher(resolved, **kwargs)

    def record_event(self, context: Any, **kwargs: Any) -> Any | None:
        resolved = _trace_context(context)
        recorder = getattr(self.trace_service, "record_event", None)
        if resolved is None or not callable(recorder):
            return None
        return recorder(resolved, **kwargs)

    def summarize_trace(self, trace_id: str) -> dict[str, Any]:
        summarizer = getattr(self.trace_service, "summarize_trace", None)
        if not callable(summarizer):
            return {"authority": "runtime.trace.summary", "trace_id": trace_id, "available": False}
        return dict(summarizer(trace_id) or {})

    def prune_task_runs(self, task_run_ids: set[str] | list[str] | tuple[str, ...]) -> dict[str, Any]:
        pruner = getattr(self.trace_service, "prune_task_runs", None)
        if not callable(pruner):
            return {}
        return dict(pruner(task_run_ids) or {})

    def prune_session(self, session_id: str) -> dict[str, Any]:
        pruner = getattr(self.trace_service, "prune_session", None)
        if not callable(pruner):
            return {}
        return dict(pruner(session_id) or {})


class RuntimeEventLogSink:
    def __init__(self, event_log: Any | None) -> None:
        self.event_log = event_log

    def append_recovery_event(
        self,
        run_id: str,
        event_type: Any,
        *,
        payload: dict[str, Any] | None = None,
        refs: dict[str, Any] | None = None,
    ) -> Any | None:
        appender = getattr(self.event_log, "append", None)
        if not callable(appender):
            return None
        return appender(run_id, event_type, payload=payload, refs=refs)

    def delete_events(self, run_id: str) -> bool:
        deleter = getattr(self.event_log, "delete_events", None)
        if not callable(deleter):
            return False
        return bool(deleter(run_id))


class RuntimeFactSink:
    def __init__(self, fact_ledger: Any | None) -> None:
        self.fact_ledger = fact_ledger

    def record_fact(self, **kwargs: Any) -> Any | None:
        recorder = getattr(self.fact_ledger, "record_fact", None)
        if not callable(recorder):
            return None
        return recorder(**kwargs)

    def list_records(self, **kwargs: Any) -> list[Any]:
        reader = getattr(self.fact_ledger, "list_records", None)
        if not callable(reader):
            return []
        return list(reader(**kwargs) or [])

    def prune_task_runs(self, task_run_ids: set[str] | list[str] | tuple[str, ...]) -> dict[str, Any]:
        pruner = getattr(self.fact_ledger, "prune_task_runs", None)
        if not callable(pruner):
            return {}
        return dict(pruner(task_run_ids) or {})

    def prune_session(self, session_id: str) -> dict[str, Any]:
        pruner = getattr(self.fact_ledger, "prune_session", None)
        if not callable(pruner):
            return {}
        return dict(pruner(session_id) or {})


def _trace_context(context: Any) -> TraceContext | None:
    resolved = coerce_observability_context(context)
    if resolved is None:
        return None
    return resolved.to_trace_context()
