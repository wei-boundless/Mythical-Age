from __future__ import annotations

from runtime.shared.models import AgentRun, AgentRunResult, ProjectRuntimeStatus, TaskRun
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


def test_state_index_compacts_current_graph_harness_diagnostics_only_on_task_run(tmp_path) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:graph",
            session_id="session",
            task_id="task.graph",
            diagnostics={
                "graph_harness_config": {
                    "config_id": "ghcfg:graph.heavy:test",
                    "graph_id": "graph.heavy",
                    "graph_title": "Heavy Graph",
                    "nodes": [{"node_id": "a"}, {"node_id": "b"}],
                    "edges": [{"source_node_id": "a", "target_node_id": "b"}],
                    "modules": [{"module_id": "draft"}],
                    "config_schema_version": "graph_harness_config.v1",
                    "content_hash": "sha256:test",
                    "status": "published",
                },
            },
        )
    )

    snapshot = state_index.read_snapshot()
    stored = snapshot["task_runs"]["taskrun:graph"]
    diagnostics = stored["diagnostics"]

    assert "graph_harness_config" not in diagnostics
    assert diagnostics["graph_harness_config_ref"].startswith("rtobj:graph_harness_configs:")
    assert diagnostics["graph_harness_config_summary"]["edge_count"] == 1
    assert diagnostics["graph_harness_config_summary"]["node_count"] == 2
    assert diagnostics["graph_harness_config_summary"]["module_count"] == 1


def test_state_index_prunes_task_run_records_and_rebuilds_indexes(tmp_path) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    state_index.upsert_task_run(TaskRun(task_run_id="taskrun:keep", session_id="session", task_id="task.keep", updated_at=20))
    state_index.upsert_task_run(TaskRun(task_run_id="taskrun:delete", session_id="session", task_id="task.delete", updated_at=30))
    state_index.upsert_agent_run(AgentRun(agent_run_id="agentrun:delete", task_run_id="taskrun:delete", agent_id="agent:0", agent_profile_id="main"))
    state_index.upsert_agent_run_result(AgentRunResult(agent_run_result_id="agresult:delete", agent_run_id="agentrun:delete", task_run_id="taskrun:delete", agent_id="agent:0", status="completed"))
    state_index.upsert_project_runtime_status(
        ProjectRuntimeStatus(
            project_id="project:delete",
            session_id="session",
            graph_id="graph:delete",
            active_task_run_id="taskrun:delete",
            active_run_status="running",
            project_runtime_status="watching",
        )
    )

    result = state_index.prune_task_runs({"taskrun:delete"})
    snapshot = state_index.read_snapshot()

    assert result["deleted_task_run_ids"] == ["taskrun:delete"]
    assert "taskrun:delete" not in snapshot["task_runs"]
    assert "taskrun:keep" in snapshot["task_runs"]
    assert snapshot["sessions"]["session"] == ["taskrun:keep"]
    assert snapshot["session_latest_task_runs"]["session"] == "taskrun:keep"
    assert snapshot["agent_runs"] == {}
    assert snapshot["agent_run_results"] == {}
    assert snapshot["project_runtime_statuses"]["project:delete"]["active_task_run_id"] == ""
    assert "taskrun:delete" not in snapshot["task_project_status"]
    state_index.upsert_task_run(TaskRun(task_run_id="taskrun:delete", session_id="session", task_id="task.delete", updated_at=40))
    state_index.upsert_agent_run(AgentRun(agent_run_id="agentrun:late", task_run_id="taskrun:delete", agent_id="agent:0", agent_profile_id="main"))
    state_index.upsert_agent_run_result(AgentRunResult(agent_run_result_id="agresult:late", agent_run_id="agentrun:late", task_run_id="taskrun:delete", agent_id="agent:0", status="completed"))
    assert state_index.get_task_run("taskrun:delete") is None
    assert state_index.list_task_agent_runs("taskrun:delete") == []
    assert state_index.list_task_agent_run_results("taskrun:delete") == []


def test_state_index_indexed_lookups_do_not_load_full_record_buckets(tmp_path, monkeypatch) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:indexed",
            session_id="session:indexed",
            task_id="task.indexed",
            updated_at=20,
        )
    )
    state_index.upsert_agent_run(
        AgentRun(
            agent_run_id="agentrun:indexed",
            task_run_id="taskrun:indexed",
            agent_id="agent:0",
            agent_profile_id="main",
        )
    )
    state_index.upsert_agent_run_result(
        AgentRunResult(
            agent_run_result_id="agresult:indexed",
            agent_run_id="agentrun:indexed",
            task_run_id="taskrun:indexed",
            agent_id="agent:0",
            status="completed",
        )
    )

    def _fail_full_bucket_read(bucket: str) -> dict[str, object]:
        raise AssertionError(f"unexpected full bucket read: {bucket}")

    monkeypatch.setattr(state_index, "_read_record_bucket", _fail_full_bucket_read)

    assert [item.task_run_id for item in state_index.list_session_task_runs("session:indexed")] == ["taskrun:indexed"]
    assert [item.agent_run_id for item in state_index.list_task_agent_runs("taskrun:indexed")] == ["agentrun:indexed"]
    assert [item.agent_run_result_id for item in state_index.list_task_agent_run_results("taskrun:indexed")] == ["agresult:indexed"]


