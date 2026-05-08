from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeContextSection:
    section_id: str
    title: str
    visibility: str = "model_visible"
    content_mode: str = "summary"
    source_ref: str = ""
    model_visible: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RuntimeOutputContract:
    contract_id: str
    title_zh: str = ""
    required_fields: tuple[str, ...] = ()
    artifact_requirements: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_fields"] = list(self.required_fields)
        payload["artifact_requirements"] = [dict(item) for item in self.artifact_requirements]
        return payload


@dataclass(frozen=True, slots=True)
class RuntimeAcceptanceContract:
    contract_id: str
    rule_refs: tuple[str, ...] = ()
    hard_rule_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rule_refs"] = list(self.rule_refs)
        return payload


@dataclass(frozen=True, slots=True)
class RuntimeFailureContract:
    failure_mode: str = "fail_closed"
    retry_allowed: bool = False
    escalate_to: str = "coordinator"
    fallback_contract_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RuntimeLoopPolicy:
    loop_mode: str = "single_agent"
    max_turns: int = 1
    context_strategy: str = "assembly_visible_sections"
    acceptance_required: bool = True
    human_gate_enabled: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HandoffPacket:
    packet_id: str
    source_node_id: str
    target_node_id: str
    source_agent_id: str = ""
    target_agent_id: str = ""
    contract_refs: tuple[str, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)
    a2a_trace: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.runtime_handoff_packet"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["contract_refs"] = list(self.contract_refs)
        return payload


@dataclass(frozen=True, slots=True)
class SingleAgentRuntimeAssembly:
    assembly_id: str
    manifest_ref: str
    task_ref: str
    workflow_id: str
    agent_id: str
    agent_profile_id: str
    runtime_lane: str = ""
    context_sections: tuple[RuntimeContextSection, ...] = ()
    output_contracts: tuple[RuntimeOutputContract, ...] = ()
    acceptance_contracts: tuple[RuntimeAcceptanceContract, ...] = ()
    failure_contract: RuntimeFailureContract = field(default_factory=RuntimeFailureContract)
    loop_policy: RuntimeLoopPolicy = field(default_factory=RuntimeLoopPolicy)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.single_agent_runtime_assembly"

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "assembly_id": self.assembly_id,
            "manifest_ref": self.manifest_ref,
            "task_ref": self.task_ref,
            "workflow_id": self.workflow_id,
            "agent_id": self.agent_id,
            "agent_profile_id": self.agent_profile_id,
            "runtime_lane": self.runtime_lane,
            "context_sections": [item.to_dict() for item in self.context_sections],
            "output_contracts": [item.to_dict() for item in self.output_contracts],
            "acceptance_contracts": [item.to_dict() for item in self.acceptance_contracts],
            "failure_contract": self.failure_contract.to_dict(),
            "loop_policy": self.loop_policy.to_dict(),
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class NodeRuntimeAssembly:
    assembly_id: str
    manifest_ref: str
    coordination_task_ref: str
    graph_id: str
    node_id: str
    task_ref: str
    agent_id: str
    agent_profile_id: str = ""
    runtime_lane: str = ""
    context_sections: tuple[RuntimeContextSection, ...] = ()
    input_contract_refs: tuple[str, ...] = ()
    output_contracts: tuple[RuntimeOutputContract, ...] = ()
    acceptance_contracts: tuple[RuntimeAcceptanceContract, ...] = ()
    handoff_packets: tuple[HandoffPacket, ...] = ()
    failure_contract: RuntimeFailureContract = field(default_factory=RuntimeFailureContract)
    loop_policy: RuntimeLoopPolicy = field(default_factory=lambda: RuntimeLoopPolicy(loop_mode="coordination_node"))
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.node_runtime_assembly"

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "assembly_id": self.assembly_id,
            "manifest_ref": self.manifest_ref,
            "coordination_task_ref": self.coordination_task_ref,
            "graph_id": self.graph_id,
            "node_id": self.node_id,
            "task_ref": self.task_ref,
            "agent_id": self.agent_id,
            "agent_profile_id": self.agent_profile_id,
            "runtime_lane": self.runtime_lane,
            "context_sections": [item.to_dict() for item in self.context_sections],
            "input_contract_refs": list(self.input_contract_refs),
            "output_contracts": [item.to_dict() for item in self.output_contracts],
            "acceptance_contracts": [item.to_dict() for item in self.acceptance_contracts],
            "handoff_packets": [item.to_dict() for item in self.handoff_packets],
            "failure_contract": self.failure_contract.to_dict(),
            "loop_policy": self.loop_policy.to_dict(),
            "diagnostics": dict(self.diagnostics),
        }
