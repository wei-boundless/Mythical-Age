from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from task_system.primitives import TaskActivationRequest, TaskLifecycle, TaskRuntimeAssemblyRequest


class TaskLifecycleStore(Protocol):
    """Storage contract owned by task_system lifecycle services."""

    def upsert_task_activation_request(self, request: TaskActivationRequest) -> None:
        ...

    def upsert_task_lifecycle(self, lifecycle: TaskLifecycle) -> None:
        ...

    def upsert_task_runtime_assembly_request(self, request: TaskRuntimeAssemblyRequest) -> None:
        ...

    def get_task_activation_request(self, activation_id: str) -> TaskActivationRequest | None:
        ...

    def get_task_lifecycle(self, task_id: str) -> TaskLifecycle | None:
        ...

    def get_task_lifecycle_by_activation(self, activation_id: str) -> TaskLifecycle | None:
        ...

    def get_task_lifecycle_by_order(self, order_id: str) -> TaskLifecycle | None:
        ...

    def get_task_runtime_assembly_request(self, request_id: str) -> TaskRuntimeAssemblyRequest | None:
        ...


@dataclass(slots=True)
class InMemoryTaskLifecycleStore:
    """Task-system-native lifecycle store for tests and non-runtime callers."""

    activation_requests: dict[str, TaskActivationRequest] = field(default_factory=dict)
    lifecycles: dict[str, TaskLifecycle] = field(default_factory=dict)
    runtime_assembly_requests: dict[str, TaskRuntimeAssemblyRequest] = field(default_factory=dict)
    lifecycle_by_activation: dict[str, str] = field(default_factory=dict)
    lifecycle_by_order: dict[str, str] = field(default_factory=dict)

    def upsert_task_activation_request(self, request: TaskActivationRequest) -> None:
        self.activation_requests[request.activation_id] = request

    def upsert_task_lifecycle(self, lifecycle: TaskLifecycle) -> None:
        self.lifecycles[lifecycle.task_id] = lifecycle
        if lifecycle.activation_id:
            self.lifecycle_by_activation[lifecycle.activation_id] = lifecycle.task_id
        order_id = str(dict(lifecycle.legacy_refs or {}).get("task_order_id") or "").strip()
        if order_id:
            self.lifecycle_by_order[order_id] = lifecycle.task_id

    def upsert_task_runtime_assembly_request(self, request: TaskRuntimeAssemblyRequest) -> None:
        self.runtime_assembly_requests[request.request_id] = request

    def get_task_activation_request(self, activation_id: str) -> TaskActivationRequest | None:
        return self.activation_requests.get(activation_id)

    def get_task_lifecycle(self, task_id: str) -> TaskLifecycle | None:
        return self.lifecycles.get(task_id)

    def get_task_lifecycle_by_activation(self, activation_id: str) -> TaskLifecycle | None:
        task_id = self.lifecycle_by_activation.get(activation_id, "")
        return self.get_task_lifecycle(task_id) if task_id else None

    def get_task_lifecycle_by_order(self, order_id: str) -> TaskLifecycle | None:
        task_id = self.lifecycle_by_order.get(order_id, "")
        return self.get_task_lifecycle(task_id) if task_id else None

    def get_task_runtime_assembly_request(self, request_id: str) -> TaskRuntimeAssemblyRequest | None:
        return self.runtime_assembly_requests.get(request_id)
