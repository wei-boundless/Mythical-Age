from __future__ import annotations

from task_system.storage import TaskSystemStorage


def test_task_system_storage_keeps_snapshots_out_of_registry_root(tmp_path) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()
    storage = TaskSystemStorage(backend)

    storage.write_object("task_graphs.json", {"task_graphs": []})
    storage.write_snapshot("debug_snapshots", "run/latest.json", {"monitor": {"status": "ok"}})

    assert (tmp_path / "storage" / "tasks" / "task_graphs.json").exists()
    assert (tmp_path / "storage" / "tasks" / "debug_snapshots" / "run" / "latest.json").exists()
    assert not (tmp_path / "storage" / "tasks" / "run" / "latest.json").exists()
    assert storage.read_snapshot("debug_snapshots", "run/latest.json", {})["monitor"]["status"] == "ok"


def test_task_system_storage_rejects_unsafe_paths(tmp_path) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()
    storage = TaskSystemStorage(backend)

    try:
        storage.write_snapshot("debug_snapshots", "../escape.json", {})
    except ValueError as exc:
        assert "Unsafe task storage path" in str(exc)
    else:
        raise AssertionError("unsafe snapshot path should be rejected")
