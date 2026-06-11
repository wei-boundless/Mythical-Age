from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from bootstrap.app_runtime import AppRuntime


class _HarnessRuntimeStub:
    def __init__(self) -> None:
        self.recovered_executor_start_count = 0
        self.single_agent_runtime_host = SimpleNamespace(spawn_background_task=self._spawn_background_task)

    def _spawn_background_task(self, coro, *, name: str = ""):
        raise AssertionError(f"unexpected background task: {name}")

    def start_runtime_recovered_task_run_executors(self):
        self.recovered_executor_start_count += 1
        return {"scheduled_count": 1}


def _ready_app_runtime(harness_runtime: _HarnessRuntimeStub) -> AppRuntime:
    app = AppRuntime()
    app.base_dir = Path.cwd()
    app.settings = object()
    app.session_manager = object()
    app.skill_registry = object()
    app.tool_runtime = object()
    app.memory_facade = object()
    app.retrieval_service = object()
    app.permission_service = object()
    app.model_runtime = object()
    app.harness_runtime = harness_runtime
    app.graph_breakpoint_supervisor = None
    app.graph_breakpoint_command_supervisor = None
    return app


def test_background_services_do_not_auto_start_recovered_task_executors():
    harness_runtime = _HarnessRuntimeStub()
    app = _ready_app_runtime(harness_runtime)

    asyncio.run(app.start_background_services())

    assert app._background_services_started is True
    assert harness_runtime.recovered_executor_start_count == 0
