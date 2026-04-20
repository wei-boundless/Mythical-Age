from __future__ import annotations

from dataclasses import asdict, dataclass, field
from time import time
from typing import Any

from tasks.context_models import TaskContextRef, TaskResultRef, TaskSummary


@dataclass(slots=True)
class TaskEvent:
    event: str
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    task_type: str
    query: str
    parent_query_id: str = ""
    agent_type: str = "main"
    status: str = "pending"
    result: str = ""
    error: str = ""
    context_ref: TaskContextRef | None = None
    summary: TaskSummary | None = None
    result_ref: TaskResultRef | None = None
    created_at: float = field(default_factory=time)
    started_at: float | None = None
    finished_at: float | None = None
    events: list[TaskEvent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def mark_running(self) -> None:
        self.status = "running"
        if self.started_at is None:
            self.started_at = time()

    def mark_completed(self, result: str) -> None:
        self.status = "completed"
        self.result = result
        self.finished_at = time()

    def mark_failed(self, error: str) -> None:
        self.status = "failed"
        self.error = error
        self.finished_at = time()

    def add_event(self, event: str, *, message: str = "", payload: dict[str, Any] | None = None) -> None:
        self.events.append(
            TaskEvent(
                event=event,
                message=message,
                payload=dict(payload or {}),
            )
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["events"] = [event.to_dict() for event in self.events]
        return payload
