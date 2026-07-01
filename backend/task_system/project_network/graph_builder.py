from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from task_system.graphs.task_graph_models import (
    TaskGraphDefinition,
    TaskGraphEdgeDefinition,
    TaskGraphNodeDefinition,
)

from .layer_plan_models import NextGraphMaterializationPackage, ProjectNetworkBuildPlan, StaticGraphMaterializationPackage
from .shard_models import SemanticShardSpec, ShardPlan
from .template_catalog import ProjectNetworkNodeTemplate, build_project_network_template_catalog, resolve_project_network_node_template


@dataclass(frozen=True, slots=True)
class ProjectNetworkGraphBuilder:
    template_catalog: dict[str, ProjectNetworkNodeTemplate] = field(default_factory=build_project_network_template_catalog)

    def build_static_graph(self, package: StaticGraphMaterializationPackage) -> TaskGraphDefinition:
        return self._build_graph(
            graph_id=package.graph_id or f"graph:{package.build_id}:static",
            title=f"Project network build {package.build_id}",
            build_id=package.build_id,
            build_plan=package.build_plan,
            shard_plan=package.shard_plan,
            package_ref=package.package_id,
            materialization_mode="static_pre_materialized",
            source_work_product_refs=package.source_work_product_refs,
        )

    def build_next_graph(self, package: NextGraphMaterializationPackage) -> TaskGraphDefinition:
        return self._build_graph(
            graph_id=package.graph_id or f"graph:{package.build_id}:{_slug(package.target_layer_id)}",
            title=f"Project network build {package.build_id} {package.target_layer_id}",
            build_id=package.build_id,
            build_plan=package.build_plan,
            shard_plan=package.shard_plan,
            package_ref=package.package_id,
            materialization_mode="rolling_one_hop",
            source_work_product_refs=package.source_work_product_refs,
            parent_graph_run_id=package.parent_graph_run_id,
            parent_layer_index_ref=package.parent_layer_index_ref,
        )

    def _build_graph(
        self,
        *,
        graph_id: str,
        title: str,
        build_id: str,
        build_plan: ProjectNetworkBuildPlan,
        shard_plan: ShardPlan,
        package_ref: str,
        materialization_mode: str,
        source_work_product_refs: tuple[str, ...] = (),
        parent_graph_run_id: str = "",
        parent_layer_index_ref: str = "",
    ) -> TaskGraphDefinition:
        source_node = _source_node(build_id=build_id, package_ref=package_ref)
        output_node = _output_node(build_id=build_id, package_ref=package_ref)
        nodes: list[TaskGraphNodeDefinition] = [source_node]
        edges: list[TaskGraphEdgeDefinition] = []
        shard_node_ids: dict[str, str] = {}
        previous_layer_aggregate_node_id = ""
        sequence = 1
        for layer in build_plan.layers:
            layer_shards = shard_plan.shards_for_layer(layer.layer_id)
            if not layer_shards:
                continue
            current_layer_node_ids: list[str] = []
            for shard in layer_shards:
                node = self._materialize_shard_node(shard, sequence_index=sequence)
                sequence += 1
                nodes.append(node)
                shard_node_ids[shard.shard_id] = node.node_id
                current_layer_node_ids.append(node.node_id)
                upstream_ids = _dependency_node_ids(shard, shard_node_ids)
                if not upstream_ids and previous_layer_aggregate_node_id:
                    upstream_ids = [previous_layer_aggregate_node_id]
                for upstream_node_id in upstream_ids:
                    edges.append(_edge(upstream_node_id, node.node_id, payload_contract_id=shard.payload_contract_id))
            aggregate_node = self._aggregation_node(
                build_id=build_id,
                layer_id=layer.layer_id,
                layer_kind=layer.layer_kind,
                input_node_ids=tuple(current_layer_node_ids),
                sequence_index=sequence,
            )
            sequence += 1
            nodes.append(aggregate_node)
            for node_id in current_layer_node_ids:
                edges.append(_edge(node_id, aggregate_node.node_id, payload_contract_id=layer.output_contract_id))
            previous_layer_aggregate_node_id = aggregate_node.node_id
        nodes.append(output_node)
        return TaskGraphDefinition(
            graph_id=graph_id,
            title=title,
            domain_id="project_network",
            graph_kind="coordination",
            entry_node_id=source_node.node_id,
            output_node_id=output_node.node_id,
            nodes=tuple(nodes),
            edges=tuple(edges),
            graph_contract_id="project_network.build_graph.v1",
            runtime_policy={
                "materialization_mode": materialization_mode,
                "project_network_build_id": build_id,
                "package_ref": package_ref,
                "coordinator_agent_id": "agent:project_network_coordinator",
                "coordinator_agent_profile_id": "project_network_coordinator_agent",
                "agent_group_id": "group.project_network_builders",
            },
            context_policy={
                "state_projection": "raw_structured_refs",
                "prompt_projection": "node_contract_runtime",
            },
            publish_state="draft",
            enabled=False,
            metadata={
                "project_network_build_id": build_id,
                "project_network_package_ref": package_ref,
                "materialization_mode": materialization_mode,
                "source_work_product_refs": list(source_work_product_refs),
                "parent_graph_run_id": parent_graph_run_id,
                "parent_layer_index_ref": parent_layer_index_ref,
                "authority_boundary": "project_network_builder_materializes_task_graph_only",
            },
        )

    def _materialize_shard_node(self, shard: SemanticShardSpec, *, sequence_index: int) -> TaskGraphNodeDefinition:
        template = resolve_project_network_node_template(shard.node_template_id, self.template_catalog)
        return template.materialize_node(shard, sequence_index=sequence_index)

    def _aggregation_node(
        self,
        *,
        build_id: str,
        layer_id: str,
        layer_kind: str,
        input_node_ids: tuple[str, ...],
        sequence_index: int,
    ) -> TaskGraphNodeDefinition:
        template = resolve_project_network_node_template("project_network.layer_aggregate", self.template_catalog)
        metadata = {
            **dict(template.metadata or {}),
            "prompt_contract": dict(template.prompt_contract or {}),
            "project_network_build_id": build_id,
            "layer_id": layer_id,
            "layer_kind": layer_kind,
            "input_node_ids": list(input_node_ids),
            "route_authority": "static_edges",
            "work_product_channel_policy": "consume_layer_typed_channels",
        }
        agent_profile_id = template.agent_profile_id
        if agent_profile_id:
            metadata["agent_profile_id"] = agent_profile_id
        return TaskGraphNodeDefinition(
            node_id=f"pn.{_slug(layer_id)}.aggregate",
            node_type=template.node_type,
            title=f"{template.title}: {layer_id}",
            node_config_id=template.node_config_id,
            agent_id=template.agent_id,
            agent_group_id=template.agent_group_id,
            work_posture=template.work_posture,
            node_contract_id=template.node_contract_id,
            input_contract_id=template.input_contract_id,
            output_contract_id=template.output_contract_id,
            contract_bindings={
                "schema": {
                    "output_contract_id": template.output_contract_id,
                },
                "execution": {
                    "node_contract_id": template.node_contract_id,
                },
                "semantic": {
                    "layer_id": layer_id,
                    "layer_kind": layer_kind,
                    "aggregation_policy": "typed_work_product_channel",
                },
            },
            executor_policy=dict(template.executor_policy or {}),
            runtime_policy=dict(template.runtime_policy or {}),
            sequence_index=sequence_index,
            execution_mode=template.execution_mode,
            dispatch_group=template.dispatch_group,
            wait_policy=template.wait_policy,
            join_policy=template.join_policy,
            metadata=metadata,
        )


def _source_node(*, build_id: str, package_ref: str) -> TaskGraphNodeDefinition:
    return TaskGraphNodeDefinition(
        node_id="pn.source",
        node_type="runtime_state_store",
        title="Project network source refs",
        output_contract_id="project_network.source_refs.v1",
        metadata={
            "project_network_build_id": build_id,
            "project_network_package_ref": package_ref,
            "route_authority": "static_edges",
        },
    )


def _output_node(*, build_id: str, package_ref: str) -> TaskGraphNodeDefinition:
    return TaskGraphNodeDefinition(
        node_id="pn.output",
        node_type="artifact_repository",
        title="Project network graph output",
        input_contract_id="project_network.graph_output.v1",
        metadata={
            "project_network_build_id": build_id,
            "project_network_package_ref": package_ref,
            "output_policy": "refs_only_generation_candidate",
        },
    )


def _dependency_node_ids(shard: SemanticShardSpec, shard_node_ids: dict[str, str]) -> list[str]:
    return [shard_node_ids[item] for item in shard.dependencies if item in shard_node_ids]


def _edge(source_node_id: str, target_node_id: str, *, payload_contract_id: str = "") -> TaskGraphEdgeDefinition:
    return TaskGraphEdgeDefinition(
        edge_id=f"edge.{_slug(source_node_id)}.to.{_slug(target_node_id)}",
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        edge_type="handoff",
        payload_contract_id=payload_contract_id,
        ack_required=True,
        failure_propagation_policy="allow_partial" if target_node_id.endswith(".aggregate") else "fail_downstream",
        result_delivery_policy="contract_payload_and_refs",
        metadata={
            "project_network_edge": True,
        },
    )


def _slug(value: str) -> str:
    return ".".join(part for part in str(value or "").replace(":", ".").replace("/", ".").replace("\\", ".").replace("_", ".").replace("-", ".").split(".") if part)
