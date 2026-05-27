from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .activation import TaskDispatchKind, TaskSourceKind
from .common import clean_payload, require, require_authority, tuple_of_dicts


TaskLifecycleStatus = Literal[
    "created",
    "active",
    "waiting_confirmation",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
]


@dataclass(frozen=True, slots=True)
class TaskLifecycle:
    """Canonical task primitive: a work lifecycle opened for an agent."""

    task_id: str
    session_id: str
    environment_id: str
    source: TaskSourceKind
    dispatch: TaskDispatchKind
    objective: str
    activation_id: str = ""
    parent_task_id: str = ""
    source_ref: str = ""
    dispatch_ref: str = ""
    working_objects: tuple[dict[str, Any], ...] = ()
    input_refs: tuple[dict[str, Any], ...] = ()
    resource_scope: dict[str, Any] = field(default_factory=dict)
    tool_scope: dict[str, Any] = field(default_factory=dict)
    state_scope: dict[str, Any] = field(default_factory=dict)
    artifact_scope: dict[str, Any] = field(default_factory=dict)
    memory_scope: dict[str, Any] = field(default_factory=dict)
    agent_assignment: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)
    acceptance_policy: dict[str, Any] = field(default_factory=dict)
    recovery_policy: dict[str, Any] = field(default_factory=dict)
    approval_policy: dict[str, Any] = field(default_factory=dict)
    runtime_assembly_ref: str = ""
    latest_runtime_start_packet_ref: str = ""
    latest_loop_state_ref: str = ""
    legacy_refs: dict[str, Any] = field(default_factory=dict)
    status: TaskLifecycleStatus = "created"
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_lifecycle"

    def __post_init__(self) -> None:
        require_authority(self.authority, "task_system.task_lifecycle", "TaskLifecycle")
        require(self.task_id, "TaskLifecycle requires task_id")
        require(self.session_id, "TaskLifecycle requires session_id")
        require(self.environment_id, "TaskLifecycle requires environment_id")
        require(self.objective, "TaskLifecycle requires objective")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["working_objects"] = [dict(item) for item in self.working_objects]
        payload["input_refs"] = [dict(item) for item in self.input_refs]
        return payload


def task_lifecycle_from_dict(payload: dict[str, Any]) -> TaskLifecycle:
    cleaned = clean_payload(payload, TaskLifecycle)
    cleaned["working_objects"] = tuple_of_dicts(cleaned.get("working_objects"))
    cleaned["input_refs"] = tuple_of_dicts(cleaned.get("input_refs"))
    return TaskLifecycle(**cleaned)
