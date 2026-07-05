from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .build_contract_models import ProjectNetworkBuildContract
from .layer_plan_models import GraphGenerationLineage
from .projection import ProjectNetworkBuildProjection, build_project_network_store_projection
from .repository import PUBLISH_AUTHORITY_KINDS, ProjectNetworkRepository, content_hash, stable_project_network_id
from .semantic_artifact_materializer import ProjectNetworkSemanticArtifactMaterializer
from .shard_models import ShardPlan
from .store_models import (
    ProjectNetworkCandidateRecord,
    ProjectNetworkChannelState,
    ProjectNetworkEvidenceRecord,
    ProjectNetworkGenerationRecord,
    ProjectNetworkLayerIndexRecord,
    ProjectNetworkMaintenanceSignalRecord,
    ProjectNetworkRepairWorkItemRecord,
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
    maintenance_signals: tuple[ProjectNetworkMaintenanceSignalRecord, ...] = ()
    trace: ProjectNetworkTraceRecord | None = None
    projection: ProjectNetworkBuildProjection | None = None
    semantic_artifact_set: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.work_product_ingest_result"

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
                "maintenance_signals": [item.to_dict() for item in self.maintenance_signals],
                "trace": self.trace.to_dict() if self.trace is not None else {},
                "projection": self.projection.to_dict() if self.projection is not None else {},
                "semantic_artifact_set": self.semantic_artifact_set,
                "metadata": self.metadata,
                "authority": self.authority,
            }
        )


@dataclass(frozen=True, slots=True)
class ProjectNetworkGenerationMaterializationResult:
    build_id: str
    graph_run_id: str = ""
    generation: ProjectNetworkGenerationRecord | None = None
    semantic_artifact_set: dict[str, Any] = field(default_factory=dict)
    published: bool = False
    authority: str = "project_network_system.generation_materialization_result"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "build_id": self.build_id,
                "graph_run_id": self.graph_run_id,
                "generation": self.generation.to_dict() if self.generation is not None else {},
                "semantic_artifact_set": self.semantic_artifact_set,
                "published": self.published,
                "authority": self.authority,
            }
        )


@dataclass(frozen=True, slots=True)
class ProjectNetworkRepairQueueResult:
    build_id: str
    signal: ProjectNetworkMaintenanceSignalRecord
    repair_items: tuple[ProjectNetworkRepairWorkItemRecord, ...] = ()
    authority: str = "project_network_system.repair_queue_result"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "build_id": self.build_id,
                "signal": self.signal.to_dict(),
                "repair_items": [item.to_dict() for item in self.repair_items],
                "authority": self.authority,
            }
        )


class ProjectNetworkBuildService:
    authority = "project_network_system.build_service"

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
        node_result: Any,
        *,
        contract: ProjectNetworkBuildContract | None = None,
        build_id: str = "",
        default_shard_id: str = "",
        default_layer_id: str = "",
        channels: tuple[WorkProductChannel, ...] | list[WorkProductChannel] | None = None,
        shard_plans: tuple[ShardPlan, ...] = (),
        lineages: tuple[GraphGenerationLineage, ...] = (),
    ) -> ProjectNetworkWorkProductIngestResult:
        result_payload = _node_result_payload(node_result)
        graph_run_id = str(result_payload.get("graph_run_id") or "").strip()
        node_id = str(result_payload.get("node_id") or "").strip()
        result_id = str(result_payload.get("result_id") or "").strip()
        work_order_id = str(result_payload.get("work_order_id") or "").strip()
        if contract is not None:
            self.repository.upsert_build_contract(contract)
        resolved_build_id = (
            str(build_id or "").strip()
            or (contract.build_id if contract is not None else "")
            or _result_build_id(result_payload)
        )
        products = extract_graph_build_work_products(
            result_payload,
            default_build_id=resolved_build_id,
            default_graph_run_id=graph_run_id,
            default_node_id=node_id,
            default_shard_id=default_shard_id or _result_shard_id(result_payload),
            default_layer_id=default_layer_id or _result_layer_id(result_payload),
        )
        if not resolved_build_id and products:
            resolved_build_id = products[0].build_id
        if not resolved_build_id:
            return ProjectNetworkWorkProductIngestResult(
                build_id="",
                graph_run_id=graph_run_id,
                node_id=node_id,
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
                trace_id=stable_project_network_id("pntrace", resolved_build_id, graph_run_id, node_id, result_id),
                build_id=resolved_build_id,
                graph_run_id=graph_run_id,
                node_id=node_id,
                shard_id=default_shard_id or _result_shard_id(result_payload),
                work_order_id=work_order_id,
                result_id=result_id,
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
        if products:
            maintenance_signals = self._queue_ingest_dirty_signals(
                build_id=resolved_build_id,
                graph_run_id=graph_run_id,
                node_id=node_id,
                work_product_ids=tuple(product.work_product_id for product in products),
                product_kinds=tuple(product.product_kind for product in products),
            )
        else:
            maintenance_signals = ()
        return ProjectNetworkWorkProductIngestResult(
            build_id=resolved_build_id,
            graph_run_id=graph_run_id,
            node_id=node_id,
            work_products=products,
            channel_states=channel_states,
            evidence=evidence_records,
            candidates=candidate_records,
            layer_indexes=layer_indexes,
            generations=generation_records,
            maintenance_signals=maintenance_signals,
            trace=trace,
            projection=projection,
            metadata={
                "materialization_lifecycle": "dirty_signal_queued",
                "maintenance_signal_ids": [item.signal_id for item in maintenance_signals],
                "dirty_signal_codes": [item.signal_code for item in maintenance_signals],
            }
            if maintenance_signals
            else {},
        )

    def materialize_generation_candidate(
        self,
        build_id: str,
        *,
        graph_run_id: str = "",
        actor_kind: str = "system",
        actor_ref: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ProjectNetworkGenerationMaterializationResult:
        resolved_build_id = str(build_id or "").strip()
        if not resolved_build_id:
            raise ValueError("materialize_generation_candidate requires build_id")
        artifact_set = ProjectNetworkSemanticArtifactMaterializer(
            base_dir=self.repository.root.parent.parent,
            repository=self.repository,
        ).materialize_build(
            resolved_build_id,
            graph_run_id=graph_run_id,
            publish_human_reports=False,
        )
        payload = _semantic_artifact_payload(artifact_set)
        identity_payload = _semantic_artifact_identity_payload(resolved_build_id, payload)
        generation_id = stable_project_network_id(
            "pngen",
            resolved_build_id,
            "semantic_artifact_set",
            content_hash(identity_payload),
        )
        existing = self.repository.get_generation(generation_id)
        generation = self.repository.upsert_generation(
            ProjectNetworkGenerationRecord(
                generation_id=generation_id,
                build_id=resolved_build_id,
                generation=int(existing.generation or 0) if existing is not None else self.repository.next_generation_number(resolved_build_id),
                generation_ref=str(payload.get("manifest_path") or ""),
                status=str(existing.status if existing is not None else "candidate"),  # type: ignore[arg-type]
                source_snapshot_ref=str(payload.get("unified_control_graph_path") or ""),
                layer_index_refs=existing.layer_index_refs if existing is not None else (),
                work_product_refs=existing.work_product_refs if existing is not None else (),
                validation_refs=existing.validation_refs if existing is not None else (),
                payload_ref=str(payload.get("manifest_path") or ""),
                payload=payload,
                published_at=existing.published_at if existing is not None else "",
                supersedes_generation_id=existing.supersedes_generation_id if existing is not None else "",
                created_at=existing.created_at if existing is not None else "",
                metadata={
                    **dict(existing.metadata if existing is not None else {}),
                    **dict(metadata or {}),
                    "materialization_actor_kind": str(actor_kind or ""),
                    "materialization_actor_ref": str(actor_ref or ""),
                    "publish_human_reports": False,
                    "materialization_lifecycle": "candidate",
                },
            )
        )
        return ProjectNetworkGenerationMaterializationResult(
            build_id=resolved_build_id,
            graph_run_id=str(graph_run_id or ""),
            generation=generation,
            semantic_artifact_set=payload,
            published=False,
        )

    def publish_materialized_generation(
        self,
        generation_id: str,
        *,
        graph_run_id: str = "",
        actor_kind: str,
        actor_ref: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ProjectNetworkGenerationMaterializationResult:
        current = self.repository.get_generation(generation_id)
        if current is None:
            raise KeyError(f"project network generation not found: {generation_id}")
        if str(actor_kind or "").strip() not in PUBLISH_AUTHORITY_KINDS:
            raise PermissionError("generation publish requires curator or publish-gate authority")
        if current.status not in {"candidate", "validating", "published"}:
            raise ValueError(f"generation cannot be published from status: {current.status}")
        artifact_set = ProjectNetworkSemanticArtifactMaterializer(
            base_dir=self.repository.root.parent.parent,
            repository=self.repository,
        ).materialize_build(
            current.build_id,
            graph_run_id=graph_run_id,
            publish_human_reports=True,
        )
        payload = _semantic_artifact_payload(artifact_set)
        refreshed = self.repository.upsert_generation(
            ProjectNetworkGenerationRecord(
                generation_id=current.generation_id,
                build_id=current.build_id,
                generation=current.generation,
                generation_ref=str(payload.get("manifest_path") or current.generation_ref),
                status=current.status,
                source_snapshot_ref=str(payload.get("unified_control_graph_path") or current.source_snapshot_ref),
                layer_index_refs=current.layer_index_refs,
                work_product_refs=current.work_product_refs,
                validation_refs=current.validation_refs,
                payload_ref=str(payload.get("manifest_path") or current.payload_ref),
                payload=payload,
                supersedes_generation_id=current.supersedes_generation_id,
                created_at=current.created_at,
                metadata={
                    **dict(current.metadata or {}),
                    **dict(metadata or {}),
                    "publish_actor_kind": str(actor_kind or ""),
                    "publish_actor_ref": str(actor_ref or ""),
                    "publish_human_reports": True,
                    "materialization_lifecycle": "published",
                },
            )
        )
        published = self.repository.publish_generation(
            refreshed.generation_id,
            actor_kind=actor_kind,
            actor_ref=actor_ref,
            metadata={
                **dict(metadata or {}),
                "semantic_artifact_set": payload,
            },
        )
        return ProjectNetworkGenerationMaterializationResult(
            build_id=published.build_id,
            graph_run_id=str(graph_run_id or ""),
            generation=published,
            semantic_artifact_set=payload,
            published=True,
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

    def queue_maintenance_signal(
        self,
        *,
        build_id: str,
        signal_source: str,
        signal_code: str,
        severity: str = "info",
        subject_ref: str = "",
        stable_ref: str = "",
        edge_id: str = "",
        anchor_ref: str = "",
        scope_refs: tuple[str, ...] | list[str] = (),
        evidence_refs: tuple[str, ...] | list[str] = (),
        requested_layers: tuple[str, ...] | list[str] = (),
        payload: dict[str, Any] | None = None,
        status: str = "queued",
        metadata: dict[str, Any] | None = None,
    ) -> ProjectNetworkMaintenanceSignalRecord:
        resolved_build_id = str(build_id or "").strip()
        if not resolved_build_id:
            raise ValueError("queue_maintenance_signal requires build_id")
        resolved_subject_ref = str(subject_ref or stable_ref or "").strip()
        resolved_stable_ref = str(stable_ref or subject_ref or "").strip()
        signal = ProjectNetworkMaintenanceSignalRecord(
            signal_id=stable_project_network_id(
                "pnsignal",
                resolved_build_id,
                signal_source,
                signal_code,
                severity,
                resolved_subject_ref,
                resolved_stable_ref,
                edge_id,
                anchor_ref,
                content_hash(
                    {
                        "scope_refs": list(scope_refs or ()),
                        "evidence_refs": list(evidence_refs or ()),
                        "requested_layers": list(requested_layers or ()),
                        "payload": dict(payload or {}),
                    }
                ),
            ),
            build_id=resolved_build_id,
            signal_source=str(signal_source or "").strip(),
            signal_code=str(signal_code or "").strip(),
            severity=str(severity or "info").strip() or "info",
            subject_ref=resolved_subject_ref,
            stable_ref=resolved_stable_ref,
            edge_id=str(edge_id or "").strip(),
            anchor_ref=str(anchor_ref or "").strip(),
            scope_refs=_normalize_strings(scope_refs, fallback=(resolved_subject_ref, resolved_stable_ref)),
            evidence_refs=_normalize_strings(evidence_refs),
            requested_layers=_normalize_requested_layers(requested_layers, subject_ref=resolved_subject_ref, signal_code=signal_code),
            payload=dict(payload or {}),
            status=str(status or "queued").strip() or "queued",
            metadata=dict(metadata or {}),
        )
        return self.repository.upsert_maintenance_signal(signal)

    def queue_repair(
        self,
        *,
        build_id: str,
        signal_source: str,
        signal_code: str,
        severity: str = "info",
        subject_ref: str = "",
        stable_ref: str = "",
        edge_id: str = "",
        anchor_ref: str = "",
        scope_refs: tuple[str, ...] | list[str] = (),
        evidence_refs: tuple[str, ...] | list[str] = (),
        requested_layers: tuple[str, ...] | list[str] = (),
        payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProjectNetworkRepairQueueResult:
        signal = self.queue_maintenance_signal(
            build_id=build_id,
            signal_source=signal_source,
            signal_code=signal_code,
            severity=severity,
            subject_ref=subject_ref,
            stable_ref=stable_ref,
            edge_id=edge_id,
            anchor_ref=anchor_ref,
            scope_refs=scope_refs,
            evidence_refs=evidence_refs,
            requested_layers=requested_layers,
            payload=payload,
            metadata=metadata,
        )
        items = self._plan_repair_items(signal)
        stored = tuple(self.repository.upsert_repair_item(item) for item in items)
        return ProjectNetworkRepairQueueResult(build_id=signal.build_id, signal=signal, repair_items=stored)

    def read_repairs(
        self,
        *,
        build_id: str,
        stable_ref: str = "",
        subject_ref: str = "",
        trigger_signal_id: str = "",
        status: str = "",
        limit: int = 200,
    ) -> dict[str, Any]:
        signals = self.repository.list_maintenance_signals(
            build_id=build_id,
            stable_ref=stable_ref,
            subject_ref=subject_ref,
            status=status,
            limit=limit,
        )
        items = self.repository.list_repair_items(
            build_id=build_id,
            stable_ref=stable_ref,
            subject_ref=subject_ref,
            trigger_signal_id=trigger_signal_id,
            status=status,
            limit=limit,
        )
        return {
            "build_id": build_id,
            "signals": [item.to_dict() for item in signals],
            "repair_items": [item.to_dict() for item in items],
            "summary": {
                "signal_count": len(signals),
                "repair_item_count": len(items),
                "queued_signal_count": sum(1 for item in signals if item.status == "queued"),
                "queued_repair_count": sum(1 for item in items if item.status == "queued"),
            },
            "authority": "project_network_system.repair_read_projection",
        }

    def _generation_record(self, product: GraphBuildWorkProductEnvelope) -> ProjectNetworkGenerationRecord:
        generation = int(product.generation or 0) or self.repository.next_generation_number(product.build_id)
        generation_id = (
            str(product.payload.get("generation_id") or product.payload.get("generation_candidate_ref") or "").strip()
            or stable_project_network_id("pngen", product.build_id, product.work_product_id, str(generation), product.payload_ref)
        )
        return ProjectNetworkGenerationRecord.from_work_product(product, generation_id=generation_id, generation=generation)

    def _queue_ingest_dirty_signals(
        self,
        *,
        build_id: str,
        graph_run_id: str,
        node_id: str,
        work_product_ids: tuple[str, ...],
        product_kinds: tuple[str, ...],
    ) -> tuple[ProjectNetworkMaintenanceSignalRecord, ...]:
        subject_ref = f"project-network://{build_id}"
        payload = {
            "graph_run_id": graph_run_id,
            "node_id": node_id,
            "work_product_ids": list(work_product_ids),
            "product_kinds": list(dict.fromkeys(product_kinds)),
            "lifecycle": "ingest_dirty_signal",
        }
        signal_specs = (
            ("semantic_facts_changed", ("semantic_coordinate", "semantic_file_module", "folder")),
            ("route_index_dirty", ("relation_route",)),
            ("signal_chain_dirty", ("signal_chain", "relation_route")),
            ("link_audit_required", ("link_signal_audit", "relation_route")),
        )
        return tuple(
            self.queue_maintenance_signal(
                build_id=build_id,
                signal_source="project_network_system.work_product_ingest",
                signal_code=code,
                severity="info",
                subject_ref=subject_ref,
                stable_ref=subject_ref,
                scope_refs=(subject_ref, *work_product_ids),
                requested_layers=layers,
                payload=payload,
                metadata={
                    "materialization_lifecycle": "dirty",
                    "materialize_command_kind": "materialize_project_network_generation",
                    "publish_command_kind": "publish_project_network_generation",
                },
            )
            for code, layers in signal_specs
        )

    def _plan_repair_items(self, signal: ProjectNetworkMaintenanceSignalRecord) -> tuple[ProjectNetworkRepairWorkItemRecord, ...]:
        scope_refs = signal.scope_refs or _normalize_strings((signal.subject_ref, signal.stable_ref))
        requested_layers = signal.requested_layers or _normalize_requested_layers((), subject_ref=signal.subject_ref or signal.stable_ref, signal_code=signal.signal_code)
        repair_scope_kind = _repair_scope_kind(signal)
        repair_kind = _repair_kind(signal)
        priority = _repair_priority(signal)
        reason_codes = (signal.signal_code,) if signal.signal_code else ()
        evidence_refs = signal.evidence_refs
        item = ProjectNetworkRepairWorkItemRecord(
            repair_item_id=stable_project_network_id(
                "pnrepair",
                signal.build_id,
                signal.signal_id,
                repair_kind,
                repair_scope_kind,
                content_hash({"scope_refs": list(scope_refs), "requested_layers": list(requested_layers)}),
            ),
            build_id=signal.build_id,
            trigger_kind="maintenance_signal",
            trigger_ref=signal.signal_id,
            trigger_signal_id=signal.signal_id,
            repair_kind=repair_kind,
            repair_scope_kind=repair_scope_kind,
            subject_ref=signal.subject_ref,
            stable_ref=signal.stable_ref,
            scope_refs=scope_refs,
            requested_layers=requested_layers,
            reason_codes=reason_codes,
            evidence_refs=evidence_refs,
            payload={
                "signal_source": signal.signal_source,
                "signal_code": signal.signal_code,
                "severity": signal.severity,
                "edge_id": signal.edge_id,
                "anchor_ref": signal.anchor_ref,
                "signal_payload": signal.payload,
            },
            priority=priority,
            status="queued",
            metadata={
                "signal_id": signal.signal_id,
                "repair_contract": "localized_project_network_repair",
            },
        )
        return (item,)


def _normalize_strings(
    value: tuple[str, ...] | list[str] | set[str] | None,
    *,
    fallback: tuple[str, ...] | list[str] = (),
) -> tuple[str, ...]:
    items = [str(item).strip() for item in list(value or fallback or ()) if str(item).strip()]
    return tuple(dict.fromkeys(items))


def _normalize_requested_layers(
    requested_layers: tuple[str, ...] | list[str] | None,
    *,
    subject_ref: str,
    signal_code: str,
) -> tuple[str, ...]:
    layers = _normalize_strings(requested_layers)
    if layers:
        return layers
    code = str(signal_code or "").strip().lower()
    ref = str(subject_ref or "").strip()
    if code in {"unresolved_route_ref", "candidate_relation_needs_resolution", "accepted_edge_missing_evidence", "accepted_edge_missing_anchor", "conflict_signal_present", "bridge_gap"}:
        return ("relation_route",)
    if ref.startswith("folder://"):
        return ("folder", "relation_route")
    if ref.startswith("file://"):
        return ("semantic_file_module", "relation_route")
    if any(ref.startswith(prefix) for prefix in ("handler://", "fn://", "function://", "func://", "pyast://", "symbol://", "type://")):
        return ("semantic_file_module", "relation_route")
    return ("relation_route",)


def _repair_scope_kind(signal: ProjectNetworkMaintenanceSignalRecord) -> str:
    ref = str(signal.subject_ref or signal.stable_ref or "").strip()
    code = str(signal.signal_code or "").strip().lower()
    if code in {"unresolved_route_ref", "candidate_relation_needs_resolution", "accepted_edge_missing_evidence", "accepted_edge_missing_anchor", "conflict_signal_present", "bridge_gap"}:
        return "relation_slice"
    if ref.startswith("folder://"):
        return "directory"
    if ref.startswith("file://"):
        return "file_module"
    if any(ref.startswith(prefix) for prefix in ("handler://", "fn://", "function://", "func://", "pyast://", "symbol://", "type://")):
        return "route_bridge"
    return "audit_slice"


def _repair_kind(signal: ProjectNetworkMaintenanceSignalRecord) -> str:
    code = str(signal.signal_code or "").strip().lower()
    if code in {"accepted_edge_missing_evidence", "accepted_edge_missing_anchor", "candidate_relation_needs_resolution", "conflict_signal_present", "bridge_gap"}:
        return "refresh_relation_route_for_signal_gap"
    if code == "unresolved_route_ref":
        return "refresh_route_landing_for_unresolved_ref"
    if code.startswith("locate_"):
        return "refresh_navigation_landings_for_locate_failure"
    return "refresh_semantic_control_slice"


def _repair_priority(signal: ProjectNetworkMaintenanceSignalRecord) -> int:
    severity = str(signal.severity or "info").strip().lower()
    base = {"error": 90, "warning": 75, "info": 55}.get(severity, 50)
    if str(signal.signal_code or "").strip().lower().startswith("locate_"):
        base = max(base, 70)
    return base


def _node_result_payload(node_result: Any) -> dict[str, Any]:
    if hasattr(node_result, "to_dict"):
        payload = dict(node_result.to_dict() or {})
    elif isinstance(node_result, dict):
        payload = dict(node_result)
    else:
        raise ValueError("ProjectNetworkBuildService requires node result payload")
    missing = [
        key
        for key in ("result_id", "graph_run_id", "node_id", "work_order_id")
        if not str(payload.get(key) or "").strip()
    ]
    if missing:
        raise ValueError(f"ProjectNetworkBuildService node result missing required fields: {', '.join(missing)}")
    payload["outputs"] = dict(payload.get("outputs") or {})
    payload["diagnostics"] = dict(payload.get("diagnostics") or {})
    return payload


def _result_build_id(result: dict[str, Any]) -> str:
    outputs = dict(result.get("outputs") or {})
    diagnostics = dict(result.get("diagnostics") or {})
    return str(
        outputs.get("project_network_build_id")
        or outputs.get("build_id")
        or dict(outputs.get("project_network") or {}).get("build_id")
        or dict(diagnostics.get("project_network") or {}).get("build_id")
        or ""
    ).strip()


def _result_shard_id(result: dict[str, Any]) -> str:
    outputs = dict(result.get("outputs") or {})
    diagnostics = dict(result.get("diagnostics") or {})
    return str(
        outputs.get("project_network_shard_id")
        or outputs.get("shard_id")
        or dict(outputs.get("project_network") or {}).get("shard_id")
        or dict(diagnostics.get("project_network") or {}).get("shard_id")
        or ""
    ).strip()


def _result_layer_id(result: dict[str, Any]) -> str:
    outputs = dict(result.get("outputs") or {})
    diagnostics = dict(result.get("diagnostics") or {})
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


def _semantic_artifact_payload(artifact_set: Any) -> dict[str, Any]:
    payload = dict(artifact_set.to_dict() if hasattr(artifact_set, "to_dict") else artifact_set or {})
    manifest_path = Path(str(payload.get("manifest_path") or ""))
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                manifest = dict(loaded)
        except (OSError, json.JSONDecodeError):
            manifest = {}
    artifact_hashes = {
        key: str(manifest.get(key) or "")
        for key in (
            "unified_control_graph_hash",
            "semantic_coordinates_hash",
            "route_index_hash",
            "signal_chain_index_hash",
            "link_signal_audit_hash",
        )
        if str(manifest.get(key) or "").strip()
    }
    if manifest:
        payload["manifest"] = manifest
    if artifact_hashes:
        payload["artifact_hashes"] = artifact_hashes
    return payload


def _semantic_artifact_identity_payload(build_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(
        {
            "build_id": build_id,
            "artifact_hashes": dict(payload.get("artifact_hashes") or {}),
            "source_work_product_count": payload.get("source_work_product_count"),
            "semantic_coordinate_count": payload.get("semantic_coordinate_count"),
            "reliable_route_count": payload.get("reliable_route_count"),
            "unresolved_route_count": payload.get("unresolved_route_count"),
            "signal_chain_count": payload.get("signal_chain_count"),
            "audit_signal_count": payload.get("audit_signal_count"),
        }
    )

