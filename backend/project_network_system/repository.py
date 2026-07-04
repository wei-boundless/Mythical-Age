from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.project_layout import ProjectLayout

from .build_contract_models import ProjectNetworkBuildContract
from .directory_render_models import (
    DirectoryChildReturnEnvelope,
    DirectoryManifestProduct,
    DirectoryRenderBudget,
    DirectoryRenderFrame,
)
from .lifecycle_policy import validate_generation_status_transition
from .store_models import (
    ProjectNetworkBuildRecord,
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
from .work_product_models import GraphBuildWorkProductEnvelope, WorkProductChannel, reduce_work_products


PUBLISH_AUTHORITY_KINDS = {"curator", "publish_gate", "human_gate", "system_publish_gate"}


class ProjectNetworkRepository:
    authority = "project_network_system.repository"

    def __init__(self, base_dir: str | Path) -> None:
        layout = ProjectLayout.from_backend_dir(base_dir)
        self.root = layout.tasks_dir
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "project_network.sqlite"
        self._ensure_schema()

    def upsert_build_contract(
        self,
        contract: ProjectNetworkBuildContract,
        *,
        status: str = "draft",
        metadata: dict[str, Any] | None = None,
    ) -> ProjectNetworkBuildRecord:
        existing = self.get_build(contract.build_id)
        record = ProjectNetworkBuildRecord.from_contract(
            contract,
            status=str(existing.status if existing is not None else status or "draft"),
            active_generation_id=existing.active_generation_id if existing is not None else "",
            created_at=existing.created_at if existing is not None else "",
            metadata={**dict(existing.metadata if existing is not None else {}), **dict(metadata or {})},
        )
        return self.upsert_build(record)

    def upsert_build(self, record: ProjectNetworkBuildRecord) -> ProjectNetworkBuildRecord:
        now = utc_now_iso()
        stored = replace(record, created_at=record.created_at or now, updated_at=now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_network_builds (
                    build_id, build_kind, build_mode, status, contract_json,
                    active_generation_id, metadata_json, created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(build_id) DO UPDATE SET
                    build_kind = excluded.build_kind,
                    build_mode = excluded.build_mode,
                    status = excluded.status,
                    contract_json = excluded.contract_json,
                    active_generation_id = excluded.active_generation_id,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.build_id,
                    stored.build_kind,
                    stored.build_mode,
                    stored.status,
                    _json(stored.contract),
                    stored.active_generation_id,
                    _json(stored.metadata),
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def get_build(self, build_id: str) -> ProjectNetworkBuildRecord | None:
        target = str(build_id or "").strip()
        if not target:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM project_network_builds WHERE build_id = ?", (target,)).fetchone()
        return _build_from_row(row) if row is not None else None

    def upsert_work_product(self, product: GraphBuildWorkProductEnvelope) -> GraphBuildWorkProductEnvelope:
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_network_work_products (
                    work_product_id, build_id, graph_run_id, node_id, shard_id, layer_id,
                    product_kind, contract_id, payload_ref, payload_json, evidence_refs_json,
                    anchor_refs_json, coverage_json, confidence, status, stable_ref, generation,
                    metadata_json, created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(work_product_id) DO UPDATE SET
                    build_id = excluded.build_id,
                    graph_run_id = excluded.graph_run_id,
                    node_id = excluded.node_id,
                    shard_id = excluded.shard_id,
                    layer_id = excluded.layer_id,
                    product_kind = excluded.product_kind,
                    contract_id = excluded.contract_id,
                    payload_ref = excluded.payload_ref,
                    payload_json = excluded.payload_json,
                    evidence_refs_json = excluded.evidence_refs_json,
                    anchor_refs_json = excluded.anchor_refs_json,
                    coverage_json = excluded.coverage_json,
                    confidence = excluded.confidence,
                    status = excluded.status,
                    stable_ref = excluded.stable_ref,
                    generation = excluded.generation,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    product.work_product_id,
                    product.build_id,
                    product.graph_run_id,
                    product.node_id,
                    product.shard_id,
                    product.layer_id,
                    product.product_kind,
                    product.contract_id,
                    product.payload_ref,
                    _json(product.payload),
                    _json(list(product.evidence_refs)),
                    _json(list(product.anchor_refs)),
                    _json(product.coverage),
                    product.confidence,
                    product.status,
                    product.stable_ref,
                    int(product.generation or 0),
                    _json(product.metadata),
                    _existing_created_at(conn, "project_network_work_products", "work_product_id", product.work_product_id) or now,
                    now,
                    product.authority,
                ),
            )
        return product

    def upsert_work_products(
        self,
        products: tuple[GraphBuildWorkProductEnvelope, ...] | list[GraphBuildWorkProductEnvelope],
    ) -> tuple[GraphBuildWorkProductEnvelope, ...]:
        return tuple(self.upsert_work_product(product) for product in products)

    def get_work_product(self, work_product_id: str) -> GraphBuildWorkProductEnvelope | None:
        target = str(work_product_id or "").strip()
        if not target:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM project_network_work_products WHERE work_product_id = ?", (target,)).fetchone()
        return _work_product_from_row(row) if row is not None else None

    def list_work_products(
        self,
        *,
        build_id: str = "",
        layer_id: str = "",
        product_kind: str = "",
        status: str = "",
        graph_run_id: str = "",
        limit: int = 2000,
    ) -> tuple[GraphBuildWorkProductEnvelope, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if build_id:
            filters.append("build_id = ?")
            params.append(build_id)
        if layer_id:
            filters.append("layer_id = ?")
            params.append(layer_id)
        if product_kind:
            filters.append("product_kind = ?")
            params.append(product_kind)
        if status:
            filters.append("status = ?")
            params.append(status)
        if graph_run_id:
            filters.append("graph_run_id = ?")
            params.append(graph_run_id)
        sql = "SELECT * FROM project_network_work_products"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY updated_at DESC, work_product_id ASC LIMIT ?"
        params.append(_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_work_product_from_row(row) for row in rows)

    def reduce_channel(
        self,
        channel: WorkProductChannel,
        *,
        build_id: str,
        incoming_products: tuple[GraphBuildWorkProductEnvelope, ...],
    ) -> ProjectNetworkChannelState:
        existing_state = self.get_channel_state(build_id=build_id, channel_id=channel.channel_id)
        existing_products = tuple(
            product
            for product_id in (existing_state.product_ids if existing_state is not None else ())
            for product in (self.get_work_product(product_id),)
            if product is not None
        )
        reduced = reduce_work_products(channel, existing_products, incoming_products)
        conflict_ids = tuple(item.work_product_id for item in reduced if item.product_kind == "conflict_report")
        return self.upsert_channel_state(
            ProjectNetworkChannelState(
                channel_id=channel.channel_id,
                build_id=build_id,
                layer_id=channel.layer_id,
                reducer_policy=channel.reducer_policy,
                accepted_product_kinds=tuple(channel.accepted_product_kinds),
                product_ids=tuple(item.work_product_id for item in reduced),
                conflict_product_ids=conflict_ids,
                metadata={"visibility": channel.visibility, "identity_keys": list(channel.identity_keys)},
            )
        )

    def upsert_channel_state(self, state: ProjectNetworkChannelState) -> ProjectNetworkChannelState:
        now = utc_now_iso()
        stored = replace(state, updated_at=now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_network_channel_states (
                    channel_id, build_id, layer_id, reducer_policy, accepted_product_kinds_json,
                    product_ids_json, conflict_product_ids_json, metadata_json, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(build_id, channel_id) DO UPDATE SET
                    layer_id = excluded.layer_id,
                    reducer_policy = excluded.reducer_policy,
                    accepted_product_kinds_json = excluded.accepted_product_kinds_json,
                    product_ids_json = excluded.product_ids_json,
                    conflict_product_ids_json = excluded.conflict_product_ids_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.channel_id,
                    stored.build_id,
                    stored.layer_id,
                    stored.reducer_policy,
                    _json(list(stored.accepted_product_kinds)),
                    _json(list(stored.product_ids)),
                    _json(list(stored.conflict_product_ids)),
                    _json(stored.metadata),
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def get_channel_state(self, *, build_id: str, channel_id: str) -> ProjectNetworkChannelState | None:
        if not str(build_id or "").strip() or not str(channel_id or "").strip():
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM project_network_channel_states
                WHERE build_id = ? AND channel_id = ?
                """,
                (build_id, channel_id),
            ).fetchone()
        return _channel_state_from_row(row) if row is not None else None

    def list_channel_states(self, *, build_id: str = "", layer_id: str = "", limit: int = 2000) -> tuple[ProjectNetworkChannelState, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if build_id:
            filters.append("build_id = ?")
            params.append(build_id)
        if layer_id:
            filters.append("layer_id = ?")
            params.append(layer_id)
        sql = "SELECT * FROM project_network_channel_states"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY updated_at DESC, channel_id ASC LIMIT ?"
        params.append(_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_channel_state_from_row(row) for row in rows)

    def upsert_evidence(self, record: ProjectNetworkEvidenceRecord) -> ProjectNetworkEvidenceRecord:
        now = utc_now_iso()
        stored = replace(record, created_at=record.created_at or now, updated_at=now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_network_evidence (
                    evidence_id, build_id, evidence_kind, source_ref, stable_ref, layer_id,
                    shard_id, graph_run_id, node_id, payload_ref, payload_json, anchor_refs_json,
                    content_hash, status, metadata_json, created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(evidence_id) DO UPDATE SET
                    evidence_kind = excluded.evidence_kind,
                    source_ref = excluded.source_ref,
                    stable_ref = excluded.stable_ref,
                    layer_id = excluded.layer_id,
                    shard_id = excluded.shard_id,
                    graph_run_id = excluded.graph_run_id,
                    node_id = excluded.node_id,
                    payload_ref = excluded.payload_ref,
                    payload_json = excluded.payload_json,
                    anchor_refs_json = excluded.anchor_refs_json,
                    content_hash = excluded.content_hash,
                    status = excluded.status,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.evidence_id,
                    stored.build_id,
                    stored.evidence_kind,
                    stored.source_ref,
                    stored.stable_ref,
                    stored.layer_id,
                    stored.shard_id,
                    stored.graph_run_id,
                    stored.node_id,
                    stored.payload_ref,
                    _json(stored.payload),
                    _json(list(stored.anchor_refs)),
                    stored.content_hash,
                    stored.status,
                    _json(stored.metadata),
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def list_evidence(self, *, build_id: str = "", layer_id: str = "", limit: int = 2000) -> tuple[ProjectNetworkEvidenceRecord, ...]:
        filters, params = _filters(build_id=build_id, layer_id=layer_id)
        sql = "SELECT * FROM project_network_evidence"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY updated_at DESC, evidence_id ASC LIMIT ?"
        params.append(_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_evidence_from_row(row) for row in rows)

    def upsert_candidate(self, record: ProjectNetworkCandidateRecord) -> ProjectNetworkCandidateRecord:
        now = utc_now_iso()
        stored = replace(record, created_at=record.created_at or now, updated_at=now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_network_candidates (
                    candidate_id, build_id, work_product_id, product_kind, layer_id, stable_ref,
                    shard_id, graph_run_id, node_id, payload_ref, payload_json, evidence_refs_json,
                    anchor_refs_json, confidence, status, generation, metadata_json,
                    created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET
                    work_product_id = excluded.work_product_id,
                    product_kind = excluded.product_kind,
                    layer_id = excluded.layer_id,
                    stable_ref = excluded.stable_ref,
                    shard_id = excluded.shard_id,
                    graph_run_id = excluded.graph_run_id,
                    node_id = excluded.node_id,
                    payload_ref = excluded.payload_ref,
                    payload_json = excluded.payload_json,
                    evidence_refs_json = excluded.evidence_refs_json,
                    anchor_refs_json = excluded.anchor_refs_json,
                    confidence = excluded.confidence,
                    status = excluded.status,
                    generation = excluded.generation,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.candidate_id,
                    stored.build_id,
                    stored.work_product_id,
                    stored.product_kind,
                    stored.layer_id,
                    stored.stable_ref,
                    stored.shard_id,
                    stored.graph_run_id,
                    stored.node_id,
                    stored.payload_ref,
                    _json(stored.payload),
                    _json(list(stored.evidence_refs)),
                    _json(list(stored.anchor_refs)),
                    stored.confidence,
                    stored.status,
                    int(stored.generation or 0),
                    _json(stored.metadata),
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def list_candidates(
        self,
        *,
        build_id: str = "",
        layer_id: str = "",
        stable_ref: str = "",
        product_kind: str = "",
        status: str = "",
        limit: int = 2000,
    ) -> tuple[ProjectNetworkCandidateRecord, ...]:
        filters, params = _filters(build_id=build_id, layer_id=layer_id)
        if stable_ref:
            filters.append("stable_ref = ?")
            params.append(stable_ref)
        if product_kind:
            filters.append("product_kind = ?")
            params.append(product_kind)
        if status:
            filters.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM project_network_candidates"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY updated_at DESC, candidate_id ASC LIMIT ?"
        params.append(_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_candidate_from_row(row) for row in rows)

    def upsert_layer_index(self, record: ProjectNetworkLayerIndexRecord) -> ProjectNetworkLayerIndexRecord:
        now = utc_now_iso()
        stored = replace(record, created_at=record.created_at or now, updated_at=now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_network_layer_indexes (
                    layer_index_id, build_id, layer_id, generation, source_work_product_ids_json,
                    coverage_json, conflict_work_product_ids_json, payload_ref, payload_json,
                    status, metadata_json, created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(layer_index_id) DO UPDATE SET
                    layer_id = excluded.layer_id,
                    generation = excluded.generation,
                    source_work_product_ids_json = excluded.source_work_product_ids_json,
                    coverage_json = excluded.coverage_json,
                    conflict_work_product_ids_json = excluded.conflict_work_product_ids_json,
                    payload_ref = excluded.payload_ref,
                    payload_json = excluded.payload_json,
                    status = excluded.status,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.layer_index_id,
                    stored.build_id,
                    stored.layer_id,
                    int(stored.generation or 0),
                    _json(list(stored.source_work_product_ids)),
                    _json(stored.coverage),
                    _json(list(stored.conflict_work_product_ids)),
                    stored.payload_ref,
                    _json(stored.payload),
                    stored.status,
                    _json(stored.metadata),
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def list_layer_indexes(self, *, build_id: str = "", layer_id: str = "", limit: int = 2000) -> tuple[ProjectNetworkLayerIndexRecord, ...]:
        filters, params = _filters(build_id=build_id, layer_id=layer_id)
        sql = "SELECT * FROM project_network_layer_indexes"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY generation DESC, updated_at DESC, layer_index_id ASC LIMIT ?"
        params.append(_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_layer_index_from_row(row) for row in rows)

    def upsert_generation(self, record: ProjectNetworkGenerationRecord) -> ProjectNetworkGenerationRecord:
        now = utc_now_iso()
        stored = replace(record, created_at=record.created_at or now, updated_at=now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_network_generations (
                    generation_id, build_id, generation, generation_ref, status, source_snapshot_ref,
                    layer_index_refs_json, work_product_refs_json, validation_refs_json,
                    payload_ref, payload_json, published_at, supersedes_generation_id,
                    metadata_json, created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(generation_id) DO UPDATE SET
                    generation = excluded.generation,
                    generation_ref = excluded.generation_ref,
                    status = excluded.status,
                    source_snapshot_ref = excluded.source_snapshot_ref,
                    layer_index_refs_json = excluded.layer_index_refs_json,
                    work_product_refs_json = excluded.work_product_refs_json,
                    validation_refs_json = excluded.validation_refs_json,
                    payload_ref = excluded.payload_ref,
                    payload_json = excluded.payload_json,
                    published_at = excluded.published_at,
                    supersedes_generation_id = excluded.supersedes_generation_id,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.generation_id,
                    stored.build_id,
                    int(stored.generation or 0),
                    stored.generation_ref,
                    stored.status,
                    stored.source_snapshot_ref,
                    _json(list(stored.layer_index_refs)),
                    _json(list(stored.work_product_refs)),
                    _json(list(stored.validation_refs)),
                    stored.payload_ref,
                    _json(stored.payload),
                    stored.published_at,
                    stored.supersedes_generation_id,
                    _json(stored.metadata),
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def get_generation(self, generation_id: str) -> ProjectNetworkGenerationRecord | None:
        target = str(generation_id or "").strip()
        if not target:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM project_network_generations WHERE generation_id = ?", (target,)).fetchone()
        return _generation_from_row(row) if row is not None else None

    def list_generations(
        self,
        *,
        build_id: str = "",
        status: str = "",
        limit: int = 2000,
    ) -> tuple[ProjectNetworkGenerationRecord, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if build_id:
            filters.append("build_id = ?")
            params.append(build_id)
        if status:
            filters.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM project_network_generations"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY generation DESC, updated_at DESC, generation_id ASC LIMIT ?"
        params.append(_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_generation_from_row(row) for row in rows)

    def next_generation_number(self, build_id: str) -> int:
        with self._connect() as conn:
            value = conn.execute(
                "SELECT MAX(generation) FROM project_network_generations WHERE build_id = ?",
                (build_id,),
            ).fetchone()[0]
        return int(value or 0) + 1

    def transition_generation(
        self,
        generation_id: str,
        *,
        next_status: str,
        actor_kind: str,
        actor_ref: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ProjectNetworkGenerationRecord:
        current = self.get_generation(generation_id)
        if current is None:
            raise KeyError(f"project network generation not found: {generation_id}")
        if next_status == "published":
            return self.publish_generation(
                generation_id,
                actor_kind=actor_kind,
                actor_ref=actor_ref,
                metadata=metadata,
            )
        if current.status == next_status:
            return current
        if not validate_generation_status_transition(current.status, next_status):
            raise ValueError(f"invalid generation status transition: {current.status} -> {next_status}")
        return self.upsert_generation(
            replace(
                current,
                status=next_status,  # type: ignore[arg-type]
                metadata={
                    **dict(current.metadata or {}),
                    **dict(metadata or {}),
                    "last_transition_actor_kind": str(actor_kind or ""),
                    "last_transition_actor_ref": str(actor_ref or ""),
                },
            )
        )

    def publish_generation(
        self,
        generation_id: str,
        *,
        actor_kind: str,
        actor_ref: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ProjectNetworkGenerationRecord:
        if str(actor_kind or "").strip() not in PUBLISH_AUTHORITY_KINDS:
            raise PermissionError("generation publish requires curator or publish-gate authority")
        current = self.get_generation(generation_id)
        if current is None:
            raise KeyError(f"project network generation not found: {generation_id}")
        if current.status not in {"candidate", "validating", "published"}:
            raise ValueError(f"generation cannot be published from status: {current.status}")
        now = utc_now_iso()
        prior_published = tuple(item for item in self.list_generations(build_id=current.build_id, status="published") if item.generation_id != current.generation_id)
        supersedes = prior_published[0].generation_id if prior_published else current.supersedes_generation_id
        with self._connect() as conn:
            for item in prior_published:
                conn.execute(
                    """
                    UPDATE project_network_generations
                    SET status = 'superseded', updated_at = ?, metadata_json = ?
                    WHERE generation_id = ?
                    """,
                    (
                        now,
                        _json(
                            {
                                **dict(item.metadata or {}),
                                "superseded_by": current.generation_id,
                                "superseded_actor_kind": actor_kind,
                                "superseded_actor_ref": actor_ref,
                            }
                        ),
                        item.generation_id,
                    ),
                )
            conn.execute(
                """
                UPDATE project_network_generations
                SET status = 'published', published_at = ?, supersedes_generation_id = ?,
                    metadata_json = ?, updated_at = ?
                WHERE generation_id = ?
                """,
                (
                    now,
                    supersedes,
                    _json(
                        {
                            **dict(current.metadata or {}),
                            **dict(metadata or {}),
                            "publish_actor_kind": actor_kind,
                            "publish_actor_ref": actor_ref,
                        }
                    ),
                    now,
                    current.generation_id,
                ),
            )
            conn.execute(
                """
                UPDATE project_network_builds
                SET status = 'published', active_generation_id = ?, updated_at = ?
                WHERE build_id = ?
                """,
                (current.generation_id, now, current.build_id),
            )
        published = self.get_generation(current.generation_id)
        if published is None:
            raise RuntimeError("project network generation publish did not persist")
        return published

    def upsert_trace(self, record: ProjectNetworkTraceRecord) -> ProjectNetworkTraceRecord:
        now = utc_now_iso()
        stored = replace(record, created_at=record.created_at or now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_network_traces (
                    trace_id, build_id, graph_run_id, node_id, shard_id, work_order_id,
                    result_id, event_kind, status, work_product_ids_json, payload_json,
                    created_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trace_id) DO UPDATE SET
                    graph_run_id = excluded.graph_run_id,
                    node_id = excluded.node_id,
                    shard_id = excluded.shard_id,
                    work_order_id = excluded.work_order_id,
                    result_id = excluded.result_id,
                    event_kind = excluded.event_kind,
                    status = excluded.status,
                    work_product_ids_json = excluded.work_product_ids_json,
                    payload_json = excluded.payload_json,
                    authority = excluded.authority
                """,
                (
                    stored.trace_id,
                    stored.build_id,
                    stored.graph_run_id,
                    stored.node_id,
                    stored.shard_id,
                    stored.work_order_id,
                    stored.result_id,
                    stored.event_kind,
                    stored.status,
                    _json(list(stored.work_product_ids)),
                    _json(stored.payload),
                    stored.created_at,
                    stored.authority,
                ),
            )
        return stored

    def list_traces(self, *, build_id: str = "", graph_run_id: str = "", limit: int = 2000) -> tuple[ProjectNetworkTraceRecord, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if build_id:
            filters.append("build_id = ?")
            params.append(build_id)
        if graph_run_id:
            filters.append("graph_run_id = ?")
            params.append(graph_run_id)
        sql = "SELECT * FROM project_network_traces"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY created_at DESC, trace_id ASC LIMIT ?"
        params.append(_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_trace_from_row(row) for row in rows)

    def upsert_maintenance_signal(self, record: ProjectNetworkMaintenanceSignalRecord) -> ProjectNetworkMaintenanceSignalRecord:
        now = utc_now_iso()
        stored = replace(record, created_at=record.created_at or now, updated_at=now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_network_maintenance_signals (
                    signal_id, build_id, signal_source, signal_code, severity, subject_ref,
                    stable_ref, edge_id, anchor_ref, scope_refs_json, evidence_refs_json,
                    requested_layers_json, payload_json, status, metadata_json,
                    created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(signal_id) DO UPDATE SET
                    signal_source = excluded.signal_source,
                    signal_code = excluded.signal_code,
                    severity = excluded.severity,
                    subject_ref = excluded.subject_ref,
                    stable_ref = excluded.stable_ref,
                    edge_id = excluded.edge_id,
                    anchor_ref = excluded.anchor_ref,
                    scope_refs_json = excluded.scope_refs_json,
                    evidence_refs_json = excluded.evidence_refs_json,
                    requested_layers_json = excluded.requested_layers_json,
                    payload_json = excluded.payload_json,
                    status = excluded.status,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.signal_id,
                    stored.build_id,
                    stored.signal_source,
                    stored.signal_code,
                    stored.severity,
                    stored.subject_ref,
                    stored.stable_ref,
                    stored.edge_id,
                    stored.anchor_ref,
                    _json(list(stored.scope_refs)),
                    _json(list(stored.evidence_refs)),
                    _json(list(stored.requested_layers)),
                    _json(stored.payload),
                    stored.status,
                    _json(stored.metadata),
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def get_maintenance_signal(self, signal_id: str) -> ProjectNetworkMaintenanceSignalRecord | None:
        target = str(signal_id or "").strip()
        if not target:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM project_network_maintenance_signals WHERE signal_id = ?",
                (target,),
            ).fetchone()
        return _maintenance_signal_from_row(row) if row is not None else None

    def list_maintenance_signals(
        self,
        *,
        build_id: str = "",
        stable_ref: str = "",
        subject_ref: str = "",
        signal_source: str = "",
        status: str = "",
        limit: int = 2000,
    ) -> tuple[ProjectNetworkMaintenanceSignalRecord, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if build_id:
            filters.append("build_id = ?")
            params.append(build_id)
        if stable_ref:
            filters.append("stable_ref = ?")
            params.append(stable_ref)
        if subject_ref:
            filters.append("subject_ref = ?")
            params.append(subject_ref)
        if signal_source:
            filters.append("signal_source = ?")
            params.append(signal_source)
        if status:
            filters.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM project_network_maintenance_signals"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY updated_at DESC, signal_id ASC LIMIT ?"
        params.append(_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_maintenance_signal_from_row(row) for row in rows)

    def upsert_repair_item(self, record: ProjectNetworkRepairWorkItemRecord) -> ProjectNetworkRepairWorkItemRecord:
        now = utc_now_iso()
        stored = replace(record, created_at=record.created_at or now, updated_at=now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_network_repair_work_items (
                    repair_item_id, build_id, trigger_kind, trigger_ref, trigger_signal_id,
                    repair_kind, repair_scope_kind, subject_ref, stable_ref, scope_refs_json,
                    requested_layers_json, reason_codes_json, evidence_refs_json, payload_json,
                    priority, status, metadata_json, created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repair_item_id) DO UPDATE SET
                    trigger_kind = excluded.trigger_kind,
                    trigger_ref = excluded.trigger_ref,
                    trigger_signal_id = excluded.trigger_signal_id,
                    repair_kind = excluded.repair_kind,
                    repair_scope_kind = excluded.repair_scope_kind,
                    subject_ref = excluded.subject_ref,
                    stable_ref = excluded.stable_ref,
                    scope_refs_json = excluded.scope_refs_json,
                    requested_layers_json = excluded.requested_layers_json,
                    reason_codes_json = excluded.reason_codes_json,
                    evidence_refs_json = excluded.evidence_refs_json,
                    payload_json = excluded.payload_json,
                    priority = excluded.priority,
                    status = excluded.status,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.repair_item_id,
                    stored.build_id,
                    stored.trigger_kind,
                    stored.trigger_ref,
                    stored.trigger_signal_id,
                    stored.repair_kind,
                    stored.repair_scope_kind,
                    stored.subject_ref,
                    stored.stable_ref,
                    _json(list(stored.scope_refs)),
                    _json(list(stored.requested_layers)),
                    _json(list(stored.reason_codes)),
                    _json(list(stored.evidence_refs)),
                    _json(stored.payload),
                    int(stored.priority or 0),
                    stored.status,
                    _json(stored.metadata),
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def list_repair_items(
        self,
        *,
        build_id: str = "",
        stable_ref: str = "",
        subject_ref: str = "",
        trigger_signal_id: str = "",
        status: str = "",
        limit: int = 2000,
    ) -> tuple[ProjectNetworkRepairWorkItemRecord, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if build_id:
            filters.append("build_id = ?")
            params.append(build_id)
        if stable_ref:
            filters.append("stable_ref = ?")
            params.append(stable_ref)
        if subject_ref:
            filters.append("subject_ref = ?")
            params.append(subject_ref)
        if trigger_signal_id:
            filters.append("trigger_signal_id = ?")
            params.append(trigger_signal_id)
        if status:
            filters.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM project_network_repair_work_items"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY priority DESC, updated_at DESC, repair_item_id ASC LIMIT ?"
        params.append(_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_repair_item_from_row(row) for row in rows)

    def upsert_directory_frame(self, frame: DirectoryRenderFrame) -> DirectoryRenderFrame:
        now = utc_now_iso()
        with self._connect() as conn:
            created_at = _existing_created_at(conn, "project_network_directory_frames", "frame_id", frame.frame_id) or now
            stored = replace(frame, created_at=frame.created_at or created_at, updated_at=now)
            conn.execute(
                """
                INSERT INTO project_network_directory_frames (
                    frame_id, build_id, root_frame_id, parent_frame_id, depth,
                    skeleton_build_id, skeleton_generation, folder_node_id,
                    folder_stable_ref, folder_path, manifest_ref, child_frame_ids_json,
                    direct_file_refs_json, child_return_refs_json, aggregate_work_product_ref,
                    graph_id, graph_run_id, status, budget_json, metadata_json,
                    created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(frame_id) DO UPDATE SET
                    build_id = excluded.build_id,
                    root_frame_id = excluded.root_frame_id,
                    parent_frame_id = excluded.parent_frame_id,
                    depth = excluded.depth,
                    skeleton_build_id = excluded.skeleton_build_id,
                    skeleton_generation = excluded.skeleton_generation,
                    folder_node_id = excluded.folder_node_id,
                    folder_stable_ref = excluded.folder_stable_ref,
                    folder_path = excluded.folder_path,
                    manifest_ref = excluded.manifest_ref,
                    child_frame_ids_json = excluded.child_frame_ids_json,
                    direct_file_refs_json = excluded.direct_file_refs_json,
                    child_return_refs_json = excluded.child_return_refs_json,
                    aggregate_work_product_ref = excluded.aggregate_work_product_ref,
                    graph_id = excluded.graph_id,
                    graph_run_id = excluded.graph_run_id,
                    status = excluded.status,
                    budget_json = excluded.budget_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.frame_id,
                    stored.build_id,
                    stored.root_frame_id,
                    stored.parent_frame_id,
                    int(stored.depth or 0),
                    stored.skeleton_build_id,
                    int(stored.skeleton_generation or 0),
                    stored.folder_node_id,
                    stored.folder_stable_ref,
                    stored.folder_path,
                    stored.manifest_ref,
                    _json(list(stored.child_frame_ids)),
                    _json(list(stored.direct_file_refs)),
                    _json(list(stored.child_return_refs)),
                    stored.aggregate_work_product_ref,
                    stored.graph_id,
                    stored.graph_run_id,
                    stored.status,
                    _json(stored.budget.to_dict()),
                    _json(stored.metadata),
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def get_directory_frame(self, frame_id: str) -> DirectoryRenderFrame | None:
        target = str(frame_id or "").strip()
        if not target:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM project_network_directory_frames WHERE frame_id = ?", (target,)).fetchone()
        return _directory_frame_from_row(row) if row is not None else None

    def list_directory_frames(
        self,
        *,
        build_id: str = "",
        root_frame_id: str = "",
        parent_frame_id: str = "",
        graph_run_id: str = "",
        status: str = "",
        limit: int = 2000,
    ) -> tuple[DirectoryRenderFrame, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if build_id:
            filters.append("build_id = ?")
            params.append(build_id)
        if root_frame_id:
            filters.append("root_frame_id = ?")
            params.append(root_frame_id)
        if parent_frame_id:
            filters.append("parent_frame_id = ?")
            params.append(parent_frame_id)
        if graph_run_id:
            filters.append("graph_run_id = ?")
            params.append(graph_run_id)
        if status:
            filters.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM project_network_directory_frames"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY depth ASC, folder_path ASC, frame_id ASC LIMIT ?"
        params.append(_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_directory_frame_from_row(row) for row in rows)

    def upsert_directory_manifest(self, manifest: DirectoryManifestProduct) -> DirectoryManifestProduct:
        now = utc_now_iso()
        with self._connect() as conn:
            created_at = _existing_created_at(conn, "project_network_directory_manifests", "manifest_id", manifest.manifest_id) or now
            stored = replace(manifest, created_at=manifest.created_at or created_at, updated_at=now)
            conn.execute(
                """
                INSERT INTO project_network_directory_manifests (
                    manifest_id, build_id, frame_id, skeleton_build_id, skeleton_generation,
                    folder_node_id, folder_stable_ref, folder_path, child_folder_node_ids_json,
                    child_folder_refs_json, direct_file_node_ids_json, direct_file_refs_json,
                    skipped_refs_json, child_folder_nodes_json, direct_file_nodes_json,
                    content_hash, status, metadata_json, created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(manifest_id) DO UPDATE SET
                    build_id = excluded.build_id,
                    frame_id = excluded.frame_id,
                    skeleton_build_id = excluded.skeleton_build_id,
                    skeleton_generation = excluded.skeleton_generation,
                    folder_node_id = excluded.folder_node_id,
                    folder_stable_ref = excluded.folder_stable_ref,
                    folder_path = excluded.folder_path,
                    child_folder_node_ids_json = excluded.child_folder_node_ids_json,
                    child_folder_refs_json = excluded.child_folder_refs_json,
                    direct_file_node_ids_json = excluded.direct_file_node_ids_json,
                    direct_file_refs_json = excluded.direct_file_refs_json,
                    skipped_refs_json = excluded.skipped_refs_json,
                    child_folder_nodes_json = excluded.child_folder_nodes_json,
                    direct_file_nodes_json = excluded.direct_file_nodes_json,
                    content_hash = excluded.content_hash,
                    status = excluded.status,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.manifest_id,
                    stored.build_id,
                    stored.frame_id,
                    stored.skeleton_build_id,
                    int(stored.skeleton_generation or 0),
                    stored.folder_node_id,
                    stored.folder_stable_ref,
                    stored.folder_path,
                    _json(list(stored.child_folder_node_ids)),
                    _json(list(stored.child_folder_refs)),
                    _json(list(stored.direct_file_node_ids)),
                    _json(list(stored.direct_file_refs)),
                    _json(list(stored.skipped_refs)),
                    _json([dict(item) for item in stored.child_folder_nodes]),
                    _json([dict(item) for item in stored.direct_file_nodes]),
                    stored.content_hash,
                    stored.status,
                    _json(stored.metadata),
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def get_directory_manifest(self, manifest_id: str) -> DirectoryManifestProduct | None:
        target = str(manifest_id or "").strip()
        if not target:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM project_network_directory_manifests WHERE manifest_id = ?", (target,)).fetchone()
        return _directory_manifest_from_row(row) if row is not None else None

    def upsert_directory_child_return(self, envelope: DirectoryChildReturnEnvelope) -> DirectoryChildReturnEnvelope:
        now = utc_now_iso()
        with self._connect() as conn:
            created_at = _existing_created_at(conn, "project_network_directory_child_returns", "return_id", envelope.return_id) or now
            stored = replace(envelope, created_at=envelope.created_at or created_at, updated_at=now)
            conn.execute(
                """
                INSERT INTO project_network_directory_child_returns (
                    return_id, build_id, parent_frame_id, child_frame_id, child_folder_ref,
                    child_folder_node_id, child_summary_product_ref, status, payload_ref,
                    coverage_json, blockers_json, metadata_json, created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(return_id) DO UPDATE SET
                    build_id = excluded.build_id,
                    parent_frame_id = excluded.parent_frame_id,
                    child_frame_id = excluded.child_frame_id,
                    child_folder_ref = excluded.child_folder_ref,
                    child_folder_node_id = excluded.child_folder_node_id,
                    child_summary_product_ref = excluded.child_summary_product_ref,
                    status = excluded.status,
                    payload_ref = excluded.payload_ref,
                    coverage_json = excluded.coverage_json,
                    blockers_json = excluded.blockers_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.return_id,
                    stored.build_id,
                    stored.parent_frame_id,
                    stored.child_frame_id,
                    stored.child_folder_ref,
                    stored.child_folder_node_id,
                    stored.child_summary_product_ref,
                    stored.status,
                    stored.payload_ref,
                    _json(stored.coverage),
                    _json(list(stored.blockers)),
                    _json(stored.metadata),
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def list_directory_child_returns(
        self,
        *,
        build_id: str = "",
        parent_frame_id: str = "",
        child_frame_id: str = "",
        status: str = "",
        limit: int = 2000,
    ) -> tuple[DirectoryChildReturnEnvelope, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if build_id:
            filters.append("build_id = ?")
            params.append(build_id)
        if parent_frame_id:
            filters.append("parent_frame_id = ?")
            params.append(parent_frame_id)
        if child_frame_id:
            filters.append("child_frame_id = ?")
            params.append(child_frame_id)
        if status:
            filters.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM project_network_directory_child_returns"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY updated_at DESC, return_id ASC LIMIT ?"
        params.append(_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_directory_child_return_from_row(row) for row in rows)

    def snapshot(self, build_id: str, *, limit: int = 2000) -> ProjectNetworkStoreSnapshot:
        target = str(build_id or "").strip()
        return ProjectNetworkStoreSnapshot(
            build=self.get_build(target),
            work_products=self.list_work_products(build_id=target, limit=limit),
            channel_states=self.list_channel_states(build_id=target, limit=limit),
            evidence=self.list_evidence(build_id=target, limit=limit),
            candidates=self.list_candidates(build_id=target, limit=limit),
            layer_indexes=self.list_layer_indexes(build_id=target, limit=limit),
            generations=self.list_generations(build_id=target, limit=limit),
            traces=self.list_traces(build_id=target, limit=limit),
            maintenance_signals=self.list_maintenance_signals(build_id=target, limit=limit),
            repair_items=self.list_repair_items(build_id=target, limit=limit),
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS project_network_builds (
                    build_id TEXT PRIMARY KEY,
                    build_kind TEXT NOT NULL DEFAULT '',
                    build_mode TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    contract_json TEXT NOT NULL DEFAULT '{}',
                    active_generation_id TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'project_network_system.build_record'
                );

                CREATE TABLE IF NOT EXISTS project_network_work_products (
                    work_product_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    graph_run_id TEXT NOT NULL DEFAULT '',
                    node_id TEXT NOT NULL DEFAULT '',
                    shard_id TEXT NOT NULL DEFAULT '',
                    layer_id TEXT NOT NULL DEFAULT '',
                    product_kind TEXT NOT NULL DEFAULT '',
                    contract_id TEXT NOT NULL DEFAULT '',
                    payload_ref TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    anchor_refs_json TEXT NOT NULL DEFAULT '[]',
                    coverage_json TEXT NOT NULL DEFAULT '{}',
                    confidence TEXT NOT NULL DEFAULT 'derived',
                    status TEXT NOT NULL DEFAULT 'candidate',
                    stable_ref TEXT NOT NULL DEFAULT '',
                    generation INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'project_network_system.graph_build_work_product'
                );

                CREATE TABLE IF NOT EXISTS project_network_channel_states (
                    channel_id TEXT NOT NULL,
                    build_id TEXT NOT NULL,
                    layer_id TEXT NOT NULL DEFAULT '',
                    reducer_policy TEXT NOT NULL DEFAULT '',
                    accepted_product_kinds_json TEXT NOT NULL DEFAULT '[]',
                    product_ids_json TEXT NOT NULL DEFAULT '[]',
                    conflict_product_ids_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'project_network_system.channel_state',
                    PRIMARY KEY(build_id, channel_id)
                );

                CREATE TABLE IF NOT EXISTS project_network_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    evidence_kind TEXT NOT NULL DEFAULT '',
                    source_ref TEXT NOT NULL DEFAULT '',
                    stable_ref TEXT NOT NULL DEFAULT '',
                    layer_id TEXT NOT NULL DEFAULT '',
                    shard_id TEXT NOT NULL DEFAULT '',
                    graph_run_id TEXT NOT NULL DEFAULT '',
                    node_id TEXT NOT NULL DEFAULT '',
                    payload_ref TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    anchor_refs_json TEXT NOT NULL DEFAULT '[]',
                    content_hash TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'project_network_system.evidence_record'
                );

                CREATE TABLE IF NOT EXISTS project_network_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    work_product_id TEXT NOT NULL,
                    product_kind TEXT NOT NULL DEFAULT '',
                    layer_id TEXT NOT NULL DEFAULT '',
                    stable_ref TEXT NOT NULL DEFAULT '',
                    shard_id TEXT NOT NULL DEFAULT '',
                    graph_run_id TEXT NOT NULL DEFAULT '',
                    node_id TEXT NOT NULL DEFAULT '',
                    payload_ref TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    anchor_refs_json TEXT NOT NULL DEFAULT '[]',
                    confidence TEXT NOT NULL DEFAULT 'derived',
                    status TEXT NOT NULL DEFAULT 'candidate',
                    generation INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'project_network_system.candidate_record'
                );

                CREATE TABLE IF NOT EXISTS project_network_layer_indexes (
                    layer_index_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    layer_id TEXT NOT NULL DEFAULT '',
                    generation INTEGER NOT NULL DEFAULT 0,
                    source_work_product_ids_json TEXT NOT NULL DEFAULT '[]',
                    coverage_json TEXT NOT NULL DEFAULT '{}',
                    conflict_work_product_ids_json TEXT NOT NULL DEFAULT '[]',
                    payload_ref TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'candidate',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'project_network_system.layer_index_record'
                );

                CREATE TABLE IF NOT EXISTS project_network_generations (
                    generation_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    generation_ref TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'candidate',
                    source_snapshot_ref TEXT NOT NULL DEFAULT '',
                    layer_index_refs_json TEXT NOT NULL DEFAULT '[]',
                    work_product_refs_json TEXT NOT NULL DEFAULT '[]',
                    validation_refs_json TEXT NOT NULL DEFAULT '[]',
                    payload_ref TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    published_at TEXT NOT NULL DEFAULT '',
                    supersedes_generation_id TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'project_network_system.generation_record'
                );

                CREATE TABLE IF NOT EXISTS project_network_traces (
                    trace_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    graph_run_id TEXT NOT NULL DEFAULT '',
                    node_id TEXT NOT NULL DEFAULT '',
                    shard_id TEXT NOT NULL DEFAULT '',
                    work_order_id TEXT NOT NULL DEFAULT '',
                    result_id TEXT NOT NULL DEFAULT '',
                    event_kind TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    work_product_ids_json TEXT NOT NULL DEFAULT '[]',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'project_network_system.trace_record'
                );

                CREATE TABLE IF NOT EXISTS project_network_maintenance_signals (
                    signal_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    signal_source TEXT NOT NULL DEFAULT '',
                    signal_code TEXT NOT NULL DEFAULT '',
                    severity TEXT NOT NULL DEFAULT 'info',
                    subject_ref TEXT NOT NULL DEFAULT '',
                    stable_ref TEXT NOT NULL DEFAULT '',
                    edge_id TEXT NOT NULL DEFAULT '',
                    anchor_ref TEXT NOT NULL DEFAULT '',
                    scope_refs_json TEXT NOT NULL DEFAULT '[]',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    requested_layers_json TEXT NOT NULL DEFAULT '[]',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'queued',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'project_network_system.maintenance_signal_record'
                );

                CREATE TABLE IF NOT EXISTS project_network_repair_work_items (
                    repair_item_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    trigger_kind TEXT NOT NULL DEFAULT '',
                    trigger_ref TEXT NOT NULL DEFAULT '',
                    trigger_signal_id TEXT NOT NULL DEFAULT '',
                    repair_kind TEXT NOT NULL DEFAULT '',
                    repair_scope_kind TEXT NOT NULL DEFAULT '',
                    subject_ref TEXT NOT NULL DEFAULT '',
                    stable_ref TEXT NOT NULL DEFAULT '',
                    scope_refs_json TEXT NOT NULL DEFAULT '[]',
                    requested_layers_json TEXT NOT NULL DEFAULT '[]',
                    reason_codes_json TEXT NOT NULL DEFAULT '[]',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    priority INTEGER NOT NULL DEFAULT 50,
                    status TEXT NOT NULL DEFAULT 'queued',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'project_network_system.repair_work_item_record'
                );

                CREATE TABLE IF NOT EXISTS project_network_directory_frames (
                    frame_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    root_frame_id TEXT NOT NULL DEFAULT '',
                    parent_frame_id TEXT NOT NULL DEFAULT '',
                    depth INTEGER NOT NULL DEFAULT 0,
                    skeleton_build_id TEXT NOT NULL DEFAULT '',
                    skeleton_generation INTEGER NOT NULL DEFAULT 0,
                    folder_node_id TEXT NOT NULL DEFAULT '',
                    folder_stable_ref TEXT NOT NULL DEFAULT '',
                    folder_path TEXT NOT NULL DEFAULT '',
                    manifest_ref TEXT NOT NULL DEFAULT '',
                    child_frame_ids_json TEXT NOT NULL DEFAULT '[]',
                    direct_file_refs_json TEXT NOT NULL DEFAULT '[]',
                    child_return_refs_json TEXT NOT NULL DEFAULT '[]',
                    aggregate_work_product_ref TEXT NOT NULL DEFAULT '',
                    graph_id TEXT NOT NULL DEFAULT '',
                    graph_run_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'planned',
                    budget_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'project_network_system.directory_render_frame'
                );

                CREATE TABLE IF NOT EXISTS project_network_directory_manifests (
                    manifest_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    frame_id TEXT NOT NULL,
                    skeleton_build_id TEXT NOT NULL DEFAULT '',
                    skeleton_generation INTEGER NOT NULL DEFAULT 0,
                    folder_node_id TEXT NOT NULL DEFAULT '',
                    folder_stable_ref TEXT NOT NULL DEFAULT '',
                    folder_path TEXT NOT NULL DEFAULT '',
                    child_folder_node_ids_json TEXT NOT NULL DEFAULT '[]',
                    child_folder_refs_json TEXT NOT NULL DEFAULT '[]',
                    direct_file_node_ids_json TEXT NOT NULL DEFAULT '[]',
                    direct_file_refs_json TEXT NOT NULL DEFAULT '[]',
                    skipped_refs_json TEXT NOT NULL DEFAULT '[]',
                    child_folder_nodes_json TEXT NOT NULL DEFAULT '[]',
                    direct_file_nodes_json TEXT NOT NULL DEFAULT '[]',
                    content_hash TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'manifest_ready',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'project_network_system.directory_manifest_product'
                );

                CREATE TABLE IF NOT EXISTS project_network_directory_child_returns (
                    return_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    parent_frame_id TEXT NOT NULL DEFAULT '',
                    child_frame_id TEXT NOT NULL DEFAULT '',
                    child_folder_ref TEXT NOT NULL DEFAULT '',
                    child_folder_node_id TEXT NOT NULL DEFAULT '',
                    child_summary_product_ref TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'candidate',
                    payload_ref TEXT NOT NULL DEFAULT '',
                    coverage_json TEXT NOT NULL DEFAULT '{}',
                    blockers_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'project_network_system.directory_child_return'
                );

                CREATE INDEX IF NOT EXISTS idx_project_network_work_products_build_layer
                    ON project_network_work_products(build_id, layer_id, product_kind, status);
                CREATE INDEX IF NOT EXISTS idx_project_network_work_products_graph
                    ON project_network_work_products(graph_run_id, node_id, shard_id);
                CREATE INDEX IF NOT EXISTS idx_project_network_candidates_build_layer
                    ON project_network_candidates(build_id, layer_id, product_kind, status);
                CREATE INDEX IF NOT EXISTS idx_project_network_candidates_stable
                    ON project_network_candidates(build_id, stable_ref, status, product_kind);
                CREATE INDEX IF NOT EXISTS idx_project_network_layer_indexes_build_layer
                    ON project_network_layer_indexes(build_id, layer_id, generation);
                CREATE INDEX IF NOT EXISTS idx_project_network_generations_build_status
                    ON project_network_generations(build_id, status, generation);
                CREATE INDEX IF NOT EXISTS idx_project_network_traces_build_graph
                    ON project_network_traces(build_id, graph_run_id, node_id);
                CREATE INDEX IF NOT EXISTS idx_project_network_maintenance_signals_build_status
                    ON project_network_maintenance_signals(build_id, status, signal_source, signal_code);
                CREATE INDEX IF NOT EXISTS idx_project_network_maintenance_signals_subject
                    ON project_network_maintenance_signals(build_id, stable_ref, subject_ref);
                CREATE INDEX IF NOT EXISTS idx_project_network_repair_items_build_status
                    ON project_network_repair_work_items(build_id, status, priority);
                CREATE INDEX IF NOT EXISTS idx_project_network_repair_items_subject
                    ON project_network_repair_work_items(build_id, stable_ref, subject_ref, trigger_signal_id);
                CREATE INDEX IF NOT EXISTS idx_project_network_directory_frames_build_parent
                    ON project_network_directory_frames(build_id, root_frame_id, parent_frame_id, status);
                CREATE INDEX IF NOT EXISTS idx_project_network_directory_frames_folder
                    ON project_network_directory_frames(build_id, skeleton_build_id, skeleton_generation, folder_stable_ref);
                CREATE INDEX IF NOT EXISTS idx_project_network_directory_manifests_frame
                    ON project_network_directory_manifests(build_id, frame_id, content_hash);
                CREATE INDEX IF NOT EXISTS idx_project_network_directory_child_returns_parent
                    ON project_network_directory_child_returns(build_id, parent_frame_id, status);
                """
            )
            _normalize_project_network_authorities(conn)


def stable_project_network_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part or "").strip() for part in parts)
    return f"{prefix}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:20]}"


def content_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _authority(value: Any, fallback: str) -> str:
    return str(value or fallback).strip() or fallback


def _normalize_project_network_authorities(conn: sqlite3.Connection) -> None:
    legacy_prefix = "task_system.project_network."
    current_prefix = "project_network_system."
    authority_tables = (
        "project_network_builds",
        "project_network_work_products",
        "project_network_channel_states",
        "project_network_evidence",
        "project_network_candidates",
        "project_network_layer_indexes",
        "project_network_generations",
        "project_network_traces",
        "project_network_maintenance_signals",
        "project_network_repair_work_items",
        "project_network_directory_frames",
        "project_network_directory_manifests",
        "project_network_directory_child_returns",
    )
    for table in authority_tables:
        conn.execute(
            f"""
            UPDATE {table}
            SET authority = ? || substr(authority, ?)
            WHERE authority LIKE ?
            """,
            (current_prefix, len(legacy_prefix) + 1, f"{legacy_prefix}%"),
        )


def _build_from_row(row: sqlite3.Row) -> ProjectNetworkBuildRecord:
    return ProjectNetworkBuildRecord(
        build_id=str(row["build_id"]),
        build_kind=str(row["build_kind"] or ""),
        build_mode=str(row["build_mode"] or ""),
        status=str(row["status"] or "draft"),  # type: ignore[arg-type]
        contract=_loads(row["contract_json"], {}),
        active_generation_id=str(row["active_generation_id"] or ""),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        metadata=_loads(row["metadata_json"], {}),
        authority=_authority(row["authority"], "project_network_system.build_record"),
    )


def _work_product_from_row(row: sqlite3.Row) -> GraphBuildWorkProductEnvelope:
    return GraphBuildWorkProductEnvelope(
        work_product_id=str(row["work_product_id"]),
        build_id=str(row["build_id"]),
        graph_run_id=str(row["graph_run_id"] or ""),
        node_id=str(row["node_id"] or ""),
        shard_id=str(row["shard_id"] or ""),
        layer_id=str(row["layer_id"] or ""),
        product_kind=str(row["product_kind"] or "layer_summary"),  # type: ignore[arg-type]
        contract_id=str(row["contract_id"] or ""),
        payload_ref=str(row["payload_ref"] or ""),
        payload=_loads(row["payload_json"], {}),
        evidence_refs=tuple(_strings(_loads(row["evidence_refs_json"], []))),
        anchor_refs=tuple(_strings(_loads(row["anchor_refs_json"], []))),
        coverage=_loads(row["coverage_json"], {}),
        confidence=str(row["confidence"] or "derived"),  # type: ignore[arg-type]
        status=str(row["status"] or "candidate"),  # type: ignore[arg-type]
        stable_ref=str(row["stable_ref"] or ""),
        generation=int(row["generation"] or 0),
        metadata=_loads(row["metadata_json"], {}),
        authority=_authority(row["authority"], "project_network_system.graph_build_work_product"),
    )


def _channel_state_from_row(row: sqlite3.Row) -> ProjectNetworkChannelState:
    return ProjectNetworkChannelState(
        channel_id=str(row["channel_id"]),
        build_id=str(row["build_id"]),
        layer_id=str(row["layer_id"] or ""),
        reducer_policy=str(row["reducer_policy"] or ""),
        accepted_product_kinds=tuple(_strings(_loads(row["accepted_product_kinds_json"], []))),
        product_ids=tuple(_strings(_loads(row["product_ids_json"], []))),
        conflict_product_ids=tuple(_strings(_loads(row["conflict_product_ids_json"], []))),
        updated_at=str(row["updated_at"] or ""),
        metadata=_loads(row["metadata_json"], {}),
        authority=_authority(row["authority"], "project_network_system.channel_state"),
    )


def _evidence_from_row(row: sqlite3.Row) -> ProjectNetworkEvidenceRecord:
    return ProjectNetworkEvidenceRecord(
        evidence_id=str(row["evidence_id"]),
        build_id=str(row["build_id"]),
        evidence_kind=str(row["evidence_kind"] or ""),
        source_ref=str(row["source_ref"] or ""),
        stable_ref=str(row["stable_ref"] or ""),
        layer_id=str(row["layer_id"] or ""),
        shard_id=str(row["shard_id"] or ""),
        graph_run_id=str(row["graph_run_id"] or ""),
        node_id=str(row["node_id"] or ""),
        payload_ref=str(row["payload_ref"] or ""),
        payload=_loads(row["payload_json"], {}),
        anchor_refs=tuple(_strings(_loads(row["anchor_refs_json"], []))),
        content_hash=str(row["content_hash"] or ""),
        status=str(row["status"] or "active"),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        metadata=_loads(row["metadata_json"], {}),
        authority=_authority(row["authority"], "project_network_system.evidence_record"),
    )


def _candidate_from_row(row: sqlite3.Row) -> ProjectNetworkCandidateRecord:
    return ProjectNetworkCandidateRecord(
        candidate_id=str(row["candidate_id"]),
        build_id=str(row["build_id"]),
        work_product_id=str(row["work_product_id"] or ""),
        product_kind=str(row["product_kind"] or ""),
        layer_id=str(row["layer_id"] or ""),
        stable_ref=str(row["stable_ref"] or ""),
        shard_id=str(row["shard_id"] or ""),
        graph_run_id=str(row["graph_run_id"] or ""),
        node_id=str(row["node_id"] or ""),
        payload_ref=str(row["payload_ref"] or ""),
        payload=_loads(row["payload_json"], {}),
        evidence_refs=tuple(_strings(_loads(row["evidence_refs_json"], []))),
        anchor_refs=tuple(_strings(_loads(row["anchor_refs_json"], []))),
        confidence=str(row["confidence"] or "derived"),
        status=str(row["status"] or "candidate"),
        generation=int(row["generation"] or 0),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        metadata=_loads(row["metadata_json"], {}),
        authority=_authority(row["authority"], "project_network_system.candidate_record"),
    )


def _layer_index_from_row(row: sqlite3.Row) -> ProjectNetworkLayerIndexRecord:
    return ProjectNetworkLayerIndexRecord(
        layer_index_id=str(row["layer_index_id"]),
        build_id=str(row["build_id"]),
        layer_id=str(row["layer_id"] or ""),
        generation=int(row["generation"] or 0),
        source_work_product_ids=tuple(_strings(_loads(row["source_work_product_ids_json"], []))),
        coverage=_loads(row["coverage_json"], {}),
        conflict_work_product_ids=tuple(_strings(_loads(row["conflict_work_product_ids_json"], []))),
        payload_ref=str(row["payload_ref"] or ""),
        payload=_loads(row["payload_json"], {}),
        status=str(row["status"] or "candidate"),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        metadata=_loads(row["metadata_json"], {}),
        authority=_authority(row["authority"], "project_network_system.layer_index_record"),
    )


def _generation_from_row(row: sqlite3.Row) -> ProjectNetworkGenerationRecord:
    return ProjectNetworkGenerationRecord(
        generation_id=str(row["generation_id"]),
        build_id=str(row["build_id"]),
        generation=int(row["generation"] or 0),
        generation_ref=str(row["generation_ref"] or ""),
        status=str(row["status"] or "candidate"),  # type: ignore[arg-type]
        source_snapshot_ref=str(row["source_snapshot_ref"] or ""),
        layer_index_refs=tuple(_strings(_loads(row["layer_index_refs_json"], []))),
        work_product_refs=tuple(_strings(_loads(row["work_product_refs_json"], []))),
        validation_refs=tuple(_strings(_loads(row["validation_refs_json"], []))),
        payload_ref=str(row["payload_ref"] or ""),
        payload=_loads(row["payload_json"], {}),
        published_at=str(row["published_at"] or ""),
        supersedes_generation_id=str(row["supersedes_generation_id"] or ""),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        metadata=_loads(row["metadata_json"], {}),
        authority=_authority(row["authority"], "project_network_system.generation_record"),
    )


def _trace_from_row(row: sqlite3.Row) -> ProjectNetworkTraceRecord:
    return ProjectNetworkTraceRecord(
        trace_id=str(row["trace_id"]),
        build_id=str(row["build_id"]),
        graph_run_id=str(row["graph_run_id"] or ""),
        node_id=str(row["node_id"] or ""),
        shard_id=str(row["shard_id"] or ""),
        work_order_id=str(row["work_order_id"] or ""),
        result_id=str(row["result_id"] or ""),
        event_kind=str(row["event_kind"] or ""),
        status=str(row["status"] or ""),
        work_product_ids=tuple(_strings(_loads(row["work_product_ids_json"], []))),
        payload=_loads(row["payload_json"], {}),
        created_at=str(row["created_at"] or ""),
        authority=_authority(row["authority"], "project_network_system.trace_record"),
    )


def _maintenance_signal_from_row(row: sqlite3.Row) -> ProjectNetworkMaintenanceSignalRecord:
    return ProjectNetworkMaintenanceSignalRecord(
        signal_id=str(row["signal_id"]),
        build_id=str(row["build_id"]),
        signal_source=str(row["signal_source"] or ""),
        signal_code=str(row["signal_code"] or ""),
        severity=str(row["severity"] or "info"),
        subject_ref=str(row["subject_ref"] or ""),
        stable_ref=str(row["stable_ref"] or ""),
        edge_id=str(row["edge_id"] or ""),
        anchor_ref=str(row["anchor_ref"] or ""),
        scope_refs=tuple(_strings(_loads(row["scope_refs_json"], []))),
        evidence_refs=tuple(_strings(_loads(row["evidence_refs_json"], []))),
        requested_layers=tuple(_strings(_loads(row["requested_layers_json"], []))),
        payload=_loads(row["payload_json"], {}),
        status=str(row["status"] or "queued"),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        metadata=_loads(row["metadata_json"], {}),
        authority=_authority(row["authority"], "project_network_system.maintenance_signal_record"),
    )


def _repair_item_from_row(row: sqlite3.Row) -> ProjectNetworkRepairWorkItemRecord:
    return ProjectNetworkRepairWorkItemRecord(
        repair_item_id=str(row["repair_item_id"]),
        build_id=str(row["build_id"]),
        trigger_kind=str(row["trigger_kind"] or ""),
        trigger_ref=str(row["trigger_ref"] or ""),
        trigger_signal_id=str(row["trigger_signal_id"] or ""),
        repair_kind=str(row["repair_kind"] or ""),
        repair_scope_kind=str(row["repair_scope_kind"] or ""),
        subject_ref=str(row["subject_ref"] or ""),
        stable_ref=str(row["stable_ref"] or ""),
        scope_refs=tuple(_strings(_loads(row["scope_refs_json"], []))),
        requested_layers=tuple(_strings(_loads(row["requested_layers_json"], []))),
        reason_codes=tuple(_strings(_loads(row["reason_codes_json"], []))),
        evidence_refs=tuple(_strings(_loads(row["evidence_refs_json"], []))),
        payload=_loads(row["payload_json"], {}),
        priority=int(row["priority"] or 0),
        status=str(row["status"] or "queued"),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        metadata=_loads(row["metadata_json"], {}),
        authority=_authority(row["authority"], "project_network_system.repair_work_item_record"),
    )


def _directory_frame_from_row(row: sqlite3.Row) -> DirectoryRenderFrame:
    return DirectoryRenderFrame(
        frame_id=str(row["frame_id"]),
        build_id=str(row["build_id"]),
        root_frame_id=str(row["root_frame_id"] or ""),
        parent_frame_id=str(row["parent_frame_id"] or ""),
        depth=int(row["depth"] or 0),
        skeleton_build_id=str(row["skeleton_build_id"] or ""),
        skeleton_generation=int(row["skeleton_generation"] or 0),
        folder_node_id=str(row["folder_node_id"] or ""),
        folder_stable_ref=str(row["folder_stable_ref"] or ""),
        folder_path=str(row["folder_path"] or ""),
        manifest_ref=str(row["manifest_ref"] or ""),
        child_frame_ids=tuple(_strings(_loads(row["child_frame_ids_json"], []))),
        direct_file_refs=tuple(_strings(_loads(row["direct_file_refs_json"], []))),
        child_return_refs=tuple(_strings(_loads(row["child_return_refs_json"], []))),
        aggregate_work_product_ref=str(row["aggregate_work_product_ref"] or ""),
        graph_id=str(row["graph_id"] or ""),
        graph_run_id=str(row["graph_run_id"] or ""),
        status=str(row["status"] or "planned"),  # type: ignore[arg-type]
        budget=DirectoryRenderBudget.from_dict(_loads(row["budget_json"], {})),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        metadata=_loads(row["metadata_json"], {}),
        authority=_authority(row["authority"], "project_network_system.directory_render_frame"),
    )


def _directory_manifest_from_row(row: sqlite3.Row) -> DirectoryManifestProduct:
    return DirectoryManifestProduct(
        manifest_id=str(row["manifest_id"]),
        build_id=str(row["build_id"]),
        frame_id=str(row["frame_id"] or ""),
        skeleton_build_id=str(row["skeleton_build_id"] or ""),
        skeleton_generation=int(row["skeleton_generation"] or 0),
        folder_node_id=str(row["folder_node_id"] or ""),
        folder_stable_ref=str(row["folder_stable_ref"] or ""),
        folder_path=str(row["folder_path"] or ""),
        child_folder_node_ids=tuple(_strings(_loads(row["child_folder_node_ids_json"], []))),
        child_folder_refs=tuple(_strings(_loads(row["child_folder_refs_json"], []))),
        direct_file_node_ids=tuple(_strings(_loads(row["direct_file_node_ids_json"], []))),
        direct_file_refs=tuple(_strings(_loads(row["direct_file_refs_json"], []))),
        skipped_refs=tuple(_strings(_loads(row["skipped_refs_json"], []))),
        child_folder_nodes=tuple(dict(item) for item in list(_loads(row["child_folder_nodes_json"], [])) if isinstance(item, dict)),
        direct_file_nodes=tuple(dict(item) for item in list(_loads(row["direct_file_nodes_json"], [])) if isinstance(item, dict)),
        content_hash=str(row["content_hash"] or ""),
        status=str(row["status"] or "manifest_ready"),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        metadata=_loads(row["metadata_json"], {}),
        authority=_authority(row["authority"], "project_network_system.directory_manifest_product"),
    )


def _directory_child_return_from_row(row: sqlite3.Row) -> DirectoryChildReturnEnvelope:
    return DirectoryChildReturnEnvelope(
        return_id=str(row["return_id"]),
        build_id=str(row["build_id"]),
        parent_frame_id=str(row["parent_frame_id"] or ""),
        child_frame_id=str(row["child_frame_id"] or ""),
        child_folder_ref=str(row["child_folder_ref"] or ""),
        child_folder_node_id=str(row["child_folder_node_id"] or ""),
        child_summary_product_ref=str(row["child_summary_product_ref"] or ""),
        status=str(row["status"] or "candidate"),
        payload_ref=str(row["payload_ref"] or ""),
        coverage=_loads(row["coverage_json"], {}),
        blockers=tuple(_strings(_loads(row["blockers_json"], []))),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        metadata=_loads(row["metadata_json"], {}),
        authority=_authority(row["authority"], "project_network_system.directory_child_return"),
    )


def _filters(*, build_id: str = "", layer_id: str = "") -> tuple[list[str], list[Any]]:
    filters: list[str] = []
    params: list[Any] = []
    if build_id:
        filters.append("build_id = ?")
        params.append(build_id)
    if layer_id:
        filters.append("layer_id = ?")
        params.append(layer_id)
    return filters, params


def _existing_created_at(conn: sqlite3.Connection, table: str, key: str, value: str) -> str:
    try:
        row = conn.execute(f"SELECT created_at FROM {table} WHERE {key} = ?", (value,)).fetchone()
    except sqlite3.Error:
        return ""
    return str(row["created_at"] or "") if row is not None else ""


def _limit(value: int) -> int:
    return max(1, min(int(value or 2000), 10000))


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _loads(value: Any, default: Any) -> Any:
    try:
        loaded = json.loads(str(value or ""))
    except (TypeError, json.JSONDecodeError):
        return default
    return loaded if isinstance(loaded, type(default)) else default


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(item).strip() for item in list(value or []) if str(item).strip()]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


