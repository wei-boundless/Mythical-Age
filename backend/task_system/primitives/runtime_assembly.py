from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .common import clean_payload, require, require_authority


@dataclass(frozen=True, slots=True)
class TaskRuntimeAssemblyRequest:
    """Task-system-side request prepared for later runtime assembly."""

    request_id: str
    task_lifecycle_ref: str
    environment_ref: str
    activation_ref: str = ""
    agent_assignment_ref: str = ""
    tool_scope_ref: str = ""
    resource_scope_ref: str = ""
    memory_scope_ref: str = ""
    artifact_scope_ref: str = ""
    output_contract_ref: str = ""
    acceptance_policy_ref: str = ""
    recovery_policy_ref: str = ""
    approval_policy_ref: str = ""
    dispatch_context_ref: str = ""
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_runtime_assembly_request"

    def __post_init__(self) -> None:
        require_authority(
            self.authority,
            "task_system.task_runtime_assembly_request",
            "TaskRuntimeAssemblyRequest",
        )
        require(self.request_id, "TaskRuntimeAssemblyRequest requires request_id")
        require(self.task_lifecycle_ref, "TaskRuntimeAssemblyRequest requires task_lifecycle_ref")
        require(self.environment_ref, "TaskRuntimeAssemblyRequest requires environment_ref")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def task_runtime_assembly_request_from_dict(payload: dict[str, Any]) -> TaskRuntimeAssemblyRequest:
    return TaskRuntimeAssemblyRequest(**clean_payload(payload, TaskRuntimeAssemblyRequest))
