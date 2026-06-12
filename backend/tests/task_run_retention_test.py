from __future__ import annotations

import time
from pathlib import Path

from harness.runtime.dynamic_context.replacement_store import ReplacementStore
from harness.runtime.run_monitor import RuntimeMonitorService
from runtime.cache_manager import RuntimeCacheManager
from runtime.memory.file_state_store import FileStateAuthorityStore
from runtime.memory.state_index import RuntimeStateIndex
from runtime.shared.event_log import RuntimeEventLog
from runtime.shared.models import TaskRun
from runtime.shared.runtime_object_store import RuntimeObjectStore
from runtime.tool_runtime.tool_invocation_control import registry_for
from runtime_objects.tool_result_storage import ToolResultStore


class _ActiveTurnRegistry:
    def __init__(self) -> None:
        self.completed: list[dict[str, str]] = []

    def complete_bound_task(self, *, session_id: str, task_run_id: str, terminal_reason: str):
        record = {
            "session_id": session_id,
            "task_run_id": task_run_id,
            "terminal_reason": terminal_reason,
        }
        self.completed.append(record)
        return record

    def resolve_current(self, session_id: str):
        del session_id
        return None


class _RuntimeHost:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.backend_dir = root_dir
        self.task_run_retention_policy = {
            "blocked_ttl_seconds": 10,
            "waiting_executor_ttl_seconds": 10,
            "waiting_approval_ttl_seconds": 10,
            "stop_grace_seconds": 1,
        }
        self.state_index = RuntimeStateIndex(root_dir)
        self.event_log = RuntimeEventLog(root_dir)
        self.runtime_objects = RuntimeObjectStore(root_dir)
        self.file_state_store = FileStateAuthorityStore(root_dir)
        self.runtime_cache = RuntimeCacheManager.from_runtime_root(root_dir)
        self.active_turn_registry = _ActiveTurnRegistry()
        self._background_tasks_by_name = {}


class _RetentionSweepProbe:
    def __init__(self) -> None:
        self.calls: list[dict[str, float | int]] = []

    def sweep_expired_task_runs(self, *, now: float, limit: int):
        self.calls.append({"now": now, "limit": limit})
        return {
            "authority": "harness.runtime.task_run_lifecycle_retention",
            "terminal_update_count": 0,
            "stop_request_count": 0,
        }


def _task_run(task_run_id: str, *, status: str, updated_at: float, diagnostics: dict | None = None) -> TaskRun:
    return TaskRun(
        task_run_id=task_run_id,
        session_id=f"session:{task_run_id}",
        task_id=f"task:{task_run_id}",
        execution_runtime_kind="single_agent_task",
        status=status,  # type: ignore[arg-type]
        created_at=updated_at - 10,
        updated_at=updated_at,
        terminal_reason="waiting_executor" if status == "waiting_executor" else "",
        diagnostics=dict(diagnostics or {}),
    )


def test_retention_stops_old_blocked_and_releases_ephemeral_state(tmp_path: Path) -> None:
    host = _RuntimeHost(tmp_path / "runtime_state")
    task_run_id = "taskrun:blocked-old"
    host.state_index.upsert_task_run(_task_run(task_run_id, status="blocked", updated_at=100.0))
    host.file_state_store.apply_events(
        task_run_id,
        [{"event_type": "read", "path": "docs/a.md", "start_line": 1, "end_line": 2, "total_lines": 2}],
        observation_ref="obs:file",
    )
    sandbox = host.runtime_cache.sandbox_root(task_run_id)
    (sandbox / "scratch.txt").write_text("temporary", encoding="utf-8")
    ReplacementStore(host.root_dir).get_or_put(
        source_kind="observation",
        source_id="obs:file",
        task_run_id=task_run_id,
        content={"task_run_id": task_run_id, "summary": "temporary"},
        projection_policy={},
        projector_version="test",
        projection={"task_run_id": task_run_id, "summary": "temporary"},
    )
    ToolResultStore(host.root_dir, run_id=task_run_id).apply_budget(
        {"text": "large\n" * 2000},
        field_limit_bytes=100,
        preview_size_bytes=50,
        payload_budget_bytes=200,
    )
    registry = registry_for(host)
    assert registry is not None
    registry.start(
        tool_invocation_id="toolinv:blocked-old",
        caller_kind="task_run",
        caller_ref=task_run_id,
        task_run_id=task_run_id,
        tool_name="read_file",
    )

    monitor = RuntimeMonitorService(runtime_host=host, freshness_seconds=300).collect_global_runtime_monitor(limit=20)
    updated = host.state_index.get_task_run(task_run_id)

    assert updated is not None
    assert updated.status == "aborted"
    assert updated.terminal_reason == "blocked_expired"
    assert dict(updated.diagnostics["runtime_control"])["state"] == "stopped"
    attention_ids = {item.get("task_run_id") for item in monitor["management"]["lanes"]["attention"]}
    recent = {item.get("task_run_id"): item for item in monitor["management"]["lanes"]["recent"]}
    assert task_run_id not in attention_ids
    assert recent[task_run_id]["activity_state"] == "stopped"
    assert not sandbox.exists()
    assert host.file_state_store.snapshot(task_run_id) == []
    assert not (host.root_dir / "dynamic_context" / "replacements").exists() or not any((host.root_dir / "dynamic_context" / "replacements").glob("*.json"))
    assert not (host.root_dir / "tool_results" / "taskrun-blocked-old").exists()
    assert registry.record("toolinv:blocked-old").status == "cancelled"
    assert host.active_turn_registry.completed[-1]["terminal_reason"] == "blocked_expired"


def test_retention_keeps_fresh_blocked_visible(tmp_path: Path) -> None:
    host = _RuntimeHost(tmp_path / "runtime_state")
    task_run_id = "taskrun:blocked-fresh"
    host.state_index.upsert_task_run(_task_run(task_run_id, status="blocked", updated_at=time.time()))

    monitor = RuntimeMonitorService(runtime_host=host, freshness_seconds=300).collect_global_runtime_monitor(limit=20)
    current = host.state_index.get_task_run(task_run_id)

    assert current is not None
    assert current.status == "blocked"
    attention_ids = {item.get("task_run_id") for item in monitor["management"]["lanes"]["attention"]}
    assert task_run_id in attention_ids


def test_retention_does_not_auto_stop_paused_task(tmp_path: Path) -> None:
    host = _RuntimeHost(tmp_path / "runtime_state")
    task_run_id = "taskrun:paused"
    host.state_index.upsert_task_run(
        _task_run(
            task_run_id,
            status="waiting_executor",
            updated_at=100.0,
            diagnostics={"runtime_control": {"state": "paused"}},
        )
    )

    RuntimeMonitorService(runtime_host=host, freshness_seconds=300).collect_global_runtime_monitor(limit=20)
    current = host.state_index.get_task_run(task_run_id)

    assert current is not None
    assert current.status == "waiting_executor"
    assert current.terminal_reason == "waiting_executor"


def test_retention_stops_old_waiting_executor_and_clears_recovery(tmp_path: Path) -> None:
    host = _RuntimeHost(tmp_path / "runtime_state")
    task_run_id = "taskrun:waiting-executor"
    host.state_index.upsert_task_run(
        _task_run(
            task_run_id,
            status="waiting_executor",
            updated_at=100.0,
            diagnostics={"recovery_action": "resume_task_run", "recoverable_error": {"retryable": True}},
        )
    )

    RuntimeMonitorService(runtime_host=host, freshness_seconds=300).collect_global_runtime_monitor(limit=20)
    current = host.state_index.get_task_run(task_run_id)

    assert current is not None
    assert current.status == "aborted"
    assert current.terminal_reason == "runtime_retention_expired"
    assert "recovery_action" not in current.diagnostics
    assert "recoverable_error" not in current.diagnostics


def test_retention_expires_old_waiting_approval(tmp_path: Path) -> None:
    host = _RuntimeHost(tmp_path / "runtime_state")
    task_run_id = "taskrun:approval"
    host.state_index.upsert_task_run(
        _task_run(
            task_run_id,
            status="waiting_approval",
            updated_at=100.0,
            diagnostics={"pending_approval": {"approval_request_id": "approval:1", "status": "pending"}},
        )
    )

    RuntimeMonitorService(runtime_host=host, freshness_seconds=300).collect_global_runtime_monitor(limit=20)
    current = host.state_index.get_task_run(task_run_id)

    assert current is not None
    assert current.status == "aborted"
    assert current.terminal_reason == "approval_expired"
    assert current.diagnostics["pending_approval"]["status"] == "expired"


def test_monitor_service_throttles_retention_sweep_between_projection_refreshes(tmp_path: Path) -> None:
    host = _RuntimeHost(tmp_path / "runtime_state")
    service = RuntimeMonitorService(
        runtime_host=host,
        freshness_seconds=300,
        retention_sweep_interval_seconds=30,
    )
    probe = _RetentionSweepProbe()
    service.lifecycle_retention = probe  # type: ignore[assignment]

    first = service._sweep_expired_task_runs(now=100.0, limit=80)
    second = service._sweep_expired_task_runs(now=110.0, limit=80)
    third = service._sweep_expired_task_runs(now=131.0, limit=80)

    assert first.get("skipped") is not True
    assert second["skipped"] is True
    assert second["reason"] == "retention_sweep_interval"
    assert third.get("skipped") is not True
    assert probe.calls == [
        {"now": 100.0, "limit": 80},
        {"now": 131.0, "limit": 80},
    ]
