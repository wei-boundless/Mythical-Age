from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ComposableUnitType = Literal[
    "node",
    "graph",
    "resource",
    "human_gate",
    "tool",
    "runtime_monitor",
]
UnitPortDirection = Literal["input", "output"]


@dataclass(frozen=True, slots=True)
class UnitPort:
    port_id: str
    title: str
    direction: UnitPortDirection
    payload_contract_id: str = ""
    required: bool = True
    status_required: str = ""
    visibility_policy: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class UnitInterface:
    interface_id: str
    unit_id: str
    display_name_zh: str
    input_ports: tuple[UnitPort, ...] = ()
    output_ports: tuple[UnitPort, ...] = ()
    memory_visibility_policy: str = "explicit_refs_only"
    artifact_visibility_policy: str = "refs_only"
    runtime_state_policy: str = "status_only"
    version: str = "v1"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface_id": self.interface_id,
            "unit_id": self.unit_id,
            "display_name_zh": self.display_name_zh,
            "input_ports": [item.to_dict() for item in self.input_ports],
            "output_ports": [item.to_dict() for item in self.output_ports],
            "memory_visibility_policy": self.memory_visibility_policy,
            "artifact_visibility_policy": self.artifact_visibility_policy,
            "runtime_state_policy": self.runtime_state_policy,
            "version": self.version,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ComposableUnit:
    unit_id: str
    unit_type: ComposableUnitType
    title: str
    ref: dict[str, Any] = field(default_factory=dict)
    interface_id: str = ""
    runtime_policy: dict[str, Any] = field(default_factory=dict)
    phase_id: str = ""
    sequence_index: int = 0
    source_kind: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class UnitPortEdge:
    edge_id: str
    source_unit_id: str
    source_port_id: str
    target_unit_id: str
    target_port_id: str
    payload_contract_id: str = ""
    edge_type: str = "handoff"
    temporal_semantics: dict[str, Any] = field(default_factory=dict)
    handoff: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GraphModuleRuntimePlan:
    plan_id: str
    importing_graph_id: str
    unit_id: str
    linked_graph_id: str
    version_ref: str = ""
    handoff_contract_id: str = ""
    input_port_id: str = "input.default"
    output_port_id: str = "output.default"
    isolation_policy: str = "isolated_per_graph_module_run"
    visibility_policy: str = "committed_only"
    detach_policy: str = "preserve_version_anchor"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ComposableGraphView:
    authority: str
    graph: dict[str, Any]
    units: tuple[ComposableUnit, ...]
    interfaces: tuple[UnitInterface, ...]
    port_edges: tuple[UnitPortEdge, ...]
    graph_module_runtime: tuple[GraphModuleRuntimePlan, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    issues: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "graph": dict(self.graph),
            "units": [item.to_dict() for item in self.units],
            "interfaces": [item.to_dict() for item in self.interfaces],
            "port_edges": [item.to_dict() for item in self.port_edges],
            "graph_module_runtime": [item.to_dict() for item in self.graph_module_runtime],
            "diagnostics": dict(self.diagnostics),
            "issues": [dict(item) for item in self.issues],
        }
