from __future__ import annotations

from typing import Any

__all__ = [
    "RunMonitorActionService",
    "RunMonitorManagementProjector",
    "RunMonitorProjector",
    "RunMonitorRetentionStore",
    "RunMonitorService",
    "TaskRunLifecycleRetention",
]


def __getattr__(name: str) -> Any:
    if name == "RunMonitorActionService":
        from .actions import RunMonitorActionService

        globals()[name] = RunMonitorActionService
        return RunMonitorActionService
    if name == "RunMonitorManagementProjector":
        from .management import RunMonitorManagementProjector

        globals()[name] = RunMonitorManagementProjector
        return RunMonitorManagementProjector
    if name == "RunMonitorProjector":
        from .projector import RunMonitorProjector

        globals()[name] = RunMonitorProjector
        return RunMonitorProjector
    if name == "RunMonitorRetentionStore":
        from .retention_store import RunMonitorRetentionStore

        globals()[name] = RunMonitorRetentionStore
        return RunMonitorRetentionStore
    if name == "RunMonitorService":
        from .service import RunMonitorService

        globals()[name] = RunMonitorService
        return RunMonitorService
    if name == "TaskRunLifecycleRetention":
        from ..task_run_retention import TaskRunLifecycleRetention

        globals()[name] = TaskRunLifecycleRetention
        return TaskRunLifecycleRetention
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
