from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


AgentTurnStatus = Literal[
    "received",
    "facts_built",
    "boundary_checked",
    "context_candidates_built",
    "understanding",
    "deciding",
    "permit_checking",
    "direct_responding",
    "tool_turn_running",
    "launching_task_run",
    "waiting_task_run",
    "closing",
    "completed",
    "clarification_required",
    "blocked",
    "failed",
    "timed_out",
    "aborted",
]


@dataclass(frozen=True, slots=True)
class AgentTurnRecord:
    turn_id: str
    session_id: str
    agent_invocation_id: str
    user_message: str
    status: AgentTurnStatus
    source: str = "chat"
    created_at: float = 0.0
    updated_at: float = 0.0
    request_facts: dict[str, Any] = field(default_factory=dict)
    boundary_policy: dict[str, Any] = field(default_factory=dict)
    context_candidates: dict[str, Any] = field(default_factory=dict)
    understanding_decision: dict[str, Any] = field(default_factory=dict)
    execution_decision: dict[str, Any] = field(default_factory=dict)
    action_permit: dict[str, Any] = field(default_factory=dict)
    active_task_run_id: str = ""
    terminal_reason: str = ""
    status_code: str = ""
    phase: str = ""
    blocking_reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "agent_runtime.agent_turn"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
