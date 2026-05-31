from __future__ import annotations

from harness.graph.models import GraphHarnessConfig
from harness.graph.state_machine import GraphStateMachine


def test_terminal_completion_waits_for_active_parallel_work() -> None:
    graph_config = GraphHarnessConfig(
        config_id="config:test",
        graph_id="graph:test",
        graph_title="Parallel Terminal",
        publish_version="test",
        content_hash="hash:test",
        control={"terminal_node_ids": ["terminal"]},
        nodes=(
            {"node_id": "terminal", "node_type": "agent"},
            {"node_id": "parallel", "node_type": "agent"},
        ),
        edges=(),
    )

    snapshot = GraphStateMachine().status_snapshot(
        graph_config=graph_config,
        node_states={
            "terminal": {"node_id": "terminal", "status": "completed"},
            "parallel": {"node_id": "parallel", "status": "running"},
        },
        active_work_orders={"parallel": "work:parallel"},
    )

    assert snapshot.status == "running"
    assert snapshot.terminal_result_status == ""
    assert snapshot.terminal_reason == "terminal_nodes_completed_pending_active"
    assert snapshot.running_node_ids == ("parallel",)
