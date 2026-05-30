from __future__ import annotations

from scripts.maintain_runtime_artifacts import RuntimeArtifactMaintenance


def test_runtime_artifact_maintenance_moves_task_debug_snapshots_without_touching_registries(tmp_path) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()
    tasks = tmp_path / "storage" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "task_graphs.json").write_text("{}", encoding="utf-8")
    (tasks / "writing_graph_smoke_start_latest.json").write_text("x" * 10, encoding="utf-8")

    result = RuntimeArtifactMaintenance(tmp_path, stamp="20260530").execute()

    assert result["summary"]["runtime_fact_delete_count"] == 0
    assert (tasks / "task_graphs.json").exists()
    assert not (tasks / "writing_graph_smoke_start_latest.json").exists()
    assert (tasks / "debug_snapshots" / "20260530" / "writing_graph_smoke_start_latest.json").exists()


def test_runtime_artifact_maintenance_deletes_only_diagnostics_and_build_cache(tmp_path) -> None:
    (tmp_path / "output" / "runtime").mkdir(parents=True)
    (tmp_path / "output" / "runtime" / "backend-fixed-8003.pid").write_text("1", encoding="utf-8")
    (tmp_path / "output" / "runtime" / "old-trace.json").write_text("x", encoding="utf-8")
    (tmp_path / "frontend" / ".next").mkdir(parents=True)
    (tmp_path / "frontend" / ".next" / "cache.bin").write_text("x", encoding="utf-8")
    (tmp_path / "storage" / "runtime_state" / "events").mkdir(parents=True)
    (tmp_path / "storage" / "runtime_state" / "events" / "taskrun.jsonl").write_text("{}", encoding="utf-8")

    result = RuntimeArtifactMaintenance(tmp_path).execute()

    assert not (tmp_path / "output" / "runtime" / "old-trace.json").exists()
    assert (tmp_path / "output" / "runtime" / "backend-fixed-8003.pid").exists()
    assert not (tmp_path / "frontend" / ".next").exists()
    assert (tmp_path / "storage" / "runtime_state" / "events" / "taskrun.jsonl").exists()
    assert result["summary"]["runtime_fact_delete_count"] == 0


def test_runtime_artifact_maintenance_can_delete_existing_task_debug_snapshot_partition(tmp_path) -> None:
    snapshot_dir = tmp_path / "storage" / "tasks" / "debug_snapshots" / "20260530"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "old.json").write_text("x", encoding="utf-8")
    (tmp_path / "storage" / "tasks" / "task_graphs.json").write_text("{}", encoding="utf-8")

    result = RuntimeArtifactMaintenance(tmp_path, stamp="20260530").execute()

    assert not snapshot_dir.exists()
    assert (tmp_path / "storage" / "tasks" / "task_graphs.json").exists()
    assert result["summary"]["runtime_fact_delete_count"] == 0
