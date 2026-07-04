from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .shard_models import ShardPlan


GraphMaterializationMode = Literal["static_pre_materialized", "rolling_one_hop", "runtime_requested_expansion"]
NodeRouteAuthority = Literal["static_edges", "conditional_route", "next_graph_materialization", "human_gate_decision"]


@dataclass(frozen=True, slots=True)
class ProjectNetworkLayerPlan:
    layer_id: str
    layer_kind: str
    input_refs: tuple[str, ...] = ()
    upstream_layer_refs: tuple[str, ...] = ()
    shard_policy: dict[str, Any] = field(default_factory=dict)
    node_template_refs: tuple[str, ...] = ()
    aggregation_policy: dict[str, Any] = field(default_factory=dict)
    validation_policy: dict[str, Any] = field(default_factory=dict)
    output_contract_id: str = ""
    publish_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.layer_plan"

    def __post_init__(self) -> None:
        if self.authority != "project_network_system.layer_plan":
            raise ValueError("ProjectNetworkLayerPlan authority mismatch")
        if not str(self.layer_id or "").strip():
            raise ValueError("ProjectNetworkLayerPlan requires layer_id")
        if not str(self.layer_kind or "").strip():
            raise ValueError("ProjectNetworkLayerPlan requires layer_kind")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectNetworkLayerPlan":
        payload = dict(payload or {})
        return cls(
            layer_id=str(payload.get("layer_id") or ""),
            layer_kind=str(payload.get("layer_kind") or payload.get("target_layer") or ""),
            input_refs=_tuple_of_strings(payload.get("input_refs")),
            upstream_layer_refs=_tuple_of_strings(payload.get("upstream_layer_refs")),
            shard_policy=dict(payload.get("shard_policy") or {}),
            node_template_refs=_tuple_of_strings(payload.get("node_template_refs")),
            aggregation_policy=dict(payload.get("aggregation_policy") or {}),
            validation_policy=dict(payload.get("validation_policy") or {}),
            output_contract_id=str(payload.get("output_contract_id") or ""),
            publish_policy=dict(payload.get("publish_policy") or {}),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class ProjectNetworkBuildPlan:
    plan_id: str
    build_id: str
    materialization_mode: GraphMaterializationMode
    layers: tuple[ProjectNetworkLayerPlan, ...] = ()
    source_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.build_plan"

    def __post_init__(self) -> None:
        if self.authority != "project_network_system.build_plan":
            raise ValueError("ProjectNetworkBuildPlan authority mismatch")
        if not str(self.plan_id or "").strip():
            raise ValueError("ProjectNetworkBuildPlan requires plan_id")
        if not str(self.build_id or "").strip():
            raise ValueError("ProjectNetworkBuildPlan requires build_id")
        if self.materialization_mode not in {"static_pre_materialized", "rolling_one_hop", "runtime_requested_expansion"}:
            raise ValueError("unsupported ProjectNetworkBuildPlan materialization_mode")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectNetworkBuildPlan":
        payload = dict(payload or {})
        return cls(
            plan_id=str(payload.get("plan_id") or ""),
            build_id=str(payload.get("build_id") or ""),
            materialization_mode=str(payload.get("materialization_mode") or "static_pre_materialized"),  # type: ignore[arg-type]
            layers=tuple(ProjectNetworkLayerPlan.from_dict(item) for item in list(payload.get("layers") or []) if isinstance(item, dict)),
            source_refs=_tuple_of_strings(payload.get("source_refs")),
            metadata=dict(payload.get("metadata") or {}),
        )

    def layer_by_id(self, layer_id: str) -> ProjectNetworkLayerPlan | None:
        for layer in self.layers:
            if layer.layer_id == layer_id:
                return layer
        return None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["layers"] = [item.to_dict() for item in self.layers]
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class ProjectStructureIntakeProduct:
    product_id: str
    build_id: str
    file_tree_snapshot_ref: str = ""
    deep_ast_generation_ref: str = ""
    observed: dict[str, Any] = field(default_factory=dict)
    mode_recommendation: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.structure_intake_product"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class ProjectNetworkBootstrapPlan:
    bootstrap_plan_id: str
    build_id: str
    intake_product_ref: str = ""
    selected_mode: GraphMaterializationMode = "rolling_one_hop"
    first_layer_id: str = ""
    validation_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.bootstrap_plan"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class StaticGraphMaterializationPackage:
    package_id: str
    build_id: str
    build_plan: ProjectNetworkBuildPlan
    shard_plan: ShardPlan
    graph_id: str = ""
    source_work_product_refs: tuple[str, ...] = ()
    validation_product_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.static_graph_materialization_package"

    def __post_init__(self) -> None:
        if self.authority != "project_network_system.static_graph_materialization_package":
            raise ValueError("StaticGraphMaterializationPackage authority mismatch")
        if not str(self.package_id or "").strip():
            raise ValueError("StaticGraphMaterializationPackage requires package_id")
        if not str(self.build_id or "").strip():
            raise ValueError("StaticGraphMaterializationPackage requires build_id")
        if self.build_plan.materialization_mode != "static_pre_materialized":
            raise ValueError("StaticGraphMaterializationPackage requires static_pre_materialized build_plan")
        if self.shard_plan.mode != "static_pre_materialized":
            raise ValueError("StaticGraphMaterializationPackage requires static_pre_materialized shard_plan")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["build_plan"] = self.build_plan.to_dict()
        payload["shard_plan"] = self.shard_plan.to_dict()
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class NextGraphMaterializationPackage:
    package_id: str
    build_id: str
    parent_graph_run_id: str
    target_layer_id: str
    build_plan: ProjectNetworkBuildPlan
    shard_plan: ShardPlan
    graph_id: str = ""
    parent_layer_index_ref: str = ""
    source_work_product_refs: tuple[str, ...] = ()
    validation_product_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.next_graph_materialization_package"

    def __post_init__(self) -> None:
        if self.authority != "project_network_system.next_graph_materialization_package":
            raise ValueError("NextGraphMaterializationPackage authority mismatch")
        if not str(self.package_id or "").strip():
            raise ValueError("NextGraphMaterializationPackage requires package_id")
        if not str(self.build_id or "").strip():
            raise ValueError("NextGraphMaterializationPackage requires build_id")
        if self.build_plan.materialization_mode != "rolling_one_hop":
            raise ValueError("NextGraphMaterializationPackage requires rolling_one_hop build_plan")
        if self.shard_plan.mode != "rolling_one_hop":
            raise ValueError("NextGraphMaterializationPackage requires rolling_one_hop shard_plan")
        if not str(self.parent_graph_run_id or "").strip():
            raise ValueError("NextGraphMaterializationPackage requires parent_graph_run_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["build_plan"] = self.build_plan.to_dict()
        payload["shard_plan"] = self.shard_plan.to_dict()
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class NodeRouteDecision:
    node_id: str
    route_authority: NodeRouteAuthority
    state_update_refs: tuple[str, ...] = ()
    next_package_ref: str = ""
    conditional_route_id: str = ""
    human_gate_ref: str = ""
    allowed_static_edges: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.node_route_decision"

    def __post_init__(self) -> None:
        if self.authority != "project_network_system.node_route_decision":
            raise ValueError("NodeRouteDecision authority mismatch")
        if self.route_authority not in {"static_edges", "conditional_route", "next_graph_materialization", "human_gate_decision"}:
            raise ValueError("unsupported NodeRouteDecision route_authority")
        if self.route_authority == "next_graph_materialization" and self.allowed_static_edges:
            raise ValueError("next_graph_materialization nodes must not also continue through static edges")
        if self.route_authority == "next_graph_materialization" and not self.next_package_ref:
            raise ValueError("next_graph_materialization requires next_package_ref")
        if self.route_authority == "conditional_route" and not self.conditional_route_id:
            raise ValueError("conditional_route requires conditional_route_id")
        if self.route_authority == "human_gate_decision" and not self.human_gate_ref:
            raise ValueError("human_gate_decision requires human_gate_ref")

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class GraphGenerationLineage:
    lineage_id: str
    build_id: str
    graph_generation: int
    materialization_mode: GraphMaterializationMode
    parent_graph_run_id: str = ""
    parent_layer_index_ref: str = ""
    source_work_product_refs: tuple[str, ...] = ()
    materialization_package_ref: str = ""
    executable_graph_config_ref: str = ""
    forked_from: str = ""
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.graph_generation_lineage"

    def __post_init__(self) -> None:
        if self.authority != "project_network_system.graph_generation_lineage":
            raise ValueError("GraphGenerationLineage authority mismatch")
        if not str(self.lineage_id or "").strip():
            raise ValueError("GraphGenerationLineage requires lineage_id")
        if not str(self.build_id or "").strip():
            raise ValueError("GraphGenerationLineage requires build_id")
        if self.materialization_mode not in {"static_pre_materialized", "rolling_one_hop", "runtime_requested_expansion"}:
            raise ValueError("unsupported GraphGenerationLineage materialization_mode")
        if self.graph_generation < 0:
            raise ValueError("GraphGenerationLineage graph_generation must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.replace(",", "\n").splitlines() if item.strip())
    return tuple(str(item).strip() for item in list(value or []) if str(item).strip())


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}

