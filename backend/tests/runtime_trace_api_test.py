from __future__ import annotations

from types import SimpleNamespace

from api import runtime_trace as runtime_trace_api
from app import app
from harness.runtime.single_agent_host import SingleAgentRuntimeHost


def test_runtime_trace_and_fact_api_routes_are_registered() -> None:
    paths = {str(getattr(route, "path", "") or "") for route in app.routes}

    assert "/api/runtime/traces" in paths
    assert "/api/runtime/traces/{trace_id:path}" in paths
    assert "/api/runtime/facts" in paths
    assert "/api/runtime/facts/{fact_id:path}" in paths


def test_runtime_trace_api_returns_compact_trace_detail_without_raw_payload(tmp_path, monkeypatch) -> None:
    host = SingleAgentRuntimeHost(tmp_path)
    runtime = SimpleNamespace(harness_runtime=SimpleNamespace(single_agent_runtime_host=host))
    monkeypatch.setattr(runtime_trace_api, "require_runtime", lambda: runtime)
    trace = host.trace_service.start_trace(
        run_kind="task_executor",
        root_run_id="taskrun:trace-api",
        scope={"session_id": "session:trace-api", "task_run_id": "taskrun:trace-api"},
        refs={"task_run_id": "taskrun:trace-api"},
        attributes={"prompt": "must not leak"},
        idempotency_key="task-executor:trace-api",
        started_at=10.0,
    )
    span = host.trace_service.start_span(
        trace,
        name="model.invoke",
        span_kind="model",
        refs={"usage_id": "usage:trace-api"},
        attributes={"request": {"messages": ["must not leak"]}},
        idempotency_key="model:trace-api",
        started_at=11.0,
    )
    host.trace_service.record_event(
        span,
        name="model.provider_usage_recorded",
        refs={"usage_id": "usage:trace-api"},
        attributes={"payload": "must not leak"},
        idempotency_key="usage:trace-api",
        created_at=12.0,
    )
    host.trace_service.finish_span(span, status="ok", ended_at=13.0)
    host.trace_service.finish_trace(trace, status="completed", ended_at=14.0)

    detail = runtime_trace_api.get_runtime_trace(trace.trace_id, include_spans=True, include_events=True, limit=20)

    assert detail["authority"] == "runtime_trace.api.trace_detail"
    assert detail["summary"]["run"]["run_kind"] == "task_executor"
    assert detail["summary"]["span_count"] == 1
    assert detail["summary"]["event_count"] == 1
    assert detail["spans"][0]["name"] == "model.invoke"
    assert detail["spans"][0]["refs"]["usage_id"] == "usage:trace-api"
    assert detail["events"][0]["name"] == "model.provider_usage_recorded"
    assert "attributes" not in detail["summary"]["run"]
    assert "attributes" not in detail["spans"][0]
    assert "attributes" not in detail["events"][0]


def test_runtime_trace_api_lists_trace_refs_from_fact_ledger(tmp_path, monkeypatch) -> None:
    host = SingleAgentRuntimeHost(tmp_path)
    runtime = SimpleNamespace(harness_runtime=SimpleNamespace(single_agent_runtime_host=host))
    monkeypatch.setattr(runtime_trace_api, "require_runtime", lambda: runtime)
    trace = host.trace_service.start_trace(
        run_kind="task_graph",
        root_run_id="grun:trace-api",
        scope={"session_id": "session:trace-api", "graph_run_id": "grun:trace-api"},
        refs={"graph_run_id": "grun:trace-api"},
        idempotency_key="task-graph:trace-api",
        started_at=10.0,
    )

    result = runtime_trace_api.list_runtime_traces(graph_run_id="grun:trace-api", limit=10)

    assert result["authority"] == "runtime_trace.api.trace_index"
    assert result["count"] == 1
    assert result["traces"][0]["trace_id"] == trace.trace_id
    assert result["traces"][0]["run_kind"] == "task_graph"
