from __future__ import annotations

from harness.runtime.single_agent_host import SingleAgentRuntimeHost
from runtime.shared.models import TaskRun


def test_runtime_monitor_projects_fact_trace_summaries_without_raw_payload(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path)
    task_run_id = "taskrun:monitor-trace"
    session_id = "session:monitor-trace"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id="task:monitor-trace",
            execution_runtime_kind="single_agent_task",
            status="running",
            created_at=100.0,
            updated_at=130.0,
        )
    )
    trace = host.trace_service.start_trace(
        run_kind="task_executor",
        root_run_id=task_run_id,
        scope={"session_id": session_id, "task_run_id": task_run_id},
        refs={"task_run_id": task_run_id},
        attributes={"prompt": "must not leak to monitor"},
        idempotency_key="task-executor:monitor-trace",
        started_at=101.0,
    )
    span = host.trace_service.start_span(
        trace,
        name="tool.dispatch",
        span_kind="tool",
        refs={"execution_id": "rtexec:monitor-trace"},
        attributes={"tool_args": {"secret": "must not leak"}},
        idempotency_key="tool:monitor-trace",
        started_at=102.0,
    )
    host.trace_service.record_event(
        span,
        name="tool.result_recorded",
        refs={"execution_id": "rtexec:monitor-trace"},
        attributes={"payload": "must not leak"},
        idempotency_key="tool-result:monitor-trace",
        created_at=103.0,
    )
    host.trace_service.finish_span(span, status="ok", ended_at=104.0)
    host.trace_service.finish_trace(trace, status="completed", ended_at=105.0)
    host.event_log.append(
        task_run_id,
        "task_run_lifecycle_finished",
        payload={
            "task_run_id": task_run_id,
            "task_run": {"task_run_id": task_run_id, "session_id": session_id},
            "execution_receipt": {"execution_id": "rtexec:monitor-trace"},
        },
        refs={"task_run_ref": task_run_id, "trace_id": trace.trace_id},
    )

    monitor = host.runtime_monitor_service.get_task_run_live_monitor(task_run_id)

    assert monitor is not None
    assert monitor["fact_summary"]["available"] is True
    assert monitor["fact_summary"]["fact_type_counts"]["trace_run"] == 1
    assert monitor["fact_summary"]["fact_type_counts"]["trace_span"] == 1
    assert monitor["fact_summary"]["fact_type_counts"]["runtime_event"] == 1
    assert monitor["trace_summary"]["available"] is True
    assert monitor["trace_summary"]["hydrated"] is True
    assert monitor["trace_summary"]["trace_id"] == trace.trace_id
    assert monitor["trace_summary"]["run"]["run_kind"] == "task_executor"
    assert monitor["trace_summary"]["run"]["status"] == "completed"
    assert monitor["trace_summary"]["span_count"] == 1
    assert monitor["trace_summary"]["event_count"] == 1
    assert monitor["trace_summary"]["latest_span"]["name"] == "tool.dispatch"
    assert monitor["trace_summary"]["latest_span"]["refs"]["execution_id"] == "rtexec:monitor-trace"
    assert "attributes" not in monitor["trace_summary"]["run"]
    assert "attributes" not in monitor["trace_summary"]["latest_span"]
    assert "error" not in monitor["trace_summary"]["latest_span"]
    assert any(item["kind"] == "trace" and item["trace_id"] == trace.trace_id for item in monitor["diagnostic_signal_refs"])
    assert any(item["kind"] == "fact_scope" for item in monitor["diagnostic_signal_refs"])


def test_runtime_monitor_uses_observability_query_for_trace_summary(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path)
    task_run_id = "taskrun:monitor-observability-query"
    session_id = "session:monitor-observability-query"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id="task:monitor-observability-query",
            execution_runtime_kind="single_agent_task",
            status="running",
            created_at=100.0,
            updated_at=130.0,
        )
    )
    query = _TraceSummaryQueryStub()
    host.runtime_monitor_service.projector.observability_query = query
    host.runtime_monitor_service.projector.fact_ledger = None
    host.runtime_monitor_service.projector.trace_service = None

    monitor = host.runtime_monitor_service.get_task_run_live_monitor(task_run_id)

    assert monitor is not None
    assert query.calls == [
        {
            "task_run_id": task_run_id,
            "session_id": session_id,
            "graph_run_id": "",
            "hydrate": True,
        }
    ]
    assert monitor["trace_summary"]["authority"] == "runtime_monitor.trace_summary"
    assert monitor["trace_summary"]["source_authority"] == "runtime.observability.trace_summary"
    assert monitor["trace_summary"]["trace_id"] == "trace:from-observability-query"
    assert monitor["trace_summary"]["latest_span"]["name"] == "tool.read_file"
    assert any(item["kind"] == "trace" and item["trace_id"] == "trace:from-observability-query" for item in monitor["diagnostic_signal_refs"])


def test_runtime_monitor_global_signal_reuses_compact_projection_summary(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path)
    task_run_id = "taskrun:monitor-signal"
    session_id = "session:monitor-signal"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id="task:monitor-signal",
            execution_runtime_kind="single_agent_task",
            status="running",
            created_at=100.0,
            updated_at=130.0,
        )
    )
    trace = host.trace_service.start_trace(
        run_kind="task_executor",
        root_run_id=task_run_id,
        scope={"session_id": session_id, "task_run_id": task_run_id},
        refs={"task_run_id": task_run_id},
        attributes={"prompt": "must not leak to monitor signal"},
        idempotency_key="task-executor:monitor-signal",
        started_at=101.0,
    )
    host.event_log.append(
        task_run_id,
        "task_run_lifecycle_started",
        payload={"task_run_id": task_run_id, "task_run": {"task_run_id": task_run_id, "session_id": session_id}},
        refs={"task_run_ref": task_run_id, "trace_id": trace.trace_id},
    )

    monitor = host.runtime_monitor_service.collect_global_runtime_monitor(limit=10)
    signal = next(item for item in monitor["signals"] if item["task_run_id"] == task_run_id)

    assert signal["fact_summary"]["available"] is False
    assert signal["fact_summary"]["deferred"] is True
    assert signal["fact_summary"]["fact_type_counts"] == {}
    assert signal["trace_summary"]["available"] is False
    assert signal["trace_summary"]["deferred"] is True
    assert signal["trace_summary"]["hydrated"] is False
    assert signal["trace_summary"]["trace_id"] == ""
    assert "run" not in signal["trace_summary"]
    assert "latest_span" not in signal["trace_summary"]
    assert signal["diagnostic_signal_refs"] == []

    detail = host.runtime_monitor_service.get_task_run_live_monitor(task_run_id)
    assert detail is not None
    assert detail["fact_summary"]["available"] is True
    assert detail["fact_summary"]["fact_type_counts"]["trace_run"] == 1
    assert detail["fact_summary"]["fact_type_counts"]["runtime_event"] == 1
    assert detail["trace_summary"]["available"] is True
    assert detail["trace_summary"]["trace_id"] == trace.trace_id
    assert any(item["kind"] == "trace" and item["trace_id"] == trace.trace_id for item in detail["diagnostic_signal_refs"])


def test_runtime_monitor_summarizes_graph_run_scoped_facts(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path)
    task_run_id = "taskrun:monitor-graph"
    session_id = "session:monitor-graph"
    graph_run_id = "grun:monitor-graph"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id="task:monitor-graph",
            execution_runtime_kind="task_graph",
            status="running",
            created_at=100.0,
            updated_at=130.0,
            diagnostics={
                "graph_id": "graph:monitor",
                "graph_run_id": graph_run_id,
                "graph_harness_config_id": "ghcfg:monitor",
            },
        )
    )
    trace = host.trace_service.start_trace(
        run_kind="task_graph",
        root_run_id=graph_run_id,
        scope={"session_id": session_id, "graph_run_id": graph_run_id},
        refs={"graph_run_id": graph_run_id},
        idempotency_key="task-graph:monitor-graph",
        started_at=101.0,
    )
    host.fact_ledger.record_fact(
        fact_type="health_issue",
        scope={"session_id": session_id, "graph_run_id": graph_run_id},
        refs={"trace_id": trace.trace_id},
        summary="graph scoped diagnostic",
        idempotency_key="health:monitor-graph",
        created_at=102.0,
    )

    monitor = host.runtime_monitor_service.get_task_run_live_monitor(task_run_id)

    assert monitor is not None
    assert monitor["fact_summary"]["graph_run_id"] == graph_run_id
    assert monitor["fact_summary"]["fact_type_counts"]["trace_run"] == 1
    assert monitor["fact_summary"]["fact_type_counts"]["health_issue"] == 1
    assert monitor["trace_summary"]["trace_id"] == trace.trace_id
    assert monitor["trace_summary"]["run"]["run_kind"] == "task_graph"
    assert any(item.get("graph_run_id") == graph_run_id and item["kind"] == "fact" for item in monitor["diagnostic_signal_refs"])


class _TraceSummaryQueryStub:
    def __init__(self) -> None:
        self.calls = []

    def trace_summary(self, *, task_run_id: str, session_id: str, graph_run_id: str, hydrate: bool) -> dict[str, object]:
        self.calls.append(
            {
                "task_run_id": task_run_id,
                "session_id": session_id,
                "graph_run_id": graph_run_id,
                "hydrate": hydrate,
            }
        )
        return {
            "authority": "runtime.observability.trace_summary",
            "available": True,
            "hydrated": hydrate,
            "trace_id": "trace:from-observability-query",
            "task_run_id": task_run_id,
            "session_id": session_id,
            "graph_run_id": graph_run_id,
            "detail_ref": {"kind": "trace", "trace_id": "trace:from-observability-query"},
            "run": {"trace_id": "trace:from-observability-query", "run_kind": "task_executor", "status": "running"},
            "span_count": 1,
            "event_count": 0,
            "error_span_count": 0,
            "latest_span": {"trace_id": "trace:from-observability-query", "name": "tool.read_file", "span_kind": "tool"},
        }
