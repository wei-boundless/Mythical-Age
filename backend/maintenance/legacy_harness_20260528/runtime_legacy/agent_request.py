from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    """Stable boundary packet for one agent invocation."""

    session_id: str
    task_id: str
    user_message: str
    history: list[dict[str, Any]]
    source: str
    agent_runtime_chain: Any
    model_response_executor: Any
    runtime_context_manager: Any
    memory_intent: Any | None = None
    task_selection: dict[str, Any] | None = None
    assistant_message_committer: Callable[[dict[str, Any]], Any] | None = None
    tool_runtime_executor: Any | None = None
    tool_instances: list[Any] | None = None
    agent_runtime_profile: Any | None = None
    search_policy: list[str] | None = None
    model_selection: dict[str, Any] | None = None
    agent_invocation: dict[str, Any] | None = None


