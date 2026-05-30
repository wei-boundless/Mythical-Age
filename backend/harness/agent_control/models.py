from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


SubagentMessageDirection = Literal["parent_to_child", "child_to_parent", "system"]


@dataclass(frozen=True, slots=True)
class SubagentMessage:
    message_id: str
    task_run_id: str
    parent_agent_run_ref: str
    subagent_run_ref: str
    direction: SubagentMessageDirection
    message_type: str
    content: str = ""
    refs: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    authority: str = "orchestration.subagent_message"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.subagent_message":
            raise ValueError("SubagentMessage authority must be orchestration.subagent_message")
        if not self.message_id:
            raise ValueError("SubagentMessage requires message_id")
        if not self.task_run_id:
            raise ValueError("SubagentMessage requires task_run_id")
        if not self.parent_agent_run_ref:
            raise ValueError("SubagentMessage requires parent_agent_run_ref")
        if not self.subagent_run_ref:
            raise ValueError("SubagentMessage requires subagent_run_ref")
        if self.direction not in {"parent_to_child", "child_to_parent", "system"}:
            raise ValueError("SubagentMessage direction is invalid")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def subagent_message_from_dict(payload: dict[str, Any]) -> SubagentMessage:
    return SubagentMessage(
        message_id=str(payload.get("message_id") or ""),
        task_run_id=str(payload.get("task_run_id") or ""),
        parent_agent_run_ref=str(payload.get("parent_agent_run_ref") or ""),
        subagent_run_ref=str(payload.get("subagent_run_ref") or ""),
        direction=payload.get("direction", "system"),
        message_type=str(payload.get("message_type") or "status"),
        content=str(payload.get("content") or ""),
        refs=dict(payload.get("refs") or {}),
        created_at=float(payload.get("created_at") or 0.0),
    )

