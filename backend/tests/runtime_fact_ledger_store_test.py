from __future__ import annotations

import tempfile

from runtime.facts import RuntimeFactLedger


def test_runtime_fact_ledger_records_idempotent_queryable_facts(tmp_path) -> None:
    ledger = RuntimeFactLedger(tmp_path)

    first = ledger.record_fact(
        fact_type="tool_execution",
        scope={"session_id": "session:a", "task_run_id": "taskrun:a"},
        source={"system": "execution_store", "source_ref": "rtexec:a"},
        refs={
            "execution_id": "rtexec:a",
            "trace_id": "trace:a",
            "agent_run_ref": "agentrun:a",
            "run_cell_ref": "runcell:a",
            "runtime_control_signal_ref": "rtsig:a",
            "evidence_projection_ref": "rtevp:a",
        },
        summary="tool executed",
        idempotency_key="tool:rtexec:a",
    )
    duplicate = ledger.record_fact(
        fact_type="tool_execution",
        scope={"session_id": "session:a", "task_run_id": "taskrun:a"},
        refs={"execution_id": "rtexec:a", "trace_id": "trace:a"},
        summary="duplicate should not create a second row",
        idempotency_key="tool:rtexec:a",
    )

    assert duplicate.fact_id == first.fact_id
    by_task = ledger.list_records(task_run_id="taskrun:a")
    by_execution = ledger.list_records(execution_id="rtexec:a")
    by_trace = ledger.list_records(trace_id="trace:a")
    by_agent_run = ledger.list_records(agent_run_ref="agentrun:a")
    by_run_cell = ledger.list_records(run_cell_ref="runcell:a")
    by_control_signal = ledger.list_records(runtime_control_signal_ref="rtsig:a")
    by_evidence_projection = ledger.list_records(evidence_projection_ref="rtevp:a")
    assert [item.fact_id for item in by_task] == [first.fact_id]
    assert [item.fact_id for item in by_execution] == [first.fact_id]
    assert [item.fact_id for item in by_trace] == [first.fact_id]
    assert [item.fact_id for item in by_agent_run] == [first.fact_id]
    assert [item.fact_id for item in by_run_cell] == [first.fact_id]
    assert [item.fact_id for item in by_control_signal] == [first.fact_id]
    assert [item.fact_id for item in by_evidence_projection] == [first.fact_id]


def test_runtime_fact_ledger_prunes_diagnostics_but_tombstones_memory_provenance(tmp_path) -> None:
    ledger = RuntimeFactLedger(tmp_path)
    diagnostic = ledger.record_fact(
        fact_type="trace_span",
        scope={"session_id": "session:a", "task_run_id": "taskrun:a"},
        refs={"trace_id": "trace:a", "span_id": "span:a"},
        summary="diagnostic span",
        idempotency_key="span:a",
    )
    memory = ledger.record_fact(
        fact_type="memory_commit",
        scope={"session_id": "session:a", "task_run_id": "taskrun:a"},
        refs={"memory_version_id": "memver:a"},
        attributes={"content_hash": "sha256:test"},
        retention_class="memory_governed",
        model_visibility="governed_memory_only",
        idempotency_key="memory:memver:a",
    )
    edge = ledger.link_facts(
        source_fact_id=diagnostic.fact_id,
        target_fact_id=memory.fact_id,
        relation="promoted_to_memory",
    )

    result = ledger.prune_task_runs({"taskrun:a"})

    assert result["deleted_count"] >= 1
    assert result["tombstoned_count"] >= 2
    assert ledger.list_records(task_run_id="taskrun:a") == []
    tombstones = ledger.list_records(task_run_id="taskrun:a", include_tombstones=True)
    tombstone_ids = {item.fact_id for item in tombstones if item.tombstoned}
    assert memory.fact_id in tombstone_ids
    assert diagnostic.fact_id not in tombstone_ids
    tombstone_edges = ledger.list_edges(include_tombstones=True)
    assert [item.edge_id for item in tombstone_edges] == [edge.edge_id]
    assert tombstone_edges[0].tombstoned is True


def test_runtime_fact_ledger_closes_sqlite_handles_for_temp_directory_cleanup() -> None:
    with tempfile.TemporaryDirectory() as root_dir:
        ledger = RuntimeFactLedger(root_dir)
        first = ledger.record_fact(
            fact_type="tool_execution",
            scope={"task_run_id": "taskrun:cleanup"},
            refs={"trace_id": "trace:cleanup"},
            idempotency_key="tool:cleanup",
        )
        ledger.link_facts(
            source_fact_id=first.fact_id,
            target_fact_id=first.fact_id,
            relation="self_test",
        )
