from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import api.sessions as sessions_api
from harness.runtime.session_lifecycle import SessionRuntimeLifecycleManager
from runtime.shared.models import TaskRun, TurnRun
from tests.graph_harness_api_regression import GRAPH_TEST_SCOPE, _graph, _harness_runtime_with_graph_executor
from task_system.compiler.graph_harness_config_publisher import build_graph_harness_config_from_graph


def test_session_runtime_lifecycle_detaches_session_without_deleting_graph_or_logs(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    runtime = _harness_runtime_with_graph_executor(base_dir=backend_dir)
    session = runtime.session_manager.create_session(title="Delete graph session", scope=GRAPH_TEST_SCOPE)
    session_id = str(session["id"])
    graph_config = build_graph_harness_config_from_graph(graph=_graph())
    started = runtime.harness_runtime.graph_harness.start_run(
        session_id=session_id,
        task_id="task.test.lifecycle",
        graph_config=graph_config,
        initial_inputs={},
        dispatch_ready=False,
    )
    graph_run_id = started.graph_run.graph_run_id
    task_run_id = started.task_run.task_run_id
    runtime.session_manager.bind_session_graph_instance(
        session_id,
        graph_run_id=graph_run_id,
        task_run_id=task_run_id,
        graph_id=graph_config.graph_id,
        graph_harness_config_id=graph_config.config_id,
        session_scope=GRAPH_TEST_SCOPE,
    )
    host = runtime.harness_runtime.single_agent_runtime_host
    chat_run = host.run_registry.create_run(session_id=session_id)
    host.event_log.append(chat_run.event_log_id, "chat_run_started", payload={"session_id": session_id})
    host.event_log.append(task_run_id, "test_event", payload={"graph_run_id": graph_run_id})

    result = asyncio.run(SessionRuntimeLifecycleManager(runtime).detach_session_runtime(session_id))

    assert "graph_run_ids" not in result
    assert runtime.harness_runtime.graph_harness.get_graph_run(graph_run_id) is not None
    assert host.state_index.get_task_run(task_run_id) is None
    assert host.run_registry.list_session_runs(session_id) == []
    assert host.event_log.list_events(task_run_id) != []
    assert host.event_log.list_events(chat_run.event_log_id) != []
    assert runtime.session_manager.get_history(session_id)["task_binding"]["graph_run_id"] == graph_run_id


def test_session_runtime_lifecycle_prunes_orphan_runtime_after_session_file_is_missing(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    runtime = _harness_runtime_with_graph_executor(base_dir=backend_dir)
    session = runtime.session_manager.create_session(title="Delete orphan runtime", scope=GRAPH_TEST_SCOPE)
    session_id = str(session["id"])
    host = runtime.harness_runtime.single_agent_runtime_host
    task_run_id = f"taskrun:turn:{session_id}:1:test"
    turn_run_id = f"turnrun:turn:{session_id}:1"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id=f"task:turn:{session_id}:1",
            execution_runtime_kind="single_agent_task",
            status="running",
            created_at=1.0,
            updated_at=2.0,
            diagnostics={"executor_status": "running"},
        )
    )
    host.state_index.upsert_turn_run(
        TurnRun(
            turn_run_id=turn_run_id,
            session_id=session_id,
            turn_id=f"turn:{session_id}:1",
            status="running",
            created_at=1.0,
            updated_at=2.0,
        )
    )
    runtime.session_manager.delete_session(session_id)

    result = asyncio.run(SessionRuntimeLifecycleManager(runtime).detach_session_runtime(session_id))

    assert result["task_run_ids"] == [task_run_id]
    assert result["turn_run_ids"] == [turn_run_id]
    assert host.state_index.get_task_run(task_run_id) is None
    assert host.state_index.get_turn_run(turn_run_id) is None
    assert host.state_index.list_session_task_runs(session_id) == []
    assert host.state_index.list_recent_task_runs(limit=20) == []
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id=f"task:turn:{session_id}:1",
            execution_runtime_kind="single_agent_task",
            status="running",
            created_at=3.0,
            updated_at=4.0,
        )
    )
    assert host.state_index.get_task_run(task_run_id) is None


def test_delete_session_api_detaches_runtime_without_memory_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _harness_runtime_with_graph_executor(base_dir=tmp_path / "backend")
    session = runtime.session_manager.create_session(title="Delete through API", scope={})
    session_id = str(session["id"])
    host = runtime.harness_runtime.single_agent_runtime_host
    task_run_id = f"taskrun:turn:{session_id}:1:test"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id=f"task:turn:{session_id}:1",
            execution_runtime_kind="single_agent_task",
            status="completed",
            created_at=1.0,
            updated_at=2.0,
        )
    )

    def fail_memory_delete(_session_id: str) -> bool:
        raise AssertionError("session delete must not delete memory")

    monkeypatch.setattr(sessions_api, "require_runtime", lambda: runtime)
    monkeypatch.setattr(runtime, "memory_facade", SimpleNamespace(delete_session_memory=fail_memory_delete), raising=False)

    result = asyncio.run(
        sessions_api.delete_session(
            session_id,
            workspace_view=None,
            task_environment_id=None,
            project_id=None,
        )
    )

    assert result["ok"] is True
    assert "graph_run_ids" not in result["cleanup"]
    assert host.state_index.get_task_run(task_run_id) is None
    with pytest.raises(ValueError, match="Unknown session_id"):
        runtime.session_manager.get_history(session_id)
