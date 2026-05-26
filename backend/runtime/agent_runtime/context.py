from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentRunContext:
    """Immutable system facts prepared before the agent turn loop runs."""

    request_facts: dict[str, Any] = field(default_factory=dict)
    boundary_policy: dict[str, Any] = field(default_factory=dict)
    context_candidates: dict[str, Any] = field(default_factory=dict)
    model_turn_decision: dict[str, Any] = field(default_factory=dict)
    action_permit: dict[str, Any] = field(default_factory=dict)
    runtime_start_packet: dict[str, Any] = field(default_factory=dict)
    agent_invocation: dict[str, Any] = field(default_factory=dict)
    execution_permit: dict[str, Any] = field(default_factory=dict)
    task_operation: dict[str, Any] = field(default_factory=dict)
    resource_policy: dict[str, Any] = field(default_factory=dict)
    tool_capability_table: dict[str, Any] = field(default_factory=dict)
    sandbox_policy: dict[str, Any] = field(default_factory=dict)
    file_management_policy: dict[str, Any] = field(default_factory=dict)
    agent_runtime_config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_facts": dict(self.request_facts),
            "boundary_policy": dict(self.boundary_policy),
            "context_candidates": dict(self.context_candidates),
            "model_turn_decision": dict(self.model_turn_decision),
            "action_permit": dict(self.action_permit),
            "runtime_start_packet": dict(self.runtime_start_packet),
            "agent_invocation": dict(self.agent_invocation),
            "execution_permit": dict(self.execution_permit),
            "task_operation": dict(self.task_operation),
            "resource_policy": dict(self.resource_policy),
            "tool_capability_table": dict(self.tool_capability_table),
            "sandbox_policy": dict(self.sandbox_policy),
            "file_management_policy": dict(self.file_management_policy),
            "agent_runtime_config": dict(self.agent_runtime_config),
            "authority": "runtime.agent_runtime.context",
        }
