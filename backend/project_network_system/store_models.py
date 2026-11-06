from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .build_contract_models import ProjectNetworkBuildContract
from .work_product_models import GraphBuildWorkProductEnvelope


ProjectNetworkGenerationStatus = Literal[
    "draft",
    "candidate",
    "validating",
    "published",
    "superseded",
    "rejected",
    "rolled_back",
]


@dataclass(frozen=True, slots=True)
class ProjectNetworkBuildRecord:
    build_id: str
    build_kind: str
    build_mode: str
    status: ProjectNetworkGenerationStatus = "draft"
    contract: dict[str, Any] = field(default_factory=dict)
    active_generation_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.build_record"

    @classmethod
    def from_contract(
        cls,
        contract: ProjectNetworkBuildContract,
        *,
        status: ProjectNetworkGenerationStatus = "draft",
        active_generation_id: str = "",
        created_at: str = "",
        updated_at: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> "ProjectNetworkBuildRecord":
        return cls(
            build_id=contract.build_id,
            build_kind=contract.build_kind,
            build_mode=contract.build_mode,
            status=status,
            contract=contract.to_dict(),
            active_generation_id=active_generation_id,
            created_at=created_at,
            updated_at=updated_at,
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class ProjectNetworkEvidenceRecord:
    evidence_id: str
    build_id: str
    evidence_kind: str
    source_ref: str = ""
    stable_ref: str = ""
    layer_id: str = ""
    shard_id: str = ""
    graph_run_id: str = ""
    node_id: str = ""
    payload_ref: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    anchor_refs: tuple[str, ...] = ()
    content_hash: str = ""
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.evidence_record"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["anchor_refs"] = list(self.anchor_refs)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class ProjectNetworkCandidateRecord:
    candidate_id: str
    build_id: str
    work_product_id: str
    product_kind: str
    layer_id: str = ""
    stable_ref: str = ""
    shard_id: str = ""
    graph_run_id: str = ""
    node_id: str = ""
    payload_ref: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    anchor_refs: tuple[str, ...] = ()
    confidence: str = "derived"
    status: str = "candidate"
    generation: int = 0
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.candidate_record"

    @classmethod
    def from_work_product(cls, product: GraphBuildWorkProductEnvelope, *, candidate_id: str) -> "ProjectNetworkCandidateRecord":
        return cls(
            candidate_id=candidate_id,
            build_id=product.build_id,
            work_product_id=product.work_product_id,
            product_kind=product.product_kind,
            layer_id=product.layer_id,
            stable_ref=product.stable_ref,
            shard_id=product.shard_id,
            graph_run_id=product.graph_run_id,
            node_id=product.node_id,
            payload_ref=product.payload_ref,
            payload=dict(product.payload or {}),
            evidence_refs=tuple(product.evidence_refs),
            anchor_refs=tuple(product.anchor_refs),
            confidence=product.confidence,
            status=product.status,
            generation=product.generation,
            metadata=dict(product.metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_refs"] = list(self.evidence_refs)
        payload["anchor_refs"] = list(self.anchor_refs)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class ProjectNetworkLayerIndexRecord:
    layer_index_id: str
    build_id: str
    layer_id: str
    generation: int = 0
    source_work_product_ids: tuple[str, ...] = ()
    coverage: dict[str, Any] = field(default_factory=dict)
    conflict_work_product_ids: tuple[str, ...] = ()
    payload_ref: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "candidate"
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.layer_index_record"

    @classmethod
    def from_work_product(cls, product: GraphBuildWorkProductEnvelope, *, layer_index_id: str) -> "ProjectNetworkLayerIndexRecord":
        payload = dict(product.payload or {})
        return cls(
            layer_index_id=layer_index_id,
            build_id=product.build_id,
            layer_id=product.layer_id,
            generation=product.generation,
            source_work_product_ids=_tuple_of_strings(payload.get("source_work_product_ids") or payload.get("work_product_ids")),
            coverage=dict(product.coverage or payload.get("coverage") or {}),
            conflict_work_product_ids=_tuple_of_strings(payload.get("conflict_work_product_ids") or payload.get("conflict_product_ids")),
            payload_ref=product.payload_ref,
            payload=payload,
            status=product.status,
            metadata=dict(product.metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_work_product_ids"] = list(self.source_work_product_ids)
        payload["conflict_work_product_ids"] = list(self.conflict_work_product_ids)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class ProjectNetworkGenerationRecord:
    generation_id: str
    build_id: str
    generation: int = 0
    generation_ref: str = ""
    status: ProjectNetworkGenerationStatus = "candidate"
    source_snapshot_ref: str = ""
    layer_index_refs: tuple[str, ...] = ()
    work_product_refs: tuple[str, ...] = ()
    validation_refs: tuple[str, ...] = ()
    payload_ref: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    published_at: str = ""
    supersedes_generation_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.generation_record"

    @classmethod
    def from_work_product(
        cls,
        product: GraphBuildWorkProductEnvelope,
        *,
        generation_id: str,
        generation: int,
    ) -> "ProjectNetworkGenerationRecord":
        payload = dict(product.payload or {})
        return cls(
            generation_id=generation_id,
            build_id=product.build_id,
            generation=generation,
            generation_ref=str(payload.get("generation_candidate_ref") or product.payload_ref or generation_id),
            status="candidate",
            source_snapshot_ref=str(payload.get("source_snapshot_ref") or ""),
            layer_index_refs=_tuple_of_strings(payload.get("layer_index_refs") or payload.get("source_layer_refs")),
            work_product_refs=_tuple_of_strings(payload.get("work_product_refs") or product.work_product_id),
            validation_refs=_tuple_of_strings(payload.get("validation_refs")),
            payload_ref=product.payload_ref,
            payload=payload,
            metadata=dict(product.metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["layer_index_refs"] = list(self.layer_index_refs)
        payload["work_product_refs"] = list(self.work_product_refs)
        payload["validation_refs"] = list(self.validation_refs)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class ProjectNetworkTraceRecord:
    trace_id: str
    build_id: str
    graph_run_id: str = ""
    node_id: str = ""
    shard_id: str = ""
    work_order_id: str = ""
    result_id: str = ""
    event_kind: str = "work_product_ingested"
    status: str = "accepted"
    work_product_ids: tuple[str, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    authority: str = "project_network_system.trace_record"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["work_product_ids"] = list(self.work_product_ids)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class ProjectNetworkMaintenanceSignalRecord:
    signal_id: str
    build_id: str
    signal_source: str
    signal_code: str
    severity: str = "info"
    subject_ref: str = ""
    stable_ref: str = ""
    edge_id: str = ""
    anchor_ref: str = ""
    scope_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    requested_layers: tuple[str, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "queued"
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.maintenance_signal_record"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scope_refs"] = list(self.scope_refs)
        payload["evidence_refs"] = list(self.evidence_refs)
        payload["requested_layers"] = list(self.requested_layers)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class ProjectNetworkRepairWorkItemRecord:
    repair_item_id: str
    build_id: str
    trigger_kind: str
    trigger_ref: str
    trigger_signal_id: str = ""
    repair_kind: str = ""
    repair_scope_kind: str = ""
    subject_ref: str = ""
    stable_ref: str = ""
    scope_refs: tuple[str, ...] = ()
    requested_layers: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 50
    status: str = "queued"
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.repair_work_item_record"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scope_refs"] = list(self.scope_refs)
        payload["requested_layers"] = list(self.requested_layers)
        payload["reason_codes"] = list(self.reason_codes)
        payload["evidence_refs"] = list(self.evidence_refs)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class ProjectNetworkChannelState:
    channel_id: str
    build_id: str
    layer_id: str
    reducer_policy: str
    accepted_product_kinds: tuple[str, ...] = ()
    product_ids: tuple[str, ...] = ()
    conflict_product_ids: tuple[str, ...] = ()
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "project_network_system.channel_state"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["accepted_product_kinds"] = list(self.accepted_product_kinds)
        payload["product_ids"] = list(self.product_ids)
        payload["conflict_product_ids"] = list(self.conflict_product_ids)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class ProjectNetworkStoreSnapshot:
    build: ProjectNetworkBuildRecord | None = None
    work_products: tuple[GraphBuildWorkProductEnvelope, ...] = ()
    channel_states: tuple[ProjectNetworkChannelState, ...] = ()
    evidence: tuple[ProjectNetworkEvidenceRecord, ...] = ()
    candidates: tuple[ProjectNetworkCandidateRecord, ...] = ()
    layer_indexes: tuple[ProjectNetworkLayerIndexRecord, ...] = ()
    generations: tuple[ProjectNetworkGenerationRecord, ...] = ()
    traces: tuple[ProjectNetworkTraceRecord, ...] = ()
    maintenance_signals: tuple[ProjectNetworkMaintenanceSignalRecord, ...] = ()
    repair_items: tuple[ProjectNetworkRepairWorkItemRecord, ...] = ()
    authority: str = "project_network_system.store_snapshot"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "build": self.build.to_dict() if self.build is not None else {},
                "work_products": [item.to_dict() for item in self.work_products],
                "channel_states": [item.to_dict() for item in self.channel_states],
                "evidence": [item.to_dict() for item in self.evidence],
                "candidates": [item.to_dict() for item in self.candidates],
                "layer_indexes": [item.to_dict() for item in self.layer_indexes],
                "generations": [item.to_dict() for item in self.generations],
                "traces": [item.to_dict() for item in self.traces],
                "maintenance_signals": [item.to_dict() for item in self.maintenance_signals],
                "repair_items": [item.to_dict() for item in self.repair_items],
                "authority": self.authority,
            }
        )


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.replace(",", "\n").splitlines() if item.strip())
    return tuple(str(item).strip() for item in list(value or []) if str(item).strip())


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}

