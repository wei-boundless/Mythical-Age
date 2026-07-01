from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from graph_system.models import NodeResultEnvelope

from .build_contract_models import ProjectNetworkBuildContract
from .layer_plan_models import GraphGenerationLineage
from .projection import ProjectNetworkBuildProjection, build_project_network_store_projection
from .repository import ProjectNetworkRepository, content_hash, stable_project_network_id
from .semantic_artifact_materializer import ProjectNetworkSemanticArtifactMaterializer
from .shard_models import ShardPlan
from .store_models import (
    ProjectNetworkCandidateRecord,
    ProjectNetworkChannelState,
    ProjectNetworkEvidenceRecord,
    ProjectNetworkGenerationRecord,
    ProjectNetworkLayerIndexRecord,
    ProjectNetworkStoreSnapshot,
    ProjectNetworkTraceRecord,
)
from .work_product_extractor import extract_graph_build_work_products
from .work_product_models import GraphBuildWorkProductEnvelope, WorkProductChannel


@dataclass(frozen=True, slots=True)
class ProjectNetworkWorkProductIngestResult:
    build_id: str
    graph_run_id: str = ""
    node_id: str = ""
    work_products: tuple[GraphBuildWorkProductEnvelope, ...] = ()
    channel_states: tuple[ProjectNetworkChannelState, ...] = ()
    evidence: tuple[ProjectNetworkEvidenceRecord, ...] = ()
    candidates: tuple[ProjectNetworkCandidateRecord, ...] = ()
    layer_indexes: tuple[ProjectNetworkLayerIndexRecord, ...] = ()
    generations: tuple[ProjectNetworkGenerationRecord, ...] = ()
    trace: ProjectNetworkTraceRecord | None = None
    projection: ProjectNetworkBuildProjection | None = None
    semantic_artifact_set: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.project_network.work_product_ingest_result"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "build_id": self.build_id,
                "graph_run_id": self.graph_run_id,
                "node_id": self.node_id,
                "work_products": [item.to_dict() for item in self.work_products],
                "channel_states": [item.to_dict() for item in self.channel_states],
                "evidence": [item.to_dict() for item in self.evidence],
                "candidates": [item.to_dict() for item in self.candidates],
                "layer_indexes": [item.to_dict() for item in self.layer_indexes],
                "generations": [item.to_dict() for item in self.generations],
                "trace": self.trace.to_dict() if self.trace is not None else {},
                "projection": self.projection.to_dict() if self.projection is not None else {},
                "semantic_artifact_set": self.semantic_artifact_set,
                "metadata": self.metadata,
                "authority": self.authority,
            }
        )


class ProjectNetworkBuildService:
    authority = "task_system.project_network.build_service"

    def __init__(self, repository: ProjectNetworkRepository) -> None:
        self.repository = repository

    @classmethod
    def from_backend_dir(cls, base_dir: str | Path) -> "ProjectNetworkBuildService":
        return cls(ProjectNetworkRepository(base_dir))

    def register_build(
        self,
        contract: ProjectNetworkBuildContract,
        *,
        status: str = "draft",
        metadata: dict[str, Any] | None = None,
    ) -> ProjectNetworkStoreSnapshot:
        self.repository.upsert_build_contract(contract, status=status, metadata=metadata)
        return self.repository.snapshot(contract.build_id)

    def accept_node_result(
        self,
        node_result: NodeResultEnvelope | dict[str, Any],
        *,
        contract: ProjectNetworkBuildContract | None = None,
        build_id: str = "",
        default_shard_id: str = "",
        default_layer_id: str = "",
        channels: tuple[WorkProductChannel, ...] | list[WorkProductChannel] | None = None,
        shard_plans: tuple[ShardPlan, ...] = (),
        lineages: tuple[GraphGenerationLineage, ...] = (),
    ) -> ProjectNetworkWorkProductIngestResult:
        envelope = _node_result_envelope(node_result)
        if contract is not None:
            self.repository.upsert_build_contract(contract)
        resolved_build_id = (
            str(build_id or "").strip()
            or (contract.build_id if contract is not None else "")
            or _result_build_id(envelope)
        )
        products = extract_graph_build_work_products(
            envelope.to_dict(),
            default_build_id=resolved_build_id,
            default_graph_run_id=envelope.graph_run_id,
            default_node_id=envelope.node_id,
            default_shard_id=default_shard_id or _result_shard_id(envelope),
            default_layer_id=default_layer_id or _result_layer_id(envelope),
        )
        if not resolved_build_id and products:
            resolved_build_id = products[0].build_id
        if not resolved_build_id:
            return ProjectNetworkWorkProductIngestResult(
                build_id="",
                graph_run_id=envelope.graph_run_id,
                node_id=envelope.node_id,
                metadata={"reason": "project_network_build_id_missing"},
            )
        self.repository.upsert_work_products(products)
        active_channels = tuple(channels or ()) or _default_channels(products)
        channel_states = tuple(
            self.repository.reduce_channel(
                channel,
                build_id=resolved_build_id,
                incoming_products=tuple(product for product in products if channel.accepts(product)),
            )
            for channel in active_channels
        )
        evidence_records = tuple(record for product in products for record in _evidence_records(product))
        candidate_records = tuple(_candidate_record(product) for product in products if _is_candidate_product(product))
        layer_indexes = tuple(_layer_index_record(product) for product in products if product.product_kind == "layer_summary")
        generation_records = tuple(self._generation_record(product) for product in products if product.product_kind == "publish_candidate")
        for record in evidence_records:
            self.repository.upsert_evidence(record)
        for record in candidate_records:
            self.repository.upsert_candidate(record)
        for record in layer_indexes:
            self.repository.upsert_layer_index(record)
        for record in generation_records:
            self.repository.upsert_generation(record)
        trace = self.repository.upsert_trace(
            ProjectNetworkTraceRecord(
                trace_id=stable_project_network_id("pntrace", resolved_build_id, envelope.graph_run_id, envelope.node_id, envelope.result_id),
                build_id=resolved_build_id,
                graph_run_id=envelope.graph_run_id,
                node_id=envelope.node_id,
                shard_id=default_shard_id or _result_shard_id(envelope),
                work_order_id=envelope.work_order_id,
                result_id=envelope.result_id,
                event_kind="work_product_ingested",
                status="accepted" if products else "no_work_products",
                work_product_ids=tuple(product.work_product_id for product in products),
                payload={
                    "product_count": len(products),
                    "channel_count": len(channel_states),
                    "evidence_count": len(evidence_records),
                    "candidate_count": len(candidate_records),
                    "layer_index_count": len(layer_indexes),
                    "generation_count": len(generation_records),
                },
            )
        )
        projection = self.build_projection(
            resolved_build_id,
            contract=contract,
            shard_plans=shard_plans,
            lineages=lineages,
        )
        semantic_artifact_set = {}
        if products:
            semantic_artifact_set = ProjectNetworkSemanticArtifactMaterializer(
                base_dir=self.repository.root.parent.parent,
                repository=self.repository,
            ).materialize_build(resolved_build_id, graph_run_id=envelope.graph_run_id).to_dict()
        return ProjectNetworkWorkProductIngestResult(
            build_id=resolved_build_id,
            graph_run_id=envelope.graph_run_id,
            node_id=envelope.node_id,
            work_products=products,
            channel_states=channel_states,
            evidence=evidence_records,
            candidates=candidate_records,
            layer_indexes=layer_indexes,
            generations=generation_records,
            trace=trace,
            projection=projection,
            semantic_artifact_set=semantic_artifact_set,
            metadata={"semantic_artifact_set": semantic_artifact_set} if semantic_artifact_set else {},
        )

    def publish_generation(
        self,
        generation_id: str,
        *,
        actor_kind: str,
        actor_ref: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ProjectNetworkGenerationRecord:
        return self.repository.publish_generation(
            generation_id,
            actor_kind=actor_kind,
            actor_ref=actor_ref,
            metadata=metadata,
        )

    def transition_generation(
        self,
        generation_id: str,
        *,
        next_status: str,
        actor_kind: str,
        actor_ref: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ProjectNetworkGenerationRecord:
        return self.repository.transition_generation(
            generation_id,
            next_status=next_status,
            actor_kind=actor_kind,
            actor_ref=actor_ref,
            metadata=metadata,
        )

    def build_projection(
        self,
        build_id: str,
        *,
        contract: ProjectNetworkBuildContract | None = None,
        shard_plans: tuple[ShardPlan, ...] = (),
        lineages: tuple[GraphGenerationLineage, ...] = (),
    ) -> ProjectNetworkBuildProjection:
        snapshot = self.repository.snapshot(build_id)
        resolved_contract = contract or _contract_from_snapshot(snapshot)
        if resolved_contract is None:
            return ProjectNetworkBuildProjection(
                build_id=build_id,
                build_kind=str(snapshot.build.build_kind if snapshot.build is not None else ""),
                build_mode=str(snapshot.build.build_mode if snapshot.build is not None else ""),
                status=str(snapshot.build.status if snapshot.build is not None else "draft"),
                work_product_count=len(snapshot.work_products),
                conflict_count=sum(1 for item in snapshot.work_products if item.product_kind == "conflict_report"),
                metadata={"projection_source": "store_without_contract"},
            )
        return build_project_network_store_projection(
            resolved_contract,
            snapshot=snapshot,
            shard_plans=shard_plans,
            lineages=lineages,
        )

    def _generation_record(self, product: GraphBuildWorkProductEnvelope) -> ProjectNetworkGenerationRecord:
        generation = int(product.generation or 0) or self.repository.next_generation_number(product.build_id)
        generation_id = (
            str(product.payload.get("generation_id") or product.payload.get("generation_candidate_ref") or "").strip()
            or stable_project_network_id("pngen", product.build_id, product.work_product_id, str(generation), product.payload_ref)
        )
        return ProjectNetworkGenerationRecord.from_work_product(product, generation_id=generation_id, generation=generation)


def _node_result_envelope(node_result: NodeResultEnvelope | dict[str, Any]) -> NodeResultEnvelope:
    if isinstance(node_result, NodeResultEnvelope):
        return node_result
    return NodeResultEnvelope.from_dict(dict(node_result or {}))


def _result_build_id(result: NodeResultEnvelope) -> str:
    outputs = dict(result.outputs or {})
    diagnostics = dict(result.diagnostics or {})
    return str(
        outputs.get("project_network_build_id")
        or outputs.get("build_id")
        or dict(outputs.get("project_network") or {}).get("build_id")
        or dict(diagnostics.get("project_network") or {}).get("build_id")
        or ""
    ).strip()


def _result_shard_id(result: NodeResultEnvelope) -> str:
    outputs = dict(result.outputs or {})
    diagnostics = dict(result.diagnostics or {})
    return str(
        outputs.get("project_network_shard_id")
        or outputs.get("shard_id")
        or dict(outputs.get("project_network") or {}).get("shard_id")
        or dict(diagnostics.get("project_network") or {}).get("shard_id")
        or ""
    ).strip()


def _result_layer_id(result: NodeResultEnvelope) -> str:
    outputs = dict(result.outputs or {})
    diagnostics = dict(result.diagnostics or {})
    return str(
        outputs.get("project_network_layer_id")
        or outputs.get("layer_id")
        or dict(outputs.get("project_network") or {}).get("layer_id")
        or dict(diagnostics.get("project_network") or {}).get("layer_id")
        or ""
    ).strip()


def _default_channels(products: tuple[GraphBuildWorkProductEnvelope, ...]) -> tuple[WorkProductChannel, ...]:
    channels: dict[str, WorkProductChannel] = {}
    for product in products:
        layer_id = product.layer_id or "global"
        reducer = _default_reducer(product)
        channel_id = f"project_network.{layer_id}.{product.product_kind}.{reducer}"
        channels[channel_id] = WorkProductChannel(
            channel_id=channel_id,
            layer_id=layer_id,
            accepted_product_kinds=(product.product_kind,),
            reducer_policy=reducer,
            identity_keys=("stable_ref", "work_product_id"),
        )
    return tuple(channels.values())


def _default_reducer(product: GraphBuildWorkProductEnvelope) -> str:
    if product.product_kind == "coverage_report":
        return "merge_scope_coverage"
    if product.product_kind in {"directory_summary", "layer_summary", "publish_candidate"}:
        return "replace_by_generation"
    if product.product_kind == "endpoint_index":
        return "reject_on_anchor_mismatch"
    return "merge_by_stable_ref" if product.stable_ref else "append_by_work_product_id"


def _evidence_records(product: GraphBuildWorkProductEnvelope) -> tuple[ProjectNetworkEvidenceRecord, ...]:
    records: list[ProjectNetworkEvidenceRecord] = []
    if product.product_kind == "source_snapshot":
        records.append(
            ProjectNetworkEvidenceRecord(
                evidence_id=stable_project_network_id("pnevd", product.build_id, product.work_product_id, "source_snapshot"),
                build_id=product.build_id,
                evidence_kind="source_snapshot",
                source_ref=product.payload_ref or product.stable_ref,
                stable_ref=product.stable_ref or product.payload_ref,
                layer_id=product.layer_id,
                shard_id=product.shard_id,
                graph_run_id=product.graph_run_id,
                node_id=product.node_id,
                payload_ref=product.payload_ref,
                payload=dict(product.payload or {}),
                anchor_refs=tuple(product.anchor_refs),
                content_hash=content_hash(product.payload),
                metadata={"source_work_product_id": product.work_product_id},
            )
        )
    for ref in product.evidence_refs:
        records.append(
            ProjectNetworkEvidenceRecord(
                evidence_id=stable_project_network_id("pnevd", product.build_id, product.work_product_id, "evidence", ref),
                build_id=product.build_id,
                evidence_kind="evidence_ref",
                source_ref=ref,
                stable_ref=ref,
                layer_id=product.layer_id,
                shard_id=product.shard_id,
                graph_run_id=product.graph_run_id,
                node_id=product.node_id,
                payload_ref=product.payload_ref,
                metadata={"source_work_product_id": product.work_product_id},
            )
        )
    for ref in product.anchor_refs:
        records.append(
            ProjectNetworkEvidenceRecord(
                evidence_id=stable_project_network_id("pnevd", product.build_id, product.work_product_id, "anchor", ref),
                build_id=product.build_id,
                evidence_kind="anchor_ref",
                source_ref=ref,
                stable_ref=ref,
                layer_id=product.layer_id,
                shard_id=product.shard_id,
                graph_run_id=product.graph_run_id,
                node_id=product.node_id,
                payload_ref=product.payload_ref,
                anchor_refs=(ref,),
                metadata={"source_work_product_id": product.work_product_id},
            )
        )
    return tuple(records)


def _is_candidate_product(product: GraphBuildWorkProductEnvelope) -> bool:
    return product.product_kind in {
        "system_map",
        "folder_index",
        "module_index",
        "endpoint_index",
        "relation_candidates",
        "directory_summary",
        "coverage_report",
        "conflict_report",
    }


def _candidate_record(product: GraphBuildWorkProductEnvelope) -> ProjectNetworkCandidateRecord:
    return ProjectNetworkCandidateRecord.from_work_product(
        product,
        candidate_id=stable_project_network_id(
            "pncand",
            product.build_id,
            product.layer_id,
            product.stable_ref or product.work_product_id,
            product.generation,
        ),
    )


def _layer_index_record(product: GraphBuildWorkProductEnvelope) -> ProjectNetworkLayerIndexRecord:
    payload = dict(product.payload or {})
    layer_index_id = (
        str(payload.get("layer_index_id") or payload.get("layer_index_ref") or "").strip()
        or stable_project_network_id("pnlayer", product.build_id, product.layer_id, product.work_product_id, product.generation)
    )
    return ProjectNetworkLayerIndexRecord.from_work_product(product, layer_index_id=layer_index_id)


def _contract_from_snapshot(snapshot: ProjectNetworkStoreSnapshot) -> ProjectNetworkBuildContract | None:
    if snapshot.build is None or not snapshot.build.contract:
        return None
    try:
        return ProjectNetworkBuildContract.from_dict(dict(snapshot.build.contract or {}))
    except ValueError:
        return None


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
