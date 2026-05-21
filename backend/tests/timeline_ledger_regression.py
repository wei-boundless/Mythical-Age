from __future__ import annotations

from runtime.memory.timeline_ledger import TimelineLedgerStore


def test_timeline_ledger_appends_monotonic_events_by_coordination_run(tmp_path) -> None:
    store = TimelineLedgerStore(tmp_path)

    first = store.append_event(
        coordination_run_id="coordrun:test",
        root_task_run_id="taskrun:test",
        graph_id="graph:test",
        event_type="run_started",
        scope_path=["run"],
        idempotency_key="run:start",
    )
    same = store.append_event(
        coordination_run_id="coordrun:test",
        root_task_run_id="taskrun:test",
        graph_id="graph:test",
        event_type="run_started",
        scope_path=["run"],
        idempotency_key="run:start",
    )
    second = store.append_event(
        coordination_run_id="coordrun:test",
        root_task_run_id="taskrun:test",
        graph_id="graph:test",
        event_type="node_dispatch_requested",
        scope_path=["run", "phase.design"],
        node_id="design",
    )

    snapshot = store.snapshot("coordrun:test")

    assert first.clock_seq == 1
    assert same.event_id == first.event_id
    assert second.clock_seq == 2
    assert snapshot["current_clock_seq"] == 2
    assert [event["event_type"] for event in snapshot["recent_events"]] == [
        "run_started",
        "node_dispatch_requested",
    ]
    assert snapshot["recent_events"][1]["scope_path"] == ["run", "phase.design"]
