from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


RuntimeShape = Literal["single_agent", "task_graph", "human_gate", "subruntime"]


@dataclass(frozen=True, slots=True)
class AgentSelectionPolicy:
    default_agent_id: str = "agent:0"
    agent_profile_ref: str = ""
    worker_blueprint_id: str = ""
    allow_worker_spawn: bool = False
    participant_agent_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["participant_agent_refs"] = list(self.participant_agent_refs)
        return payload


@dataclass(frozen=True, slots=True)
class RequirementRefs:
    required_refs: tuple[str, ...] = ()
    optional_refs: tuple[str, ...] = ()
    denied_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_refs": list(self.required_refs),
            "optional_refs": list(self.optional_refs),
            "denied_refs": list(self.denied_refs),
        }


@dataclass(frozen=True, slots=True)
class ToolCapabilityRequirements:
    required_operations: tuple[str, ...] = ()
    optional_operations: tuple[str, ...] = ()
    denied_operations: tuple[str, ...] = ()
    required_tool_tags: tuple[str, ...] = ()
    preferred_tools: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_operations": list(self.required_operations),
            "optional_operations": list(self.optional_operations),
            "denied_operations": list(self.denied_operations),
            "required_tool_tags": list(self.required_tool_tags),
            "preferred_tools": list(self.preferred_tools),
        }


@dataclass(frozen=True, slots=True)
class SpecificTaskAssemblyPolicy:
    policy_id: str
    task_id: str
    environment_id: str
    flow_ref: str = ""
    agent_selection: AgentSelectionPolicy = field(default_factory=AgentSelectionPolicy)
    skill_requirements: RequirementRefs = field(default_factory=RequirementRefs)
    prompt_requirements: RequirementRefs = field(default_factory=RequirementRefs)
    tool_capability_requirements: ToolCapabilityRequirements = field(default_factory=ToolCapabilityRequirements)
    memory_requirements: dict[str, Any] = field(default_factory=dict)
    resource_requirements: dict[str, Any] = field(default_factory=dict)
    output_contract_ref: str = ""
    acceptance_policy: dict[str, Any] = field(default_factory=dict)
    runtime_shape: RuntimeShape = "single_agent"
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.specific_task_assembly_policy"

    def __post_init__(self) -> None:
        if self.authority != "task_system.specific_task_assembly_policy":
            raise ValueError("SpecificTaskAssemblyPolicy authority must be task_system.specific_task_assembly_policy")
        if not str(self.task_id or "").strip():
            raise ValueError("SpecificTaskAssemblyPolicy requires task_id")
        if not str(self.environment_id or "").strip():
            raise ValueError("SpecificTaskAssemblyPolicy requires environment_id")
        if not str(self.policy_id or "").strip():
            object.__setattr__(self, "policy_id", build_specific_task_assembly_policy_id(self.task_id, self.environment_id))

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "task_id": self.task_id,
            "environment_id": self.environment_id,
            "flow_ref": self.flow_ref,
            "agent_selection": self.agent_selection.to_dict(),
            "skill_requirements": self.skill_requirements.to_dict(),
            "prompt_requirements": self.prompt_requirements.to_dict(),
            "tool_capability_requirements": self.tool_capability_requirements.to_dict(),
            "memory_requirements": dict(self.memory_requirements),
            "resource_requirements": dict(self.resource_requirements),
            "output_contract_ref": self.output_contract_ref,
            "acceptance_policy": dict(self.acceptance_policy),
            "runtime_shape": self.runtime_shape,
            "metadata": dict(self.metadata),
            "authority": self.authority,
        }


def build_specific_task_assembly_policy_id(task_id: str, environment_id: str) -> str:
    raw = json.dumps(
        {"task_id": str(task_id or ""), "environment_id": str(environment_id or "")},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"taskasm:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"
