from __future__ import annotations

from typing import Any

__all__ = [
    "RuntimeMonitorActionService",
    "RuntimeMonitorManagementProjector",
    "RuntimeMonitorProjector",
    "RuntimeMonitorRetentionStore",
    "RuntimeMonitorService",
    "TaskRunLifecycleRetention",
]


def __getattr__(name: str) -> Any:
    if name == "RuntimeMonitorActionService":
        from .actions import RuntimeMonitorActionService

        globals()[name] = RuntimeMonitorActionService
        return RuntimeMonitorActionService
    if name == "RuntimeMonitorManagementProjector":
        from .management import RuntimeMonitorManagementProjector

        globals()[name] = RuntimeMonitorManagementProjector
        return RuntimeMonitorManagementProjector
    if name == "RuntimeMonitorProjector":
        from .projector import RuntimeMonitorProjector

        globals()[name] = RuntimeMonitorProjector
        return RuntimeMonitorProjector
    if name == "RuntimeMonitorRetentionStore":
        from .retention_store import RuntimeMonitorRetentionStore

        globals()[name] = RuntimeMonitorRetentionStore
        return RuntimeMonitorRetentionStore
    if name == "RuntimeMonitorService":
        from .service import RuntimeMonitorService

        globals()[name] = RuntimeMonitorService
        return RuntimeMonitorService
    if name == "TaskRunLifecycleRetention":
        from ..task_run_retention import TaskRunLifecycleRetention

        globals()[name] = TaskRunLifecycleRetention
        return TaskRunLifecycleRetention
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
