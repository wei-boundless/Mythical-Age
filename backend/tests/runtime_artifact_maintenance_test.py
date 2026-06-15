from __future__ import annotations

import os
from pathlib import Path

from runtime.cache_manager import safe_cache_namespace
from runtime.memory.state_index import RuntimeStateIndex
from runtime.shared.models import TaskRun
from scripts.maintain_runtime_artifacts import RuntimeArtifactMaintenance


def test_runtime_artifact_maintenance_plans_expired_runtime_cache_without_active_task_cache(tmp_path: Path) -> None:
    project = tmp_path
    (project / "backend").mkdir()
    sandbox_root = project / "storage" / "runtime_cache" / "sandboxes"
    old = sandbox_root / "old"
    fresh = sandbox_root / "fresh"
    active_task_run_id = "taskrun:active"
    active = sandbox_root / safe_cache_namespace(active_task_run_id)
    for path in (old, fresh, active):
        path.mkdir(parents=True)
        (path / "scratch.txt").write_text("cache", encoding="utf-8")
    os.utime(old, (100.0, 100.0))
    os.utime(active, (100.0, 100.0))

    RuntimeStateIndex(project / "storage" / "runtime_state").upsert_task_run(
        TaskRun(
            task_run_id=active_task_run_id,
            session_id="session:active",
            task_id="task:active",
            execution_runtime_kind="single_agent_task",
            status="running",
            created_at=100.0,
            updated_at=100.0,
        )
    )

    result = RuntimeArtifactMaintenance(project, runtime_cache_ttl_seconds=1).plan()
    cache_deletes = [
        item
        for item in result["actions"]
        if item["reason"] == "runtime_cache_ttl_expired"
    ]

    assert [item["source"] for item in cache_deletes] == ["storage/runtime_cache/sandboxes/old"]
    assert result["mode"] == "dry_run"
    assert old.exists()
    assert active.exists()
