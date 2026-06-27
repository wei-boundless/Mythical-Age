from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentTaskBodyAssembly:
    task_body_assembly_id: str
    task_id: str
    agent_id: str
    task_execution_assembly_ref: str
    body_profile_ref: str
    prompt_structure_profile_ref: str
    memory_scope_profile_ref: str
    output_boundary_profile_ref: str
    stage_plan: dict[str, Any] = field(default_factory=dict)
    resource_binding_plan: dict[str, Any] = field(default_factory=dict)
    verification_gate_plan: dict[str, Any] = field(default_factory=dict)
    fallback_plan: dict[str, Any] = field(default_factory=dict)
    prompt_manifest: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "agent_system.task_body_assembly"

    def __post_init__(self) -> None:
        if self.authority != "agent_system.task_body_assembly":
            raise ValueError("AgentTaskBodyAssembly authority must be agent_system.task_body_assembly")
        if not self.task_body_assembly_id:
            raise ValueError("AgentTaskBodyAssembly requires task_body_assembly_id")
        if not self.task_id:
            raise ValueError("AgentTaskBodyAssembly requires task_id")
        if not self.agent_id:
            raise ValueError("AgentTaskBodyAssembly requires agent_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentRuntimeSpec:
    runtime_spec_id: str
    task_id: str
    session_id: str
    agent_id: str
    task_execution_assembly_ref: str
    task_body_assembly_ref: str
    context_input_refs: tuple[str, ...] = ()
    resource_policy_candidate_ref: str = ""
    input_contract_ref: str = ""
    output_contract_ref: str = ""
    runtime_executable: bool = True
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "agent_system.agent_runtime_spec"

    def __post_init__(self) -> None:
        if self.authority != "agent_system.agent_runtime_spec":
            raise ValueError("AgentRuntimeSpec authority must be agent_system.agent_runtime_spec")
        if not self.runtime_spec_id:
            raise ValueError("AgentRuntimeSpec requires runtime_spec_id")
        if not self.task_id:
            raise ValueError("AgentRuntimeSpec requires task_id")
        if not self.session_id:
            raise ValueError("AgentRuntimeSpec requires session_id")
        if not self.agent_id:
            raise ValueError("AgentRuntimeSpec requires agent_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["context_input_refs"] = list(self.context_input_refs)
        return payload



