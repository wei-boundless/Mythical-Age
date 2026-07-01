from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.project_layout import ProjectLayout

from .change_models import GitChangeSetRecord
from .control_models import (
    ProjectNetworkControlDecisionRecord,
    ProjectNetworkFrontierItemRecord,
    ProjectNetworkTraversalSessionRecord,
    ProjectNetworkVisitedRefRecord,
)
from .semantic_models import (
    NetworkMaintenanceRunRecord,
    SemanticOverlayRecord,
    SemanticRepairDecisionRecord,
    SemanticRepairWorkItemRecord,
)
from .skeleton_models import (
    SkeletonEdgeRecord,
    SkeletonFactRecord,
    SkeletonGenerationRecord,
    SkeletonNodeRecord,
)


class ProjectStructureRepository:
    authority = "file_management.project_structure.repository"

    def __init__(self, base_dir: str | Path) -> None:
        layout = ProjectLayout.from_backend_dir(base_dir)
        self.root = layout.storage_root / "file_management" / "project_structure"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "project_structure.sqlite"
        self._ensure_schema()

    def upsert_skeleton_facts(self, facts: tuple[SkeletonFactRecord, ...] | list[SkeletonFactRecord]) -> tuple[SkeletonFactRecord, ...]:
        now = utc_now_iso()
        with self._connect() as conn:
            for fact in facts:
                stored = replace(fact, created_at=fact.created_at or now)
                conn.execute(
                    """
                    INSERT INTO project_structure_skeleton_facts (
                        fact_id, build_id, generation, source_kind, subject_ref, predicate,
                        object_ref, object_literal, qualifiers_json, evidence_refs_json,
                        anchor_refs_json, source_snapshot_ref, extractor_id, extractor_version,
                        content_hash, confidence, created_at, authority
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(fact_id) DO UPDATE SET
                        build_id = excluded.build_id,
                        generation = excluded.generation,
                        source_kind = excluded.source_kind,
                        subject_ref = excluded.subject_ref,
                        predicate = excluded.predicate,
                        object_ref = excluded.object_ref,
                        object_literal = excluded.object_literal,
                        qualifiers_json = excluded.qualifiers_json,
                        evidence_refs_json = excluded.evidence_refs_json,
                        anchor_refs_json = excluded.anchor_refs_json,
                        source_snapshot_ref = excluded.source_snapshot_ref,
                        extractor_id = excluded.extractor_id,
                        extractor_version = excluded.extractor_version,
                        content_hash = excluded.content_hash,
                        confidence = excluded.confidence,
                        authority = excluded.authority
                    """,
                    (
                        stored.fact_id,
                        stored.build_id,
                        int(stored.generation or 0),
                        stored.source_kind,
                        stored.subject_ref,
                        stored.predicate,
                        stored.object_ref,
                        stored.object_literal,
                        _json(stored.qualifiers),
                        _json(list(stored.evidence_refs)),
                        _json(list(stored.anchor_refs)),
                        stored.source_snapshot_ref,
                        stored.extractor_id,
                        stored.extractor_version,
                        stored.content_hash,
                        stored.confidence,
                        stored.created_at,
                        stored.authority,
                    ),
                )
        return tuple(facts)

    def list_skeleton_facts(
        self,
        *,
        build_id: str = "",
        generation: int | None = None,
        source_kind: str = "",
        subject_ref: str = "",
        limit: int = 5000,
    ) -> tuple[SkeletonFactRecord, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if build_id:
            filters.append("build_id = ?")
            params.append(build_id)
        if generation is not None:
            filters.append("generation = ?")
            params.append(int(generation or 0))
        if source_kind:
            filters.append("source_kind = ?")
            params.append(source_kind)
        if subject_ref:
            filters.append("subject_ref = ?")
            params.append(subject_ref)
        sql = "SELECT * FROM project_structure_skeleton_facts"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY source_kind ASC, subject_ref ASC, predicate ASC LIMIT ?"
        params.append(_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_skeleton_fact_from_row(row) for row in rows)

    def get_skeleton_fact(self, fact_id: str) -> SkeletonFactRecord | None:
        target = str(fact_id or "").strip()
        if not target:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM project_structure_skeleton_facts WHERE fact_id = ?", (target,)).fetchone()
        return _skeleton_fact_from_row(row) if row is not None else None

    def upsert_skeleton_nodes(self, nodes: tuple[SkeletonNodeRecord, ...] | list[SkeletonNodeRecord]) -> tuple[SkeletonNodeRecord, ...]:
        now = utc_now_iso()
        with self._connect() as conn:
            for node in nodes:
                created_at = _existing_created_at(conn, "project_structure_skeleton_nodes", "node_id", node.node_id) or now
                stored = replace(node, created_at=node.created_at or created_at, updated_at=now)
                conn.execute(
                    """
                    INSERT INTO project_structure_skeleton_nodes (
                        node_id, build_id, generation, node_kind, stable_ref, display_name,
                        path, layer_kind, hierarchy_path, parent_node_ids_json,
                        ancestor_node_ids_json, anchor_ref, file_hash, extractor, confidence,
                        status, payload_json, created_at, updated_at, authority
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(node_id) DO UPDATE SET
                        build_id = excluded.build_id,
                        generation = excluded.generation,
                        node_kind = excluded.node_kind,
                        stable_ref = excluded.stable_ref,
                        display_name = excluded.display_name,
                        path = excluded.path,
                        layer_kind = excluded.layer_kind,
                        hierarchy_path = excluded.hierarchy_path,
                        parent_node_ids_json = excluded.parent_node_ids_json,
                        ancestor_node_ids_json = excluded.ancestor_node_ids_json,
                        anchor_ref = excluded.anchor_ref,
                        file_hash = excluded.file_hash,
                        extractor = excluded.extractor,
                        confidence = excluded.confidence,
                        status = excluded.status,
                        payload_json = excluded.payload_json,
                        updated_at = excluded.updated_at,
                        authority = excluded.authority
                    """,
                    (
                        stored.node_id,
                        stored.build_id,
                        int(stored.generation or 0),
                        stored.node_kind,
                        stored.stable_ref,
                        stored.display_name,
                        stored.path,
                        stored.layer_kind,
                        stored.hierarchy_path,
                        _json(list(stored.parent_node_ids)),
                        _json(list(stored.ancestor_node_ids)),
                        stored.anchor_ref,
                        stored.file_hash,
                        stored.extractor,
                        stored.confidence,
                        stored.status,
                        _json(stored.payload),
                        stored.created_at,
                        stored.updated_at,
                        stored.authority,
                    ),
                )
        return tuple(nodes)

    def get_skeleton_node(self, node_id: str) -> SkeletonNodeRecord | None:
        target = str(node_id or "").strip()
        if not target:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM project_structure_skeleton_nodes WHERE node_id = ?", (target,)).fetchone()
        return _skeleton_node_from_row(row) if row is not None else None

    def find_skeleton_node(self, *, build_id: str, stable_ref: str, generation: int | None = None) -> SkeletonNodeRecord | None:
        filters = ["build_id = ?", "stable_ref = ?"]
        params: list[Any] = [build_id, stable_ref]
        if generation is not None:
            filters.append("generation = ?")
            params.append(int(generation or 0))
        sql = "SELECT * FROM project_structure_skeleton_nodes WHERE " + " AND ".join(filters)
        sql += " ORDER BY generation DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(sql, tuple(params)).fetchone()
        return _skeleton_node_from_row(row) if row is not None else None

    def list_skeleton_nodes(
        self,
        *,
        build_id: str = "",
        generation: int | None = None,
        node_kind: str = "",
        path: str = "",
        status: str = "",
        limit: int = 5000,
    ) -> tuple[SkeletonNodeRecord, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if build_id:
            filters.append("build_id = ?")
            params.append(build_id)
        if generation is not None:
            filters.append("generation = ?")
            params.append(int(generation or 0))
        if node_kind:
            filters.append("node_kind = ?")
            params.append(node_kind)
        if path:
            filters.append("path = ?")
            params.append(path)
        if status:
            filters.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM project_structure_skeleton_nodes"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY hierarchy_path ASC, node_kind ASC, stable_ref ASC LIMIT ?"
        params.append(_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_skeleton_node_from_row(row) for row in rows)

    def upsert_skeleton_edges(self, edges: tuple[SkeletonEdgeRecord, ...] | list[SkeletonEdgeRecord]) -> tuple[SkeletonEdgeRecord, ...]:
        now = utc_now_iso()
        with self._connect() as conn:
            for edge in edges:
                created_at = _existing_created_at(conn, "project_structure_skeleton_edges", "edge_id", edge.edge_id) or now
                stored = replace(edge, created_at=edge.created_at or created_at, updated_at=now)
                conn.execute(
                    """
                    INSERT INTO project_structure_skeleton_edges (
                        edge_id, build_id, generation, edge_kind, src_node_id, dst_node_id,
                        dst_candidate_ref, src_anchor_ref, dst_anchor_ref, evidence_refs_json,
                        source_fact_ids_json, extractor, confidence, resolution_status,
                        freshness, payload_json, created_at, updated_at, authority
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(edge_id) DO UPDATE SET
                        build_id = excluded.build_id,
                        generation = excluded.generation,
                        edge_kind = excluded.edge_kind,
                        src_node_id = excluded.src_node_id,
                        dst_node_id = excluded.dst_node_id,
                        dst_candidate_ref = excluded.dst_candidate_ref,
                        src_anchor_ref = excluded.src_anchor_ref,
                        dst_anchor_ref = excluded.dst_anchor_ref,
                        evidence_refs_json = excluded.evidence_refs_json,
                        source_fact_ids_json = excluded.source_fact_ids_json,
                        extractor = excluded.extractor,
                        confidence = excluded.confidence,
                        resolution_status = excluded.resolution_status,
                        freshness = excluded.freshness,
                        payload_json = excluded.payload_json,
                        updated_at = excluded.updated_at,
                        authority = excluded.authority
                    """,
                    (
                        stored.edge_id,
                        stored.build_id,
                        int(stored.generation or 0),
                        stored.edge_kind,
                        stored.src_node_id,
                        stored.dst_node_id,
                        stored.dst_candidate_ref,
                        stored.src_anchor_ref,
                        stored.dst_anchor_ref,
                        _json(list(stored.evidence_refs)),
                        _json(list(stored.source_fact_ids)),
                        stored.extractor,
                        stored.confidence,
                        stored.resolution_status,
                        stored.freshness,
                        _json(stored.payload),
                        stored.created_at,
                        stored.updated_at,
                        stored.authority,
                    ),
                )
        return tuple(edges)

    def get_skeleton_edge(self, edge_id: str) -> SkeletonEdgeRecord | None:
        target = str(edge_id or "").strip()
        if not target:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM project_structure_skeleton_edges WHERE edge_id = ?", (target,)).fetchone()
        return _skeleton_edge_from_row(row) if row is not None else None

    def list_skeleton_edges(
        self,
        *,
        build_id: str = "",
        generation: int | None = None,
        edge_kind: str = "",
        src_node_id: str = "",
        dst_node_id: str = "",
        freshness: str = "",
        limit: int = 5000,
    ) -> tuple[SkeletonEdgeRecord, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if build_id:
            filters.append("build_id = ?")
            params.append(build_id)
        if generation is not None:
            filters.append("generation = ?")
            params.append(int(generation or 0))
        if edge_kind:
            filters.append("edge_kind = ?")
            params.append(edge_kind)
        if src_node_id:
            filters.append("src_node_id = ?")
            params.append(src_node_id)
        if dst_node_id:
            filters.append("dst_node_id = ?")
            params.append(dst_node_id)
        if freshness:
            filters.append("freshness = ?")
            params.append(freshness)
        sql = "SELECT * FROM project_structure_skeleton_edges"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY edge_kind ASC, src_node_id ASC, dst_node_id ASC LIMIT ?"
        params.append(_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_skeleton_edge_from_row(row) for row in rows)

    def upsert_skeleton_generation(self, record: SkeletonGenerationRecord) -> SkeletonGenerationRecord:
        now = utc_now_iso()
        stored = replace(record, created_at=record.created_at or now, updated_at=now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_structure_skeleton_generations (
                    skeleton_generation_id, build_id, generation, status, source_snapshot_ref,
                    fact_count, node_count, edge_count, stale_count, payload_json,
                    created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(skeleton_generation_id) DO UPDATE SET
                    build_id = excluded.build_id,
                    generation = excluded.generation,
                    status = excluded.status,
                    source_snapshot_ref = excluded.source_snapshot_ref,
                    fact_count = excluded.fact_count,
                    node_count = excluded.node_count,
                    edge_count = excluded.edge_count,
                    stale_count = excluded.stale_count,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.skeleton_generation_id,
                    stored.build_id,
                    int(stored.generation or 0),
                    stored.status,
                    stored.source_snapshot_ref,
                    int(stored.fact_count or 0),
                    int(stored.node_count or 0),
                    int(stored.edge_count or 0),
                    int(stored.stale_count or 0),
                    _json(stored.payload),
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def get_skeleton_generation(self, skeleton_generation_id: str) -> SkeletonGenerationRecord | None:
        target = str(skeleton_generation_id or "").strip()
        if not target:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM project_structure_skeleton_generations WHERE skeleton_generation_id = ?", (target,)).fetchone()
        return _skeleton_generation_from_row(row) if row is not None else None

    def list_skeleton_generations(self, *, build_id: str = "", status: str = "", limit: int = 2000) -> tuple[SkeletonGenerationRecord, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if build_id:
            filters.append("build_id = ?")
            params.append(build_id)
        if status:
            filters.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM project_structure_skeleton_generations"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY generation DESC, updated_at DESC LIMIT ?"
        params.append(_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_skeleton_generation_from_row(row) for row in rows)

    def upsert_git_change_set(self, record: GitChangeSetRecord) -> GitChangeSetRecord:
        now = utc_now_iso()
        stored = replace(record, created_at=record.created_at or now, updated_at=now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_structure_git_change_sets (
                    change_set_id, build_id, base_ref, head_ref, change_mode,
                    changed_files_json, renamed_files_json, deleted_files_json, added_files_json,
                    diff_stats_json, touched_skeleton_node_ids_json, touched_skeleton_edge_ids_json,
                    semantic_refs_to_mark_stale_json, status, created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(change_set_id) DO UPDATE SET
                    build_id = excluded.build_id,
                    base_ref = excluded.base_ref,
                    head_ref = excluded.head_ref,
                    change_mode = excluded.change_mode,
                    changed_files_json = excluded.changed_files_json,
                    renamed_files_json = excluded.renamed_files_json,
                    deleted_files_json = excluded.deleted_files_json,
                    added_files_json = excluded.added_files_json,
                    diff_stats_json = excluded.diff_stats_json,
                    touched_skeleton_node_ids_json = excluded.touched_skeleton_node_ids_json,
                    touched_skeleton_edge_ids_json = excluded.touched_skeleton_edge_ids_json,
                    semantic_refs_to_mark_stale_json = excluded.semantic_refs_to_mark_stale_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.change_set_id,
                    stored.build_id,
                    stored.base_ref,
                    stored.head_ref,
                    stored.change_mode,
                    _json(list(stored.changed_files)),
                    _json([dict(item) for item in stored.renamed_files]),
                    _json(list(stored.deleted_files)),
                    _json(list(stored.added_files)),
                    _json(stored.diff_stats),
                    _json(list(stored.touched_skeleton_node_ids)),
                    _json(list(stored.touched_skeleton_edge_ids)),
                    _json(list(stored.semantic_refs_to_mark_stale)),
                    stored.status,
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def get_git_change_set(self, change_set_id: str) -> GitChangeSetRecord | None:
        target = str(change_set_id or "").strip()
        if not target:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM project_structure_git_change_sets WHERE change_set_id = ?", (target,)).fetchone()
        return _git_change_set_from_row(row) if row is not None else None

    def upsert_semantic_overlay(self, record: SemanticOverlayRecord) -> SemanticOverlayRecord:
        now = utc_now_iso()
        stored = replace(record, created_at=record.created_at or now, updated_at=now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_structure_semantic_overlays (
                    overlay_id, build_id, overlay_kind, stable_ref, skeleton_node_id,
                    skeleton_edge_id, anchor_ref, status, confidence, generation,
                    payload_json, evidence_refs_json, created_by_task_run_id,
                    created_by_agent_id, created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(overlay_id) DO UPDATE SET
                    build_id = excluded.build_id,
                    overlay_kind = excluded.overlay_kind,
                    stable_ref = excluded.stable_ref,
                    skeleton_node_id = excluded.skeleton_node_id,
                    skeleton_edge_id = excluded.skeleton_edge_id,
                    anchor_ref = excluded.anchor_ref,
                    status = excluded.status,
                    confidence = excluded.confidence,
                    generation = excluded.generation,
                    payload_json = excluded.payload_json,
                    evidence_refs_json = excluded.evidence_refs_json,
                    created_by_task_run_id = excluded.created_by_task_run_id,
                    created_by_agent_id = excluded.created_by_agent_id,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.overlay_id,
                    stored.build_id,
                    stored.overlay_kind,
                    stored.stable_ref,
                    stored.skeleton_node_id,
                    stored.skeleton_edge_id,
                    stored.anchor_ref,
                    stored.status,
                    stored.confidence,
                    int(stored.generation or 0),
                    _json(stored.payload),
                    _json(list(stored.evidence_refs)),
                    stored.created_by_task_run_id,
                    stored.created_by_agent_id,
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def list_semantic_overlays(
        self,
        *,
        build_id: str = "",
        stable_ref: str = "",
        skeleton_node_id: str = "",
        skeleton_edge_id: str = "",
        overlay_kind: str = "",
        status: str = "",
        limit: int = 2000,
    ) -> tuple[SemanticOverlayRecord, ...]:
        filters: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("build_id", build_id),
            ("stable_ref", stable_ref),
            ("skeleton_node_id", skeleton_node_id),
            ("skeleton_edge_id", skeleton_edge_id),
            ("overlay_kind", overlay_kind),
            ("status", status),
        ):
            if str(value or "").strip():
                filters.append(f"{column} = ?")
                params.append(str(value).strip())
        sql = "SELECT * FROM project_structure_semantic_overlays"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY generation DESC, updated_at DESC, overlay_id ASC LIMIT ?"
        params.append(_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_semantic_overlay_from_row(row) for row in rows)

    def upsert_traversal_session(self, record: ProjectNetworkTraversalSessionRecord) -> ProjectNetworkTraversalSessionRecord:
        now = utc_now_iso()
        created_at = record.created_at or now
        stored = replace(record, created_at=created_at, updated_at=now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_structure_traversal_sessions (
                    traversal_session_id, build_id, generation, goal,
                    anchor_node_ids_json, anchor_stable_refs_json, current_node_ids_json,
                    crawl_budget, status, created_by_task_run_id, created_by_agent_id,
                    metadata_json, created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(traversal_session_id) DO UPDATE SET
                    build_id = excluded.build_id,
                    generation = excluded.generation,
                    goal = excluded.goal,
                    anchor_node_ids_json = excluded.anchor_node_ids_json,
                    anchor_stable_refs_json = excluded.anchor_stable_refs_json,
                    current_node_ids_json = excluded.current_node_ids_json,
                    crawl_budget = excluded.crawl_budget,
                    status = excluded.status,
                    created_by_task_run_id = excluded.created_by_task_run_id,
                    created_by_agent_id = excluded.created_by_agent_id,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.traversal_session_id,
                    stored.build_id,
                    int(stored.generation or 0),
                    stored.goal,
                    _json(list(stored.anchor_node_ids)),
                    _json(list(stored.anchor_stable_refs)),
                    _json(list(stored.current_node_ids)),
                    int(stored.crawl_budget or 0),
                    stored.status,
                    stored.created_by_task_run_id,
                    stored.created_by_agent_id,
                    _json(stored.metadata),
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def get_traversal_session(self, traversal_session_id: str) -> ProjectNetworkTraversalSessionRecord | None:
        target = str(traversal_session_id or "").strip()
        if not target:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM project_structure_traversal_sessions WHERE traversal_session_id = ?", (target,)).fetchone()
        return _traversal_session_from_row(row) if row is not None else None

    def list_traversal_sessions(
        self,
        *,
        build_id: str = "",
        status: str = "",
        limit: int = 2000,
    ) -> tuple[ProjectNetworkTraversalSessionRecord, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if build_id:
            filters.append("build_id = ?")
            params.append(build_id)
        if status:
            filters.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM project_structure_traversal_sessions"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY updated_at DESC, traversal_session_id ASC LIMIT ?"
        params.append(_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_traversal_session_from_row(row) for row in rows)

    def upsert_frontier_items(
        self,
        records: tuple[ProjectNetworkFrontierItemRecord, ...] | list[ProjectNetworkFrontierItemRecord],
    ) -> tuple[ProjectNetworkFrontierItemRecord, ...]:
        now = utc_now_iso()
        stored_records: list[ProjectNetworkFrontierItemRecord] = []
        with self._connect() as conn:
            for record in records:
                created_at = _existing_created_at(conn, "project_structure_frontier_items", "frontier_item_id", record.frontier_item_id) or now
                stored = replace(record, created_at=record.created_at or created_at, updated_at=now)
                stored_records.append(stored)
                conn.execute(
                    """
                    INSERT INTO project_structure_frontier_items (
                        frontier_item_id, traversal_session_id, build_id, generation,
                        target_node_id, target_edge_id, stable_ref, source_node_id,
                        via_edge_id, relation_kind, priority, reason, status,
                        evidence_refs_json, semantic_overlay_ids_json, payload_json,
                        created_at, updated_at, authority
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(frontier_item_id) DO UPDATE SET
                        traversal_session_id = excluded.traversal_session_id,
                        build_id = excluded.build_id,
                        generation = excluded.generation,
                        target_node_id = excluded.target_node_id,
                        target_edge_id = excluded.target_edge_id,
                        stable_ref = excluded.stable_ref,
                        source_node_id = excluded.source_node_id,
                        via_edge_id = excluded.via_edge_id,
                        relation_kind = excluded.relation_kind,
                        priority = excluded.priority,
                        reason = excluded.reason,
                        status = excluded.status,
                        evidence_refs_json = excluded.evidence_refs_json,
                        semantic_overlay_ids_json = excluded.semantic_overlay_ids_json,
                        payload_json = excluded.payload_json,
                        updated_at = excluded.updated_at,
                        authority = excluded.authority
                    """,
                    (
                        stored.frontier_item_id,
                        stored.traversal_session_id,
                        stored.build_id,
                        int(stored.generation or 0),
                        stored.target_node_id,
                        stored.target_edge_id,
                        stored.stable_ref,
                        stored.source_node_id,
                        stored.via_edge_id,
                        stored.relation_kind,
                        int(stored.priority or 0),
                        stored.reason,
                        stored.status,
                        _json(list(stored.evidence_refs)),
                        _json(list(stored.semantic_overlay_ids)),
                        _json(stored.payload),
                        stored.created_at,
                        stored.updated_at,
                        stored.authority,
                    ),
                )
        return tuple(stored_records)

    def list_frontier_items(
        self,
        *,
        traversal_session_id: str,
        status: str = "",
        limit: int = 2000,
    ) -> tuple[ProjectNetworkFrontierItemRecord, ...]:
        filters = ["traversal_session_id = ?"]
        params: list[Any] = [str(traversal_session_id or "").strip()]
        if status:
            filters.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM project_structure_frontier_items WHERE " + " AND ".join(filters)
        sql += " ORDER BY priority DESC, updated_at DESC, frontier_item_id ASC LIMIT ?"
        params.append(_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_frontier_item_from_row(row) for row in rows)

    def upsert_visited_refs(
        self,
        records: tuple[ProjectNetworkVisitedRefRecord, ...] | list[ProjectNetworkVisitedRefRecord],
    ) -> tuple[ProjectNetworkVisitedRefRecord, ...]:
        now = utc_now_iso()
        stored_records: list[ProjectNetworkVisitedRefRecord] = []
        with self._connect() as conn:
            for record in records:
                stored = replace(record, created_at=record.created_at or now)
                stored_records.append(stored)
                conn.execute(
                    """
                    INSERT INTO project_structure_visited_refs (
                        visited_ref_id, traversal_session_id, build_id, generation,
                        ref_kind, ref_id, reason, payload_json, created_at, authority
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(visited_ref_id) DO UPDATE SET
                        traversal_session_id = excluded.traversal_session_id,
                        build_id = excluded.build_id,
                        generation = excluded.generation,
                        ref_kind = excluded.ref_kind,
                        ref_id = excluded.ref_id,
                        reason = excluded.reason,
                        payload_json = excluded.payload_json,
                        authority = excluded.authority
                    """,
                    (
                        stored.visited_ref_id,
                        stored.traversal_session_id,
                        stored.build_id,
                        int(stored.generation or 0),
                        stored.ref_kind,
                        stored.ref_id,
                        stored.reason,
                        _json(stored.payload),
                        stored.created_at,
                        stored.authority,
                    ),
                )
        return tuple(stored_records)

    def list_visited_refs(
        self,
        *,
        traversal_session_id: str,
        ref_kind: str = "",
        limit: int = 2000,
    ) -> tuple[ProjectNetworkVisitedRefRecord, ...]:
        filters = ["traversal_session_id = ?"]
        params: list[Any] = [str(traversal_session_id or "").strip()]
        if ref_kind:
            filters.append("ref_kind = ?")
            params.append(ref_kind)
        sql = "SELECT * FROM project_structure_visited_refs WHERE " + " AND ".join(filters)
        sql += " ORDER BY created_at DESC, visited_ref_id ASC LIMIT ?"
        params.append(_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_visited_ref_from_row(row) for row in rows)

    def upsert_control_decision(self, record: ProjectNetworkControlDecisionRecord) -> ProjectNetworkControlDecisionRecord:
        now = utc_now_iso()
        stored = replace(record, created_at=record.created_at or now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_structure_control_decisions (
                    decision_id, traversal_session_id, build_id, generation,
                    decision_kind, selected_frontier_item_id, selected_node_id,
                    selected_edge_id, reason, status, evidence_refs_json,
                    created_by_task_run_id, created_by_agent_id, payload_json,
                    created_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(decision_id) DO UPDATE SET
                    traversal_session_id = excluded.traversal_session_id,
                    build_id = excluded.build_id,
                    generation = excluded.generation,
                    decision_kind = excluded.decision_kind,
                    selected_frontier_item_id = excluded.selected_frontier_item_id,
                    selected_node_id = excluded.selected_node_id,
                    selected_edge_id = excluded.selected_edge_id,
                    reason = excluded.reason,
                    status = excluded.status,
                    evidence_refs_json = excluded.evidence_refs_json,
                    created_by_task_run_id = excluded.created_by_task_run_id,
                    created_by_agent_id = excluded.created_by_agent_id,
                    payload_json = excluded.payload_json,
                    authority = excluded.authority
                """,
                (
                    stored.decision_id,
                    stored.traversal_session_id,
                    stored.build_id,
                    int(stored.generation or 0),
                    stored.decision_kind,
                    stored.selected_frontier_item_id,
                    stored.selected_node_id,
                    stored.selected_edge_id,
                    stored.reason,
                    stored.status,
                    _json(list(stored.evidence_refs)),
                    stored.created_by_task_run_id,
                    stored.created_by_agent_id,
                    _json(stored.payload),
                    stored.created_at,
                    stored.authority,
                ),
            )
        return stored

    def list_control_decisions(
        self,
        *,
        traversal_session_id: str,
        limit: int = 2000,
    ) -> tuple[ProjectNetworkControlDecisionRecord, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM project_structure_control_decisions
                WHERE traversal_session_id = ?
                ORDER BY created_at DESC, decision_id ASC
                LIMIT ?
                """,
                (str(traversal_session_id or "").strip(), _limit(limit)),
            ).fetchall()
        return tuple(_control_decision_from_row(row) for row in rows)

    def upsert_maintenance_run(self, record: NetworkMaintenanceRunRecord) -> NetworkMaintenanceRunRecord:
        now = utc_now_iso()
        stored = replace(record, created_at=record.created_at or now, updated_at=now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_structure_maintenance_runs (
                    maintenance_run_id, build_id, change_set_id, status,
                    affected_node_ids_json, affected_edge_ids_json, repair_work_item_ids_json,
                    shared_memory_refs_json, metadata_json, created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(maintenance_run_id) DO UPDATE SET
                    build_id = excluded.build_id,
                    change_set_id = excluded.change_set_id,
                    status = excluded.status,
                    affected_node_ids_json = excluded.affected_node_ids_json,
                    affected_edge_ids_json = excluded.affected_edge_ids_json,
                    repair_work_item_ids_json = excluded.repair_work_item_ids_json,
                    shared_memory_refs_json = excluded.shared_memory_refs_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.maintenance_run_id,
                    stored.build_id,
                    stored.change_set_id,
                    stored.status,
                    _json(list(stored.affected_node_ids)),
                    _json(list(stored.affected_edge_ids)),
                    _json(list(stored.repair_work_item_ids)),
                    _json(list(stored.shared_memory_refs)),
                    _json(stored.metadata),
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def upsert_repair_work_items(
        self,
        records: tuple[SemanticRepairWorkItemRecord, ...] | list[SemanticRepairWorkItemRecord],
    ) -> tuple[SemanticRepairWorkItemRecord, ...]:
        now = utc_now_iso()
        with self._connect() as conn:
            for record in records:
                stored = replace(record, created_at=record.created_at or now, updated_at=now)
                conn.execute(
                    """
                    INSERT INTO project_structure_semantic_repair_work_items (
                        work_item_id, build_id, change_set_id, skeleton_generation, repair_kind,
                        assigned_scope_json, affected_node_ids_json, affected_edge_ids_json,
                        previous_semantic_refs_json, shared_memory_refs_json, required_evidence_refs_json,
                        priority, status, metadata_json, created_at, updated_at, authority
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(work_item_id) DO UPDATE SET
                        build_id = excluded.build_id,
                        change_set_id = excluded.change_set_id,
                        skeleton_generation = excluded.skeleton_generation,
                        repair_kind = excluded.repair_kind,
                        assigned_scope_json = excluded.assigned_scope_json,
                        affected_node_ids_json = excluded.affected_node_ids_json,
                        affected_edge_ids_json = excluded.affected_edge_ids_json,
                        previous_semantic_refs_json = excluded.previous_semantic_refs_json,
                        shared_memory_refs_json = excluded.shared_memory_refs_json,
                        required_evidence_refs_json = excluded.required_evidence_refs_json,
                        priority = excluded.priority,
                        status = excluded.status,
                        metadata_json = excluded.metadata_json,
                        updated_at = excluded.updated_at,
                        authority = excluded.authority
                    """,
                    (
                        stored.work_item_id,
                        stored.build_id,
                        stored.change_set_id,
                        int(stored.skeleton_generation or 0),
                        stored.repair_kind,
                        _json(stored.assigned_scope),
                        _json(list(stored.affected_node_ids)),
                        _json(list(stored.affected_edge_ids)),
                        _json(list(stored.previous_semantic_refs)),
                        _json(list(stored.shared_memory_refs)),
                        _json(list(stored.required_evidence_refs)),
                        int(stored.priority or 0),
                        stored.status,
                        _json(stored.metadata),
                        stored.created_at,
                        stored.updated_at,
                        stored.authority,
                    ),
                )
        return tuple(records)

    def list_repair_work_items(
        self,
        *,
        build_id: str = "",
        change_set_id: str = "",
        status: str = "",
        limit: int = 2000,
    ) -> tuple[SemanticRepairWorkItemRecord, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if build_id:
            filters.append("build_id = ?")
            params.append(build_id)
        if change_set_id:
            filters.append("change_set_id = ?")
            params.append(change_set_id)
        if status:
            filters.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM project_structure_semantic_repair_work_items"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY priority DESC, updated_at DESC LIMIT ?"
        params.append(_limit(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_repair_work_item_from_row(row) for row in rows)

    def upsert_repair_decision(self, record: SemanticRepairDecisionRecord) -> SemanticRepairDecisionRecord:
        now = utc_now_iso()
        stored = replace(record, created_at=record.created_at or now, updated_at=now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_structure_semantic_repair_decisions (
                    decision_id, build_id, change_set_id, work_item_id, decision,
                    affected_node_ids_json, affected_edge_ids_json, evidence_refs_json,
                    shared_memory_refs_json, reason, payload_json, status,
                    created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(decision_id) DO UPDATE SET
                    build_id = excluded.build_id,
                    change_set_id = excluded.change_set_id,
                    work_item_id = excluded.work_item_id,
                    decision = excluded.decision,
                    affected_node_ids_json = excluded.affected_node_ids_json,
                    affected_edge_ids_json = excluded.affected_edge_ids_json,
                    evidence_refs_json = excluded.evidence_refs_json,
                    shared_memory_refs_json = excluded.shared_memory_refs_json,
                    reason = excluded.reason,
                    payload_json = excluded.payload_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.decision_id,
                    stored.build_id,
                    stored.change_set_id,
                    stored.work_item_id,
                    stored.decision,
                    _json(list(stored.affected_node_ids)),
                    _json(list(stored.affected_edge_ids)),
                    _json(list(stored.evidence_refs)),
                    _json(list(stored.shared_memory_refs)),
                    stored.reason,
                    _json(stored.payload),
                    stored.status,
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS project_structure_skeleton_facts (
                    fact_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    source_kind TEXT NOT NULL DEFAULT '',
                    subject_ref TEXT NOT NULL DEFAULT '',
                    predicate TEXT NOT NULL DEFAULT '',
                    object_ref TEXT NOT NULL DEFAULT '',
                    object_literal TEXT NOT NULL DEFAULT '',
                    qualifiers_json TEXT NOT NULL DEFAULT '{}',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    anchor_refs_json TEXT NOT NULL DEFAULT '[]',
                    source_snapshot_ref TEXT NOT NULL DEFAULT '',
                    extractor_id TEXT NOT NULL DEFAULT '',
                    extractor_version TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL DEFAULT '',
                    confidence TEXT NOT NULL DEFAULT 'exact',
                    created_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'file_management.project_structure.skeleton_fact'
                );

                CREATE TABLE IF NOT EXISTS project_structure_skeleton_nodes (
                    node_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    node_kind TEXT NOT NULL DEFAULT '',
                    stable_ref TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL DEFAULT '',
                    path TEXT NOT NULL DEFAULT '',
                    layer_kind TEXT NOT NULL DEFAULT '',
                    hierarchy_path TEXT NOT NULL DEFAULT '',
                    parent_node_ids_json TEXT NOT NULL DEFAULT '[]',
                    ancestor_node_ids_json TEXT NOT NULL DEFAULT '[]',
                    anchor_ref TEXT NOT NULL DEFAULT '',
                    file_hash TEXT NOT NULL DEFAULT '',
                    extractor TEXT NOT NULL DEFAULT '',
                    confidence TEXT NOT NULL DEFAULT 'exact',
                    status TEXT NOT NULL DEFAULT 'active',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'file_management.project_structure.skeleton_node'
                );

                CREATE TABLE IF NOT EXISTS project_structure_skeleton_edges (
                    edge_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    edge_kind TEXT NOT NULL DEFAULT '',
                    src_node_id TEXT NOT NULL DEFAULT '',
                    dst_node_id TEXT NOT NULL DEFAULT '',
                    dst_candidate_ref TEXT NOT NULL DEFAULT '',
                    src_anchor_ref TEXT NOT NULL DEFAULT '',
                    dst_anchor_ref TEXT NOT NULL DEFAULT '',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    source_fact_ids_json TEXT NOT NULL DEFAULT '[]',
                    extractor TEXT NOT NULL DEFAULT '',
                    confidence TEXT NOT NULL DEFAULT 'exact',
                    resolution_status TEXT NOT NULL DEFAULT 'resolved',
                    freshness TEXT NOT NULL DEFAULT 'fresh',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'file_management.project_structure.skeleton_edge'
                );

                CREATE TABLE IF NOT EXISTS project_structure_skeleton_generations (
                    skeleton_generation_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'candidate',
                    source_snapshot_ref TEXT NOT NULL DEFAULT '',
                    fact_count INTEGER NOT NULL DEFAULT 0,
                    node_count INTEGER NOT NULL DEFAULT 0,
                    edge_count INTEGER NOT NULL DEFAULT 0,
                    stale_count INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'file_management.project_structure.skeleton_generation'
                );

                CREATE TABLE IF NOT EXISTS project_structure_git_change_sets (
                    change_set_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    base_ref TEXT NOT NULL DEFAULT '',
                    head_ref TEXT NOT NULL DEFAULT '',
                    change_mode TEXT NOT NULL DEFAULT 'working_tree',
                    changed_files_json TEXT NOT NULL DEFAULT '[]',
                    renamed_files_json TEXT NOT NULL DEFAULT '[]',
                    deleted_files_json TEXT NOT NULL DEFAULT '[]',
                    added_files_json TEXT NOT NULL DEFAULT '[]',
                    diff_stats_json TEXT NOT NULL DEFAULT '{}',
                    touched_skeleton_node_ids_json TEXT NOT NULL DEFAULT '[]',
                    touched_skeleton_edge_ids_json TEXT NOT NULL DEFAULT '[]',
                    semantic_refs_to_mark_stale_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'candidate',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'file_management.project_structure.git_change_set'
                );

                CREATE TABLE IF NOT EXISTS project_structure_semantic_overlays (
                    overlay_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    overlay_kind TEXT NOT NULL DEFAULT '',
                    stable_ref TEXT NOT NULL DEFAULT '',
                    skeleton_node_id TEXT NOT NULL DEFAULT '',
                    skeleton_edge_id TEXT NOT NULL DEFAULT '',
                    anchor_ref TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'candidate',
                    confidence TEXT NOT NULL DEFAULT 'derived',
                    generation INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    created_by_task_run_id TEXT NOT NULL DEFAULT '',
                    created_by_agent_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'file_management.project_structure.semantic_overlay'
                );

                CREATE TABLE IF NOT EXISTS project_structure_traversal_sessions (
                    traversal_session_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    goal TEXT NOT NULL DEFAULT '',
                    anchor_node_ids_json TEXT NOT NULL DEFAULT '[]',
                    anchor_stable_refs_json TEXT NOT NULL DEFAULT '[]',
                    current_node_ids_json TEXT NOT NULL DEFAULT '[]',
                    crawl_budget INTEGER NOT NULL DEFAULT 40,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_by_task_run_id TEXT NOT NULL DEFAULT '',
                    created_by_agent_id TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'file_management.project_structure.project_network_traversal_session'
                );

                CREATE TABLE IF NOT EXISTS project_structure_frontier_items (
                    frontier_item_id TEXT PRIMARY KEY,
                    traversal_session_id TEXT NOT NULL,
                    build_id TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    target_node_id TEXT NOT NULL DEFAULT '',
                    target_edge_id TEXT NOT NULL DEFAULT '',
                    stable_ref TEXT NOT NULL DEFAULT '',
                    source_node_id TEXT NOT NULL DEFAULT '',
                    via_edge_id TEXT NOT NULL DEFAULT '',
                    relation_kind TEXT NOT NULL DEFAULT '',
                    priority INTEGER NOT NULL DEFAULT 50,
                    reason TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'queued',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    semantic_overlay_ids_json TEXT NOT NULL DEFAULT '[]',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'file_management.project_structure.project_network_frontier_item'
                );

                CREATE TABLE IF NOT EXISTS project_structure_visited_refs (
                    visited_ref_id TEXT PRIMARY KEY,
                    traversal_session_id TEXT NOT NULL,
                    build_id TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    ref_kind TEXT NOT NULL DEFAULT '',
                    ref_id TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'file_management.project_structure.project_network_visited_ref'
                );

                CREATE TABLE IF NOT EXISTS project_structure_control_decisions (
                    decision_id TEXT PRIMARY KEY,
                    traversal_session_id TEXT NOT NULL,
                    build_id TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    decision_kind TEXT NOT NULL DEFAULT '',
                    selected_frontier_item_id TEXT NOT NULL DEFAULT '',
                    selected_node_id TEXT NOT NULL DEFAULT '',
                    selected_edge_id TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'recorded',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    created_by_task_run_id TEXT NOT NULL DEFAULT '',
                    created_by_agent_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'file_management.project_structure.project_network_control_decision'
                );

                CREATE TABLE IF NOT EXISTS project_structure_maintenance_runs (
                    maintenance_run_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    change_set_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'planned',
                    affected_node_ids_json TEXT NOT NULL DEFAULT '[]',
                    affected_edge_ids_json TEXT NOT NULL DEFAULT '[]',
                    repair_work_item_ids_json TEXT NOT NULL DEFAULT '[]',
                    shared_memory_refs_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'file_management.project_structure.maintenance_run'
                );

                CREATE TABLE IF NOT EXISTS project_structure_semantic_repair_work_items (
                    work_item_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    change_set_id TEXT NOT NULL DEFAULT '',
                    skeleton_generation INTEGER NOT NULL DEFAULT 0,
                    repair_kind TEXT NOT NULL DEFAULT '',
                    assigned_scope_json TEXT NOT NULL DEFAULT '{}',
                    affected_node_ids_json TEXT NOT NULL DEFAULT '[]',
                    affected_edge_ids_json TEXT NOT NULL DEFAULT '[]',
                    previous_semantic_refs_json TEXT NOT NULL DEFAULT '[]',
                    shared_memory_refs_json TEXT NOT NULL DEFAULT '[]',
                    required_evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    priority INTEGER NOT NULL DEFAULT 50,
                    status TEXT NOT NULL DEFAULT 'queued',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'file_management.project_structure.semantic_repair_work_item'
                );

                CREATE TABLE IF NOT EXISTS project_structure_semantic_repair_decisions (
                    decision_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    change_set_id TEXT NOT NULL DEFAULT '',
                    work_item_id TEXT NOT NULL DEFAULT '',
                    decision TEXT NOT NULL DEFAULT '',
                    affected_node_ids_json TEXT NOT NULL DEFAULT '[]',
                    affected_edge_ids_json TEXT NOT NULL DEFAULT '[]',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    shared_memory_refs_json TEXT NOT NULL DEFAULT '[]',
                    reason TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'candidate',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'file_management.project_structure.semantic_repair_decision'
                );

                CREATE INDEX IF NOT EXISTS idx_project_structure_skeleton_facts_build
                    ON project_structure_skeleton_facts(build_id, generation, source_kind);
                CREATE INDEX IF NOT EXISTS idx_project_structure_skeleton_facts_subject
                    ON project_structure_skeleton_facts(subject_ref, predicate);
                CREATE INDEX IF NOT EXISTS idx_project_structure_skeleton_nodes_build
                    ON project_structure_skeleton_nodes(build_id, generation, node_kind, status);
                CREATE INDEX IF NOT EXISTS idx_project_structure_skeleton_nodes_stable
                    ON project_structure_skeleton_nodes(build_id, stable_ref, generation);
                CREATE INDEX IF NOT EXISTS idx_project_structure_skeleton_nodes_path
                    ON project_structure_skeleton_nodes(build_id, path, generation);
                CREATE INDEX IF NOT EXISTS idx_project_structure_skeleton_edges_src
                    ON project_structure_skeleton_edges(build_id, generation, src_node_id, edge_kind);
                CREATE INDEX IF NOT EXISTS idx_project_structure_skeleton_edges_dst
                    ON project_structure_skeleton_edges(build_id, generation, dst_node_id, edge_kind);
                CREATE INDEX IF NOT EXISTS idx_project_structure_git_change_sets_build
                    ON project_structure_git_change_sets(build_id, status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_project_structure_semantic_overlays_stable
                    ON project_structure_semantic_overlays(build_id, stable_ref, status, overlay_kind);
                CREATE INDEX IF NOT EXISTS idx_project_structure_semantic_overlays_node
                    ON project_structure_semantic_overlays(build_id, skeleton_node_id, status, overlay_kind);
                CREATE INDEX IF NOT EXISTS idx_project_structure_semantic_overlays_edge
                    ON project_structure_semantic_overlays(build_id, skeleton_edge_id, status, overlay_kind);
                CREATE INDEX IF NOT EXISTS idx_project_structure_traversal_sessions_build
                    ON project_structure_traversal_sessions(build_id, status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_project_structure_frontier_items_session
                    ON project_structure_frontier_items(traversal_session_id, status, priority);
                CREATE INDEX IF NOT EXISTS idx_project_structure_visited_refs_session
                    ON project_structure_visited_refs(traversal_session_id, ref_kind, created_at);
                CREATE INDEX IF NOT EXISTS idx_project_structure_control_decisions_session
                    ON project_structure_control_decisions(traversal_session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_project_structure_repair_items_change_set
                    ON project_structure_semantic_repair_work_items(change_set_id, status, priority);
                """
            )


def stable_project_structure_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part or "").strip() for part in parts)
    return f"{prefix}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:20]}"


def content_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _skeleton_fact_from_row(row: sqlite3.Row) -> SkeletonFactRecord:
    return SkeletonFactRecord(
        fact_id=str(row["fact_id"]),
        build_id=str(row["build_id"]),
        generation=int(row["generation"] or 0),
        source_kind=str(row["source_kind"] or ""),
        subject_ref=str(row["subject_ref"] or ""),
        predicate=str(row["predicate"] or ""),
        object_ref=str(row["object_ref"] or ""),
        object_literal=str(row["object_literal"] or ""),
        qualifiers=_loads(row["qualifiers_json"], {}),
        evidence_refs=tuple(_strings(_loads(row["evidence_refs_json"], []))),
        anchor_refs=tuple(_strings(_loads(row["anchor_refs_json"], []))),
        source_snapshot_ref=str(row["source_snapshot_ref"] or ""),
        extractor_id=str(row["extractor_id"] or ""),
        extractor_version=str(row["extractor_version"] or ""),
        content_hash=str(row["content_hash"] or ""),
        confidence=str(row["confidence"] or "exact"),  # type: ignore[arg-type]
        created_at=str(row["created_at"] or ""),
        authority=str(row["authority"] or "file_management.project_structure.skeleton_fact"),
    )


def _skeleton_node_from_row(row: sqlite3.Row) -> SkeletonNodeRecord:
    return SkeletonNodeRecord(
        node_id=str(row["node_id"]),
        build_id=str(row["build_id"]),
        generation=int(row["generation"] or 0),
        node_kind=str(row["node_kind"] or ""),
        stable_ref=str(row["stable_ref"] or ""),
        display_name=str(row["display_name"] or ""),
        path=str(row["path"] or ""),
        layer_kind=str(row["layer_kind"] or ""),
        hierarchy_path=str(row["hierarchy_path"] or ""),
        parent_node_ids=tuple(_strings(_loads(row["parent_node_ids_json"], []))),
        ancestor_node_ids=tuple(_strings(_loads(row["ancestor_node_ids_json"], []))),
        anchor_ref=str(row["anchor_ref"] or ""),
        file_hash=str(row["file_hash"] or ""),
        extractor=str(row["extractor"] or ""),
        confidence=str(row["confidence"] or "exact"),  # type: ignore[arg-type]
        status=str(row["status"] or "active"),  # type: ignore[arg-type]
        payload=_loads(row["payload_json"], {}),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        authority=str(row["authority"] or "file_management.project_structure.skeleton_node"),
    )


def _skeleton_edge_from_row(row: sqlite3.Row) -> SkeletonEdgeRecord:
    return SkeletonEdgeRecord(
        edge_id=str(row["edge_id"]),
        build_id=str(row["build_id"]),
        generation=int(row["generation"] or 0),
        edge_kind=str(row["edge_kind"] or ""),
        src_node_id=str(row["src_node_id"] or ""),
        dst_node_id=str(row["dst_node_id"] or ""),
        dst_candidate_ref=str(row["dst_candidate_ref"] or ""),
        src_anchor_ref=str(row["src_anchor_ref"] or ""),
        dst_anchor_ref=str(row["dst_anchor_ref"] or ""),
        evidence_refs=tuple(_strings(_loads(row["evidence_refs_json"], []))),
        source_fact_ids=tuple(_strings(_loads(row["source_fact_ids_json"], []))),
        extractor=str(row["extractor"] or ""),
        confidence=str(row["confidence"] or "exact"),  # type: ignore[arg-type]
        resolution_status=str(row["resolution_status"] or "resolved"),  # type: ignore[arg-type]
        freshness=str(row["freshness"] or "fresh"),  # type: ignore[arg-type]
        payload=_loads(row["payload_json"], {}),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        authority=str(row["authority"] or "file_management.project_structure.skeleton_edge"),
    )


def _skeleton_generation_from_row(row: sqlite3.Row) -> SkeletonGenerationRecord:
    return SkeletonGenerationRecord(
        skeleton_generation_id=str(row["skeleton_generation_id"]),
        build_id=str(row["build_id"]),
        generation=int(row["generation"] or 0),
        status=str(row["status"] or "candidate"),
        source_snapshot_ref=str(row["source_snapshot_ref"] or ""),
        fact_count=int(row["fact_count"] or 0),
        node_count=int(row["node_count"] or 0),
        edge_count=int(row["edge_count"] or 0),
        stale_count=int(row["stale_count"] or 0),
        payload=_loads(row["payload_json"], {}),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        authority=str(row["authority"] or "file_management.project_structure.skeleton_generation"),
    )


def _git_change_set_from_row(row: sqlite3.Row) -> GitChangeSetRecord:
    renamed = tuple(dict(item) for item in list(_loads(row["renamed_files_json"], [])) if isinstance(item, dict))
    return GitChangeSetRecord(
        change_set_id=str(row["change_set_id"]),
        build_id=str(row["build_id"]),
        base_ref=str(row["base_ref"] or ""),
        head_ref=str(row["head_ref"] or ""),
        change_mode=str(row["change_mode"] or "working_tree"),
        changed_files=tuple(_strings(_loads(row["changed_files_json"], []))),
        renamed_files=renamed,
        deleted_files=tuple(_strings(_loads(row["deleted_files_json"], []))),
        added_files=tuple(_strings(_loads(row["added_files_json"], []))),
        diff_stats=_loads(row["diff_stats_json"], {}),
        touched_skeleton_node_ids=tuple(_strings(_loads(row["touched_skeleton_node_ids_json"], []))),
        touched_skeleton_edge_ids=tuple(_strings(_loads(row["touched_skeleton_edge_ids_json"], []))),
        semantic_refs_to_mark_stale=tuple(_strings(_loads(row["semantic_refs_to_mark_stale_json"], []))),
        status=str(row["status"] or "candidate"),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        authority=str(row["authority"] or "file_management.project_structure.git_change_set"),
    )


def _semantic_overlay_from_row(row: sqlite3.Row) -> SemanticOverlayRecord:
    return SemanticOverlayRecord(
        overlay_id=str(row["overlay_id"]),
        build_id=str(row["build_id"]),
        overlay_kind=str(row["overlay_kind"] or ""),
        stable_ref=str(row["stable_ref"] or ""),
        skeleton_node_id=str(row["skeleton_node_id"] or ""),
        skeleton_edge_id=str(row["skeleton_edge_id"] or ""),
        anchor_ref=str(row["anchor_ref"] or ""),
        status=str(row["status"] or "candidate"),
        confidence=str(row["confidence"] or "derived"),
        generation=int(row["generation"] or 0),
        payload=_loads(row["payload_json"], {}),
        evidence_refs=tuple(_strings(_loads(row["evidence_refs_json"], []))),
        created_by_task_run_id=str(row["created_by_task_run_id"] or ""),
        created_by_agent_id=str(row["created_by_agent_id"] or ""),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        authority=str(row["authority"] or "file_management.project_structure.semantic_overlay"),
    )


def _traversal_session_from_row(row: sqlite3.Row) -> ProjectNetworkTraversalSessionRecord:
    return ProjectNetworkTraversalSessionRecord(
        traversal_session_id=str(row["traversal_session_id"]),
        build_id=str(row["build_id"]),
        generation=int(row["generation"] or 0),
        goal=str(row["goal"] or ""),
        anchor_node_ids=tuple(_strings(_loads(row["anchor_node_ids_json"], []))),
        anchor_stable_refs=tuple(_strings(_loads(row["anchor_stable_refs_json"], []))),
        current_node_ids=tuple(_strings(_loads(row["current_node_ids_json"], []))),
        crawl_budget=int(row["crawl_budget"] or 0),
        status=str(row["status"] or "active"),
        created_by_task_run_id=str(row["created_by_task_run_id"] or ""),
        created_by_agent_id=str(row["created_by_agent_id"] or ""),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        metadata=_loads(row["metadata_json"], {}),
        authority=str(row["authority"] or "file_management.project_structure.project_network_traversal_session"),
    )


def _frontier_item_from_row(row: sqlite3.Row) -> ProjectNetworkFrontierItemRecord:
    return ProjectNetworkFrontierItemRecord(
        frontier_item_id=str(row["frontier_item_id"]),
        traversal_session_id=str(row["traversal_session_id"]),
        build_id=str(row["build_id"]),
        generation=int(row["generation"] or 0),
        target_node_id=str(row["target_node_id"] or ""),
        target_edge_id=str(row["target_edge_id"] or ""),
        stable_ref=str(row["stable_ref"] or ""),
        source_node_id=str(row["source_node_id"] or ""),
        via_edge_id=str(row["via_edge_id"] or ""),
        relation_kind=str(row["relation_kind"] or ""),
        priority=int(row["priority"] or 0),
        reason=str(row["reason"] or ""),
        status=str(row["status"] or "queued"),
        evidence_refs=tuple(_strings(_loads(row["evidence_refs_json"], []))),
        semantic_overlay_ids=tuple(_strings(_loads(row["semantic_overlay_ids_json"], []))),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        payload=_loads(row["payload_json"], {}),
        authority=str(row["authority"] or "file_management.project_structure.project_network_frontier_item"),
    )


def _visited_ref_from_row(row: sqlite3.Row) -> ProjectNetworkVisitedRefRecord:
    return ProjectNetworkVisitedRefRecord(
        visited_ref_id=str(row["visited_ref_id"]),
        traversal_session_id=str(row["traversal_session_id"]),
        build_id=str(row["build_id"]),
        generation=int(row["generation"] or 0),
        ref_kind=str(row["ref_kind"] or ""),
        ref_id=str(row["ref_id"] or ""),
        reason=str(row["reason"] or ""),
        created_at=str(row["created_at"] or ""),
        payload=_loads(row["payload_json"], {}),
        authority=str(row["authority"] or "file_management.project_structure.project_network_visited_ref"),
    )


def _control_decision_from_row(row: sqlite3.Row) -> ProjectNetworkControlDecisionRecord:
    return ProjectNetworkControlDecisionRecord(
        decision_id=str(row["decision_id"]),
        traversal_session_id=str(row["traversal_session_id"]),
        build_id=str(row["build_id"]),
        generation=int(row["generation"] or 0),
        decision_kind=str(row["decision_kind"] or ""),
        selected_frontier_item_id=str(row["selected_frontier_item_id"] or ""),
        selected_node_id=str(row["selected_node_id"] or ""),
        selected_edge_id=str(row["selected_edge_id"] or ""),
        reason=str(row["reason"] or ""),
        status=str(row["status"] or "recorded"),
        evidence_refs=tuple(_strings(_loads(row["evidence_refs_json"], []))),
        created_by_task_run_id=str(row["created_by_task_run_id"] or ""),
        created_by_agent_id=str(row["created_by_agent_id"] or ""),
        created_at=str(row["created_at"] or ""),
        payload=_loads(row["payload_json"], {}),
        authority=str(row["authority"] or "file_management.project_structure.project_network_control_decision"),
    )


def _repair_work_item_from_row(row: sqlite3.Row) -> SemanticRepairWorkItemRecord:
    return SemanticRepairWorkItemRecord(
        work_item_id=str(row["work_item_id"]),
        build_id=str(row["build_id"]),
        change_set_id=str(row["change_set_id"] or ""),
        skeleton_generation=int(row["skeleton_generation"] or 0),
        repair_kind=str(row["repair_kind"] or ""),
        assigned_scope=_loads(row["assigned_scope_json"], {}),
        affected_node_ids=tuple(_strings(_loads(row["affected_node_ids_json"], []))),
        affected_edge_ids=tuple(_strings(_loads(row["affected_edge_ids_json"], []))),
        previous_semantic_refs=tuple(_strings(_loads(row["previous_semantic_refs_json"], []))),
        shared_memory_refs=tuple(_strings(_loads(row["shared_memory_refs_json"], []))),
        required_evidence_refs=tuple(_strings(_loads(row["required_evidence_refs_json"], []))),
        priority=int(row["priority"] or 0),
        status=str(row["status"] or "queued"),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        metadata=_loads(row["metadata_json"], {}),
        authority=str(row["authority"] or "file_management.project_structure.semantic_repair_work_item"),
    )


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
