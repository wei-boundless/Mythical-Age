from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskExecutionAssembly:
    assembly_id: str
    task_id: str
    session_id: str
    task_mode: str
    task_kind: str = ""
    task_intent_ref: str = ""
    task_spec_ref: str = ""
    bundle_spec_ref: str = ""
    workflow_id: str = ""
    flow_contract_binding_ref: str = ""
    flow_contract_id: str = ""
    execution_chain_type: str = "agent_harness_chain"
    task_execution_policy_ref: str = ""
    memory_request_profile_ref: str = ""
    communication_protocol_ref: str = ""
    graph_ref: str = ""
    operation_requirement_ref: str = ""
    input_contract_id: str = ""
    output_contract_id: str = ""
    safety_envelope: dict[str, Any] = field(default_factory=dict)
    task_constraints: dict[str, Any] = field(default_factory=dict)
    requested_outputs: tuple[str, ...] = ()
    status: str = "assembled"
    authority: str = "task_system.task_execution_assembly"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != "task_system.task_execution_assembly":
            raise ValueError("TaskExecutionAssembly authority must be task_system.task_execution_assembly")
        if not self.assembly_id:
            raise ValueError("TaskExecutionAssembly requires assembly_id")
        if not self.task_id:
            raise ValueError("TaskExecutionAssembly requires task_id")
        if not self.session_id:
            raise ValueError("TaskExecutionAssembly requires session_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["requested_outputs"] = list(self.requested_outputs)
        payload["graph_ref"] = self.graph_ref
        return payload


