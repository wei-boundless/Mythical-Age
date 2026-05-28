from __future__ import annotations

from runtime.shared.models import AgentRun, AgentRunResult, CoordinationRun, TaskRun
from runtime.memory.state_index import RuntimeStateIndex


def test_state_index_compacts_task_run_heavy_diagnostics(tmp_path) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:heavy",
            session_id="session",
            task_id="task.heavy",
            diagnostics={
                "graph_harness_config_payload": {
                    "config_id": "ghcfg:graph.heavy:test",
                    "graph_id": "graph.heavy",
                    "graph_title": "Heavy Graph",
                    "nodes": [{"node_id": "a"}],
                    "edges": [],
                    "modules": [],
                    "status": "published",
                },
            },
        )
    )

    snapshot = state_index.read_snapshot()
    stored = snapshot["task_runs"]["taskrun:heavy"]
    diagnostics = stored["diagnostics"]

    assert "graph_harness_config_payload" not in diagnostics
    assert diagnostics["graph_harness_config_ref"].startswith("rtobj:graph_harness_configs:")
    assert diagnostics["graph_harness_config_summary"]["config_id"] == "ghcfg:graph.heavy:test"


def test_state_index_compacts_coordination_run_heavy_diagnostics(tmp_path) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    state_index.upsert_coordination_run(
        CoordinationRun(
            coordination_run_id="coordrun:heavy",
            task_run_id="taskrun:heavy",
            graph_ref="graph.heavy",
            coordinator_agent_id="agent:0",
            diagnostics={
                "graph_harness_config_payload": {
                    "config_id": "ghcfg:graph.heavy:test",
                    "graph_id": "graph.heavy",
                    "graph_title": "Heavy Graph",
                    "nodes": [{"node_id": "a"}],
                    "edges": [{"source_node_id": "a", "target_node_id": "b"}],
                    "modules": [],
                    "status": "published",
                },
                "coordination_graph_spec": {
                    "graph_id": "graph.heavy",
                    "nodes": [{"node_id": "a"}],
                    "edges": [{"from_node_id": "a", "to_node_id": "b"}],
                },
                "graph_coordination_state": {
                    "active_stage_id": "a",
                    "running_nodes": ["a"],
                    "completed_nodes": ["root"],
                    "working_memory_operations": [{"operation": "read"}],
                },
                "task_graph_scheduler_state": {
                    "node_statuses": {"a": "running"},
                    "running_nodes": ["a"],
                },
            },
        )
    )

    snapshot = state_index.read_snapshot()
    stored = snapshot["coordination_runs"]["coordrun:heavy"]
    diagnostics = stored["diagnostics"]

    assert "graph_harness_config_payload" not in diagnostics
    assert "coordination_graph_spec" not in diagnostics
    assert "graph_coordination_state" not in diagnostics
    assert "task_graph_scheduler_state" not in diagnostics
    assert diagnostics["graph_harness_config_ref"].startswith("rtobj:graph_harness_configs:")
    assert diagnostics["graph_harness_config_summary"]["edge_count"] == 1
    assert diagnostics["coordination_graph_spec_ref"].startswith("rtobj:coordination_graph_specs:")
    assert diagnostics["graph_coordination_state_summary"]["running_nodes"] == ["a"]
    assert diagnostics["graph_coordination_state_summary"]["completed_node_count"] == 1


def test_state_index_prunes_task_run_records_and_rebuilds_indexes(tmp_path) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    state_index.upsert_task_run(TaskRun(task_run_id="taskrun:keep", session_id="session", task_id="task.keep", updated_at=20))
    state_index.upsert_task_run(TaskRun(task_run_id="taskrun:delete", session_id="session", task_id="task.delete", updated_at=30))
    state_index.upsert_agent_run(AgentRun(agent_run_id="agentrun:delete", task_run_id="taskrun:delete", agent_id="agent:0", agent_profile_id="main"))
    state_index.upsert_agent_run_result(AgentRunResult(agent_run_result_id="agresult:delete", agent_run_id="agentrun:delete", task_run_id="taskrun:delete", agent_id="agent:0", status="completed"))
    state_index.upsert_coordination_run(CoordinationRun(coordination_run_id="coordrun:delete", task_run_id="taskrun:delete", graph_ref="graph", coordinator_agent_id="agent:0"))

    result = state_index.prune_task_runs({"taskrun:delete"})
    snapshot = state_index.read_snapshot()

    assert result["deleted_task_run_ids"] == ["taskrun:delete"]
    assert "taskrun:delete" not in snapshot["task_runs"]
    assert "taskrun:keep" in snapshot["task_runs"]
    assert snapshot["sessions"]["session"] == ["taskrun:keep"]
    assert snapshot["session_latest_task_runs"]["session"] == "taskrun:keep"
    assert snapshot["agent_runs"] == {}
    assert snapshot["agent_run_results"] == {}
    assert snapshot["coordination_runs"] == {}


