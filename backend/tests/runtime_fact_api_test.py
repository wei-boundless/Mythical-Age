from __future__ import annotations

from types import SimpleNamespace

from api import runtime_facts as runtime_facts_api
from harness.runtime.single_agent_host import SingleAgentRuntimeHost


def test_runtime_facts_api_lists_records_without_attributes_by_default(tmp_path, monkeypatch) -> None:
    host = SingleAgentRuntimeHost(tmp_path)
    runtime = SimpleNamespace(harness_runtime=SimpleNamespace(single_agent_runtime_host=host))
    monkeypatch.setattr(runtime_facts_api, "require_runtime", lambda: runtime)
    fact = host.fact_ledger.record_fact(
        fact_type="health_issue",
        scope={"session_id": "session:fact-api", "task_run_id": "taskrun:fact-api"},
        refs={"trace_id": "trace:fact-api"},
        attributes={"internal_payload": "must not leak by default"},
        summary="diagnostic fact",
        idempotency_key="health:fact-api",
        created_at=10.0,
    )

    result = runtime_facts_api.list_runtime_facts(task_run_id="taskrun:fact-api", limit=10)

    assert result["authority"] == "runtime_facts.api.fact_index"
    assert result["count"] == 1
    assert result["records"][0]["fact_id"] == fact.fact_id
    assert result["records"][0]["refs"]["trace_id"] == "trace:fact-api"
    assert "attributes" not in result["records"][0]


def test_runtime_facts_api_can_include_attributes_and_get_detail(tmp_path, monkeypatch) -> None:
    host = SingleAgentRuntimeHost(tmp_path)
    runtime = SimpleNamespace(harness_runtime=SimpleNamespace(single_agent_runtime_host=host))
    monkeypatch.setattr(runtime_facts_api, "require_runtime", lambda: runtime)
    fact = host.fact_ledger.record_fact(
        fact_type="monitor_signal",
        scope={"session_id": "session:fact-api", "graph_run_id": "grun:fact-api"},
        refs={"trace_id": "trace:fact-api"},
        attributes={"severity": "warning"},
        summary="monitor signal",
        idempotency_key="monitor-signal:fact-api",
        created_at=10.0,
    )

    indexed = runtime_facts_api.list_runtime_facts(
        graph_run_id="grun:fact-api",
        fact_type="monitor_signal",
        include_attributes=True,
        limit=10,
    )
    detail = runtime_facts_api.get_runtime_fact(fact.fact_id, include_attributes=True)

    assert indexed["count"] == 1
    assert indexed["records"][0]["attributes"]["severity"] == "warning"
    assert detail["authority"] == "runtime_facts.api.fact_detail"
    assert detail["record"]["fact_id"] == fact.fact_id
    assert detail["record"]["attributes"]["severity"] == "warning"
