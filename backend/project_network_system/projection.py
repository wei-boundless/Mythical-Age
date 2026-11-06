from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .build_contract_models import ProjectNetworkBuildContract
from .layer_plan_models import GraphGenerationLineage
from .shard_models import ShardPlan
from .store_models import ProjectNetworkStoreSnapshot
from .work_product_models import GraphBuildWorkProductEnvelope


@dataclass(frozen=True, slots=True)
class ProjectNetworkBuildProjection:
    build_id: str
    build_kind: str
    build_mode: str
    status: str = "draft"
    layer_count: int = 0
    shard_count: int = 0
    work_product_count: int = 0
    conflict_count: int = 0
    lineage_count: int = 0
    latest_generation_ref: str = ""
    layers: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.build_projection"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


def build_project_network_projection(
    contract: ProjectNetworkBuildContract,
    *,
    shard_plans: tuple[ShardPlan, ...] = (),
    work_products: tuple[GraphBuildWorkProductEnvelope, ...] = (),
    lineages: tuple[GraphGenerationLineage, ...] = (),
    status: str = "draft",
) -> ProjectNetworkBuildProjection:
    layer_ids = tuple(dict.fromkeys(item.layer_id for plan in shard_plans for item in plan.shards if item.layer_id))
    layer_items: list[dict[str, Any]] = []
    for layer_id in layer_ids:
        layer_shards = [item for plan in shard_plans for item in plan.shards if item.layer_id == layer_id]
        layer_products = [item for item in work_products if item.layer_id == layer_id]
        layer_items.append(
            {
                "layer_id": layer_id,
                "shard_count": len(layer_shards),
                "work_product_count": len(layer_products),
                "accepted_count": sum(1 for item in layer_products if item.status == "accepted"),
                "conflict_count": sum(1 for item in layer_products if item.product_kind == "conflict_report"),
            }
        )
    publish_products = [item for item in work_products if item.product_kind == "publish_candidate"]
    latest_generation_ref = ""
    if publish_products:
        latest_generation_ref = sorted(publish_products, key=lambda item: item.generation)[-1].payload_ref
    return ProjectNetworkBuildProjection(
        build_id=contract.build_id,
        build_kind=contract.build_kind,
        build_mode=contract.build_mode,
        status=status,
        layer_count=len(layer_ids),
        shard_count=sum(len(plan.shards) for plan in shard_plans),
        work_product_count=len(work_products),
        conflict_count=sum(1 for item in work_products if item.product_kind == "conflict_report"),
        lineage_count=len(lineages),
        latest_generation_ref=latest_generation_ref,
        layers=tuple(layer_items),
    )


def build_project_network_store_projection(
    contract: ProjectNetworkBuildContract,
    *,
    snapshot: ProjectNetworkStoreSnapshot,
    shard_plans: tuple[ShardPlan, ...] = (),
    lineages: tuple[GraphGenerationLineage, ...] = (),
) -> ProjectNetworkBuildProjection:
    work_products = tuple(snapshot.work_products)
    build_status = str(snapshot.build.status if snapshot.build is not None else "draft")
    layer_ids = tuple(
        dict.fromkeys(
            [
                *[item.layer_id for plan in shard_plans for item in plan.shards if item.layer_id],
                *[item.layer_id for item in snapshot.layer_indexes if item.layer_id],
                *[item.layer_id for item in work_products if item.layer_id],
            ]
        )
    )
    layer_items: list[dict[str, Any]] = []
    for layer_id in layer_ids:
        layer_shards = [item for plan in shard_plans for item in plan.shards if item.layer_id == layer_id]
        layer_products = [item for item in work_products if item.layer_id == layer_id]
        channel_states = [item for item in snapshot.channel_states if item.layer_id == layer_id]
        layer_indexes = [item for item in snapshot.layer_indexes if item.layer_id == layer_id]
        layer_items.append(
            {
                "layer_id": layer_id,
                "shard_count": len(layer_shards),
                "work_product_count": len(layer_products),
                "accepted_count": sum(1 for item in layer_products if item.status == "accepted"),
                "candidate_count": sum(1 for item in snapshot.candidates if item.layer_id == layer_id),
                "evidence_count": sum(1 for item in snapshot.evidence if item.layer_id == layer_id),
                "channel_count": len(channel_states),
                "layer_index_count": len(layer_indexes),
                "conflict_count": sum(1 for item in layer_products if item.product_kind == "conflict_report"),
            }
        )
    published = [item for item in snapshot.generations if item.status == "published"]
    latest_generation = published[0] if published else (snapshot.generations[0] if snapshot.generations else None)
    latest_generation_ref = latest_generation.generation_ref if latest_generation is not None else ""
    return ProjectNetworkBuildProjection(
        build_id=contract.build_id,
        build_kind=contract.build_kind,
        build_mode=contract.build_mode,
        status=build_status,
        layer_count=len(layer_ids),
        shard_count=sum(len(plan.shards) for plan in shard_plans),
        work_product_count=len(work_products),
        conflict_count=sum(1 for item in work_products if item.product_kind == "conflict_report"),
        lineage_count=len(lineages),
        latest_generation_ref=latest_generation_ref,
        layers=tuple(layer_items),
        metadata={
            "projection_source": "project_network_store",
            "channel_count": len(snapshot.channel_states),
            "evidence_count": len(snapshot.evidence),
            "candidate_count": len(snapshot.candidates),
            "layer_index_count": len(snapshot.layer_indexes),
            "generation_count": len(snapshot.generations),
            "trace_count": len(snapshot.traces),
            "active_generation_id": str(snapshot.build.active_generation_id if snapshot.build is not None else ""),
        },
    )


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}

