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
