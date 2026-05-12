from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentRuntimeProfile:
    agent_profile_id: str
    agent_id: str
    allowed_task_modes: tuple[str, ...] = ()
    allowed_runtime_lanes: tuple[str, ...] = ()
    allowed_operations: tuple[str, ...] = ()
    blocked_operations: tuple[str, ...] = ()
    allowed_memory_scopes: tuple[str, ...] = ()
    allowed_context_sections: tuple[str, ...] = ()
    use_shared_contract: bool = True
    output_contracts: tuple[str, ...] = ()
    can_delegate_to_agents: bool = False
    allowed_delegate_agent_ids: tuple[str, ...] = ()
    allowed_delegate_agent_categories: tuple[str, ...] = ("worker_sub_agent",)
    max_delegate_calls_per_turn: int = 1
    delegate_context_policy: str = "summary_and_refs_only"
    approval_policy: str = "default"
    trace_policy: str = "runtime_event_log"
    lifecycle_policy: str = "orchestration_managed"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "allowed_task_modes",
            "allowed_runtime_lanes",
            "allowed_operations",
            "blocked_operations",
            "allowed_memory_scopes",
            "allowed_context_sections",
            "output_contracts",
            "allowed_delegate_agent_ids",
            "allowed_delegate_agent_categories",
        ):
            payload[key] = list(payload[key])
        return payload
