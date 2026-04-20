from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    agent_type: str
    description: str
    permission_mode: str = "default"
    allowed_tools: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AgentContext:
    session_id: str
    task_id: str | None = None
    parent_agent_type: str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


MAIN_AGENT = AgentDefinition(
    agent_type="main",
    description="Default conversation agent for the interactive workspace.",
)

EXPLORER_AGENT = AgentDefinition(
    agent_type="explorer",
    description="Read-heavy agent used for investigation and discovery tasks.",
    permission_mode="plan",
)

WORKER_AGENT = AgentDefinition(
    agent_type="worker",
    description="Execution-focused agent used for bounded implementation tasks.",
)
