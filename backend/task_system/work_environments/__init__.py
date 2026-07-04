from __future__ import annotations

from .models import (
    SessionTaskBinding,
    TaskControlSignal,
    TaskContextPackage,
    TaskEnvironmentLease,
    TaskEvent,
    TaskInstance,
    TaskPlan,
    TaskTodoItem,
    TaskWorkEnvironment,
    context_package_hash,
    stable_task_environment_id,
)
from .repository import TaskEnvironmentRepository

__all__ = [
    "SessionTaskBinding",
    "TaskControlSignal",
    "TaskContextPackage",
    "TaskEnvironmentLease",
    "TaskEvent",
    "TaskInstance",
    "TaskPlan",
    "TaskTodoItem",
    "TaskWorkEnvironment",
    "context_package_hash",
    "stable_task_environment_id",
    "TaskEpisodeLeaseProjection",
    "TaskEpisodePreparation",
    "TaskEnvironmentRepository",
    "TaskWorkEnvironmentService",
    "TaskEnvironmentViewService",
]


def __getattr__(name: str) -> object:
    if name in {"TaskEpisodeLeaseProjection", "TaskEpisodePreparation", "TaskWorkEnvironmentService"}:
        from .service import TaskEpisodeLeaseProjection, TaskEpisodePreparation, TaskWorkEnvironmentService

        exports = {
            "TaskEpisodeLeaseProjection": TaskEpisodeLeaseProjection,
            "TaskEpisodePreparation": TaskEpisodePreparation,
            "TaskWorkEnvironmentService": TaskWorkEnvironmentService,
        }
        return exports[name]
    if name == "TaskEnvironmentViewService":
        from .view_service import TaskEnvironmentViewService

        return TaskEnvironmentViewService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
