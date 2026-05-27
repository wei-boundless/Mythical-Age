from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from orchestration.execution_scheduler import BackgroundTaskManager, resolve_execution_dispatch


def test_resolve_execution_dispatch_marks_async_and_background_as_non_blocking() -> None:
    async_decision = resolve_execution_dispatch(execution_mode="async", wait_policy="fire_and_continue")
    background_decision = resolve_execution_dispatch(
        execution_mode="background",
        background_policy={"enabled": True, "blocks_downstream": False},
    )

    assert async_decision.dispatch_mode == "async"
    assert async_decision.wait_for_completion is False
    assert background_decision.dispatch_mode == "background"
    assert background_decision.wait_for_completion is False


def test_background_task_manager_persists_queued_task(tmp_path: Path) -> None:
    manager = BackgroundTaskManager(tmp_path)
    record = manager.enqueue("memory_maintenance_after_commit", payload={"session_id": "session-test"})

    stored = manager.load(record.task_id, record.task_kind)
    assert stored is not None
    assert stored.status == "queued"
    assert stored.payload["session_id"] == "session-test"
    assert stored.receipt_path.endswith(".json")


def test_background_task_manager_coalesces_repeated_tasks(tmp_path: Path) -> None:
    manager = BackgroundTaskManager(tmp_path)
    first = manager.enqueue(
        "durable_memory_index_rebuild",
        payload={"collection": "durable_memory"},
        coalesce_key="durable_memory",
    )
    second = manager.enqueue(
        "durable_memory_index_rebuild",
        payload={"collection": "durable_memory", "reason": "duplicate"},
        coalesce_key="durable_memory",
    )

    assert second.task_id == first.task_id
    assert manager.load(first.task_id, first.task_kind) is not None


