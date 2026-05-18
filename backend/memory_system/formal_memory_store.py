from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .formal_memory_models import (
    FormalMemoryCollection,
    FormalMemoryReadLog,
    FormalMemoryRecord,
    FormalMemoryRecordVersion,
    FormalMemoryRepository,
    FormalMemoryTransaction,
)


class FormalMemoryStore:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir = self.root_dir / "archive"
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root_dir / "formal_memory.sqlite"
        self._ensure_schema()

    def upsert_repository(self, repository: FormalMemoryRepository) -> FormalMemoryRepository:
        now = utc_now_iso()
        effective_repository_id = repository.effective_repository_id or repository.repository_id
        logical_repository_id = repository.logical_repository_id or repository.repository_id
        stored = replace(
            repository,
            repository_id=effective_repository_id,
            effective_repository_id=effective_repository_id,
            logical_repository_id=logical_repository_id,
            scope_id=repository.scope_id or repository.task_run_id or effective_repository_id,
            created_at=repository.created_at or now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO formal_repositories (
                    repository_id, logical_repository_id, effective_repository_id, task_run_id,
                    scope_kind, scope_id, graph_id, node_id, title, repository_kind,
                    lifecycle_policy_json, created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repository_id) DO UPDATE SET
                    logical_repository_id = excluded.logical_repository_id,
                    effective_repository_id = excluded.effective_repository_id,
                    task_run_id = excluded.task_run_id,
                    scope_kind = excluded.scope_kind,
                    scope_id = excluded.scope_id,
                    graph_id = excluded.graph_id,
                    node_id = excluded.node_id,
                    title = excluded.title,
                    repository_kind = excluded.repository_kind,
                    lifecycle_policy_json = excluded.lifecycle_policy_json,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.repository_id,
                    stored.logical_repository_id,
                    stored.effective_repository_id,
                    stored.task_run_id,
                    stored.scope_kind,
                    stored.scope_id,
                    stored.graph_id,
                    stored.node_id,
                    stored.title,
                    stored.repository_kind,
                    _json(stored.lifecycle_policy),
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def upsert_collection(self, collection: FormalMemoryCollection) -> FormalMemoryCollection:
        now = utc_now_iso()
        effective_repository_id = collection.effective_repository_id or collection.repository_id
        logical_repository_id = collection.logical_repository_id or collection.repository_id
        stored = replace(
            collection,
            repository_id=effective_repository_id,
            effective_repository_id=effective_repository_id,
            logical_repository_id=logical_repository_id,
            scope_id=collection.scope_id or collection.task_run_id or effective_repository_id,
            created_at=collection.created_at or now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO formal_collections (
                    repository_id, collection_id, logical_repository_id, effective_repository_id,
                    task_run_id, scope_kind, scope_id, title, schema_id, record_kinds_json,
                    key_strategy, default_version_selector, retention_policy_json,
                    created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repository_id, collection_id) DO UPDATE SET
                    logical_repository_id = excluded.logical_repository_id,
                    effective_repository_id = excluded.effective_repository_id,
                    task_run_id = excluded.task_run_id,
                    scope_kind = excluded.scope_kind,
                    scope_id = excluded.scope_id,
                    title = excluded.title,
                    schema_id = excluded.schema_id,
                    record_kinds_json = excluded.record_kinds_json,
                    key_strategy = excluded.key_strategy,
                    default_version_selector = excluded.default_version_selector,
                    retention_policy_json = excluded.retention_policy_json,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                (
                    stored.repository_id,
                    stored.collection_id,
                    stored.logical_repository_id,
                    stored.effective_repository_id,
                    stored.task_run_id,
                    stored.scope_kind,
                    stored.scope_id,
                    stored.title,
                    stored.schema_id,
                    _json(list(stored.record_kinds)),
                    stored.key_strategy,
                    stored.default_version_selector,
                    _json(stored.retention_policy),
                    stored.created_at,
                    stored.updated_at,
                    stored.authority,
                ),
            )
        return stored

    def get_repository(self, repository_id: str) -> FormalMemoryRepository | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM formal_repositories WHERE repository_id = ?",
                (repository_id,),
            ).fetchone()
        return _repository_from_row(row) if row is not None else None

    def get_collection(self, repository_id: str, collection_id: str) -> FormalMemoryCollection | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM formal_collections
                WHERE repository_id = ? AND collection_id = ?
                """,
                (repository_id, collection_id),
            ).fetchone()
        return _collection_from_row(row) if row is not None else None

    def list_repositories(self) -> tuple[FormalMemoryRepository, ...]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM formal_repositories ORDER BY repository_id ASC").fetchall()
        return tuple(_repository_from_row(row) for row in rows)

    def list_collections(self, repository_id: str = "") -> tuple[FormalMemoryCollection, ...]:
        sql = "SELECT * FROM formal_collections"
        params: list[Any] = []
        if repository_id:
            sql += " WHERE repository_id = ?"
            params.append(repository_id)
        sql += " ORDER BY repository_id ASC, collection_id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_collection_from_row(row) for row in rows)

    def list_records(
        self,
        *,
        task_run_id: str = "",
        repository_id: str = "",
        logical_repository_id: str = "",
        collection_id: str = "",
        limit: int = 500,
    ) -> tuple[FormalMemoryRecord, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if task_run_id:
            filters.append("task_run_id = ?")
            params.append(task_run_id)
        if repository_id:
            filters.append("(repository_id = ? OR logical_repository_id = ?)")
            params.extend([repository_id, repository_id])
        if logical_repository_id:
            filters.append("logical_repository_id = ?")
            params.append(logical_repository_id)
        if collection_id:
            filters.append("collection_id = ?")
            params.append(collection_id)
        sql = "SELECT * FROM formal_records"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY updated_at DESC, repository_id ASC, collection_id ASC, record_key ASC LIMIT ?"
        params.append(max(1, min(int(limit or 500), 2000)))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_record_from_row(row) for row in rows)

    def list_versions(
        self,
        *,
        task_run_id: str = "",
        repository_id: str = "",
        logical_repository_id: str = "",
        collection_id: str = "",
        record_key: str = "",
        limit: int = 500,
    ) -> tuple[FormalMemoryRecordVersion, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if task_run_id:
            filters.append("task_run_id = ?")
            params.append(task_run_id)
        if repository_id:
            filters.append("(repository_id = ? OR logical_repository_id = ?)")
            params.extend([repository_id, repository_id])
        if logical_repository_id:
            filters.append("logical_repository_id = ?")
            params.append(logical_repository_id)
        if collection_id:
            filters.append("collection_id = ?")
            params.append(collection_id)
        if record_key:
            filters.append("record_key = ?")
            params.append(record_key)
        sql = "SELECT * FROM formal_record_versions"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY created_at DESC, repository_id ASC, collection_id ASC, record_key ASC LIMIT ?"
        params.append(max(1, min(int(limit or 500), 2000)))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_version_from_row(row) for row in rows)

    def list_read_logs(self, *, task_run_id: str = "", repository_id: str = "", limit: int = 500) -> tuple[dict[str, Any], ...]:
        filters: list[str] = []
        params: list[Any] = []
        if task_run_id:
            filters.append("task_run_id = ?")
            params.append(task_run_id)
        if repository_id:
            filters.append("(repository_id = ? OR logical_repository_id = ?)")
            params.extend([repository_id, repository_id])
        sql = "SELECT * FROM formal_memory_read_logs"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit or 500), 2000)))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_read_log_payload(row) for row in rows)

    def get_record_by_key(
        self,
        *,
        repository_id: str,
        collection_id: str,
        record_key: str,
    ) -> FormalMemoryRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM formal_records
                WHERE repository_id = ? AND collection_id = ? AND record_key = ?
                """,
                (repository_id, collection_id, record_key),
            ).fetchone()
        return _record_from_row(row) if row is not None else None

    def get_version(self, version_id: str) -> FormalMemoryRecordVersion | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM formal_record_versions WHERE version_id = ?",
                (version_id,),
            ).fetchone()
        return _version_from_row(row) if row is not None else None

    def get_transaction_by_idempotency(self, idempotency_key: str) -> FormalMemoryTransaction | None:
        if not idempotency_key:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM formal_memory_transactions WHERE idempotency_key = ? LIMIT 1",
                (idempotency_key,),
            ).fetchone()
        return _transaction_from_row(row) if row is not None else None

    def write_candidate(
        self,
        *,
        repository_id: str,
        collection_id: str,
        record_key: str,
        logical_repository_id: str = "",
        task_run_id: str = "",
        scope_kind: str = "run_scoped",
        scope_id: str = "",
        record_kind: str = "",
        payload: dict[str, Any] | None = None,
        canonical_text: str = "",
        summary: str = "",
        artifact_refs: list[str] | tuple[str, ...] = (),
        source_node_id: str = "",
        source_edge_id: str = "",
        source_node_run_id: str = "",
        source_clock: str = "",
        source_clock_seq: int = 0,
        idempotency_key: str = "",
    ) -> tuple[FormalMemoryRecordVersion, FormalMemoryTransaction]:
        repository_id = _required(repository_id, "repository_id")
        collection_id = _required(collection_id, "collection_id")
        record_key = _required(record_key, "record_key")
        effective_repository_id = repository_id
        logical_repository_id = logical_repository_id or repository_id
        scope_id = scope_id or task_run_id or repository_id
        idempotency_key = idempotency_key or _stable_id(
            "fmidem",
            repository_id,
            collection_id,
            record_key,
            source_node_run_id,
            source_edge_id,
            _content_hash(payload or {}, canonical_text, summary, artifact_refs),
        )
        existing_transaction = self.get_transaction_by_idempotency(idempotency_key)
        if existing_transaction and existing_transaction.candidate_version_id:
            existing_version = self.get_version(existing_transaction.candidate_version_id)
            if existing_version is not None:
                return existing_version, existing_transaction
        now = utc_now_iso()
        content_hash = _content_hash(payload or {}, canonical_text, summary, artifact_refs)
        record_id = _stable_id("fmrec", effective_repository_id, collection_id, record_key)
        transaction_id = _stable_id("fmtxn", idempotency_key)
        with self._connect() as conn:
            _ensure_repository_collection(
                conn,
                repository_id=effective_repository_id,
                collection_id=collection_id,
                logical_repository_id=logical_repository_id,
                task_run_id=task_run_id,
                scope_kind=scope_kind,
                scope_id=scope_id,
                now=now,
            )
            record_row = conn.execute(
                "SELECT * FROM formal_records WHERE record_id = ?",
                (record_id,),
            ).fetchone()
            if record_row is None:
                conn.execute(
                    """
                    INSERT INTO formal_records (
                        record_id, repository_id, collection_id, record_key, logical_repository_id,
                        effective_repository_id, task_run_id, scope_kind, scope_id, record_kind,
                        status, current_committed_version, head_version_id, created_at, updated_at, authority
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record_id,
                        effective_repository_id,
                        collection_id,
                        record_key,
                        logical_repository_id,
                        effective_repository_id,
                        task_run_id,
                        scope_kind,
                        scope_id,
                        record_kind,
                        "active",
                        0,
                        "",
                        now,
                        now,
                        "formal_memory.record",
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE formal_records
                    SET record_kind = CASE WHEN record_kind = '' THEN ? ELSE record_kind END,
                        updated_at = ?
                    WHERE record_id = ?
                    """,
                    (record_kind, now, record_id),
                )
            max_version = conn.execute(
                "SELECT MAX(version) FROM formal_record_versions WHERE record_id = ?",
                (record_id,),
            ).fetchone()[0]
            version = int(max_version or 0) + 1
            version_id = _stable_id("fmver", record_id, str(version), content_hash, idempotency_key)
            conn.execute(
                """
                INSERT INTO formal_record_versions (
                    version_id, record_id, repository_id, collection_id, record_key,
                    logical_repository_id, effective_repository_id, task_run_id, scope_kind, scope_id, record_kind,
                    version, status, payload_json, canonical_text, summary, artifact_refs_json,
                    source_node_id, source_edge_id, source_node_run_id, source_clock, source_clock_seq,
                    visible_after_clock, visible_after_clock_seq, content_hash,
                    supersedes_version_id, created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    record_id,
                    effective_repository_id,
                    collection_id,
                    record_key,
                    logical_repository_id,
                    effective_repository_id,
                    task_run_id,
                    scope_kind,
                    scope_id,
                    record_kind,
                    version,
                    "candidate",
                    _json(payload or {}),
                    canonical_text,
                    summary,
                    _json(_strings(artifact_refs)),
                    source_node_id,
                    source_edge_id,
                    source_node_run_id,
                    source_clock,
                    int(source_clock_seq or 0),
                    source_clock,
                    int(source_clock_seq or 0),
                    content_hash,
                    "",
                    now,
                    now,
                    "formal_memory.record_version",
                ),
            )
            receipt = {
                "transaction_id": transaction_id,
                "operation": "write_candidate",
                "repository_id": effective_repository_id,
                "logical_repository_id": logical_repository_id,
                "effective_repository_id": effective_repository_id,
                "task_run_id": task_run_id,
                "scope_kind": scope_kind,
                "scope_id": scope_id,
                "collection_id": collection_id,
                "record_id": record_id,
                "record_key": record_key,
                "version_id": version_id,
                "version": version,
                "status": "candidate",
                "content_hash": content_hash,
                "source_clock": source_clock,
                "source_clock_seq": int(source_clock_seq or 0),
            }
            conn.execute(
                """
                INSERT INTO formal_memory_transactions (
                    transaction_id, operation, edge_id, node_run_id, repository_id, collection_id,
                    record_key, record_id, logical_repository_id, effective_repository_id,
                    task_run_id, scope_kind, scope_id, candidate_version_id, committed_version_id,
                    receipt_json, status, idempotency_key, created_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transaction_id,
                    "write_candidate",
                    source_edge_id,
                    source_node_run_id,
                    effective_repository_id,
                    collection_id,
                    record_key,
                    record_id,
                    logical_repository_id,
                    effective_repository_id,
                    task_run_id,
                    scope_kind,
                    scope_id,
                    version_id,
                    "",
                    _json(receipt),
                    "completed",
                    idempotency_key,
                    now,
                    "formal_memory.transaction",
                ),
            )
        version_obj = self.get_version(version_id)
        txn = self.get_transaction_by_idempotency(idempotency_key)
        if version_obj is None or txn is None:
            raise RuntimeError("Formal memory candidate write did not persist")
        return version_obj, txn

    def commit_version(
        self,
        *,
        candidate_version_id: str,
        edge_id: str = "",
        node_run_id: str = "",
        source_clock: str = "",
        source_clock_seq: int = 0,
        visible_after_clock: str = "",
        visible_after_clock_seq: int = 0,
        idempotency_key: str = "",
        reject: bool = False,
        reject_reason: str = "",
    ) -> tuple[FormalMemoryRecordVersion, FormalMemoryTransaction]:
        candidate_version_id = _required(candidate_version_id, "candidate_version_id")
        status = "rejected" if reject else "committed"
        idempotency_key = idempotency_key or _stable_id("fmidem", "commit", candidate_version_id, node_run_id, edge_id, status)
        existing_transaction = self.get_transaction_by_idempotency(idempotency_key)
        if existing_transaction:
            existing_version = self.get_version(existing_transaction.committed_version_id or existing_transaction.candidate_version_id)
            if existing_version is not None:
                return existing_version, existing_transaction
        current = self.get_version(candidate_version_id)
        if current is None:
            raise KeyError(f"Unknown formal memory candidate version: {candidate_version_id}")
        now = utc_now_iso()
        transaction_id = _stable_id("fmtxn", idempotency_key)
        visible_clock = visible_after_clock or source_clock
        visible_clock_seq = int(visible_after_clock_seq or source_clock_seq or 0)
        with self._connect() as conn:
            if reject:
                conn.execute(
                    """
                    UPDATE formal_record_versions
                    SET status = ?, updated_at = ?
                    WHERE version_id = ?
                    """,
                    ("rejected", now, candidate_version_id),
                )
                committed_version_id = ""
            else:
                previous = conn.execute(
                    """
                    SELECT head_version_id FROM formal_records
                    WHERE record_id = ?
                    """,
                    (current.record_id,),
                ).fetchone()
                previous_head = str(previous["head_version_id"] or "") if previous is not None else ""
                if previous_head and previous_head != candidate_version_id:
                    conn.execute(
                        """
                        UPDATE formal_record_versions
                        SET status = ?, supersedes_version_id = CASE WHEN supersedes_version_id = '' THEN supersedes_version_id ELSE supersedes_version_id END,
                            updated_at = ?
                        WHERE version_id = ? AND status = 'committed'
                        """,
                        ("superseded", now, previous_head),
                    )
                conn.execute(
                    """
                    UPDATE formal_record_versions
                    SET status = ?, visible_after_clock = ?, visible_after_clock_seq = ?, updated_at = ?
                    WHERE version_id = ?
                    """,
                    ("committed", visible_clock, visible_clock_seq, now, candidate_version_id),
                )
                conn.execute(
                    """
                    UPDATE formal_records
                    SET current_committed_version = ?, head_version_id = ?, updated_at = ?
                    WHERE record_id = ?
                    """,
                    (current.version, candidate_version_id, now, current.record_id),
                )
                committed_version_id = candidate_version_id
            receipt = {
                "transaction_id": transaction_id,
                "operation": "memory_commit",
                "repository_id": current.repository_id,
                "logical_repository_id": current.logical_repository_id,
                "effective_repository_id": current.effective_repository_id or current.repository_id,
                "task_run_id": current.task_run_id,
                "scope_kind": current.scope_kind,
                "scope_id": current.scope_id,
                "collection_id": current.collection_id,
                "record_id": current.record_id,
                "record_key": current.record_key,
                "candidate_version_id": candidate_version_id,
                "committed_version_id": committed_version_id,
                "status": status,
                "visible_after_clock": visible_clock,
                "visible_after_clock_seq": visible_clock_seq,
                "content_hash": current.content_hash,
                "reject_reason": reject_reason,
            }
            conn.execute(
                """
                INSERT INTO formal_memory_transactions (
                    transaction_id, operation, edge_id, node_run_id, repository_id, collection_id,
                    record_key, record_id, logical_repository_id, effective_repository_id,
                    task_run_id, scope_kind, scope_id, candidate_version_id, committed_version_id,
                    receipt_json, status, idempotency_key, created_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transaction_id,
                    "memory_commit",
                    edge_id,
                    node_run_id,
                    current.repository_id,
                    current.collection_id,
                    current.record_key,
                    current.record_id,
                    current.logical_repository_id,
                    current.effective_repository_id or current.repository_id,
                    current.task_run_id,
                    current.scope_kind,
                    current.scope_id,
                    candidate_version_id,
                    committed_version_id,
                    _json(receipt),
                    status,
                    idempotency_key,
                    now,
                    "formal_memory.transaction",
                ),
            )
        version = self.get_version(candidate_version_id)
        txn = self.get_transaction_by_idempotency(idempotency_key)
        if version is None or txn is None:
            raise RuntimeError("Formal memory commit did not persist")
        return version, txn

    def select_versions(
        self,
        *,
        repository_id: str,
        collection_id: str,
        logical_repository_id: str = "",
        task_run_id: str = "",
        scope_kind: str = "run_scoped",
        scope_id: str = "",
        selector: dict[str, Any] | None = None,
        version_selector: str | dict[str, Any] = "",
        clock: str = "",
        clock_seq: int = 0,
        edge_id: str = "",
        node_run_id: str = "",
        limit: int = 50,
    ) -> tuple[tuple[FormalMemoryRecordVersion, ...], FormalMemoryReadLog]:
        selector = dict(selector or {})
        repository_id = _required(repository_id, "repository_id")
        collection_id = _required(collection_id or selector.get("collection"), "collection_id")
        logical_repository_id = logical_repository_id or selector.get("logical_repository_id") or repository_id
        scope_id = scope_id or selector.get("scope_id") or task_run_id or repository_id
        record_keys = _strings(selector.get("record_keys") or selector.get("record_key"))
        record_kinds = _strings(selector.get("record_kinds") or selector.get("record_kind"))
        statuses = _strings(selector.get("status_filter") or selector.get("statuses")) or ["committed"]
        mode = _version_selector_mode(version_selector)
        limit = max(1, min(int(selector.get("limit") or limit or 50), 500))
        filters = [
            "repository_id = ?",
            "collection_id = ?",
        ]
        params: list[Any] = [repository_id, collection_id]
        if task_run_id:
            filters.append("task_run_id = ?")
            params.append(task_run_id)
        if scope_kind:
            filters.append("scope_kind = ?")
            params.append(scope_kind)
        if scope_id:
            filters.append("scope_id = ?")
            params.append(scope_id)
        if statuses:
            filters.append(f"status IN ({','.join('?' for _ in statuses)})")
            params.extend(statuses)
        if record_keys:
            filters.append(f"record_key IN ({','.join('?' for _ in record_keys)})")
            params.extend(record_keys)
        if record_kinds:
            filters.append(f"record_kind IN ({','.join('?' for _ in record_kinds)})")
            params.extend(record_kinds)
        if mode in {"latest_committed_before_clock", "latest_committed_before_scope"}:
            filters.append("visible_after_clock_seq <= ?")
            params.append(int(clock_seq or 0))
        sql = "SELECT * FROM formal_record_versions WHERE " + " AND ".join(filters)
        sql += " ORDER BY record_id ASC, version DESC LIMIT ?"
        params.append(limit * 5)
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        selected_by_record: dict[str, FormalMemoryRecordVersion] = {}
        selected: list[FormalMemoryRecordVersion] = []
        for row in rows:
            version = _version_from_row(row)
            if mode.startswith("latest_"):
                if version.record_id in selected_by_record:
                    continue
                selected_by_record[version.record_id] = version
            else:
                selected.append(version)
        if mode.startswith("latest_"):
            selected = list(selected_by_record.values())
        selected = selected[:limit]
        read_log = FormalMemoryReadLog(
            read_log_id=_stable_id(
                "fmread",
                node_run_id,
                edge_id,
                repository_id,
                collection_id,
                logical_repository_id,
                task_run_id,
                scope_kind,
                scope_id,
                json.dumps(selector, ensure_ascii=False, sort_keys=True),
                str(clock_seq),
                ",".join(item.version_id for item in selected),
            ),
            edge_id=edge_id,
            node_run_id=node_run_id,
            repository_id=repository_id,
            collection_id=collection_id,
            logical_repository_id=logical_repository_id,
            effective_repository_id=repository_id,
            task_run_id=task_run_id,
            scope_kind=scope_kind,
            scope_id=scope_id,
            selector=selector,
            selected_version_ids=tuple(item.version_id for item in selected),
            clock=clock,
            clock_seq=int(clock_seq or 0),
        )
        stored_log = self.append_read_log(read_log)
        return tuple(selected), stored_log

    def append_read_log(self, log: FormalMemoryReadLog) -> FormalMemoryReadLog:
        stored = replace(log, created_at=log.created_at or utc_now_iso())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO formal_memory_read_logs (
                    read_log_id, edge_id, node_run_id, repository_id, collection_id,
                    logical_repository_id, effective_repository_id, task_run_id, scope_kind, scope_id,
                    selector_json, selected_version_ids_json, clock, clock_seq,
                    created_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stored.read_log_id,
                    stored.edge_id,
                    stored.node_run_id,
                    stored.repository_id,
                    stored.collection_id,
                    stored.logical_repository_id,
                    stored.effective_repository_id or stored.repository_id,
                    stored.task_run_id,
                    stored.scope_kind,
                    stored.scope_id,
                    _json(stored.selector),
                    _json(list(stored.selected_version_ids)),
                    stored.clock,
                    stored.clock_seq,
                    stored.created_at,
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
                CREATE TABLE IF NOT EXISTS formal_repositories (
                    repository_id TEXT PRIMARY KEY,
                    logical_repository_id TEXT NOT NULL DEFAULT '',
                    effective_repository_id TEXT NOT NULL DEFAULT '',
                    task_run_id TEXT NOT NULL DEFAULT '',
                    scope_kind TEXT NOT NULL DEFAULT 'run_scoped',
                    scope_id TEXT NOT NULL DEFAULT '',
                    graph_id TEXT NOT NULL DEFAULT '',
                    node_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    repository_kind TEXT NOT NULL DEFAULT 'formal_memory',
                    lifecycle_policy_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'formal_memory.repository'
                );

                CREATE TABLE IF NOT EXISTS formal_collections (
                    repository_id TEXT NOT NULL,
                    collection_id TEXT NOT NULL,
                    logical_repository_id TEXT NOT NULL DEFAULT '',
                    effective_repository_id TEXT NOT NULL DEFAULT '',
                    task_run_id TEXT NOT NULL DEFAULT '',
                    scope_kind TEXT NOT NULL DEFAULT 'run_scoped',
                    scope_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    schema_id TEXT NOT NULL DEFAULT '',
                    record_kinds_json TEXT NOT NULL DEFAULT '[]',
                    key_strategy TEXT NOT NULL DEFAULT 'stable_key',
                    default_version_selector TEXT NOT NULL DEFAULT 'latest_committed_before_clock',
                    retention_policy_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'formal_memory.collection',
                    PRIMARY KEY(repository_id, collection_id)
                );

                CREATE TABLE IF NOT EXISTS formal_records (
                    record_id TEXT PRIMARY KEY,
                    repository_id TEXT NOT NULL,
                    collection_id TEXT NOT NULL,
                    record_key TEXT NOT NULL,
                    logical_repository_id TEXT NOT NULL DEFAULT '',
                    effective_repository_id TEXT NOT NULL DEFAULT '',
                    task_run_id TEXT NOT NULL DEFAULT '',
                    scope_kind TEXT NOT NULL DEFAULT 'run_scoped',
                    scope_id TEXT NOT NULL DEFAULT '',
                    record_kind TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    current_committed_version INTEGER NOT NULL DEFAULT 0,
                    head_version_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'formal_memory.record',
                    UNIQUE(repository_id, collection_id, record_key)
                );

                CREATE TABLE IF NOT EXISTS formal_record_versions (
                    version_id TEXT PRIMARY KEY,
                    record_id TEXT NOT NULL,
                    repository_id TEXT NOT NULL,
                    collection_id TEXT NOT NULL,
                    record_key TEXT NOT NULL,
                    logical_repository_id TEXT NOT NULL DEFAULT '',
                    effective_repository_id TEXT NOT NULL DEFAULT '',
                    task_run_id TEXT NOT NULL DEFAULT '',
                    scope_kind TEXT NOT NULL DEFAULT 'run_scoped',
                    scope_id TEXT NOT NULL DEFAULT '',
                    record_kind TEXT NOT NULL DEFAULT '',
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'candidate',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    canonical_text TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    artifact_refs_json TEXT NOT NULL DEFAULT '[]',
                    source_node_id TEXT NOT NULL DEFAULT '',
                    source_edge_id TEXT NOT NULL DEFAULT '',
                    source_node_run_id TEXT NOT NULL DEFAULT '',
                    source_clock TEXT NOT NULL DEFAULT '',
                    source_clock_seq INTEGER NOT NULL DEFAULT 0,
                    visible_after_clock TEXT NOT NULL DEFAULT '',
                    visible_after_clock_seq INTEGER NOT NULL DEFAULT 0,
                    content_hash TEXT NOT NULL DEFAULT '',
                    supersedes_version_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'formal_memory.record_version',
                    UNIQUE(record_id, version)
                );

                CREATE TABLE IF NOT EXISTS formal_memory_transactions (
                    transaction_id TEXT PRIMARY KEY,
                    operation TEXT NOT NULL,
                    edge_id TEXT NOT NULL DEFAULT '',
                    node_run_id TEXT NOT NULL DEFAULT '',
                    repository_id TEXT NOT NULL DEFAULT '',
                    collection_id TEXT NOT NULL DEFAULT '',
                    record_key TEXT NOT NULL DEFAULT '',
                    record_id TEXT NOT NULL DEFAULT '',
                    logical_repository_id TEXT NOT NULL DEFAULT '',
                    effective_repository_id TEXT NOT NULL DEFAULT '',
                    task_run_id TEXT NOT NULL DEFAULT '',
                    scope_kind TEXT NOT NULL DEFAULT 'run_scoped',
                    scope_id TEXT NOT NULL DEFAULT '',
                    candidate_version_id TEXT NOT NULL DEFAULT '',
                    committed_version_id TEXT NOT NULL DEFAULT '',
                    receipt_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'completed',
                    idempotency_key TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'formal_memory.transaction',
                    UNIQUE(idempotency_key)
                );

                CREATE TABLE IF NOT EXISTS formal_memory_read_logs (
                    read_log_id TEXT PRIMARY KEY,
                    edge_id TEXT NOT NULL DEFAULT '',
                    node_run_id TEXT NOT NULL DEFAULT '',
                    repository_id TEXT NOT NULL DEFAULT '',
                    collection_id TEXT NOT NULL DEFAULT '',
                    logical_repository_id TEXT NOT NULL DEFAULT '',
                    effective_repository_id TEXT NOT NULL DEFAULT '',
                    task_run_id TEXT NOT NULL DEFAULT '',
                    scope_kind TEXT NOT NULL DEFAULT 'run_scoped',
                    scope_id TEXT NOT NULL DEFAULT '',
                    selector_json TEXT NOT NULL DEFAULT '{}',
                    selected_version_ids_json TEXT NOT NULL DEFAULT '[]',
                    clock TEXT NOT NULL DEFAULT '',
                    clock_seq INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT 'formal_memory.read_log'
                );

                CREATE INDEX IF NOT EXISTS idx_formal_record_lookup
                    ON formal_records(repository_id, collection_id, record_key);
                CREATE INDEX IF NOT EXISTS idx_formal_record_scope
                    ON formal_records(task_run_id, logical_repository_id, collection_id, record_key);
                CREATE INDEX IF NOT EXISTS idx_formal_record_kind
                    ON formal_records(repository_id, collection_id, record_kind);
                CREATE INDEX IF NOT EXISTS idx_formal_version_record_status
                    ON formal_record_versions(record_id, status, version);
                CREATE INDEX IF NOT EXISTS idx_formal_version_visible_clock
                    ON formal_record_versions(record_id, status, visible_after_clock_seq);
                CREATE INDEX IF NOT EXISTS idx_formal_transaction_edge
                    ON formal_memory_transactions(edge_id, node_run_id);
                CREATE INDEX IF NOT EXISTS idx_formal_read_log_node
                    ON formal_memory_read_logs(node_run_id, edge_id);
                CREATE INDEX IF NOT EXISTS idx_formal_read_log_scope
                    ON formal_memory_read_logs(task_run_id, logical_repository_id, collection_id);
                """
            )
            _ensure_scope_columns(conn)


def _ensure_scope_columns(conn: sqlite3.Connection) -> None:
    table_columns = {
        "formal_repositories": {
            "logical_repository_id": "TEXT NOT NULL DEFAULT ''",
            "effective_repository_id": "TEXT NOT NULL DEFAULT ''",
            "task_run_id": "TEXT NOT NULL DEFAULT ''",
            "scope_kind": "TEXT NOT NULL DEFAULT 'run_scoped'",
            "scope_id": "TEXT NOT NULL DEFAULT ''",
        },
        "formal_collections": {
            "logical_repository_id": "TEXT NOT NULL DEFAULT ''",
            "effective_repository_id": "TEXT NOT NULL DEFAULT ''",
            "task_run_id": "TEXT NOT NULL DEFAULT ''",
            "scope_kind": "TEXT NOT NULL DEFAULT 'run_scoped'",
            "scope_id": "TEXT NOT NULL DEFAULT ''",
        },
        "formal_records": {
            "logical_repository_id": "TEXT NOT NULL DEFAULT ''",
            "effective_repository_id": "TEXT NOT NULL DEFAULT ''",
            "task_run_id": "TEXT NOT NULL DEFAULT ''",
            "scope_kind": "TEXT NOT NULL DEFAULT 'run_scoped'",
            "scope_id": "TEXT NOT NULL DEFAULT ''",
        },
        "formal_record_versions": {
            "logical_repository_id": "TEXT NOT NULL DEFAULT ''",
            "effective_repository_id": "TEXT NOT NULL DEFAULT ''",
            "task_run_id": "TEXT NOT NULL DEFAULT ''",
            "scope_kind": "TEXT NOT NULL DEFAULT 'run_scoped'",
            "scope_id": "TEXT NOT NULL DEFAULT ''",
        },
        "formal_memory_transactions": {
            "logical_repository_id": "TEXT NOT NULL DEFAULT ''",
            "effective_repository_id": "TEXT NOT NULL DEFAULT ''",
            "task_run_id": "TEXT NOT NULL DEFAULT ''",
            "scope_kind": "TEXT NOT NULL DEFAULT 'run_scoped'",
            "scope_id": "TEXT NOT NULL DEFAULT ''",
        },
        "formal_memory_read_logs": {
            "logical_repository_id": "TEXT NOT NULL DEFAULT ''",
            "effective_repository_id": "TEXT NOT NULL DEFAULT ''",
            "task_run_id": "TEXT NOT NULL DEFAULT ''",
            "scope_kind": "TEXT NOT NULL DEFAULT 'run_scoped'",
            "scope_id": "TEXT NOT NULL DEFAULT ''",
        },
    }
    for table, columns in table_columns.items():
        existing = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for column, column_type in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def _ensure_repository_collection(
    conn: sqlite3.Connection,
    *,
    repository_id: str,
    collection_id: str,
    logical_repository_id: str = "",
    task_run_id: str = "",
    scope_kind: str = "run_scoped",
    scope_id: str = "",
    now: str,
) -> None:
    logical_repository_id = logical_repository_id or repository_id
    scope_id = scope_id or task_run_id or repository_id
    repo = conn.execute("SELECT repository_id FROM formal_repositories WHERE repository_id = ?", (repository_id,)).fetchone()
    if repo is None:
        conn.execute(
            """
            INSERT INTO formal_repositories (
                repository_id, logical_repository_id, effective_repository_id, task_run_id,
                scope_kind, scope_id, title, repository_kind, lifecycle_policy_json,
                created_at, updated_at, authority
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                repository_id,
                logical_repository_id,
                repository_id,
                task_run_id,
                scope_kind,
                scope_id,
                logical_repository_id,
                "implicit_from_memory_edge",
                "{}",
                now,
                now,
                "formal_memory.repository.implicit",
            ),
        )
    collection = conn.execute(
        """
        SELECT collection_id FROM formal_collections
        WHERE repository_id = ? AND collection_id = ?
        """,
        (repository_id, collection_id),
    ).fetchone()
    if collection is None:
        conn.execute(
            """
            INSERT INTO formal_collections (
                repository_id, collection_id, logical_repository_id, effective_repository_id,
                task_run_id, scope_kind, scope_id, title, schema_id, record_kinds_json,
                key_strategy, default_version_selector, retention_policy_json,
                created_at, updated_at, authority
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                repository_id,
                collection_id,
                logical_repository_id,
                repository_id,
                task_run_id,
                scope_kind,
                scope_id,
                collection_id,
                "schema.formal_memory_record",
                "[]",
                "stable_key",
                "latest_committed_before_clock",
                "{}",
                now,
                now,
                "formal_memory.collection.implicit",
            ),
        )


def _repository_from_row(row: sqlite3.Row) -> FormalMemoryRepository:
    return FormalMemoryRepository(
        repository_id=str(row["repository_id"]),
        logical_repository_id=_row_value(row, "logical_repository_id") or str(row["repository_id"]),
        effective_repository_id=_row_value(row, "effective_repository_id") or str(row["repository_id"]),
        task_run_id=_row_value(row, "task_run_id"),
        scope_kind=_row_value(row, "scope_kind") or "run_scoped",
        scope_id=_row_value(row, "scope_id"),
        graph_id=str(row["graph_id"]),
        node_id=str(row["node_id"]),
        title=str(row["title"]),
        repository_kind=str(row["repository_kind"]),
        lifecycle_policy=_loads(row["lifecycle_policy_json"], {}),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        authority=str(row["authority"]),
    )


def _collection_from_row(row: sqlite3.Row) -> FormalMemoryCollection:
    return FormalMemoryCollection(
        repository_id=str(row["repository_id"]),
        collection_id=str(row["collection_id"]),
        logical_repository_id=_row_value(row, "logical_repository_id") or str(row["repository_id"]),
        effective_repository_id=_row_value(row, "effective_repository_id") or str(row["repository_id"]),
        task_run_id=_row_value(row, "task_run_id"),
        scope_kind=_row_value(row, "scope_kind") or "run_scoped",
        scope_id=_row_value(row, "scope_id"),
        title=str(row["title"]),
        schema_id=str(row["schema_id"]),
        record_kinds=tuple(_strings(_loads(row["record_kinds_json"], []))),
        key_strategy=str(row["key_strategy"]),
        default_version_selector=str(row["default_version_selector"]),
        retention_policy=_loads(row["retention_policy_json"], {}),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        authority=str(row["authority"]),
    )


def _record_from_row(row: sqlite3.Row) -> FormalMemoryRecord:
    return FormalMemoryRecord(
        record_id=str(row["record_id"]),
        repository_id=str(row["repository_id"]),
        collection_id=str(row["collection_id"]),
        record_key=str(row["record_key"]),
        logical_repository_id=_row_value(row, "logical_repository_id") or str(row["repository_id"]),
        effective_repository_id=_row_value(row, "effective_repository_id") or str(row["repository_id"]),
        task_run_id=_row_value(row, "task_run_id"),
        scope_kind=_row_value(row, "scope_kind") or "run_scoped",
        scope_id=_row_value(row, "scope_id"),
        record_kind=str(row["record_kind"]),
        status=str(row["status"]),
        current_committed_version=int(row["current_committed_version"] or 0),
        head_version_id=str(row["head_version_id"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        authority=str(row["authority"]),
    )


def _version_from_row(row: sqlite3.Row) -> FormalMemoryRecordVersion:
    return FormalMemoryRecordVersion(
        version_id=str(row["version_id"]),
        record_id=str(row["record_id"]),
        repository_id=str(row["repository_id"]),
        collection_id=str(row["collection_id"]),
        record_key=str(row["record_key"]),
        logical_repository_id=_row_value(row, "logical_repository_id") or str(row["repository_id"]),
        effective_repository_id=_row_value(row, "effective_repository_id") or str(row["repository_id"]),
        task_run_id=_row_value(row, "task_run_id"),
        scope_kind=_row_value(row, "scope_kind") or "run_scoped",
        scope_id=_row_value(row, "scope_id"),
        record_kind=str(row["record_kind"]),
        version=int(row["version"] or 0),
        status=str(row["status"]),
        payload=_loads(row["payload_json"], {}),
        canonical_text=str(row["canonical_text"]),
        summary=str(row["summary"]),
        artifact_refs=tuple(_strings(_loads(row["artifact_refs_json"], []))),
        source_node_id=str(row["source_node_id"]),
        source_edge_id=str(row["source_edge_id"]),
        source_node_run_id=str(row["source_node_run_id"]),
        source_clock=str(row["source_clock"]),
        source_clock_seq=int(row["source_clock_seq"] or 0),
        visible_after_clock=str(row["visible_after_clock"]),
        visible_after_clock_seq=int(row["visible_after_clock_seq"] or 0),
        content_hash=str(row["content_hash"]),
        supersedes_version_id=str(row["supersedes_version_id"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        authority=str(row["authority"]),
    )


def _transaction_from_row(row: sqlite3.Row) -> FormalMemoryTransaction:
    return FormalMemoryTransaction(
        transaction_id=str(row["transaction_id"]),
        operation=str(row["operation"]),
        edge_id=str(row["edge_id"]),
        node_run_id=str(row["node_run_id"]),
        repository_id=str(row["repository_id"]),
        collection_id=str(row["collection_id"]),
        record_key=str(row["record_key"]),
        record_id=str(row["record_id"]),
        logical_repository_id=_row_value(row, "logical_repository_id") or str(row["repository_id"]),
        effective_repository_id=_row_value(row, "effective_repository_id") or str(row["repository_id"]),
        task_run_id=_row_value(row, "task_run_id"),
        scope_kind=_row_value(row, "scope_kind") or "run_scoped",
        scope_id=_row_value(row, "scope_id"),
        candidate_version_id=str(row["candidate_version_id"]),
        committed_version_id=str(row["committed_version_id"]),
        receipt=_loads(row["receipt_json"], {}),
        status=str(row["status"]),
        idempotency_key=str(row["idempotency_key"]),
        created_at=str(row["created_at"]),
        authority=str(row["authority"]),
    )


def _read_log_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "read_log_id": str(row["read_log_id"]),
        "edge_id": str(row["edge_id"]),
        "node_run_id": str(row["node_run_id"]),
        "repository_id": str(row["repository_id"]),
        "logical_repository_id": _row_value(row, "logical_repository_id") or str(row["repository_id"]),
        "effective_repository_id": _row_value(row, "effective_repository_id") or str(row["repository_id"]),
        "task_run_id": _row_value(row, "task_run_id"),
        "scope_kind": _row_value(row, "scope_kind") or "run_scoped",
        "scope_id": _row_value(row, "scope_id"),
        "collection_id": str(row["collection_id"]),
        "selector": _loads(row["selector_json"], {}),
        "selected_version_ids": _loads(row["selected_version_ids_json"], []),
        "clock": str(row["clock"]),
        "clock_seq": int(row["clock_seq"] or 0),
        "created_at": str(row["created_at"]),
        "authority": str(row["authority"]),
    }


def _row_value(row: sqlite3.Row, key: str) -> str:
    try:
        return str(row[key] or "")
    except (KeyError, IndexError):
        return ""


def _version_selector_mode(value: str | dict[str, Any]) -> str:
    if isinstance(value, dict):
        return str(value.get("mode") or value.get("strategy") or "latest_committed_before_clock").strip()
    return str(value or "latest_committed_before_clock").strip() or "latest_committed_before_clock"


def _content_hash(payload: dict[str, Any], canonical_text: str, summary: str, artifact_refs: list[str] | tuple[str, ...]) -> str:
    raw = json.dumps(
        {
            "payload": payload,
            "canonical_text": canonical_text,
            "summary": summary,
            "artifact_refs": _strings(artifact_refs),
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(str(part or "").strip() for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}:{digest}"


def _required(value: Any, key: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"FormalMemoryStore requires {key}")
    return text


def _strings(values: Any) -> list[str]:
    if isinstance(values, str):
        return [values.strip()] if values.strip() else []
    return [str(item).strip() for item in list(values or []) if str(item).strip()]


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _loads(value: Any, default: Any) -> Any:
    try:
        return json.loads(str(value or ""))
    except (TypeError, json.JSONDecodeError):
        return default


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
