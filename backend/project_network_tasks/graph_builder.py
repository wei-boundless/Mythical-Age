from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from task_system.graphs.task_graph_models import (
    TaskGraphDefinition,
    TaskGraphEdgeDefinition,
    TaskGraphNodeDefinition,
)

from project_network_system.directory_render_models import DirectoryFrameMaterializationPackage
from project_network_system.layer_plan_models import NextGraphMaterializationPackage, ProjectNetworkBuildPlan, StaticGraphMaterializationPackage
from project_network_system.shard_models import SemanticShardSpec, ShardAssignment, ShardComplexity, ShardExecutorPolicy, ShardPlan

from .template_catalog import ProjectNetworkNodeTemplate, build_project_network_template_catalog, resolve_project_network_node_template


@dataclass(frozen=True, slots=True)
class ProjectNetworkGraphBuilder:
    template_catalog: dict[str, ProjectNetworkNodeTemplate] = field(default_factory=build_project_network_template_catalog)

    def build_static_graph(self, package: StaticGraphMaterializationPackage) -> TaskGraphDefinition:
        return self._build_graph(
            graph_id=package.graph_id or f"graph.project_network.{_slug(package.build_id)}.static",
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
            graph_id=package.graph_id or f"graph.project_network.{_slug(package.build_id)}.{_slug(package.target_layer_id)}",
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

    def build_directory_frame_graph(self, package: DirectoryFrameMaterializationPackage) -> TaskGraphDefinition:
        frame = package.frame
        manifest = package.manifest
        target_metadata = _target_project_metadata(package)
        loop_frame_id = f"pn.dirframe.{_slug(frame.frame_id)}"
        layer_id = f"directory_frame:{frame.frame_id}"
        nodes: list[TaskGraphNodeDefinition] = []
        edges: list[TaskGraphEdgeDefinition] = []
        sequence = 1
        file_node_ids: list[str] = []
        for file_card in manifest.direct_file_nodes:
            shard = _directory_file_shard(
                build_id=package.build_id,
                frame_id=frame.frame_id,
                layer_id=layer_id,
                folder_ref=frame.folder_stable_ref,
                manifest_ref=manifest.manifest_id,
                file_card=dict(file_card),
            )
            node = self._materialize_shard_node(shard, sequence_index=sequence)
            sequence += 1
            node = _with_directory_loop_contract(
                node,
                loop_frame_id=loop_frame_id,
                frame_package=package,
                work_unit_kind="direct_file_module_review",
            )
            nodes.append(node)
            file_node_ids.append(node.node_id)
        aggregate_node = self._directory_aggregate_node(
            package=package,
            loop_frame_id=loop_frame_id,
            input_node_ids=tuple(file_node_ids),
            sequence_index=sequence,
        )
        nodes.append(aggregate_node)
        for node_id in file_node_ids:
            edges.append(_edge(node_id, aggregate_node.node_id, payload_contract_id="project_network.module_index.v1"))
        graph_id = package.graph_id or f"graph.project_network.directory.{_slug(package.build_id)}.{_slug(frame.frame_id)}"
        start_node_ids = tuple(file_node_ids) if file_node_ids else (aggregate_node.node_id,)
        return TaskGraphDefinition(
            graph_id=graph_id,
            title=f"Project network directory frame {frame.folder_path or frame.folder_stable_ref}",
            domain_id="project_network",
            graph_kind="coordination",
            entry_node_id=start_node_ids[0],
            output_node_id=aggregate_node.node_id,
            nodes=tuple(nodes),
            edges=tuple(edges),
            graph_contract_id="project_network.directory_tree_reduce_frame.v1",
            runtime_policy={
                "materialization_mode": "directory_tree_reduce_frame",
                "runtime_algorithm": {
                    "algorithm_kind": "directory_tree_reduce",
                    "adapter_id": "project_network_work_product",
                    "authority": "project_network_tasks.directory_frame_graph_runtime_algorithm",
                },
                "project_network_build_id": package.build_id,
                "package_ref": package.package_id,
                "directory_frame_id": frame.frame_id,
                "coordinator_agent_id": "agent:project_network_coordinator",
                "coordinator_agent_profile_id": "project_network_coordinator_agent",
                "agent_group_id": "group.project_network_reviewers",
                "start_node_ids": list(start_node_ids),
                "max_active_nodes": _directory_max_active_nodes(package=package, file_node_count=len(file_node_ids)),
                **target_metadata,
            },
            context_policy={
                "state_projection": "directory_frame_typed_refs",
                "prompt_projection": "node_contract_runtime",
                "loop_algorithm": "tree_reduce",
            },
            loop_frames=(
                _directory_loop_frame(
                    package=package,
                    loop_frame_id=loop_frame_id,
                    scope_node_ids=tuple([*file_node_ids, aggregate_node.node_id]),
                    entry_node_id=start_node_ids[0],
                    exit_node_id=aggregate_node.node_id,
                ),
            ),
            publish_state="draft",
            enabled=False,
            metadata={
                "project_network_build_id": package.build_id,
                "project_network_package_ref": package.package_id,
                "directory_frame_id": frame.frame_id,
                "directory_manifest_ref": manifest.manifest_id,
                "materialization_mode": "directory_tree_reduce_frame",
                "source_work_product_refs": list(package.source_work_product_refs),
                "child_return_refs": [item.return_id for item in package.child_returns],
                **target_metadata,
                "authority_boundary": "project_network_review_graph_materializes_directory_frame_for_graph_loop",
            },
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

    def _directory_aggregate_node(
        self,
        *,
        package: DirectoryFrameMaterializationPackage,
        loop_frame_id: str,
        input_node_ids: tuple[str, ...],
        sequence_index: int,
    ) -> TaskGraphNodeDefinition:
        template = resolve_project_network_node_template("project_network.directory_aggregate", self.template_catalog)
        frame = package.frame
        manifest = package.manifest
        target_metadata = _target_project_metadata(package)
        metadata = {
            **dict(template.metadata or {}),
            "prompt_contract": dict(template.prompt_contract or {}),
            "project_network_build_id": package.build_id,
            "directory_frame_id": frame.frame_id,
            "directory_root_frame_id": frame.root_frame_id,
            "directory_parent_frame_id": frame.parent_frame_id,
            "directory_manifest_ref": manifest.manifest_id,
            "folder_stable_ref": frame.folder_stable_ref,
            "folder_path": frame.folder_path,
            "input_node_ids": list(input_node_ids),
            "direct_file_refs": list(manifest.direct_file_refs),
            "child_return_refs": [item.return_id for item in package.child_returns],
            "child_summary_product_refs": [item.child_summary_product_ref for item in package.child_returns if item.child_summary_product_ref],
            **target_metadata,
            "route_authority": "tree_reduce_static_frame_edges",
            "work_product_channel_policy": "consume_directory_typed_channels",
            "tree_reduce_scheduler_contract": {
                "algorithm_kind": "directory_tree_reduce",
                "fan_in_node_ids": list(input_node_ids),
                "join_policy": "all_success",
                "wait_policy": "wait_all_upstream_completed",
                "aggregate_after": "all_direct_file_module_indexes_completed",
                "authority": "project_network_tasks.directory_tree_reduce_scheduler_contract",
            },
        }
        if template.agent_profile_id:
            metadata["agent_profile_id"] = template.agent_profile_id
        return TaskGraphNodeDefinition(
            node_id=f"pn.dir.{_slug(frame.frame_id)}.aggregate",
            node_type=template.node_type,
            title=f"{template.title}: {frame.folder_path or frame.folder_stable_ref}",
            node_config_id=template.node_config_id,
            node_config_overrides={
                "directory_frame": frame.to_dict(),
                "directory_manifest": manifest.to_dict(),
                "child_returns": [item.to_dict() for item in package.child_returns],
                "source_work_product_refs": list(package.source_work_product_refs),
            },
            agent_id=template.agent_id,
            agent_group_id=template.agent_group_id,
            work_posture=template.work_posture,
            node_contract_id=template.node_contract_id,
            input_contract_id="",
            output_contract_id=template.output_contract_id,
            contract_bindings={
                "schema": {
                    "output_contract_id": template.output_contract_id,
                },
                "execution": {
                    "node_contract_id": template.node_contract_id,
                },
                "semantic": {
                    "work_unit_kind": "directory_aggregate",
                    "aggregation_policy": "tree_reduce_typed_work_products",
                    "directory_frame_id": frame.frame_id,
                },
            },
            executor_policy=dict(template.executor_policy or {}),
            runtime_policy={
                **dict(template.runtime_policy or {}),
                "project_network_directory_frame": {
                    "directory_frame_id": frame.frame_id,
                    "manifest_ref": manifest.manifest_id,
                    "child_return_refs": [item.return_id for item in package.child_returns],
                    "authority": "project_network_tasks.directory_frame_node_runtime_policy",
                },
                "tree_reduce_scheduler_contract": {
                    "algorithm_kind": "directory_tree_reduce",
                    "fan_in_node_ids": list(input_node_ids),
                    "join_policy": "all_success",
                    "wait_policy": "wait_all_upstream_completed",
                    "aggregate_after": "all_direct_file_module_indexes_completed",
                    "authority": "project_network_tasks.directory_tree_reduce_scheduler_contract",
                },
            },
            sequence_index=sequence_index,
            execution_mode=template.execution_mode,
            dispatch_group=template.dispatch_group or "project_network_directory",
            wait_policy=template.wait_policy,
            join_policy=template.join_policy,
            loop={"scope_id": loop_frame_id, "bindings": {"directory_frame_id": frame.frame_id}},
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


def _directory_file_shard(
    *,
    build_id: str,
    frame_id: str,
    layer_id: str,
    folder_ref: str,
    manifest_ref: str,
    file_card: dict[str, Any],
) -> SemanticShardSpec:
    stable_ref = str(file_card.get("stable_ref") or "")
    path = str(file_card.get("path") or stable_ref)
    file_hash = str(file_card.get("file_hash") or "")
    return SemanticShardSpec(
        shard_id=f"file_module:{_slug(path or stable_ref)}",
        layer_id=layer_id,
        work_unit_kind="file_module",
        node_template_id="project_network.module_index",
        assignment=ShardAssignment(
            assigned_scope={
                "scope_kind": "single_file_module",
                "build_id": build_id,
                "directory_frame_id": frame_id,
                "folder_stable_ref": folder_ref,
                "file_node_id": str(file_card.get("node_id") or ""),
                "file_stable_ref": stable_ref,
                "file_path": path,
                "file_hash": file_hash,
                "manifest_ref": manifest_ref,
            },
            input_refs=tuple(item for item in (stable_ref, folder_ref, manifest_ref) if item),
            required_anchor_refs=tuple(item for item in (str(file_card.get("anchor_ref") or ""),) if item),
            metadata={"low_config_single_file_review": True},
        ),
        expected_work_product_contract_id="project_network.module_index.v1",
        output_contract_id="project_network.module_index.v1",
        executor_policy=ShardExecutorPolicy(
            agent_id="agent:project_network_file_reviewer",
            agent_profile_id="project_network_file_reviewer_agent",
            agent_group_id="group.project_network_reviewers",
            work_posture="index",
            metadata={"low_config_single_file_review": True},
        ),
        complexity=ShardComplexity(
            estimated_files=1,
            risk_flags=tuple("large_file" for size in (dict(file_card.get("payload") or {}).get("size_bytes"),) if _int_value(size, 0) > 250_000),
        ),
        metadata={
            "directory_frame_id": frame_id,
            "directory_manifest_ref": manifest_ref,
            "low_config_single_file_review": True,
            "allowed_context": [
                "upstream_directory_boundary",
                "current_file_skeleton_card",
                "deep_ast_file_module_if_available",
                "system_supplied_current_file_packet",
                "output_contract",
            ],
            "forbidden_context": [
                "global_search",
                "workspace_read",
                "workspace_search",
                "git_read",
                "broad_memory_read",
                "semantic_overlay_write",
                "publish_authority",
            ],
        },
    )


def _with_directory_loop_contract(
    node: TaskGraphNodeDefinition,
    *,
    loop_frame_id: str,
    frame_package: DirectoryFrameMaterializationPackage,
    work_unit_kind: str,
) -> TaskGraphNodeDefinition:
    frame = frame_package.frame
    target_metadata = _target_project_metadata(frame_package)
    metadata = {
        **dict(node.metadata or {}),
        "directory_frame_id": frame.frame_id,
        "directory_manifest_ref": frame_package.manifest.manifest_id,
        "folder_stable_ref": frame.folder_stable_ref,
        "folder_path": frame.folder_path,
        "work_unit_kind": work_unit_kind,
        "low_config_single_file_review": work_unit_kind == "direct_file_module_review",
        "loop_algorithm_kind": "tree_reduce",
        **target_metadata,
    }
    runtime_policy = {
        **dict(node.runtime_policy or {}),
        "project_network_directory_frame": {
            "directory_frame_id": frame.frame_id,
            "manifest_ref": frame_package.manifest.manifest_id,
            "single_file_low_config": work_unit_kind == "direct_file_module_review",
            **target_metadata,
            "authority": "project_network_tasks.directory_frame_node_runtime_policy",
        },
    }
    return replace(
        node,
        loop={"scope_id": loop_frame_id, "bindings": {"directory_frame_id": frame.frame_id}},
        runtime_policy=runtime_policy,
        metadata=metadata,
    )


def _directory_loop_frame(
    *,
    package: DirectoryFrameMaterializationPackage,
    loop_frame_id: str,
    scope_node_ids: tuple[str, ...],
    entry_node_id: str,
    exit_node_id: str,
) -> dict[str, Any]:
    frame = package.frame
    manifest = package.manifest
    return {
        "frame_id": loop_frame_id,
        "loop_frame_id": loop_frame_id,
        "scope_id": loop_frame_id,
        "kind": "tree_reduce",
        "algorithm_kind": "directory_tree_reduce",
        "entry_node_id": entry_node_id,
        "exit_node_id": exit_node_id,
        "scope_node_ids": list(scope_node_ids),
        "unit_kind": "directory_frame",
        "parent_scope_id": str(frame.parent_frame_id or ""),
        "initial_inputs": {
            "project_network_build_id": package.build_id,
            "directory_frame_id": frame.frame_id,
            "directory_root_frame_id": frame.root_frame_id,
            "directory_parent_frame_id": frame.parent_frame_id,
            "directory_manifest_ref": manifest.manifest_id,
            "folder_stable_ref": frame.folder_stable_ref,
            "folder_path": frame.folder_path,
            **_target_project_metadata(package),
        },
        "tree_reduce": {
            "physical_authority": "file_management.project_structure.skeleton",
            "semantic_authority": "project_network.agent_work_products",
            "frame_status": frame.status,
            "depth": frame.depth,
            "folder_node_id": frame.folder_node_id,
            "folder_stable_ref": frame.folder_stable_ref,
            "manifest_ref": manifest.manifest_id,
            "source_work_product_refs": list(package.source_work_product_refs),
            "direct_file_refs": list(manifest.direct_file_refs),
            "child_folder_refs": list(manifest.child_folder_refs),
            "child_return_refs": [item.return_id for item in package.child_returns],
            "direct_file_count": len(manifest.direct_file_refs),
            "child_folder_count": len(manifest.child_folder_refs),
            "child_return_count": len(package.child_returns),
            "aggregate_policy": "typed_tree_reduce",
        },
        "aggregate_policy": {
            "mode": "tree_reduce",
            "consume_child_returns_as_refs": True,
            "consume_direct_file_work_products": True,
        },
        "authority": "project_network_tasks.directory_tree_reduce_loop_frame",
    }


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
    is_aggregate_target = target_node_id.endswith(".aggregate")
    return TaskGraphEdgeDefinition(
        edge_id=f"edge.{_slug(source_node_id)}.to.{_slug(target_node_id)}",
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        edge_type="handoff",
        payload_contract_id=payload_contract_id,
        contract_bindings={
            "schema": {
                "payload_contract_id": payload_contract_id,
            },
            "handoff": {
                "result_delivery_policy": "contract_payload_and_refs",
                "ack_required": True,
                "ack_policy": "explicit_ack",
                "failure_propagation_policy": "allow_partial" if is_aggregate_target else "fail_downstream",
            },
            "semantic": {
                "semantic_role": "typed_work_product_handoff",
                "target_consumes": payload_contract_id,
            },
        },
        ack_required=True,
        failure_propagation_policy="allow_partial" if is_aggregate_target else "fail_downstream",
        result_delivery_policy="contract_payload_and_refs",
        metadata={
            "project_network_edge": True,
            "transition_policy": {
                "edge_status": {
                    "initial": "pending",
                    "on_source_success": "ready",
                    "on_source_failed": "source_failed",
                    "decision_ref_required": True,
                    "authority": "project_network_tasks.typed_work_product_edge_status",
                },
                "tree_reduce": {
                    "target_consumes": payload_contract_id,
                    "delivery": "typed_work_product_refs",
                    "authority": "project_network_tasks.tree_reduce_edge_policy",
                },
            },
            "readiness_policy": {
                "ack_required": True,
                "ack_policy": "explicit_ack",
                "failure_propagation_policy": "allow_partial" if is_aggregate_target else "fail_downstream",
                "result_delivery_policy": "contract_payload_and_refs",
                "authority": "project_network_tasks.edge_readiness_policy",
            },
        },
    )


def _directory_max_active_nodes(*, package: DirectoryFrameMaterializationPackage, file_node_count: int) -> int:
    explicit = _int_value(dict(package.metadata or {}).get("max_active_nodes"), 0)
    if explicit > 0:
        return max(1, explicit)
    return min(max(1, int(file_node_count or 0)), 8)


def _target_project_metadata(package: DirectoryFrameMaterializationPackage) -> dict[str, str]:
    metadata = dict(package.metadata or {})
    return {
        key: str(metadata.get(key) or "").strip()
        for key in ("project_network_target_backend_dir", "project_network_target_project_root")
        if str(metadata.get(key) or "").strip()
    }


def _slug(value: str) -> str:
    return ".".join(part for part in str(value or "").replace(":", ".").replace("/", ".").replace("\\", ".").replace("_", ".").replace("-", ".").split(".") if part)


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

