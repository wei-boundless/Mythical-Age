from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


WorkerSpawnStatus = Literal["spawned", "blocked"]


@dataclass(frozen=True, slots=True)
class WorkerAgentBlueprint:
    blueprint_id: str
    agent_name_template: str
    description: str = ""
    allowed_operations: tuple[str, ...] = ()
    blocked_operations: tuple[str, ...] = ()
    allowed_memory_scopes: tuple[str, ...] = ()
    allowed_context_sections: tuple[str, ...] = ()
    approval_policy: str = "default"
    trace_policy: str = "runtime_event_log"
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.worker_agent_blueprint"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.worker_agent_blueprint":
            raise ValueError("WorkerAgentBlueprint authority must be orchestration.worker_agent_blueprint")
        if not self.blueprint_id:
            raise ValueError("WorkerAgentBlueprint requires blueprint_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "allowed_operations",
            "blocked_operations",
            "allowed_memory_scopes",
            "allowed_context_sections",
        ):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True, slots=True)
class WorkerAgentSpawnRequest:
    spawn_request_id: str
    task_run_id: str
    parent_agent_run_ref: str
    blueprint_id: str
    requested_agent_name: str
    context_scope: str
    requested_by_agent_id: str
    spawn_reason: str
    requested_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.worker_agent_spawn_request"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.worker_agent_spawn_request":
            raise ValueError("WorkerAgentSpawnRequest authority must be orchestration.worker_agent_spawn_request")
        if not self.spawn_request_id:
            raise ValueError("WorkerAgentSpawnRequest requires spawn_request_id")
        if not self.task_run_id:
            raise ValueError("WorkerAgentSpawnRequest requires task_run_id")
        if not self.parent_agent_run_ref:
            raise ValueError("WorkerAgentSpawnRequest requires parent_agent_run_ref")
        if not self.blueprint_id:
            raise ValueError("WorkerAgentSpawnRequest requires blueprint_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WorkerAgentSpawnResult:
    spawn_result_id: str
    spawn_request_id: str
    task_run_id: str
    parent_agent_run_ref: str
    blueprint_id: str
    spawned_agent_id: str = ""
    spawned_agent_run_ref: str = ""
    spawned_agent_profile_id: str = ""
    status: WorkerSpawnStatus = "spawned"
    created_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.worker_agent_spawn_result"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.worker_agent_spawn_result":
            raise ValueError("WorkerAgentSpawnResult authority must be orchestration.worker_agent_spawn_result")
        if not self.spawn_result_id:
            raise ValueError("WorkerAgentSpawnResult requires spawn_result_id")
        if not self.spawn_request_id:
            raise ValueError("WorkerAgentSpawnResult requires spawn_request_id")
        if not self.task_run_id:
            raise ValueError("WorkerAgentSpawnResult requires task_run_id")
        if not self.parent_agent_run_ref:
            raise ValueError("WorkerAgentSpawnResult requires parent_agent_run_ref")
        if not self.blueprint_id:
            raise ValueError("WorkerAgentSpawnResult requires blueprint_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


