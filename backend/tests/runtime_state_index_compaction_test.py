from __future__ import annotations

from orchestration.runtime_loop.models import CoordinationRun, TaskRun
from orchestration.runtime_loop.state_index import RuntimeStateIndex


def test_state_index_compacts_task_run_heavy_diagnostics(tmp_path) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:heavy",
            session_id="session",
            task_id="task.heavy",
            diagnostics={
                "task_graph_definition": {"graph_id": "graph.heavy", "nodes": [{"node_id": "a"}]},
                "task_graph_runtime_spec": {"graph_id": "graph.heavy", "nodes": [{"node_id": "a"}], "valid": True},
                "agent_dispatch_plan": {
                    "dispatch_plan_id": "dispatch:heavy",
                    "records": [{"node_id": "a"}],
                    "ready_node_ids": ["a"],
                },
            },
        )
    )

    snapshot = state_index.read_snapshot()
    stored = snapshot["task_runs"]["taskrun:heavy"]
    diagnostics = stored["diagnostics"]

    assert "task_graph_definition" not in diagnostics
    assert "task_graph_runtime_spec" not in diagnostics
    assert "agent_dispatch_plan" not in diagnostics
    assert diagnostics["task_graph_definition_ref"].startswith("rtobj:task_graph_definitions:")
    assert diagnostics["task_graph_runtime_spec_ref"].startswith("rtobj:task_graph_runtime_specs:")
    assert diagnostics["agent_dispatch_plan_ref"].startswith("rtobj:dispatch_plans:")
    assert diagnostics["agent_dispatch_plan_summary"]["record_count"] == 1


def test_state_index_compacts_coordination_run_heavy_diagnostics(tmp_path) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    state_index.upsert_coordination_run(
        CoordinationRun(
            coordination_run_id="coordrun:heavy",
            task_run_id="taskrun:heavy",
            graph_ref="graph.heavy",
            coordinator_agent_id="agent:0",
            diagnostics={
                "task_graph_definition": {"graph_id": "graph.heavy", "nodes": [{"node_id": "a"}]},
                "task_graph_runtime_spec": {"graph_id": "graph.heavy", "nodes": [{"node_id": "a"}], "valid": True},
                "coordination_graph_spec": {
                    "graph_id": "graph.heavy",
                    "nodes": [{"node_id": "a"}],
                    "edges": [{"from_node_id": "a", "to_node_id": "b"}],
                },
                "langgraph_runtime_state": {
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

    assert "task_graph_definition" not in diagnostics
    assert "task_graph_runtime_spec" not in diagnostics
    assert "coordination_graph_spec" not in diagnostics
    assert "langgraph_runtime_state" not in diagnostics
    assert "task_graph_scheduler_state" not in diagnostics
    assert diagnostics["task_graph_definition_ref"].startswith("rtobj:task_graph_definitions:")
    assert diagnostics["task_graph_runtime_spec_ref"].startswith("rtobj:task_graph_runtime_specs:")
    assert diagnostics["coordination_graph_spec_ref"].startswith("rtobj:coordination_graph_specs:")
    assert diagnostics["langgraph_runtime_state_summary"]["running_nodes"] == ["a"]
    assert diagnostics["langgraph_runtime_state_summary"]["completed_node_count"] == 1
