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
    lifecycle_state: str = "enabled"
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "agent_system.agent_group"

    def __post_init__(self) -> None:
        if self.authority != "agent_system.agent_group":
            raise ValueError("AgentGroup authority must be agent_system.agent_group")
        if not self.group_id:
            raise ValueError("AgentGroup requires group_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["member_agent_ids"] = list(self.member_agent_ids)
        return payload



