from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ToolInvocationCallerKind = Literal["agent_turn", "task_run", "graph_node", "direct_route"]


@dataclass(frozen=True, slots=True)
class ToolInvocationRequest:
    invocation_id: str
    caller_kind: ToolInvocationCallerKind
    caller_ref: str
    session_id: str
    turn_id: str
    tool_name: str
    tool_call_id: str
    tool_args: dict[str, Any] = field(default_factory=dict)
    operation_id: str = ""
    task_run_id: str = ""
    agent_run_id: str = ""
    action_request_ref: str = ""
    packet_ref: str = ""
    tool_plan_ref: str = ""
    admission_ref: str = ""
    action_permit: dict[str, Any] = field(default_factory=dict)
    permission_mode: str = "default"
    caller_resource_scope: dict[str, Any] = field(default_factory=dict)
    sandbox_scope: dict[str, Any] = field(default_factory=dict)
    file_scope: dict[str, Any] = field(default_factory=dict)
    requested_constraints: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.tool_runtime.tool_invocation_request"

    def __post_init__(self) -> None:
        if self.authority != "runtime.tool_runtime.tool_invocation_request":
            raise ValueError("ToolInvocationRequest authority must be runtime.tool_runtime.tool_invocation_request")
        if not self.invocation_id:
            raise ValueError("ToolInvocationRequest requires invocation_id")
        if not self.caller_kind:
            raise ValueError("ToolInvocationRequest requires caller_kind")
        if self.caller_kind == "task_run" and not self.task_run_id:
            raise ValueError("ToolInvocationRequest caller_kind=task_run requires task_run_id")
        if not self.tool_name:
            raise ValueError("ToolInvocationRequest requires tool_name")
        if not self.tool_call_id:
            raise ValueError("ToolInvocationRequest requires tool_call_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tool_args"] = dict(self.tool_args or {})
        payload["caller_resource_scope"] = dict(self.caller_resource_scope or {})
        payload["action_permit"] = dict(self.action_permit or {})
        payload["sandbox_scope"] = dict(self.sandbox_scope or {})
        payload["file_scope"] = dict(self.file_scope or {})
        payload["requested_constraints"] = dict(self.requested_constraints or {})
        return payload
