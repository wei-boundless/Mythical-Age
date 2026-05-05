from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentGroup:
    group_id: str
    title: str
    group_kind: str
    coordinator_agent_id: str
    member_agent_ids: tuple[str, ...] = ()
    description: str = ""
    default_topology_template_ids: tuple[str, ...] = ()
    default_communication_protocol_ids: tuple[str, ...] = ()
    allowed_coordination_task_ids: tuple[str, ...] = ()
    lifecycle_state: str = "enabled"
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.agent_group"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.agent_group":
            raise ValueError("AgentGroup authority must be orchestration.agent_group")
        if not self.group_id:
            raise ValueError("AgentGroup requires group_id")
        if not self.coordinator_agent_id:
            raise ValueError("AgentGroup requires coordinator_agent_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["member_agent_ids"] = list(self.member_agent_ids)
        payload["default_topology_template_ids"] = list(self.default_topology_template_ids)
        payload["default_communication_protocol_ids"] = list(self.default_communication_protocol_ids)
        payload["allowed_coordination_task_ids"] = list(self.allowed_coordination_task_ids)
        return payload
