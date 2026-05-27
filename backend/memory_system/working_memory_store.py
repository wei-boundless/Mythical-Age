from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .working_memory_models import (
    WorkingMemoryHandoffTransaction,
    WorkingMemoryItem,
    WorkingMemoryPolicyProfile,
    WorkingMemoryQuery,
    WorkingMemoryReadLog,
    WorkingMemoryTemporalEdge,
)


class WorkingMemoryStore:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir = self.root_dir / "archive"
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root_dir / "working_memory.sqlite"
        self._ensure_schema()

    def upsert_item(self, item: WorkingMemoryItem) -> WorkingMemoryItem:
        now = utc_now_iso()
        existing = self.find_item_by_idempotency(
            task_run_id=item.task_run_id,
            owner_node_id=item.owner_node_id,
            node_run_id=item.node_run_id,
            idempotency_key=item.idempotency_key,
        )
        if existing is not None:
            return existing
        stored = replace(
            item,
            created_at=item.created_at or now,
            updated_at=item.updated_at or now,
            last_writer_agent_id=item.last_writer_agent_id or item.writer_agent_id,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO work_memory_items (
                    work_memory_id, task_run_id, task_id, graph_id, owner_node_id, owner_node_role,
                    node_run_id, run_attempt_id, stage_id, writer_agent_id, last_writer_agent_id,
                    scope, kind, memory_semantics, title, payload_json, summary, status, visibility,
                    read_policy_json, write_policy_json, version, parent_item_id, source_event_refs_json,
                    source_message_refs_json, artifact_refs_json, contract_refs_json, reader_policy_json,
                    tags_json, temporal_refs_json, conflict_refs_json, adopted_from_handoff_id,
                    idempotency_key, source_message_hash, created_at, updated_at, expires_at,
                    promotion_state, metadata_json, authority
                ) VALUES (
                    :work_memory_id, :task_run_id, :task_id, :graph_id, :owner_node_id, :owner_node_role,
                    :node_run_id, :run_attempt_id, :stage_id, :writer_agent_id, :last_writer_agent_id,
                    :scope, :kind, :memory_semantics, :title, :payload_json, :summary, :status, :visibility,
                    :read_policy_json, :write_policy_json, :version, :parent_item_id, :source_event_refs_json,
                    :source_message_refs_json, :artifact_refs_json, :contract_refs_json, :reader_policy_json,
                    :tags_json, :temporal_refs_json, :conflict_refs_json, :adopted_from_handoff_id,
                    :idempotency_key, :source_message_hash, :created_at, :updated_at, :expires_at,
                    :promotion_state, :metadata_json, :authority
                )
                """,
                _item_row(stored),
            )
            conn.execute(
                """
                INSERT INTO work_memory_events (
                    event_id, task_run_id, work_memory_id, event_type, actor_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"wmevt:{stored.work_memory_id}:created",
                    stored.task_run_id,
                    stored.work_memory_id,
                    "created",
                    stored.writer_agent_id,
                    _json({"status": stored.status, "visibility": stored.visibility}),
                    now,
                ),
            )
        return stored

    def get_item(self, work_memory_id: str) -> WorkingMemoryItem | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM work_memory_items WHERE work_memory_id = ?",
                (work_memory_id,),
            ).fetchone()
        return _item_from_row(row) if row is not None else None

    def find_item_by_idempotency(
        self,
        *,
        task_run_id: str,
        owner_node_id: str,
        node_run_id: str,
        idempotency_key: str,
    ) -> WorkingMemoryItem | None:
        if not idempotency_key:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM work_memory_items
                WHERE task_run_id = ? AND owner_node_id = ? AND node_run_id = ? AND idempotency_key = ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (task_run_id, owner_node_id, node_run_id, idempotency_key),
            ).fetchone()
        return _item_from_row(row) if row is not None else None

    def query_items(self, query: WorkingMemoryQuery | None = None) -> tuple[WorkingMemoryItem, ...]:
        query = query or WorkingMemoryQuery()
        filters: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("task_run_id", query.task_run_id),
            ("task_id", query.task_id),
            ("graph_id", query.graph_id),
            ("owner_node_id", query.owner_node_id),
            ("node_run_id", query.node_run_id),
            ("run_attempt_id", query.run_attempt_id),
            ("writer_agent_id", query.writer_agent_id),
            ("kind", query.kind),
            ("memory_semantics", query.memory_semantics),
            ("status", query.status),
            ("visibility", query.visibility),
        ):
            if str(value or "").strip():
                filters.append(f"{column} = ?")
                params.append(str(value).strip())
        sql = "SELECT * FROM work_memory_items"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY created_at ASC LIMIT ?"
        params.append(query.normalized_limit())
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_item_from_row(row) for row in rows)

    def set_item_status(
        self,
        work_memory_id: str,
        *,
        status: str,
        authority: str = "",
        actor_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> WorkingMemoryItem:
        current = self.get_item(work_memory_id)
        if current is None:
            raise KeyError(f"Unknown working memory item: {work_memory_id}")
        now = utc_now_iso()
        updated = replace(
            current,
            status=status,  # type: ignore[arg-type]
            authority=authority or current.authority,
            metadata={**current.metadata, **dict(metadata or {})},
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE work_memory_items
                SET status = ?, authority = ?, metadata_json = ?, updated_at = ?
                WHERE work_memory_id = ?
                """,
                (updated.status, updated.authority, _json(updated.metadata), now, work_memory_id),
            )
            conn.execute(
                """
                INSERT INTO work_memory_events (
                    event_id, task_run_id, work_memory_id, event_type, actor_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"wmevt:{work_memory_id}:status:{now}",
                    current.task_run_id,
                    work_memory_id,
                    "status_changed",
                    actor_id,
                    _json({"status": status, "authority": updated.authority}),
                    now,
                ),
            )
        return updated

    def update_item_lifecycle(
        self,
        work_memory_id: str,
        *,
        status: str | None = None,
        promotion_state: str | None = None,
        authority: str = "",
        actor_id: str = "",
        metadata: dict[str, Any] | None = None,
        event_type: str = "lifecycle_updated",
    ) -> WorkingMemoryItem:
        current = self.get_item(work_memory_id)
        if current is None:
            raise KeyError(f"Unknown working memory item: {work_memory_id}")
        now = utc_now_iso()
        updated = replace(
            current,
            status=(status or current.status),  # type: ignore[arg-type]
            promotion_state=(promotion_state or current.promotion_state),  # type: ignore[arg-type]
            authority=authority or current.authority,
            metadata={**current.metadata, **dict(metadata or {})},
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE work_memory_items
                SET status = ?, promotion_state = ?, authority = ?, metadata_json = ?, updated_at = ?
                WHERE work_memory_id = ?
                """,
                (
                    updated.status,
                    updated.promotion_state,
                    updated.authority,
                    _json(updated.metadata),
                    now,
                    work_memory_id,
                ),
            )
            conn.execute(
                """
                INSERT INTO work_memory_events (
                    event_id, task_run_id, work_memory_id, event_type, actor_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"wmevt:{work_memory_id}:{event_type}:{now}",
                    current.task_run_id,
                    work_memory_id,
                    event_type,
                    actor_id,
                    _json(
                        {
                            "status": updated.status,
                            "promotion_state": updated.promotion_state,
                            "authority": updated.authority,
                        }
                    ),
                    now,
                ),
            )
        return updated

    def write_archive_report(self, task_run_id: str, report: dict[str, Any]) -> Path:
        safe_id = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in task_run_id)
        path = self.archive_dir / f"{safe_id or 'task_run'}-finalization.json"
        path.write_text(_json(report), encoding="utf-8")
        return path

    def append_read_log(self, log: WorkingMemoryReadLog) -> WorkingMemoryReadLog:
        stored = replace(log, created_at=log.created_at or utc_now_iso())
        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO work_memory_read_logs (
                        read_log_id, task_run_id, graph_id, owner_node_id, node_run_id, run_attempt_id,
                        reader_agent_id, request_json, selected_item_ids_json, excluded_item_ids_json,
                        token_estimate, denied_reason, created_at, authority
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stored.read_log_id,
                        stored.task_run_id,
                        stored.graph_id,
                        stored.owner_node_id,
                        stored.node_run_id,
                        stored.run_attempt_id,
                        stored.reader_agent_id,
                        _json(stored.request),
                        _json(stored.selected_item_ids),
                        _json(stored.excluded_item_ids),
                        stored.token_estimate,
                        stored.denied_reason,
                        stored.created_at,
                        stored.authority,
                    ),
                )
            except sqlite3.IntegrityError:
                existing = conn.execute(
                    "SELECT * FROM work_memory_read_logs WHERE read_log_id = ?",
                    (stored.read_log_id,),
                ).fetchone()
                if existing is not None:
                    return _read_log_from_row(existing)
                raise
        return stored

    def list_read_logs(self, task_run_id: str = "", *, limit: int = 200) -> tuple[WorkingMemoryReadLog, ...]:
        sql = "SELECT * FROM work_memory_read_logs"
        params: list[Any] = []
        if task_run_id:
            sql += " WHERE task_run_id = ?"
            params.append(task_run_id)
        sql += " ORDER BY created_at ASC LIMIT ?"
        params.append(max(1, min(int(limit or 200), 1000)))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_read_log_from_row(row) for row in rows)

    def add_temporal_edge(self, edge: WorkingMemoryTemporalEdge) -> WorkingMemoryTemporalEdge:
        stored = replace(edge, created_at=edge.created_at or utc_now_iso())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO work_memory_temporal_edges (
                    edge_id, task_run_id, graph_id, source_item_id, target_item_id, relation,
                    confidence, source_node_id, created_at, metadata_json, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stored.edge_id,
                    stored.task_run_id,
                    stored.graph_id,
                    stored.source_item_id,
                    stored.target_item_id,
                    stored.relation,
                    stored.confidence,
                    stored.source_node_id,
                    stored.created_at,
                    _json(stored.metadata),
                    stored.authority,
                ),
            )
        return stored

    def list_temporal_edges(self, task_run_id: str = "") -> tuple[WorkingMemoryTemporalEdge, ...]:
        sql = "SELECT * FROM work_memory_temporal_edges"
        params: list[Any] = []
        if task_run_id:
            sql += " WHERE task_run_id = ?"
            params.append(task_run_id)
        sql += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_temporal_edge_from_row(row) for row in rows)

    def upsert_handoff_transaction(
        self,
        transaction: WorkingMemoryHandoffTransaction,
    ) -> WorkingMemoryHandoffTransaction:
        existing = self.find_handoff_transaction(
            task_run_id=transaction.task_run_id,
            idempotency_key=transaction.idempotency_key,
            handoff_id=transaction.handoff_id,
            source_message_hash=transaction.source_message_hash,
        )
        if existing is not None:
            return existing
        stored = replace(transaction, created_at=transaction.created_at or utc_now_iso())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO work_memory_handoff_transactions (
                    transaction_id, task_run_id, graph_id, edge_id, source_node_run_id,
                    target_node_run_id, handoff_id, source_message_hash, idempotency_key,
                    candidate_work_memory_ids_json, adopted_work_memory_ids_json,
                    rejected_work_memory_ids_json, ephemeral_context_refs_json, transaction_status,
                    created_at, committed_at, metadata_json, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _transaction_row(stored),
            )
        return stored

    def find_handoff_transaction(
        self,
        *,
        task_run_id: str,
        idempotency_key: str = "",
        handoff_id: str = "",
        source_message_hash: str = "",
    ) -> WorkingMemoryHandoffTransaction | None:
        filters = ["task_run_id = ?"]
        params: list[Any] = [task_run_id]
        if idempotency_key:
            filters.append("idempotency_key = ?")
            params.append(idempotency_key)
        elif handoff_id or source_message_hash:
            if handoff_id:
                filters.append("handoff_id = ?")
                params.append(handoff_id)
            if source_message_hash:
                filters.append("source_message_hash = ?")
                params.append(source_message_hash)
        else:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM work_memory_handoff_transactions WHERE "
                + " AND ".join(filters)
                + " ORDER BY created_at ASC LIMIT 1",
                tuple(params),
            ).fetchone()
        return _transaction_from_row(row) if row is not None else None

    def update_handoff_transaction_status(
        self,
        transaction_id: str,
        *,
        transaction_status: str,
        adopted_work_memory_ids: tuple[str, ...] = (),
        rejected_work_memory_ids: tuple[str, ...] = (),
        ephemeral_context_refs: tuple[str, ...] = (),
    ) -> WorkingMemoryHandoffTransaction:
        current = self.get_handoff_transaction(transaction_id)
        if current is None:
            raise KeyError(f"Unknown working memory handoff transaction: {transaction_id}")
        now = utc_now_iso()
        updated = replace(
            current,
            transaction_status=transaction_status,  # type: ignore[arg-type]
            adopted_work_memory_ids=adopted_work_memory_ids or current.adopted_work_memory_ids,
            rejected_work_memory_ids=rejected_work_memory_ids or current.rejected_work_memory_ids,
            ephemeral_context_refs=ephemeral_context_refs or current.ephemeral_context_refs,
            committed_at=now if transaction_status == "committed" else current.committed_at,
        )
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE work_memory_handoff_transactions
                SET transaction_status = ?, adopted_work_memory_ids_json = ?,
                    rejected_work_memory_ids_json = ?, ephemeral_context_refs_json = ?,
                    committed_at = ?
                WHERE transaction_id = ?
                """,
                (
                    updated.transaction_status,
                    _json(updated.adopted_work_memory_ids),
                    _json(updated.rejected_work_memory_ids),
                    _json(updated.ephemeral_context_refs),
                    updated.committed_at,
                    transaction_id,
                ),
            )
        return updated

    def get_handoff_transaction(self, transaction_id: str) -> WorkingMemoryHandoffTransaction | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM work_memory_handoff_transactions WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchone()
        return _transaction_from_row(row) if row is not None else None

    def list_handoff_transactions(self, task_run_id: str = "") -> tuple[WorkingMemoryHandoffTransaction, ...]:
        sql = "SELECT * FROM work_memory_handoff_transactions"
        params: list[Any] = []
        if task_run_id:
            sql += " WHERE task_run_id = ?"
            params.append(task_run_id)
        sql += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_transaction_from_row(row) for row in rows)

    def upsert_policy_profile(self, profile: WorkingMemoryPolicyProfile) -> WorkingMemoryPolicyProfile:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO work_memory_policy_profiles (
                    profile_id, profile_json, authority
                ) VALUES (?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    profile_json = excluded.profile_json,
                    authority = excluded.authority
                """,
                (profile.profile_id, _json(profile.to_dict()), profile.authority),
            )
        return profile

    def get_policy_profile(self, profile_id: str) -> WorkingMemoryPolicyProfile | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT profile_json FROM work_memory_policy_profiles WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
        if row is None:
            return None
        return _policy_profile_from_payload(_loads(row["profile_json"]))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS work_memory_items (
                    work_memory_id TEXT PRIMARY KEY,
                    task_run_id TEXT NOT NULL,
                    task_id TEXT NOT NULL DEFAULT '',
                    graph_id TEXT NOT NULL DEFAULT '',
                    owner_node_id TEXT NOT NULL DEFAULT '',
                    owner_node_role TEXT NOT NULL DEFAULT '',
                    node_run_id TEXT NOT NULL DEFAULT '',
                    run_attempt_id TEXT NOT NULL DEFAULT '',
                    stage_id TEXT NOT NULL DEFAULT '',
                    writer_agent_id TEXT NOT NULL DEFAULT '',
                    last_writer_agent_id TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    memory_semantics TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    summary TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    visibility TEXT NOT NULL,
                    read_policy_json TEXT NOT NULL DEFAULT '{}',
                    write_policy_json TEXT NOT NULL DEFAULT '{}',
                    version INTEGER NOT NULL DEFAULT 1,
                    parent_item_id TEXT NOT NULL DEFAULT '',
                    source_event_refs_json TEXT NOT NULL DEFAULT '[]',
                    source_message_refs_json TEXT NOT NULL DEFAULT '[]',
                    artifact_refs_json TEXT NOT NULL DEFAULT '[]',
                    contract_refs_json TEXT NOT NULL DEFAULT '[]',
                    reader_policy_json TEXT NOT NULL DEFAULT '{}',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    temporal_refs_json TEXT NOT NULL DEFAULT '[]',
                    conflict_refs_json TEXT NOT NULL DEFAULT '[]',
                    adopted_from_handoff_id TEXT NOT NULL DEFAULT '',
                    idempotency_key TEXT NOT NULL DEFAULT '',
                    source_message_hash TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    expires_at TEXT NOT NULL DEFAULT '',
                    promotion_state TEXT NOT NULL DEFAULT 'not_applicable',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    authority TEXT NOT NULL DEFAULT 'candidate_only'
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_work_memory_item_idempotency
                ON work_memory_items(task_run_id, owner_node_id, node_run_id, idempotency_key)
                WHERE idempotency_key != '';

                CREATE INDEX IF NOT EXISTS idx_work_memory_items_query
                ON work_memory_items(task_run_id, graph_id, owner_node_id, node_run_id, run_attempt_id, status);

                CREATE TABLE IF NOT EXISTS work_memory_events (
                    event_id TEXT PRIMARY KEY,
                    task_run_id TEXT NOT NULL,
                    work_memory_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS work_memory_read_logs (
                    read_log_id TEXT PRIMARY KEY,
                    task_run_id TEXT NOT NULL,
                    graph_id TEXT NOT NULL DEFAULT '',
                    owner_node_id TEXT NOT NULL DEFAULT '',
                    node_run_id TEXT NOT NULL DEFAULT '',
                    run_attempt_id TEXT NOT NULL DEFAULT '',
                    reader_agent_id TEXT NOT NULL DEFAULT '',
                    request_json TEXT NOT NULL DEFAULT '{}',
                    selected_item_ids_json TEXT NOT NULL DEFAULT '[]',
                    excluded_item_ids_json TEXT NOT NULL DEFAULT '[]',
                    token_estimate INTEGER NOT NULL DEFAULT 0,
                    denied_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    authority TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS work_memory_temporal_edges (
                    edge_id TEXT PRIMARY KEY,
                    task_run_id TEXT NOT NULL,
                    graph_id TEXT NOT NULL DEFAULT '',
                    source_item_id TEXT NOT NULL,
                    target_item_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.0,
                    source_node_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    authority TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS work_memory_handoff_transactions (
                    transaction_id TEXT PRIMARY KEY,
                    task_run_id TEXT NOT NULL,
                    graph_id TEXT NOT NULL DEFAULT '',
                    edge_id TEXT NOT NULL DEFAULT '',
                    source_node_run_id TEXT NOT NULL DEFAULT '',
                    target_node_run_id TEXT NOT NULL DEFAULT '',
                    handoff_id TEXT NOT NULL DEFAULT '',
                    source_message_hash TEXT NOT NULL DEFAULT '',
                    idempotency_key TEXT NOT NULL DEFAULT '',
                    candidate_work_memory_ids_json TEXT NOT NULL DEFAULT '[]',
                    adopted_work_memory_ids_json TEXT NOT NULL DEFAULT '[]',
                    rejected_work_memory_ids_json TEXT NOT NULL DEFAULT '[]',
                    ephemeral_context_refs_json TEXT NOT NULL DEFAULT '[]',
                    transaction_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    committed_at TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    authority TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_work_memory_handoff_idempotency
                ON work_memory_handoff_transactions(task_run_id, idempotency_key)
                WHERE idempotency_key != '';

                CREATE TABLE IF NOT EXISTS work_memory_policy_profiles (
                    profile_id TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    authority TEXT NOT NULL
                );
                """
            )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _item_row(item: WorkingMemoryItem) -> dict[str, Any]:
    payload = item.to_dict()
    return {
        **payload,
        "payload_json": _json(item.payload),
        "read_policy_json": _json(item.read_policy),
        "write_policy_json": _json(item.write_policy),
        "source_event_refs_json": _json(item.source_event_refs),
        "source_message_refs_json": _json(item.source_message_refs),
        "artifact_refs_json": _json(item.artifact_refs),
        "contract_refs_json": _json(item.contract_refs),
        "reader_policy_json": _json(item.reader_policy),
        "tags_json": _json(item.tags),
        "temporal_refs_json": _json(item.temporal_refs),
        "conflict_refs_json": _json(item.conflict_refs),
        "metadata_json": _json(item.metadata),
    }


def _item_from_row(row: sqlite3.Row) -> WorkingMemoryItem:
    return WorkingMemoryItem(
        work_memory_id=str(row["work_memory_id"]),
        task_run_id=str(row["task_run_id"]),
        task_id=str(row["task_id"]),
        graph_id=str(row["graph_id"]),
        owner_node_id=str(row["owner_node_id"]),
        owner_node_role=str(row["owner_node_role"]),
        node_run_id=str(row["node_run_id"]),
        run_attempt_id=str(row["run_attempt_id"]),
        stage_id=str(row["stage_id"]),
        writer_agent_id=str(row["writer_agent_id"]),
        last_writer_agent_id=str(row["last_writer_agent_id"]),
        scope=str(row["scope"]),  # type: ignore[arg-type]
        kind=str(row["kind"]),
        memory_semantics=str(row["memory_semantics"]),  # type: ignore[arg-type]
        title=str(row["title"]),
        payload=dict(_loads(row["payload_json"]) or {}),
        summary=str(row["summary"]),
        status=str(row["status"]),  # type: ignore[arg-type]
        visibility=str(row["visibility"]),  # type: ignore[arg-type]
        read_policy=dict(_loads(row["read_policy_json"]) or {}),
        write_policy=dict(_loads(row["write_policy_json"]) or {}),
        version=int(row["version"]),
        parent_item_id=str(row["parent_item_id"]),
        source_event_refs=tuple(_string_list(_loads(row["source_event_refs_json"]))),
        source_message_refs=tuple(_string_list(_loads(row["source_message_refs_json"]))),
        artifact_refs=tuple(_string_list(_loads(row["artifact_refs_json"]))),
        contract_refs=tuple(_string_list(_loads(row["contract_refs_json"]))),
        reader_policy=dict(_loads(row["reader_policy_json"]) or {}),
        tags=tuple(_string_list(_loads(row["tags_json"]))),
        temporal_refs=tuple(_string_list(_loads(row["temporal_refs_json"]))),
        conflict_refs=tuple(_string_list(_loads(row["conflict_refs_json"]))),
        adopted_from_handoff_id=str(row["adopted_from_handoff_id"]),
        idempotency_key=str(row["idempotency_key"]),
        source_message_hash=str(row["source_message_hash"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        expires_at=str(row["expires_at"]),
        promotion_state=str(row["promotion_state"]),  # type: ignore[arg-type]
        metadata=dict(_loads(row["metadata_json"]) or {}),
        authority=str(row["authority"]),  # type: ignore[arg-type]
    )


def _read_log_from_row(row: sqlite3.Row) -> WorkingMemoryReadLog:
    return WorkingMemoryReadLog(
        read_log_id=str(row["read_log_id"]),
        task_run_id=str(row["task_run_id"]),
        graph_id=str(row["graph_id"]),
        owner_node_id=str(row["owner_node_id"]),
        node_run_id=str(row["node_run_id"]),
        run_attempt_id=str(row["run_attempt_id"]),
        reader_agent_id=str(row["reader_agent_id"]),
        request=dict(_loads(row["request_json"]) or {}),
        selected_item_ids=tuple(_string_list(_loads(row["selected_item_ids_json"]))),
        excluded_item_ids=tuple(_string_list(_loads(row["excluded_item_ids_json"]))),
        token_estimate=int(row["token_estimate"]),
        denied_reason=str(row["denied_reason"]),
        created_at=str(row["created_at"]),
        authority=str(row["authority"]),
    )


def _temporal_edge_from_row(row: sqlite3.Row) -> WorkingMemoryTemporalEdge:
    return WorkingMemoryTemporalEdge(
        edge_id=str(row["edge_id"]),
        task_run_id=str(row["task_run_id"]),
        graph_id=str(row["graph_id"]),
        source_item_id=str(row["source_item_id"]),
        target_item_id=str(row["target_item_id"]),
        relation=str(row["relation"]),
        confidence=float(row["confidence"]),
        source_node_id=str(row["source_node_id"]),
        created_at=str(row["created_at"]),
        metadata=dict(_loads(row["metadata_json"]) or {}),
        authority=str(row["authority"]),
    )


def _transaction_row(transaction: WorkingMemoryHandoffTransaction) -> tuple[Any, ...]:
    return (
        transaction.transaction_id,
        transaction.task_run_id,
        transaction.graph_id,
        transaction.edge_id,
        transaction.source_node_run_id,
        transaction.target_node_run_id,
        transaction.handoff_id,
        transaction.source_message_hash,
        transaction.idempotency_key,
        _json(transaction.candidate_work_memory_ids),
        _json(transaction.adopted_work_memory_ids),
        _json(transaction.rejected_work_memory_ids),
        _json(transaction.ephemeral_context_refs),
        transaction.transaction_status,
        transaction.created_at,
        transaction.committed_at,
        _json(transaction.metadata),
        transaction.authority,
    )


def _transaction_from_row(row: sqlite3.Row) -> WorkingMemoryHandoffTransaction:
    return WorkingMemoryHandoffTransaction(
        transaction_id=str(row["transaction_id"]),
        task_run_id=str(row["task_run_id"]),
        graph_id=str(row["graph_id"]),
        edge_id=str(row["edge_id"]),
        source_node_run_id=str(row["source_node_run_id"]),
        target_node_run_id=str(row["target_node_run_id"]),
        handoff_id=str(row["handoff_id"]),
        source_message_hash=str(row["source_message_hash"]),
        idempotency_key=str(row["idempotency_key"]),
        candidate_work_memory_ids=tuple(_string_list(_loads(row["candidate_work_memory_ids_json"]))),
        adopted_work_memory_ids=tuple(_string_list(_loads(row["adopted_work_memory_ids_json"]))),
        rejected_work_memory_ids=tuple(_string_list(_loads(row["rejected_work_memory_ids_json"]))),
        ephemeral_context_refs=tuple(_string_list(_loads(row["ephemeral_context_refs_json"]))),
        transaction_status=str(row["transaction_status"]),  # type: ignore[arg-type]
        created_at=str(row["created_at"]),
        committed_at=str(row["committed_at"]),
        metadata=dict(_loads(row["metadata_json"]) or {}),
        authority=str(row["authority"]),
    )


def _policy_profile_from_payload(payload: Any) -> WorkingMemoryPolicyProfile:
    data = dict(payload or {})
    return WorkingMemoryPolicyProfile(
        profile_id=str(data.get("profile_id") or ""),
        allowed_kinds=tuple(_string_list(data.get("allowed_kinds"))),
        allowed_semantics=tuple(_string_list(data.get("allowed_semantics"))),  # type: ignore[arg-type]
        readable_scopes_by_node_role=dict(data.get("readable_scopes_by_node_role") or {}),
        writable_kinds_by_node_role=dict(data.get("writable_kinds_by_node_role") or {}),
        default_visibility_by_kind=dict(data.get("default_visibility_by_kind") or {}),
        default_status_by_semantics=dict(data.get("default_status_by_semantics") or {}),
        promotion_rules=dict(data.get("promotion_rules") or {}),
        retention_rules=dict(data.get("retention_rules") or {}),
        conflict_rules=dict(data.get("conflict_rules") or {}),
        dynamic_read_rules=dict(data.get("dynamic_read_rules") or {}),
        temporal_rules=dict(data.get("temporal_rules") or {}),
        retry_memory_rules=dict(data.get("retry_memory_rules") or {}),
        metadata=dict(data.get("metadata") or {}),
        authority=str(data.get("authority") or "working_memory.policy_profile"),
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads(value: Any) -> Any:
    try:
        return json.loads(str(value or ""))
    except json.JSONDecodeError:
        return None


def _string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in list(value or []) if str(item).strip()]


