from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class CoordinationStageAgentRunRequest:
    session_id: str
    history: list[dict[str, Any]]
    source: str
    agent_runtime_chain: Any
    model_response_executor: Any
    runtime_context_manager: Any
    continuation_payload: dict[str, Any]
    stage_projection_cycle: Any | None = None
    memory_intent: Any | None = None
    assistant_message_committer: Callable[[dict[str, Any]], Any] | None = None
    tool_runtime_executor: Any | None = None
    tool_instances: list[Any] | None = None
    agent_runtime_profile: Any | None = None
