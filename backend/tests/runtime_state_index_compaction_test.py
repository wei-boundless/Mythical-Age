from __future__ import annotations

from dataclasses import replace

import pytest

from runtime.shared.models import AgentRun, AgentRunResult, ProjectRuntimeStatus, TaskRun
from runtime.memory.state_index import RuntimeStateIndex


def test_formal_run_models_reject_noncanonical_statuses() -> None:
    with pytest.raises(ValueError, match="TaskRun status must be canonical"):
        TaskRun(task_run_id="taskrun:legacy", session_id="session", task_id="task", status="stopped")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="AgentRun status must be canonical"):
        AgentRun(
            agent_run_id="agrun:legacy",
            task_run_id="taskrun:legacy",
            agent_id="agent:0",
            agent_profile_id="main",
            status="waiting_executor",  # type: ignore[arg-type]
        )


def test_state_index_rejects_noncanonical_run_statuses_on_read(tmp_path) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    state_index._write_record(
        "task_runs",
        "taskrun:legacy",
        {
            "task_run_id": "taskrun:legacy",
            "session_id": "session",
            "task_id": "task",
            "status": "stopped",
        },
    )
    state_index._write_record(
        "agent_runs",
        "agrun:legacy",
        {
            "agent_run_id": "agrun:legacy",
            "task_run_id": "taskrun:legacy",
            "agent_id": "agent:0",
            "agent_profile_id": "main",
            "status": "waiting_executor",
        },
    )
    state_index._append_index_id("task_agent_runs", "taskrun:legacy", "agrun:legacy")

    with pytest.raises(ValueError, match="TaskRun status is not canonical"):
        state_index.get_task_run("taskrun:legacy")

    with pytest.raises(ValueError, match="AgentRun status is not canonical"):
        state_index.list_task_agent_runs("taskrun:legacy")


def test_state_index_compacts_task_run_heavy_diagnostics(tmp_path) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:heavy",
            session_id="session",
            task_id="task.heavy",
            diagnostics={
                "graph_config_payload": {
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

    assert "graph_config_payload" not in diagnostics
    assert diagnostics["graph_config_ref"].startswith("rtobj:graph_configs:")
    assert diagnostics["graph_config_summary"]["config_id"] == "ghcfg:graph.heavy:test"


def test_state_index_compacts_current_graph_system_diagnostics_only_on_task_run(tmp_path) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:graph",
            session_id="session",
            task_id="task.graph",
            diagnostics={
                "graph_config": {
                    "config_id": "ghcfg:graph.heavy:test",
                    "graph_id": "graph.heavy",
                    "graph_title": "Heavy Graph",
                    "nodes": [{"node_id": "a"}, {"node_id": "b"}],
                    "edges": [{"source_node_id": "a", "target_node_id": "b"}],
                    "modules": [{"module_id": "draft"}],
                    "config_schema_version": "graph_config.v1",
                    "content_hash": "sha256:test",
                    "status": "published",
                },
            },
        )
    )

    snapshot = state_index.read_snapshot()
    stored = snapshot["task_runs"]["taskrun:graph"]
    diagnostics = stored["diagnostics"]

    assert "graph_config" not in diagnostics
    assert diagnostics["graph_config_ref"].startswith("rtobj:graph_configs:")
    assert diagnostics["graph_config_summary"]["edge_count"] == 1
    assert diagnostics["graph_config_summary"]["node_count"] == 2
    assert diagnostics["graph_config_summary"]["module_count"] == 1


def test_state_index_compacts_graph_result_diagnostics_to_runtime_object(tmp_path) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:graph-result",
            session_id="session",
            task_id="task.graph",
            diagnostics={
                "graph_result": {
                    "result_id": "result:graph",
                    "graph_run_id": "grun:graph",
                    "task_run_id": "taskrun:graph-result",
                    "graph_id": "graph.heavy",
                    "config_id": "ghcfg:graph.heavy:test",
                    "status": "completed",
                    "outputs": {"chapter": {"text": "large"}},
                    "artifact_refs": ["artifact:a"],
                    "node_result_refs": ["node:a", "node:b"],
                    "terminal_reason": "completed",
                    "diagnostics": {"large": ["x"] * 20},
                    "created_at": 10,
                },
            },
        )
    )

    stored = state_index.read_snapshot()["task_runs"]["taskrun:graph-result"]
    diagnostics = stored["diagnostics"]

    assert "graph_result" not in diagnostics
    assert diagnostics["graph_result_ref"].startswith("rtobj:graph_results:")
    assert diagnostics["graph_result_summary"]["graph_run_id"] == "grun:graph"
    assert diagnostics["graph_result_summary"]["node_result_ref_count"] == 2
    assert state_index.runtime_objects.get_object(diagnostics["graph_result_ref"])["result_id"] == "result:graph"


def test_state_index_update_task_run_applies_single_locked_record_update(tmp_path) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:update",
            session_id="session:update",
            task_id="task.update",
            updated_at=1,
            diagnostics={"approval_state": {"status": "approved"}},
        )
    )

    updated = state_index.update_task_run(
        "taskrun:update",
        lambda current: replace(
            current,
            updated_at=2,
            diagnostics={**dict(current.diagnostics or {}), "approval_state": {"status": "consumed"}},
        ),
    )

    stored = state_index.get_task_run("taskrun:update")
    assert updated is not None
    assert stored is not None
    assert stored.updated_at == 2
    assert stored.diagnostics["approval_state"]["status"] == "consumed"


def test_state_index_monitor_summaries_do_not_load_heavy_task_records(tmp_path, monkeypatch) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:heavy-monitor",
            session_id="session:monitor",
            task_id="task.monitor",
            status="waiting_executor",
            updated_at=20,
            diagnostics={
                "contract": {
                    "user_visible_goal": "保留给 monitor 的公开目标",
                    "large_private_contract": ["x"] * 10000,
                },
                "latest_step_summary": "等待继续",
                "runtime_control": {"state": "paused", "reason": "user"},
            },
        )
    )

    original_read_record = state_index._read_record

    def fail_heavy_task_read(bucket: str, record_id: str) -> dict[str, object]:
        if bucket == "task_runs":
            raise AssertionError("monitor summary path must not load full task_run records")
        return original_read_record(bucket, record_id)

    monkeypatch.setattr(state_index, "_read_record", fail_heavy_task_read)

    [summary] = state_index.list_recent_task_run_summaries(limit=10)

    assert summary.task_run_id == "taskrun:heavy-monitor"
    assert summary.diagnostics["contract"] == {"user_visible_goal": "保留给 monitor 的公开目标"}
    assert "large_private_contract" not in str(summary.diagnostics)
    assert summary.diagnostics["latest_step_summary"] == "等待继续"


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


def test_state_index_prune_task_runs_uses_incremental_indexes(tmp_path, monkeypatch) -> None:
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

    def _fail_full_snapshot_read() -> dict[str, object]:
        raise AssertionError("prune_task_runs must not read the full state index snapshot")

    monkeypatch.setattr(state_index, "_read", _fail_full_snapshot_read)

    result = state_index.prune_task_runs({"taskrun:delete"})

    assert result["deleted_task_run_ids"] == ["taskrun:delete"]
    assert state_index.get_task_run("taskrun:delete") is None
    assert [item.task_run_id for item in state_index.list_session_task_runs("session")] == ["taskrun:keep"]
    assert state_index.list_task_agent_runs("taskrun:delete") == []
    assert state_index.list_task_agent_run_results("taskrun:delete") == []
    status = state_index.get_project_runtime_status("project:delete")
    assert status is not None
    assert status.active_task_run_id == ""


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


def test_state_index_record_read_returns_default_when_file_is_temporarily_locked(tmp_path, monkeypatch) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    record_path = state_index._bucket_record_path("task_runs", "taskrun:locked")
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text('{"task_run_id":"taskrun:locked"}', encoding="utf-8")
    original_read_text = type(record_path).read_text

    def locked_read_text(self, *args, **kwargs):
        if self == record_path:
            raise PermissionError("file is temporarily locked")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(type(record_path), "read_text", locked_read_text)

    assert state_index.get_task_run("taskrun:locked") is None

