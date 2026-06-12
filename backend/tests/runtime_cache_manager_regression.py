from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from harness.loop.single_agent_turn import _single_turn_sandbox_scope
from harness.loop.task_executor import _task_sandbox_policy
from runtime.cache_manager import RuntimeCacheManager


class _EmptyStateIndex:
    def get_task_run(self, task_run_id: str):
        del task_run_id
        return None


def test_runtime_cache_root_is_sibling_of_runtime_state_in_project_layout(tmp_path: Path) -> None:
    runtime_root = tmp_path / "storage" / "runtime_state"
    runtime_root.mkdir(parents=True)

    manager = RuntimeCacheManager.from_runtime_root(runtime_root)
    sandbox = manager.sandbox_root("taskrun:demo")

    assert manager.cache_root == (tmp_path / "storage" / "runtime_cache").resolve()
    assert sandbox == (tmp_path / "storage" / "runtime_cache" / "sandboxes" / "taskrun_demo").resolve()
    assert sandbox.exists()


def test_runtime_cache_cleanup_uses_manifest_ttl_and_protected_paths(tmp_path: Path) -> None:
    manager = RuntimeCacheManager(tmp_path / "runtime_cache")
    expired = manager.sandbox_root("expired")
    protected = manager.sandbox_root("protected")
    fresh = manager.sandbox_root("fresh")
    for path in (expired, protected, fresh):
        (path / "file.txt").write_text("cache", encoding="utf-8")
        manager.write_manifest(path, cache_key=path.name, owner="test", ttl_seconds=10)
    for path, last_accessed_at in ((expired, 100.0), (protected, 100.0), (fresh, 995.0)):
        manifest_path = path / ".runtime_cache_manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["created_at"] = last_accessed_at
        payload["last_accessed_at"] = last_accessed_at
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    preview = manager.cleanup(
        namespace="sandboxes",
        now=1000.0,
        protected_paths=[protected],
        dry_run=True,
    )
    result = manager.cleanup(
        namespace="sandboxes",
        now=1000.0,
        protected_paths=[protected],
        dry_run=False,
    )

    assert preview["action_count"] == 1
    assert preview["actions"][0]["path"] == str(expired)
    assert result["action_count"] == 1
    assert not expired.exists()
    assert protected.exists()
    assert fresh.exists()


def test_runtime_cache_deletes_single_entry_by_namespace_and_key(tmp_path: Path) -> None:
    manager = RuntimeCacheManager(tmp_path / "runtime_cache")
    target = manager.sandbox_root("taskrun:old")
    keep = manager.sandbox_root("taskrun:keep")
    (target / "file.txt").write_text("cache", encoding="utf-8")
    (keep / "file.txt").write_text("cache", encoding="utf-8")

    result = manager.delete_cache_entry(
        namespace="sandboxes",
        cache_key="taskrun:old",
        reason="blocked_expired",
    )

    assert result["deleted"] is True
    assert not target.exists()
    assert keep.exists()


def test_runtime_cache_can_detach_single_entry_without_size_scan(tmp_path: Path) -> None:
    manager = RuntimeCacheManager(tmp_path / "runtime_cache")
    target = manager.sandbox_root("taskrun:old")
    keep = manager.sandbox_root("taskrun:keep")
    (target / "file.txt").write_text("cache", encoding="utf-8")
    (keep / "file.txt").write_text("cache", encoding="utf-8")

    result = manager.delete_cache_entry(
        namespace="sandboxes",
        cache_key="taskrun:old",
        reason="blocked_expired",
        measure_size=False,
        defer_delete=True,
    )

    assert result["detached"] is True
    assert result["deleted"] is False
    assert result["size_measured"] is False
    assert result["size_bytes"] == 0
    assert not target.exists()
    assert keep.exists()


def test_task_sandbox_policy_defaults_to_runtime_cache(tmp_path: Path) -> None:
    runtime_root = tmp_path / "storage" / "runtime_state"
    runtime_root.mkdir(parents=True)
    runtime_host = SimpleNamespace(
        backend_dir=Path(__file__).resolve().parents[1],
        root_dir=runtime_root,
        state_index=_EmptyStateIndex(),
    )

    policy = _task_sandbox_policy(
        {"task_environment": {"storage_space": {}, "sandbox_policy": {}}},
        runtime_host=runtime_host,
        task_run_id="taskrun:cache-root",
    )

    sandbox_root = Path(str(policy["sandbox_root"])).resolve()
    assert sandbox_root == (tmp_path / "storage" / "runtime_cache" / "sandboxes" / "taskrun_cache-root").resolve()
    assert "storage/runtime_state/sandboxes" not in sandbox_root.as_posix()


def test_single_turn_sandbox_scope_defaults_to_runtime_cache(tmp_path: Path) -> None:
    runtime_root = tmp_path / "storage" / "runtime_state"
    runtime_root.mkdir(parents=True)
    runtime_host = SimpleNamespace(
        backend_dir=Path(__file__).resolve().parents[1],
        root_dir=runtime_root,
    )

    policy = _single_turn_sandbox_scope(
        {"task_environment": {"storage_space": {}, "sandbox_policy": {}}},
        runtime_host=runtime_host,
        turn_id="turn:cache-root",
    )

    sandbox_root = Path(str(policy["sandbox_root"])).resolve()
    assert sandbox_root == (tmp_path / "storage" / "runtime_cache" / "sandboxes" / "turn_cache-root").resolve()
    assert "storage/runtime_state/sandboxes" not in sandbox_root.as_posix()
