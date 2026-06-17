from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifact_repository_models import ArtifactRecord, ArtifactRepository
from .materialization_receipts import ArtifactMaterializationReceipt


class ArtifactRepositoryStore:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root_dir / "artifact_repository.sqlite"
        self._ensure_schema()

    def upsert_repository(self, repository: ArtifactRepository) -> ArtifactRepository:
        now = utc_now_iso()
        effective_repository_id = repository.effective_repository_id or repository.repository_id
        stored = replace(
            repository,
            repository_id=effective_repository_id,
            effective_repository_id=effective_repository_id,
            logical_repository_id=repository.logical_repository_id or repository.repository_id,
            scope_id=repository.scope_id or repository.task_run_id or effective_repository_id,
            created_at=repository.created_at or now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO artifact_repositories (
                    repository_id, logical_repository_id, effective_repository_id,
                    namespace_id, storage_owner, durability_class, retention_tier, task_run_id,
                    scope_kind, scope_id, graph_id, node_id, title, lifecycle_policy_json,
                    created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repository_id) DO UPDATE SET
                    logical_repository_id = excluded.logical_repository_id,
                    effective_repository_id = excluded.effective_repository_id,
                    namespace_id = excluded.namespace_id,
                    storage_owner = excluded.storage_owner,
                    durability_class = excluded.durability_class,
                    retention_tier = excluded.retention_tier,
                    task_run_id = excluded.task_run_id,
                    scope_kind = excluded.scope_kind,
                    scope_id = excluded.scope_id,
                    graph_id = excluded.graph_id,
                    node_id = excluded.node_id,
                    title = excluded.title,
                    lifecycle_policy_json = excluded.lifecycle_policy_json,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.repository_id,
                    stored.logical_repository_id,
                    stored.effective_repository_id,
                    stored.namespace_id,
                    stored.storage_owner,
                    stored.durability_class,
                    stored.retention_tier,
                    stored.task_run_id,
                    stored.scope_kind,
                    stored.scope_id,
                    stored.graph_id,
                    stored.node_id,
                    stored.title,
                    _json(stored.lifecycle_policy),
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def upsert_artifact(self, record: ArtifactRecord) -> ArtifactRecord:
        now = utc_now_iso()
        stored = replace(
            record,
            logical_repository_id=record.logical_repository_id or record.repository_id,
            effective_repository_id=record.effective_repository_id or record.repository_id,
            scope_id=record.scope_id or record.task_run_id or record.repository_id,
            created_at=record.created_at or now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO artifact_records (
                    artifact_id, artifact_ref, path, repository_id, collection_id,
                    namespace_id, storage_owner, physical_path, logical_path, durability_class,
                    retention_tier, materialization_receipt_id, protected_reason,
                    output_contract_id, artifact_kind, producer_node_id, content_type, materialization_id,
                    logical_repository_id, effective_repository_id, task_run_id, scope_kind, scope_id,
                    graph_id, stage_id, node_run_id, task_ref, graph_run_id,
                    status, content_hash, metadata_json, created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    artifact_ref = excluded.artifact_ref,
                    path = excluded.path,
                    namespace_id = excluded.namespace_id,
                    storage_owner = excluded.storage_owner,
                    physical_path = excluded.physical_path,
                    logical_path = excluded.logical_path,
                    durability_class = excluded.durability_class,
                    retention_tier = excluded.retention_tier,
                    materialization_receipt_id = excluded.materialization_receipt_id,
                    protected_reason = excluded.protected_reason,
                    output_contract_id = excluded.output_contract_id,
                    artifact_kind = excluded.artifact_kind,
                    producer_node_id = excluded.producer_node_id,
                    content_type = excluded.content_type,
                    materialization_id = excluded.materialization_id,
                    logical_repository_id = excluded.logical_repository_id,
                    effective_repository_id = excluded.effective_repository_id,
                    task_run_id = excluded.task_run_id,
                    scope_kind = excluded.scope_kind,
                    scope_id = excluded.scope_id,
                    graph_id = excluded.graph_id,
                    stage_id = excluded.stage_id,
                    node_run_id = excluded.node_run_id,
                    task_ref = excluded.task_ref,
                    graph_run_id = excluded.graph_run_id,
                    status = excluded.status,
                    content_hash = excluded.content_hash,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    stored.artifact_id,
                    stored.artifact_ref,
                    stored.path,
                    stored.repository_id,
                    stored.collection_id,
                    stored.namespace_id,
                    stored.storage_owner,
                    stored.physical_path,
                    stored.logical_path,
                    stored.durability_class,
                    stored.retention_tier,
                    stored.materialization_receipt_id,
                    stored.protected_reason,
                    stored.output_contract_id,
                    stored.artifact_kind,
                    stored.producer_node_id,
                    stored.content_type,
                    stored.materialization_id,
                    stored.logical_repository_id,
                    stored.effective_repository_id,
                    stored.task_run_id,
                    stored.scope_kind,
                    stored.scope_id,
                    stored.graph_id,
                    stored.stage_id,
                    stored.node_run_id,
                    stored.task_ref,
                    stored.graph_run_id,
                    stored.status,
                    stored.content_hash,
                    _json(stored.metadata),
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def upsert_materialization_receipt(self, receipt: ArtifactMaterializationReceipt) -> ArtifactMaterializationReceipt:
        now = utc_now_iso()
        stored = replace(
            receipt,
            created_at=receipt.created_at or now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO artifact_materialization_receipts (
                    receipt_id, source_kind, source_ref, target_namespace_id,
                    artifact_ids_json, content_hashes_json, producer_task_run_id,
                    producer_graph_run_id, producer_node_id, output_contract_id,
                    status, metadata_json, created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(receipt_id) DO UPDATE SET
                    source_kind = excluded.source_kind,
                    source_ref = excluded.source_ref,
                    target_namespace_id = excluded.target_namespace_id,
                    artifact_ids_json = excluded.artifact_ids_json,
                    content_hashes_json = excluded.content_hashes_json,
                    producer_task_run_id = excluded.producer_task_run_id,
                    producer_graph_run_id = excluded.producer_graph_run_id,
                    producer_node_id = excluded.producer_node_id,
                    output_contract_id = excluded.output_contract_id,
                    status = excluded.status,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.receipt_id,
                    stored.source_kind,
                    stored.source_ref,
                    stored.target_namespace_id,
                    _json(list(stored.artifact_ids)),
                    _json(dict(stored.content_hashes)),
                    stored.producer_task_run_id,
                    stored.producer_graph_run_id,
                    stored.producer_node_id,
                    stored.output_contract_id,
                    stored.status,
                    _json(stored.metadata),
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def list_materialization_receipts(
        self,
        *,
        target_namespace_id: str = "",
        producer_task_run_id: str = "",
        producer_graph_run_id: str = "",
        limit: int = 500,
    ) -> tuple[ArtifactMaterializationReceipt, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if target_namespace_id:
            filters.append("target_namespace_id = ?")
            params.append(target_namespace_id)
        if producer_task_run_id:
            filters.append("producer_task_run_id = ?")
            params.append(producer_task_run_id)
        if producer_graph_run_id:
            filters.append("producer_graph_run_id = ?")
            params.append(producer_graph_run_id)
        sql = "SELECT * FROM artifact_materialization_receipts"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY updated_at DESC, receipt_id ASC LIMIT ?"
        params.append(max(1, min(int(limit or 500), 2000)))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_receipt_from_row(row) for row in rows)

    def list_repositories(self, *, task_run_id: str = "") -> tuple[ArtifactRepository, ...]:
        sql = "SELECT * FROM artifact_repositories"
        params: list[Any] = []
        if task_run_id:
            sql += " WHERE task_run_id = ?"
            params.append(task_run_id)
        sql += " ORDER BY updated_at DESC, repository_id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_repository_from_row(row) for row in rows)

    def list_artifacts(
        self,
        *,
        task_run_id: str = "",
        repository_id: str = "",
        collection_id: str = "",
        status: str = "",
        graph_id: str = "",
        graph_run_id: str = "",
        stage_id: str = "",
        node_run_id: str = "",
        task_ref: str = "",
        output_contract_id: str = "",
        producer_node_id: str = "",
        artifact_kind: str = "",
        namespace_id: str = "",
        storage_owner: str = "",
        durability_class: str = "",
        limit: int = 500,
    ) -> tuple[ArtifactRecord, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if task_run_id:
            filters.append("task_run_id = ?")
            params.append(task_run_id)
        if repository_id:
            filters.append("(repository_id = ? OR logical_repository_id = ?)")
            params.extend([repository_id, repository_id])
        if collection_id:
            filters.append("collection_id = ?")
            params.append(collection_id)
        if status:
            filters.append("status = ?")
            params.append(status)
        if graph_id:
            filters.append("graph_id = ?")
            params.append(graph_id)
        if graph_run_id:
            filters.append("graph_run_id = ?")
            params.append(graph_run_id)
        if stage_id:
            filters.append("stage_id = ?")
            params.append(stage_id)
        if node_run_id:
            filters.append("node_run_id = ?")
            params.append(node_run_id)
        if task_ref:
            filters.append("task_ref = ?")
            params.append(task_ref)
        if output_contract_id:
            filters.append("output_contract_id = ?")
            params.append(output_contract_id)
        if producer_node_id:
            filters.append("producer_node_id = ?")
            params.append(producer_node_id)
        if artifact_kind:
            filters.append("artifact_kind = ?")
            params.append(artifact_kind)
        if namespace_id:
            filters.append("namespace_id = ?")
            params.append(namespace_id)
        if storage_owner:
            filters.append("storage_owner = ?")
            params.append(storage_owner)
        if durability_class:
            filters.append("durability_class = ?")
            params.append(durability_class)
        sql = "SELECT * FROM artifact_records"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY updated_at DESC, artifact_id ASC LIMIT ?"
        params.append(max(1, min(int(limit or 500), 2000)))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_record_from_row(row) for row in rows)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def delete_scope(
        self,
        *,
        task_run_ids: set[str] | None = None,
        graph_run_ids: set[str] | None = None,
        scope_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        task_ids = {str(item).strip() for item in set(task_run_ids or set()) if str(item).strip()}
        graph_ids = {str(item).strip() for item in set(graph_run_ids or set()) if str(item).strip()}
        scopes = {str(item).strip() for item in set(scope_ids or set()) if str(item).strip()}
        if not task_ids and not graph_ids and not scopes:
            return {"authority": "artifact_repository.store.delete_scope", "deleted_counts": {}}
        counts: dict[str, int] = {}
        with self._connect() as conn:
            record_where, record_params = _artifact_record_delete_where(task_ids=task_ids, graph_run_ids=graph_ids, scope_ids=scopes)
            protected_record_where = f"({record_where}) AND {_protected_artifact_record_where()}"
            delete_record_where = f"({record_where}) AND NOT ({_protected_artifact_record_where()})"
            protected_records = int(conn.execute(f"SELECT COUNT(*) FROM artifact_records WHERE {protected_record_where}", tuple(record_params)).fetchone()[0])
            before_records = int(conn.execute(f"SELECT COUNT(*) FROM artifact_records WHERE {delete_record_where}", tuple(record_params)).fetchone()[0])
            conn.execute(f"DELETE FROM artifact_records WHERE {delete_record_where}", tuple(record_params))
            if before_records:
                counts["artifact_records"] = before_records
            if protected_records:
                counts["protected_artifact_records_skipped"] = protected_records
            repo_where, repo_params = _artifact_repository_delete_where(task_ids=task_ids, scope_ids=scopes)
            if repo_where:
                protected_repo_where = f"({repo_where}) AND {_protected_artifact_repository_where()}"
                delete_repo_where = f"({repo_where}) AND NOT ({_protected_artifact_repository_where()})"
                protected_repos = int(conn.execute(f"SELECT COUNT(*) FROM artifact_repositories WHERE {protected_repo_where}", tuple(repo_params)).fetchone()[0])
                before_repos = int(conn.execute(f"SELECT COUNT(*) FROM artifact_repositories WHERE {delete_repo_where}", tuple(repo_params)).fetchone()[0])
                conn.execute(f"DELETE FROM artifact_repositories WHERE {delete_repo_where}", tuple(repo_params))
                if before_repos:
                    counts["artifact_repositories"] = before_repos
                if protected_repos:
                    counts["protected_artifact_repositories_skipped"] = protected_repos
        return {
            "authority": "artifact_repository.store.delete_scope",
            "task_run_ids": sorted(task_ids),
            "graph_run_ids": sorted(graph_ids),
            "scope_ids": sorted(scopes),
            "deleted_counts": counts,
        }

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS artifact_repositories (
                    repository_id TEXT PRIMARY KEY,
                    logical_repository_id TEXT NOT NULL DEFAULT '',
                    effective_repository_id TEXT NOT NULL DEFAULT '',
                    namespace_id TEXT NOT NULL DEFAULT '',
                    storage_owner TEXT NOT NULL DEFAULT '',
                    durability_class TEXT NOT NULL DEFAULT '',
                    retention_tier TEXT NOT NULL DEFAULT '',
                    task_run_id TEXT NOT NULL DEFAULT '',
                    scope_kind TEXT NOT NULL DEFAULT 'run_scoped',
                    scope_id TEXT NOT NULL DEFAULT '',
                    graph_id TEXT NOT NULL DEFAULT '',
                    node_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    lifecycle_policy_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'artifact_repository.repository'
                );

                CREATE TABLE IF NOT EXISTS artifact_records (
                    artifact_id TEXT PRIMARY KEY,
                    artifact_ref TEXT NOT NULL,
                    path TEXT NOT NULL DEFAULT '',
                    repository_id TEXT NOT NULL,
                    collection_id TEXT NOT NULL DEFAULT 'default',
                    namespace_id TEXT NOT NULL DEFAULT '',
                    storage_owner TEXT NOT NULL DEFAULT '',
                    physical_path TEXT NOT NULL DEFAULT '',
                    logical_path TEXT NOT NULL DEFAULT '',
                    durability_class TEXT NOT NULL DEFAULT '',
                    retention_tier TEXT NOT NULL DEFAULT '',
                    materialization_receipt_id TEXT NOT NULL DEFAULT '',
                    protected_reason TEXT NOT NULL DEFAULT '',
                    output_contract_id TEXT NOT NULL DEFAULT '',
                    artifact_kind TEXT NOT NULL DEFAULT 'file',
                    producer_node_id TEXT NOT NULL DEFAULT '',
                    content_type TEXT NOT NULL DEFAULT '',
                    materialization_id TEXT NOT NULL DEFAULT '',
                    logical_repository_id TEXT NOT NULL DEFAULT '',
                    effective_repository_id TEXT NOT NULL DEFAULT '',
                    task_run_id TEXT NOT NULL DEFAULT '',
                    scope_kind TEXT NOT NULL DEFAULT 'run_scoped',
                    scope_id TEXT NOT NULL DEFAULT '',
                    graph_id TEXT NOT NULL DEFAULT '',
                    stage_id TEXT NOT NULL DEFAULT '',
                    node_run_id TEXT NOT NULL DEFAULT '',
                    task_ref TEXT NOT NULL DEFAULT '',
                    graph_run_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'accepted',
                    content_hash TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'artifact_repository.record'
                );

                CREATE TABLE IF NOT EXISTS artifact_materialization_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    source_kind TEXT NOT NULL DEFAULT '',
                    source_ref TEXT NOT NULL DEFAULT '',
                    target_namespace_id TEXT NOT NULL DEFAULT '',
                    artifact_ids_json TEXT NOT NULL DEFAULT '[]',
                    content_hashes_json TEXT NOT NULL DEFAULT '{}',
                    producer_task_run_id TEXT NOT NULL DEFAULT '',
                    producer_graph_run_id TEXT NOT NULL DEFAULT '',
                    producer_node_id TEXT NOT NULL DEFAULT '',
                    output_contract_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'accepted',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'artifact_system.materializer'
                );

                """
            )
            _ensure_columns(
                conn,
                "artifact_repositories",
                {
                    "namespace_id": "TEXT NOT NULL DEFAULT ''",
                    "storage_owner": "TEXT NOT NULL DEFAULT ''",
                    "durability_class": "TEXT NOT NULL DEFAULT ''",
                    "retention_tier": "TEXT NOT NULL DEFAULT ''",
                },
            )
            _ensure_columns(
                conn,
                "artifact_records",
                {
                    "namespace_id": "TEXT NOT NULL DEFAULT ''",
                    "storage_owner": "TEXT NOT NULL DEFAULT ''",
                    "physical_path": "TEXT NOT NULL DEFAULT ''",
                    "logical_path": "TEXT NOT NULL DEFAULT ''",
                    "durability_class": "TEXT NOT NULL DEFAULT ''",
                    "retention_tier": "TEXT NOT NULL DEFAULT ''",
                    "materialization_receipt_id": "TEXT NOT NULL DEFAULT ''",
                    "protected_reason": "TEXT NOT NULL DEFAULT ''",
                    "output_contract_id": "TEXT NOT NULL DEFAULT ''",
                    "artifact_kind": "TEXT NOT NULL DEFAULT 'file'",
                    "producer_node_id": "TEXT NOT NULL DEFAULT ''",
                    "content_type": "TEXT NOT NULL DEFAULT ''",
                    "materialization_id": "TEXT NOT NULL DEFAULT ''",
                    "graph_run_id": "TEXT NOT NULL DEFAULT ''",
                },
            )
            conn.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_artifact_records_scope
                    ON artifact_records(task_run_id, logical_repository_id, collection_id, status);
                CREATE INDEX IF NOT EXISTS idx_artifact_records_stage
                    ON artifact_records(task_run_id, stage_id, node_run_id);
                CREATE INDEX IF NOT EXISTS idx_artifact_records_contract
                    ON artifact_records(output_contract_id, status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_artifact_records_producer
                    ON artifact_records(graph_id, producer_node_id, task_ref);
                CREATE INDEX IF NOT EXISTS idx_artifact_records_namespace
                    ON artifact_records(namespace_id, durability_class, retention_tier);
                CREATE INDEX IF NOT EXISTS idx_artifact_receipts_namespace
                    ON artifact_materialization_receipts(target_namespace_id, updated_at);
                """
            )


def build_artifact_id(*parts: str) -> str:
    raw = "|".join(str(part or "").strip() for part in parts)
    return f"artifactrec:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:20]}"


def _artifact_record_delete_where(*, task_ids: set[str], graph_run_ids: set[str], scope_ids: set[str]) -> tuple[str, list[str]]:
    clauses: list[str] = []
    params: list[str] = []
    if task_ids:
        placeholders = ",".join("?" for _ in task_ids)
        clauses.append(f"task_run_id IN ({placeholders})")
        params.extend(sorted(task_ids))
    if graph_run_ids:
        placeholders = ",".join("?" for _ in graph_run_ids)
        clauses.append(f"graph_run_id IN ({placeholders})")
        params.extend(sorted(graph_run_ids))
    if scope_ids:
        placeholders = ",".join("?" for _ in scope_ids)
        clauses.append(f"scope_id IN ({placeholders})")
        params.extend(sorted(scope_ids))
    return " OR ".join(clauses), params


def _artifact_repository_delete_where(*, task_ids: set[str], scope_ids: set[str]) -> tuple[str, list[str]]:
    clauses: list[str] = []
    params: list[str] = []
    if task_ids:
        placeholders = ",".join("?" for _ in task_ids)
        clauses.append(f"task_run_id IN ({placeholders})")
        params.extend(sorted(task_ids))
    if scope_ids:
        placeholders = ",".join("?" for _ in scope_ids)
        clauses.append(f"scope_id IN ({placeholders})")
        params.extend(sorted(scope_ids))
    return " OR ".join(clauses), params


def _protected_artifact_record_where() -> str:
    return "(durability_class IN ('project_artifact', 'user_asset') OR protected_reason <> '')"


def _protected_artifact_repository_where() -> str:
    return "durability_class IN ('project_artifact', 'user_asset')"


def content_hash(value: str) -> str:
    return hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()


def file_content_hash(path: Path) -> str:
    digest = hashlib.sha1()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repository_from_row(row: sqlite3.Row) -> ArtifactRepository:
    return ArtifactRepository(
        repository_id=str(row["repository_id"]),
        logical_repository_id=str(row["logical_repository_id"] or row["repository_id"]),
        effective_repository_id=str(row["effective_repository_id"] or row["repository_id"]),
        namespace_id=str(row["namespace_id"] or ""),
        storage_owner=str(row["storage_owner"] or ""),
        durability_class=str(row["durability_class"] or ""),
        retention_tier=str(row["retention_tier"] or ""),
        task_run_id=str(row["task_run_id"] or ""),
        scope_kind=str(row["scope_kind"] or "run_scoped"),
        scope_id=str(row["scope_id"] or ""),
        graph_id=str(row["graph_id"] or ""),
        node_id=str(row["node_id"] or ""),
        title=str(row["title"] or ""),
        lifecycle_policy=_loads(row["lifecycle_policy_json"], {}),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        authority=str(row["authority"] or "artifact_repository.repository"),
    )


def _record_from_row(row: sqlite3.Row) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=str(row["artifact_id"]),
        artifact_ref=str(row["artifact_ref"]),
        path=str(row["path"] or ""),
        repository_id=str(row["repository_id"]),
        collection_id=str(row["collection_id"] or "default"),
        namespace_id=str(row["namespace_id"] or ""),
        storage_owner=str(row["storage_owner"] or ""),
        physical_path=str(row["physical_path"] or ""),
        logical_path=str(row["logical_path"] or ""),
        durability_class=str(row["durability_class"] or ""),
        retention_tier=str(row["retention_tier"] or ""),
        materialization_receipt_id=str(row["materialization_receipt_id"] or ""),
        protected_reason=str(row["protected_reason"] or ""),
        output_contract_id=str(row["output_contract_id"] or ""),
        artifact_kind=str(row["artifact_kind"] or "file"),
        producer_node_id=str(row["producer_node_id"] or ""),
        content_type=str(row["content_type"] or ""),
        materialization_id=str(row["materialization_id"] or ""),
        logical_repository_id=str(row["logical_repository_id"] or row["repository_id"]),
        effective_repository_id=str(row["effective_repository_id"] or row["repository_id"]),
        task_run_id=str(row["task_run_id"] or ""),
        scope_kind=str(row["scope_kind"] or "run_scoped"),
        scope_id=str(row["scope_id"] or ""),
        graph_id=str(row["graph_id"] or ""),
        stage_id=str(row["stage_id"] or ""),
        node_run_id=str(row["node_run_id"] or ""),
        task_ref=str(row["task_ref"] or ""),
        graph_run_id=str(row["graph_run_id"] or ""),
        status=str(row["status"] or "accepted"),
        content_hash=str(row["content_hash"] or ""),
        metadata=_loads(row["metadata_json"], {}),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        authority=str(row["authority"] or "artifact_repository.record"),
    )


def _receipt_from_row(row: sqlite3.Row) -> ArtifactMaterializationReceipt:
    return ArtifactMaterializationReceipt(
        receipt_id=str(row["receipt_id"] or ""),
        source_kind=str(row["source_kind"] or ""),
        source_ref=str(row["source_ref"] or ""),
        target_namespace_id=str(row["target_namespace_id"] or ""),
        artifact_ids=tuple(str(item) for item in list(_loads(row["artifact_ids_json"], [])) if str(item)),
        content_hashes={
            str(key): str(value)
            for key, value in dict(_loads(row["content_hashes_json"], {})).items()
            if str(key)
        },
        producer_task_run_id=str(row["producer_task_run_id"] or ""),
        producer_graph_run_id=str(row["producer_graph_run_id"] or ""),
        producer_node_id=str(row["producer_node_id"] or ""),
        output_contract_id=str(row["output_contract_id"] or ""),
        status=str(row["status"] or "accepted"),
        metadata=_loads(row["metadata_json"], {}),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        authority=str(row["authority"] or "artifact_system.materializer"),
    )


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _loads(value: Any, default: Any) -> Any:
    try:
        payload = json.loads(str(value or ""))
    except (TypeError, json.JSONDecodeError):
        return default
    return payload if isinstance(payload, type(default)) else default


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_columns(conn: sqlite3.Connection, table_name: str, columns: dict[str, str]) -> None:
    existing = {
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    for column_name, column_spec in columns.items():
        if column_name in existing:
            continue
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_spec}")

