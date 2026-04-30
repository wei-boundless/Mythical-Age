from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentDescriptor:
    agent_id: str
    display_name: str
    owner_system: str
    profile_type: str
    lifecycle_state: str
    default_soul_id: str = ""
    default_projection_template_id: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    governance_status: str = "operation_managed"
    deletable: str = "archive_only"
    disable_allowed: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentCapabilityProfile:
    agent_profile_id: str
    agent_id: str
    allowed_task_modes: tuple[str, ...] = ()
    allowed_runtime_lanes: tuple[str, ...] = ()
    allowed_operations: tuple[str, ...] = ()
    blocked_operations: tuple[str, ...] = ()
    allowed_skill_workflows: tuple[str, ...] = ()
    allowed_projection_templates: tuple[str, ...] = ()
    allowed_memory_scopes: tuple[str, ...] = ()
    allowed_context_sections: tuple[str, ...] = ()
    output_contracts: tuple[str, ...] = ()
    approval_policy: str = "default"
    trace_policy: str = "runtime_event_log"
    lifecycle_policy: str = "operation_managed"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "allowed_task_modes",
            "allowed_runtime_lanes",
            "allowed_operations",
            "blocked_operations",
            "allowed_skill_workflows",
            "allowed_projection_templates",
            "allowed_memory_scopes",
            "allowed_context_sections",
            "output_contracts",
        ):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True, slots=True)
class AgentLifecycleRecord:
    record_id: str
    agent_id: str
    action: str
    operator: str = "system"
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
