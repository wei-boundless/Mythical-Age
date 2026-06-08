from __future__ import annotations

from typing import Any


class HealthRuntimeHarnessAdapter:
    """Read-only health runtime view backed by the current single-agent host."""

    def __init__(self, harness_runtime: Any) -> None:
        self._harness_runtime = harness_runtime
        self._services = getattr(harness_runtime, "agent_runtime_services", None)
        self._host = getattr(harness_runtime, "single_agent_runtime_host", None)

    def get_task_run(self, task_run_id: str) -> Any | None:
        if self._services is not None and callable(getattr(self._services, "get_task_run", None)):
            return self._services.get_task_run(task_run_id)
        if self._host is not None:
            return self._host.state_index.get_task_run(task_run_id)
        return None

    def get_trace(self, task_run_id: str, **kwargs: Any) -> dict[str, Any] | None:
        if self._services is not None and callable(getattr(self._services, "get_trace", None)):
            return self._services.get_trace(task_run_id, **kwargs)
        if self._host is not None and callable(getattr(self._host, "get_trace", None)):
            return self._host.get_trace(task_run_id, **kwargs)
        return None

    def event_count(self, task_run_id: str) -> int:
        if self._services is not None and callable(getattr(self._services, "event_count", None)):
            return int(self._services.event_count(task_run_id))
        event_log = getattr(self._host, "event_log", None)
        if event_log is not None:
            estimator = getattr(event_log, "estimated_event_count", None)
            if callable(estimator):
                return int(estimator(task_run_id))
            counter = getattr(event_log, "event_count", None)
            if callable(counter):
                return int(counter(task_run_id))
        return 0


def build_health_runtime_adapter(runtime: Any) -> HealthRuntimeHarnessAdapter:
    return HealthRuntimeHarnessAdapter(runtime.harness_runtime)
