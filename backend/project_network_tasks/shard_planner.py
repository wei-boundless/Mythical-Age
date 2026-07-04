from __future__ import annotations

from typing import Any

from project_network_system.build_contract_models import ProjectNetworkBuildContract
from project_network_system.layer_plan_models import ProjectNetworkLayerPlan
from project_network_system.shard_models import (
    SemanticShardSpec,
    ShardAssignment,
    ShardComplexity,
    ShardComplexityPolicy,
    ShardExecutorPolicy,
    ShardPlan,
)


_LAYER_KIND_TO_WORK_UNIT = {
    "source_snapshot": "system",
    "system": "system",
    "folder": "folder",
    "semantic_file_module": "file_module",
    "ast_endpoint": "ast_endpoint",
    "relation_route": "relation_route",
    "generation": "publish",
}

_LAYER_KIND_TO_TEMPLATE = {
    "source_snapshot": "project_network.source_snapshot",
    "system": "project_network.system_classify",
    "folder": "project_network.folder_index",
    "semantic_file_module": "project_network.module_index",
    "ast_endpoint": "project_network.ast_endpoint_extract",
    "relation_route": "project_network.relation_trace",
    "generation": "project_network.generation_publish",
}

_LAYER_KIND_TO_PRODUCT_CONTRACT = {
    "source_snapshot": "project_network.source_snapshot.v1",
    "system": "project_network.system_map.v1",
    "folder": "project_network.folder_index.v1",
    "semantic_file_module": "project_network.module_index.v1",
    "ast_endpoint": "project_network.endpoint_index.v1",
    "relation_route": "project_network.relation_candidates.v1",
    "generation": "project_network.publish_candidate.v1",
}


def build_static_shard_plan(
    contract: ProjectNetworkBuildContract,
    layers: tuple[ProjectNetworkLayerPlan, ...],
    *,
    complexity_policy: ShardComplexityPolicy | None = None,
) -> ShardPlan:
    shards: list[SemanticShardSpec] = []
    for layer in layers:
        shards.extend(_shards_for_layer(contract, layer, mode="static_pre_materialized", complexity_policy=complexity_policy))
    return ShardPlan(
        plan_id=f"shard-plan:{contract.build_id}:static",
        build_id=contract.build_id,
        mode="static_pre_materialized",
        shards=tuple(shards),
        source_refs=_source_refs(contract),
        metadata={"target_layer_count": len(layers)},
    )


def build_next_layer_shard_plan(
    contract: ProjectNetworkBuildContract,
    layer: ProjectNetworkLayerPlan,
    *,
    parent_work_product_refs: tuple[str, ...] = (),
    complexity_policy: ShardComplexityPolicy | None = None,
) -> ShardPlan:
    shards = tuple(
        _shards_for_layer(
            contract,
            layer,
            mode="rolling_one_hop",
            parent_work_product_refs=parent_work_product_refs,
            complexity_policy=complexity_policy,
        )
    )
    return ShardPlan(
        plan_id=f"shard-plan:{contract.build_id}:{layer.layer_id}:rolling",
        build_id=contract.build_id,
        mode="rolling_one_hop",
        target_layer_id=layer.layer_id,
        shards=shards,
        source_refs=(*_source_refs(contract), *parent_work_product_refs),
        metadata={"target_layer_id": layer.layer_id},
    )


def _shards_for_layer(
    contract: ProjectNetworkBuildContract,
    layer: ProjectNetworkLayerPlan,
    *,
    mode: str,
    parent_work_product_refs: tuple[str, ...] = (),
    complexity_policy: ShardComplexityPolicy | None = None,
) -> tuple[SemanticShardSpec, ...]:
    policy = ShardComplexityPolicy.from_dict(layer.shard_policy) if layer.shard_policy else complexity_policy or ShardComplexityPolicy()
    scope_refs = _scope_refs_for_layer(contract, layer)
    chunks = _chunk(scope_refs or (contract.scope.project_id or contract.build_id,), _max_refs_for_layer(layer, policy))
    template_id = layer.node_template_refs[0] if layer.node_template_refs else _LAYER_KIND_TO_TEMPLATE.get(layer.layer_kind, "project_network.module_index")
    work_unit_kind = _LAYER_KIND_TO_WORK_UNIT.get(layer.layer_kind, "file_module")
    output_contract_id = layer.output_contract_id or _LAYER_KIND_TO_PRODUCT_CONTRACT.get(layer.layer_kind, "project_network.layer_summary.v1")
    source_refs = _source_refs(contract)
    shards: list[SemanticShardSpec] = []
    for index, refs in enumerate(chunks, start=1):
        assigned_scope = _assigned_scope_for_layer(layer.layer_kind, refs)
        shard_id = f"shard:{contract.build_id}:{layer.layer_id}:{index:03d}"
        shards.append(
            SemanticShardSpec(
                shard_id=shard_id,
                layer_id=layer.layer_id,
                work_unit_kind=work_unit_kind,  # type: ignore[arg-type]
                node_template_id=template_id,
                assignment=ShardAssignment(
                    assigned_scope=assigned_scope,
                    input_refs=(*layer.input_refs, *parent_work_product_refs),
                    required_anchor_refs=tuple(ref for ref in refs if str(ref).startswith("anchor:")),
                    source_snapshot_refs=source_refs,
                ),
                expected_work_product_contract_id=output_contract_id,
                output_contract_id=output_contract_id,
                executor_policy=ShardExecutorPolicy.from_dict(layer.metadata.get("executor_policy") if isinstance(layer.metadata.get("executor_policy"), dict) else {}),
                complexity=ShardComplexity(score=len(refs), estimated_files=_estimated_files(layer.layer_kind, refs)),
                dependencies=tuple(layer.upstream_layer_refs),
                metadata={
                    "materialization_mode": mode,
                    "layer_kind": layer.layer_kind,
                    "shard_index": index,
                },
            )
        )
    return tuple(shards)


def _scope_refs_for_layer(contract: ProjectNetworkBuildContract, layer: ProjectNetworkLayerPlan) -> tuple[str, ...]:
    metadata_scope = layer.metadata.get("scope_refs") if isinstance(layer.metadata, dict) else None
    explicit = _tuple_of_strings(metadata_scope)
    if explicit:
        return explicit
    if layer.layer_kind == "system":
        return contract.scope.system_refs or contract.scope.root_paths or ((contract.scope.project_id,) if contract.scope.project_id else ())
    if layer.layer_kind == "folder":
        return contract.scope.folder_refs or contract.scope.root_paths
    if layer.layer_kind == "semantic_file_module":
        return contract.scope.module_refs or contract.scope.root_paths
    if layer.layer_kind == "ast_endpoint":
        return contract.scope.anchor_refs or contract.scope.module_refs
    if layer.layer_kind == "relation_route":
        return contract.scope.module_refs or contract.scope.root_paths or contract.scope.system_refs
    if layer.layer_kind == "generation":
        return contract.scope.system_refs or contract.scope.root_paths or ((contract.scope.project_id,) if contract.scope.project_id else ())
    return contract.scope.root_paths or contract.scope.module_refs or contract.scope.system_refs


def _assigned_scope_for_layer(layer_kind: str, refs: tuple[str, ...]) -> dict[str, Any]:
    key = {
        "system": "system_refs",
        "folder": "folder_refs",
        "semantic_file_module": "module_refs",
        "ast_endpoint": "anchor_refs",
        "relation_route": "relation_scope_refs",
        "generation": "generation_scope_refs",
    }.get(layer_kind, "scope_refs")
    return {key: list(refs), "layer_kind": layer_kind}


def _max_refs_for_layer(layer: ProjectNetworkLayerPlan, policy: ShardComplexityPolicy) -> int:
    if layer.layer_kind == "semantic_file_module" and policy.force_single_file_modules:
        return 1
    if layer.layer_kind == "folder":
        return policy.max_scope_refs_per_shard
    return policy.max_files_per_shard


def _estimated_files(layer_kind: str, refs: tuple[str, ...]) -> int:
    if layer_kind in {"semantic_file_module", "ast_endpoint"}:
        return max(1, len(refs))
    return len(refs)


def _source_refs(contract: ProjectNetworkBuildContract) -> tuple[str, ...]:
    snapshots = contract.source_snapshots
    return tuple(
        ref
        for ref in (
            snapshots.file_tree_snapshot,
            snapshots.deep_ast_generation,
            snapshots.registry_snapshot,
            snapshots.tool_catalog_snapshot,
            snapshots.prompt_registry_snapshot,
        )
        if ref
    )


def _chunk(values: tuple[str, ...], size: int) -> tuple[tuple[str, ...], ...]:
    size = max(1, size)
    return tuple(tuple(values[index : index + size]) for index in range(0, len(values), size))


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.replace(",", "\n").splitlines() if item.strip())
    return tuple(str(item).strip() for item in list(value or []) if str(item).strip())

