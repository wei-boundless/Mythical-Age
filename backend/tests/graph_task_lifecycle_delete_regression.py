from __future__ import annotations

from pathlib import Path

from artifact_system.artifact_repository_models import ArtifactRecord, ArtifactRepository
from harness.graph.lifecycle_manager import GraphTaskLifecycleManager
from harness.graph.models import safe_id
from memory_system.formal_memory_models import FormalMemoryCollection, FormalMemoryRepository
from project_layout import ProjectLayout
from tests.graph_harness_api_regression import _graph, _runtime_with_graph_harness
from task_system.compiler.graph_harness_config_publisher import build_graph_harness_config_from_graph


def test_graph_task_delete_removes_run_scoped_memory_artifacts_and_runtime_state(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    graph_config = build_graph_harness_config_from_graph(graph=_graph())
    runtime = _runtime_with_graph_harness(base_dir=backend_dir, runtime_root=backend_dir / "storage" / "runtime_state")
    started = runtime.harness_runtime.graph_harness.start_run(
        session_id="session-delete",
        task_id="task.test.delete",
        graph_config=graph_config,
        initial_inputs={},
        dispatch_ready=False,
    )
    graph_run_id = started.graph_run.graph_run_id
    task_run_id = started.task_run.task_run_id
    project_id = started.task_run.diagnostics["runtime_scope"]["project_id"]
    namespace_id = started.task_run.diagnostics["runtime_scope"]["memory_namespace_id"]
    services = runtime.harness_runtime.graph_harness._services

    services.formal_memory_service.store.upsert_repository(
        FormalMemoryRepository(
            repository_id=f"run:{safe_id(namespace_id)}:memory.test",
            logical_repository_id="memory.test",
            task_run_id=task_run_id,
            scope_kind="run_scoped",
            scope_id=namespace_id,
            graph_id=graph_config.graph_id,
        )
    )
    services.formal_memory_service.store.upsert_collection(
        FormalMemoryCollection(
            repository_id=f"run:{safe_id(namespace_id)}:memory.test",
            collection_id="canon",
            logical_repository_id="memory.test",
            task_run_id=task_run_id,
            scope_kind="run_scoped",
            scope_id=namespace_id,
        )
    )
    services.artifact_repository_service.store.upsert_repository(
        ArtifactRepository(
            repository_id=f"run:{safe_id(project_id)}:repo.test",
            logical_repository_id="repo.test",
            task_run_id=task_run_id,
            scope_kind="run_scoped",
            scope_id=project_id,
            graph_id=graph_config.graph_id,
        )
    )
    services.artifact_repository_service.store.upsert_artifact(
        ArtifactRecord(
            artifact_id="artifactrec:test-delete",
            artifact_ref="artifact:chapters/001.md",
            path="chapters/001.md",
            repository_id=f"run:{safe_id(project_id)}:repo.test",
            collection_id="drafts",
            logical_repository_id="repo.test",
            task_run_id=task_run_id,
            scope_kind="run_scoped",
            scope_id=project_id,
            graph_id=graph_config.graph_id,
            graph_run_id=graph_run_id,
        )
    )
    artifact_dir = ProjectLayout.from_backend_dir(backend_dir).storage_root / "task_environments" / "creation" / "writing" / "artifacts" / project_id
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "draft.md").write_text("draft", encoding="utf-8")
    services.event_log.append(task_run_id, "test_event", payload={"graph_run_id": graph_run_id})

    result = GraphTaskLifecycleManager(base_dir=backend_dir, graph_harness=runtime.harness_runtime.graph_harness).delete_graph_run(graph_run_id)

    assert result["root_task_run_id"] == task_run_id
    assert services.state_index.get_task_run(task_run_id) is None
    assert runtime.harness_runtime.graph_harness.get_graph_run(graph_run_id) is None
    assert not artifact_dir.exists()
    assert services.formal_memory_service.store.list_repositories() == ()
    assert services.artifact_repository_service.store.list_artifacts(graph_run_id=graph_run_id) == ()
    assert services.event_log.list_events(task_run_id) == []
