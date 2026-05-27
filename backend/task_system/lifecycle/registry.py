from __future__ import annotations

from dataclasses import dataclass

from task_system.primitives import TaskActivationRequest, TaskLifecycle, TaskRuntimeAssemblyRequest

from .factory import TaskLifecycleCreation
from .repository import TaskLifecycleStore


@dataclass(frozen=True, slots=True)
class TaskLifecycleRegistry:
    """Lifecycle registry over a task-system-owned storage contract."""

    store: TaskLifecycleStore
    authority: str = "task_system.task_lifecycle_registry"

    def upsert_activation_request(self, request: TaskActivationRequest) -> None:
        self.store.upsert_task_activation_request(request)

    def upsert_lifecycle(self, lifecycle: TaskLifecycle) -> None:
        self.store.upsert_task_lifecycle(lifecycle)

    def upsert_runtime_assembly_request(self, request: TaskRuntimeAssemblyRequest) -> None:
        if hasattr(self.store, "upsert_task_runtime_assembly_request"):
            self.store.upsert_task_runtime_assembly_request(request)

    def upsert_creation(self, creation: TaskLifecycleCreation) -> None:
        if creation.activation_request is not None:
            self.upsert_activation_request(creation.activation_request)
        if creation.lifecycle is not None:
            self.upsert_lifecycle(creation.lifecycle)
        if creation.runtime_assembly_request is not None:
            self.upsert_runtime_assembly_request(creation.runtime_assembly_request)

    def get_lifecycle(self, task_id: str) -> TaskLifecycle | None:
        return self.store.get_task_lifecycle(task_id)

    def get_lifecycle_by_activation(self, activation_id: str) -> TaskLifecycle | None:
        return self.store.get_task_lifecycle_by_activation(activation_id)

    def get_lifecycle_by_order(self, order_id: str) -> TaskLifecycle | None:
        return self.store.get_task_lifecycle_by_order(order_id)

    def get_runtime_assembly_request(self, request_id: str) -> TaskRuntimeAssemblyRequest | None:
        if not hasattr(self.store, "get_task_runtime_assembly_request"):
            return None
        return self.store.get_task_runtime_assembly_request(request_id)
