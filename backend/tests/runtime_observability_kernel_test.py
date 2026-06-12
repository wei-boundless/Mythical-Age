from __future__ import annotations

from harness.runtime.single_agent_host import SingleAgentRuntimeHost
from runtime.observability import ObservabilityContext


def test_runtime_observability_kernel_records_trace_and_runtime_event_without_duplicate_facts(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path)

    root = host.observability.start_run(
        run_kind="task_executor",
        root_run_id="taskrun:obs",
        scope={"session_id": "session:obs", "task_run_id": "taskrun:obs"},
        refs={"task_run_id": "taskrun:obs"},
        idempotency_key="task-executor:taskrun:obs:1",
    )
    assert isinstance(root, ObservabilityContext)
    assert root.trace_id
    assert root.task_run_id == "taskrun:obs"

    span = host.observability.start_span(
        root,
        name="tool.shell",
        span_kind="tool",
        refs={"execution_id": "rtexec:obs", "action_request_ref": "act:obs"},
        idempotency_key="tool:obs",
    )
    assert isinstance(span, ObservabilityContext)

    trace_event = host.observability.record_event(
        span,
        name="tool.observation_recorded",
        refs={"observation_ref": "toolobs:obs"},
        idempotency_key="tool-observation:obs",
    )
    assert trace_event is not None
    host.observability.finish_span(span, status="ok")
    host.observability.finish_run(root, status="completed", terminal_reason="test_completed")

    runtime_event = host.observability.record_runtime_event(
        "taskrun:obs",
        "task_run_lifecycle_finished",
        payload={
            "task_run_id": "taskrun:obs",
            "task_run": {"task_run_id": "taskrun:obs", "session_id": "session:obs"},
            "execution_receipt": {"execution_id": "rtexec:obs"},
        },
        refs={"task_run_ref": "taskrun:obs", "trace_id": root.trace_id},
    )
    assert runtime_event is not None

    summary = host.trace_service.summarize_trace(root.trace_id)
    assert summary["available"] is True
    assert summary["span_count"] == 1
    assert summary["event_count"] == 1
    assert summary["run"]["status"] == "completed"

    trace_summary = host.observability.query.trace_summary(task_run_id="taskrun:obs")
    assert trace_summary["trace_id"] == root.trace_id
    assert trace_summary["available"] is True
    assert trace_summary["hydrated"] is True

    runtime_facts = host.fact_ledger.list_records(task_run_id="taskrun:obs", fact_type="runtime_event")
    assert len(runtime_facts) == 1
    assert runtime_facts[0].refs["runtime_event_id"] == runtime_event.event_id
    assert runtime_facts[0].refs["trace_id"] == root.trace_id


def test_runtime_observability_context_payload_preserves_runtime_trace_projection_shape(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path)
    root = host.observability.start_run(
        run_kind="turn",
        root_run_id="turn:obs",
        scope={"session_id": "session:obs", "turn_id": "turn:obs"},
        refs={"turn_id": "turn:obs"},
        idempotency_key="turn:obs",
    )

    payload = host.observability.context_payload(root)

    assert payload["runtime_observability"]["trace_id"] == root.trace_id
    assert payload["runtime_trace"]["trace_id"] == root.trace_id
    assert payload["runtime_trace"]["scope"]["session_id"] == "session:obs"
    recovered = host.observability.trace_context_from_payload(payload)
    assert recovered is not None
    assert recovered.trace_id == root.trace_id
