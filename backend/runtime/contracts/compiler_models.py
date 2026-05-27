from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ContractCompileIssue:
    code: str
    message: str
    severity: str = "error"
    source_ref: str = ""
    contract_id: str = ""
    node_id: str = ""
    edge_id: str = ""
    agent_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CompiledGlobalContract:
    contract_id: str
    title_zh: str
    contract_kind: str
    source_ref: str
    input_fields: tuple[dict[str, Any], ...] = ()
    output_fields: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["input_fields"] = [dict(item) for item in self.input_fields]
        payload["output_fields"] = [dict(item) for item in self.output_fields]
        return payload


@dataclass(frozen=True, slots=True)
class CompiledWorkflowContract:
    workflow_id: str
    title: str
    output_contract_id: str
    step_contracts: tuple[dict[str, Any], ...] = ()
    source_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["step_contracts"] = [dict(item) for item in self.step_contracts]
        return payload


@dataclass(frozen=True, slots=True)
class CompiledNodeContract:
    node_id: str
    title: str
    node_type: str
    task_id: str = ""
    agent_id: str = ""
    runtime_lane: str = ""
    input_contract_id: str = ""
    output_contract_id: str = ""
    contract_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    schema_bindings: dict[str, Any] = field(default_factory=dict)
    execution_bindings: dict[str, Any] = field(default_factory=dict)
    artifact_bindings: dict[str, Any] = field(default_factory=dict)
    memory_bindings: dict[str, Any] = field(default_factory=dict)
    acceptance_bindings: dict[str, Any] = field(default_factory=dict)
    runtime_bindings: dict[str, Any] = field(default_factory=dict)
    unit_batch_bindings: dict[str, Any] = field(default_factory=dict)
    governance_bindings: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["contract_refs"] = list(self.contract_refs)
        payload["source_refs"] = list(self.source_refs)
        payload["schema_bindings"] = dict(self.schema_bindings)
        payload["execution_bindings"] = dict(self.execution_bindings)
        payload["artifact_bindings"] = dict(self.artifact_bindings)
        payload["memory_bindings"] = dict(self.memory_bindings)
        payload["acceptance_bindings"] = dict(self.acceptance_bindings)
        payload["runtime_bindings"] = dict(self.runtime_bindings)
        payload["unit_batch_bindings"] = dict(self.unit_batch_bindings)
        payload["governance_bindings"] = dict(self.governance_bindings)
        return payload


@dataclass(frozen=True, slots=True)
class CompiledEdgeHandoffContract:
    edge_id: str
    source_node_id: str
    target_node_id: str
    message_type: str
    contract_refs: tuple[str, ...] = ()
    handoff_policy: str = "structured_packet"
    schema_bindings: dict[str, Any] = field(default_factory=dict)
    handoff_bindings: dict[str, Any] = field(default_factory=dict)
    temporal_bindings: dict[str, Any] = field(default_factory=dict)
    memory_bindings: dict[str, Any] = field(default_factory=dict)
    artifact_bindings: dict[str, Any] = field(default_factory=dict)
    governance_bindings: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["contract_refs"] = list(self.contract_refs)
        payload["schema_bindings"] = dict(self.schema_bindings)
        payload["handoff_bindings"] = dict(self.handoff_bindings)
        payload["temporal_bindings"] = dict(self.temporal_bindings)
        payload["memory_bindings"] = dict(self.memory_bindings)
        payload["artifact_bindings"] = dict(self.artifact_bindings)
        payload["governance_bindings"] = dict(self.governance_bindings)
        return payload


@dataclass(frozen=True, slots=True)
class CompiledGraphModuleHandoffContract:
    plan_id: str
    importing_graph_id: str
    runtime_node_id: str
    unit_id: str
    linked_graph_id: str
    handoff_contract_id: str = ""
    contract_refs: tuple[str, ...] = ()
    version_ref: str = ""
    input_port_id: str = "input.default"
    output_port_id: str = "output.default"
    handoff_policy: str = "graph_module_commit_packet"
    source_refs: tuple[str, ...] = ()
    handoff_bindings: dict[str, Any] = field(default_factory=dict)
    runtime_bindings: dict[str, Any] = field(default_factory=dict)
    governance_bindings: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["contract_refs"] = list(self.contract_refs)
        payload["source_refs"] = list(self.source_refs)
        payload["handoff_bindings"] = dict(self.handoff_bindings)
        payload["runtime_bindings"] = dict(self.runtime_bindings)
        payload["governance_bindings"] = dict(self.governance_bindings)
        return payload


@dataclass(frozen=True, slots=True)
class CompiledRuntimeContract:
    agent_id: str
    agent_profile_id: str
    allowed_runtime_lanes: tuple[str, ...] = ()
    allowed_operations: tuple[str, ...] = ()
    allowed_memory_scopes: tuple[str, ...] = ()
    validation_state: str = "unchecked"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_runtime_lanes"] = list(self.allowed_runtime_lanes)
        payload["allowed_operations"] = list(self.allowed_operations)
        payload["allowed_memory_scopes"] = list(self.allowed_memory_scopes)
        return payload


@dataclass(frozen=True, slots=True)
class CompiledAcceptanceContract:
    contract_id: str
    rule_count: int
    rule_refs: tuple[str, ...] = ()
    source_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rule_refs"] = list(self.rule_refs)
        return payload


@dataclass(frozen=True, slots=True)
class ContractManifest:
    manifest_id: str
    manifest_kind: str
    task_ref: str = ""
    workflow_id: str = ""
    graph_id: str = ""
    graph_ref: str = ""
    global_contracts: tuple[CompiledGlobalContract, ...] = ()
    workflow_contracts: tuple[CompiledWorkflowContract, ...] = ()
    node_contracts: tuple[CompiledNodeContract, ...] = ()
    edge_handoff_contracts: tuple[CompiledEdgeHandoffContract, ...] = ()
    graph_module_handoff_contracts: tuple[CompiledGraphModuleHandoffContract, ...] = ()
    runtime_contracts: tuple[CompiledRuntimeContract, ...] = ()
    acceptance_contracts: tuple[CompiledAcceptanceContract, ...] = ()
    issues: tuple[ContractCompileIssue, ...] = ()
    graph_contract_bindings: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.contract_manifest"

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "manifest_id": self.manifest_id,
            "manifest_kind": self.manifest_kind,
            "task_ref": self.task_ref,
            "workflow_id": self.workflow_id,
            "graph_id": self.graph_id,
            "graph_ref": self.graph_ref or self.graph_id,
            "global_contracts": [item.to_dict() for item in self.global_contracts],
            "workflow_contracts": [item.to_dict() for item in self.workflow_contracts],
            "node_contracts": [item.to_dict() for item in self.node_contracts],
            "edge_handoff_contracts": [item.to_dict() for item in self.edge_handoff_contracts],
            "graph_module_handoff_contracts": [item.to_dict() for item in self.graph_module_handoff_contracts],
            "runtime_contracts": [item.to_dict() for item in self.runtime_contracts],
            "acceptance_contracts": [item.to_dict() for item in self.acceptance_contracts],
            "issues": [item.to_dict() for item in self.issues],
            "graph_contract_bindings": dict(self.graph_contract_bindings),
            "metadata": dict(self.metadata),
            "valid": self.valid,
        }
