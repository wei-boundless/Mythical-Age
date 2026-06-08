from __future__ import annotations

from typing import Any

from .sinks import RuntimeEventLogSink, RuntimeFactSink, RuntimeTraceSink


class RuntimeObservabilityLifecycle:
    authority = "runtime.observability.lifecycle"

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

    def prune_task_runs(self, task_run_ids: set[str] | list[str] | tuple[str, ...]) -> dict[str, Any]:
        targets = {str(item).strip() for item in list(task_run_ids or []) if str(item).strip()}
        event_deleted = {target: self.event_sink.delete_events(target) for target in sorted(targets)}
        return {
            "authority": self.authority,
            "operation": "prune_task_runs",
            "requested_targets": sorted(targets),
            "event_log_deleted": event_deleted,
            "trace_store": self.trace_sink.prune_task_runs(targets),
            "fact_ledger": self.fact_sink.prune_task_runs(targets),
        }

    def prune_session(self, session_id: str) -> dict[str, Any]:
        normalized = str(session_id or "").strip()
        return {
            "authority": self.authority,
            "operation": "prune_session",
            "session_id": normalized,
            "trace_store": self.trace_sink.prune_session(normalized),
            "fact_ledger": self.fact_sink.prune_session(normalized),
        }
