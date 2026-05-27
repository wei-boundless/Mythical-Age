from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    session_id: str
    user_message: str
    history: list[dict[str, Any]]
    source: str
    turn_id: str = ""
    task_id: str = ""
    model_response_executor: Any | None = None
    task_selection: dict[str, Any] | None = None
    assistant_message_committer: Callable[[dict[str, Any]], Any] | None = None
    tool_runtime_executor: Any | None = None
    tool_instances: list[Any] | None = None
    agent_runtime_profile: Any | None = None
    search_policy: list[str] | None = None
    model_selection: dict[str, Any] | None = None
    agent_invocation: dict[str, Any] | None = None
    runtime_assembly: Any | None = None
