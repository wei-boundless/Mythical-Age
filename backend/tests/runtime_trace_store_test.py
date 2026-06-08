from __future__ import annotations

import tempfile

from runtime.facts import RuntimeFactLedger
from runtime.trace import RuntimeTraceService


def test_runtime_trace_service_records_spans_events_and_fact_refs(tmp_path) -> None:
    ledger = RuntimeFactLedger(tmp_path)
    trace_service = RuntimeTraceService(tmp_path, fact_ledger=ledger)

    root = trace_service.start_trace(
        run_kind="task_run",
        root_run_id="taskrun:a",
        scope={"session_id": "session:a", "task_run_id": "taskrun:a"},
        refs={"task_run_id": "taskrun:a"},
        idempotency_key="taskrun:a",
    )
    span = trace_service.start_span(
        root,
        name="model.invoke",
        span_kind="model",
        refs={"usage_id": "usage:a"},
        idempotency_key="model:usage:a",
    )
    event = trace_service.record_event(span, name="model.provider_usage_recorded", refs={"usage_id": "usage:a"})
    finished = trace_service.finish_span(span, status="ok")
    run = trace_service.finish_trace(root, status="completed")

    assert event.trace_id == root.trace_id
    assert finished is not None
    assert finished.status == "ok"
    assert run is not None
    assert run.status == "completed"
    summary = trace_service.summarize_trace(root.trace_id)
    assert summary["span_count"] == 1
    assert summary["event_count"] == 1
    span_facts = ledger.list_records(trace_id=root.trace_id, fact_type="trace_span")
    assert len(span_facts) == 1
    assert span_facts[0].refs["usage_id"] == "usage:a"


def test_runtime_trace_store_prunes_task_run_diagnostics(tmp_path) -> None:
    trace_service = RuntimeTraceService(tmp_path)
    root = trace_service.start_trace(
        run_kind="task_run",
        root_run_id="taskrun:delete",
        scope={"session_id": "session:delete", "task_run_id": "taskrun:delete"},
    )
    span = trace_service.start_span(root, name="tool.dispatch", span_kind="tool")
    trace_service.finish_span(span, status="ok")

    result = trace_service.prune_task_runs({"taskrun:delete"})

    assert result["deleted_counts"]["trace_runs"] == 1
    assert result["deleted_counts"]["trace_spans"] == 1
    assert trace_service.summarize_trace(root.trace_id)["available"] is False


def test_runtime_trace_service_scopes_span_and_event_idempotency_by_trace(tmp_path) -> None:
    trace_service = RuntimeTraceService(tmp_path)
    first_root = trace_service.start_trace(
        run_kind="task_run",
        root_run_id="taskrun:first",
        scope={"task_run_id": "taskrun:first"},
        idempotency_key="taskrun:first",
    )
    second_root = trace_service.start_trace(
        run_kind="task_run",
        root_run_id="taskrun:second",
        scope={"task_run_id": "taskrun:second"},
        idempotency_key="taskrun:second",
    )

    first_span = trace_service.start_span(first_root, name="model.invoke", idempotency_key="model:shared")
    duplicate_span = trace_service.start_span(first_root, name="model.invoke", idempotency_key="model:shared")
    second_span = trace_service.start_span(second_root, name="model.invoke", idempotency_key="model:shared")
    first_event = trace_service.record_event(first_span, name="usage.recorded", idempotency_key="usage:shared")
    duplicate_event = trace_service.record_event(first_span, name="usage.recorded", idempotency_key="usage:shared")
    second_event = trace_service.record_event(second_span, name="usage.recorded", idempotency_key="usage:shared")

    assert duplicate_span.span_id == first_span.span_id
    assert second_span.span_id != first_span.span_id
    assert duplicate_event.event_id == first_event.event_id
    assert second_event.event_id != first_event.event_id
    assert trace_service.summarize_trace(first_root.trace_id)["span_count"] == 1
    assert trace_service.summarize_trace(second_root.trace_id)["span_count"] == 1


def test_runtime_trace_service_duplicate_start_does_not_reset_terminal_state(tmp_path) -> None:
    trace_service = RuntimeTraceService(tmp_path)
    root = trace_service.start_trace(
        run_kind="task_run",
        root_run_id="taskrun:terminal",
        scope={"task_run_id": "taskrun:terminal"},
        idempotency_key="taskrun:terminal",
    )
    span = trace_service.start_span(root, name="model.invoke", idempotency_key="model:terminal")
    trace_service.finish_span(span, status="ok")
    trace_service.finish_trace(root, status="completed")

    duplicate_root = trace_service.start_trace(
        run_kind="task_run",
        root_run_id="taskrun:terminal",
        scope={"task_run_id": "taskrun:terminal"},
        idempotency_key="taskrun:terminal",
    )
    duplicate_span = trace_service.start_span(duplicate_root, name="model.invoke", idempotency_key="model:terminal")
    summary = trace_service.summarize_trace(root.trace_id)

    assert duplicate_root.trace_id == root.trace_id
    assert duplicate_span.span_id == span.span_id
    assert summary["run"]["status"] == "completed"
    assert summary["latest_span"]["status"] == "ok"


def test_runtime_trace_service_returns_existing_identity_for_idempotency_conflict(tmp_path) -> None:
    trace_service = RuntimeTraceService(tmp_path)
    first_root = trace_service.start_trace(
        run_kind="task_run",
        root_run_id="taskrun:first",
        trace_id="trace:explicit:first",
        idempotency_key="taskrun:shared",
    )
    second_root = trace_service.start_trace(
        run_kind="task_run",
        root_run_id="taskrun:second",
        trace_id="trace:explicit:second",
        idempotency_key="taskrun:shared",
    )
    first_span = trace_service.start_span(
        first_root,
        name="tool.dispatch",
        span_id="span:explicit:first",
        idempotency_key="span:shared",
    )
    second_span = trace_service.start_span(
        first_root,
        name="tool.dispatch",
        span_id="span:explicit:second",
        idempotency_key="span:shared",
    )

    assert second_root.trace_id == first_root.trace_id
    assert second_span.span_id == first_span.span_id
    assert trace_service.summarize_trace(first_root.trace_id)["span_count"] == 1


def test_runtime_trace_store_closes_sqlite_handles_for_temp_directory_cleanup() -> None:
    with tempfile.TemporaryDirectory() as root_dir:
        trace_service = RuntimeTraceService(root_dir)
        root = trace_service.start_trace(run_kind="task_run", root_run_id="taskrun:cleanup")
        span = trace_service.start_span(root, name="tool.dispatch")
        trace_service.finish_span(span, status="ok")
        trace_service.finish_trace(root, status="completed")
