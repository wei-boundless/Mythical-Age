from __future__ import annotations

from types import SimpleNamespace

from bootstrap.app_runtime import AppRuntime


class _BackgroundTaskManagerSpy:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def enqueue(
        self,
        task_kind: str,
        *,
        payload=None,
        source: str = "",
        session_id: str = "",
        coalesce_key: str = "",
    ):
        self.calls.append(
            {
                "task_kind": task_kind,
                "payload": dict(payload or {}),
                "source": source,
                "session_id": session_id,
                "coalesce_key": coalesce_key,
            }
        )
        return SimpleNamespace(task_id="task:test", task_kind=task_kind, receipt_path="receipt.json")


def test_durable_memory_saved_uses_current_background_task_enqueue_contract() -> None:
    manager = _BackgroundTaskManagerSpy()
    runtime = SimpleNamespace(memory_facade=SimpleNamespace(background_task_manager=manager))
    app = AppRuntime()
    app.require_ready = lambda: runtime  # type: ignore[method-assign]

    app._on_durable_memory_saved(1)

    assert manager.calls == [
        {
            "task_kind": "durable_memory_index_rebuild",
            "payload": {"collection": "durable_memory", "saved_count": 1},
            "source": "bootstrap.app_runtime",
            "session_id": "",
            "coalesce_key": "durable_memory",
        }
    ]


def test_durable_memory_refresh_uses_current_background_task_enqueue_contract() -> None:
    manager = _BackgroundTaskManagerSpy()
    runtime = SimpleNamespace(memory_facade=SimpleNamespace(background_task_manager=manager))
    app = AppRuntime()
    app.require_ready = lambda: runtime  # type: ignore[method-assign]

    app.refresh_indexes_for_path("durable_memory/notes/project.md")

    assert manager.calls == [
        {
            "task_kind": "durable_memory_index_rebuild",
            "payload": {"collection": "durable_memory", "source_path": "durable_memory/notes/project.md"},
            "source": "bootstrap.app_runtime",
            "session_id": "",
            "coalesce_key": "durable_memory",
        }
    ]
