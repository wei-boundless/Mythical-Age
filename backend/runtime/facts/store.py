from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .schema import RuntimeFactEdge, RuntimeFactRecord


PROTECTED_RETENTION_CLASSES = {"audit_keep", "memory_governed"}
PROTECTED_RELATIONS = {"promoted_to_memory", "verified_by"}


class RuntimeFactLedgerStore:
    authority = "runtime.fact_ledger.store"

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.store_dir = self.root_dir / "facts"
        self.records_dir = self.store_dir / "records"
        self.edges_dir = self.store_dir / "edges"
        self.tombstone_dir = self.store_dir / "tombstones"
        self.index_dir = self.store_dir / "index"
        self.index_path = self.index_dir / "by_scope.sqlite"
        self._lock = threading.RLock()
        for path in (self.records_dir, self.edges_dir, self.tombstone_dir, self.index_dir):
            path.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def append_record(self, record: RuntimeFactRecord) -> RuntimeFactRecord:
        payload = record.to_dict()
        with self._lock:
            with self._connect() as conn:
                existing = self._record_by_id_or_key(conn, record.fact_id, record.idempotency_key)
                if existing is not None:
                    return RuntimeFactRecord.from_dict(existing)
                conn.execute(
                    """
                    INSERT INTO fact_records (
                        fact_id, idempotency_key, fact_type, created_at, session_id, turn_id,
                        turn_run_id, task_run_id, graph_run_id, node_id, work_order_id,
                        project_id, task_environment_id, trace_id, span_id, agent_run_ref,
                        run_cell_ref, runtime_control_signal_ref, evidence_projection_ref,
                        execution_id, usage_id, artifact_ref, memory_record_id, memory_version_id,
                        retention_class, visibility, model_visibility, tombstoned,
                        deleted_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._record_row_values(record, payload),
                )
                self._append_jsonl(self.records_dir / "records.jsonl", payload)
            return record

    def append_edge(self, edge: RuntimeFactEdge) -> RuntimeFactEdge:
        payload = edge.to_dict()
        with self._lock:
            with self._connect() as conn:
                existing = self._edge_by_id_or_key(conn, edge.edge_id, edge.idempotency_key)
                if existing is not None:
                    return RuntimeFactEdge.from_dict(existing)
                conn.execute(
                    """
                    INSERT INTO fact_edges (
                        edge_id, idempotency_key, source_fact_id, target_fact_id,
                        relation, confidence, created_at, tombstoned, deleted_at,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        edge.edge_id,
                        edge.idempotency_key,
                        edge.source_fact_id,
                        edge.target_fact_id,
                        edge.relation,
                        float(edge.confidence),
                        float(edge.created_at),
                        1 if edge.tombstoned else 0,
                        float(edge.deleted_at),
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    ),
                )
                self._append_jsonl(self.edges_dir / "edges.jsonl", payload)
            return edge

    def get_record(self, fact_id: str, *, include_tombstones: bool = False) -> RuntimeFactRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json, tombstoned FROM fact_records WHERE fact_id = ?",
                (str(fact_id or ""),),
            ).fetchone()
        if row is None:
            return None
        if bool(row["tombstoned"]) and not include_tombstones:
            return None
        return RuntimeFactRecord.from_dict(json.loads(str(row["payload_json"] or "{}")))

    def list_records(
        self,
        *,
        session_id: str = "",
        turn_id: str = "",
        turn_run_id: str = "",
        task_run_id: str = "",
        graph_run_id: str = "",
        trace_id: str = "",
        span_id: str = "",
        agent_run_ref: str = "",
        run_cell_ref: str = "",
        runtime_control_signal_ref: str = "",
        evidence_projection_ref: str = "",
        execution_id: str = "",
        usage_id: str = "",
        memory_ref: str = "",
        fact_type: str = "",
        include_tombstones: bool = False,
        limit: int = 200,
    ) -> list[RuntimeFactRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        filters = {
            "session_id": session_id,
            "turn_id": turn_id,
            "turn_run_id": turn_run_id,
            "task_run_id": task_run_id,
            "graph_run_id": graph_run_id,
            "trace_id": trace_id,
            "span_id": span_id,
            "agent_run_ref": agent_run_ref,
            "run_cell_ref": run_cell_ref,
            "runtime_control_signal_ref": runtime_control_signal_ref,
            "evidence_projection_ref": evidence_projection_ref,
            "execution_id": execution_id,
            "usage_id": usage_id,
            "fact_type": fact_type,
        }
        for field, value in filters.items():
            normalized = str(value or "").strip()
            if normalized:
                clauses.append(f"{field} = ?")
                params.append(normalized)
        normalized_memory_ref = str(memory_ref or "").strip()
        if normalized_memory_ref:
            clauses.append("(memory_record_id = ? OR memory_version_id = ?)")
            params.extend([normalized_memory_ref, normalized_memory_ref])
        if not include_tombstones:
            clauses.append("tombstoned = 0")
        sql = "SELECT payload_json FROM fact_records"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at ASC LIMIT ?"
        params.append(max(1, min(int(limit or 200), 5000)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [RuntimeFactRecord.from_dict(json.loads(str(row["payload_json"] or "{}"))) for row in rows]

    def list_edges(
        self,
        *,
        source_fact_id: str = "",
        target_fact_id: str = "",
        relation: str = "",
        include_tombstones: bool = False,
        limit: int = 200,
    ) -> list[RuntimeFactEdge]:
        clauses: list[str] = []
        params: list[Any] = []
        for field, value in {
            "source_fact_id": source_fact_id,
            "target_fact_id": target_fact_id,
            "relation": relation,
        }.items():
            normalized = str(value or "").strip()
            if normalized:
                clauses.append(f"{field} = ?")
                params.append(normalized)
        if not include_tombstones:
            clauses.append("tombstoned = 0")
        sql = "SELECT payload_json FROM fact_edges"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at ASC LIMIT ?"
        params.append(max(1, min(int(limit or 200), 5000)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [RuntimeFactEdge.from_dict(json.loads(str(row["payload_json"] or "{}"))) for row in rows]

    def prune_task_runs(self, task_run_ids: set[str] | list[str] | tuple[str, ...]) -> dict[str, Any]:
        targets = {str(item).strip() for item in list(task_run_ids or []) if str(item).strip()}
        return self._prune_records(where_field="task_run_id", targets=targets, reason="task_run_pruned")

    def prune_session(self, session_id: str) -> dict[str, Any]:
        target = str(session_id or "").strip()
        return self._prune_records(where_field="session_id", targets={target} if target else set(), reason="session_pruned")

    def summarize_scope(self, *, task_run_id: str = "", session_id: str = "") -> dict[str, Any]:
        records = self.list_records(task_run_id=task_run_id, session_id=session_id, limit=5000)
        return {
            "authority": "runtime.fact_ledger.summary",
            "task_run_id": task_run_id,
            "session_id": session_id,
            "fact_count": len(records),
            "fact_type_counts": _counts(item.fact_type for item in records),
            "retention_class_counts": _counts(item.retention_class for item in records),
        }

    def _prune_records(self, *, where_field: str, targets: set[str], reason: str) -> dict[str, Any]:
        if not targets:
            return {
                "authority": "runtime.fact_ledger.prune",
                "deleted_count": 0,
                "tombstoned_count": 0,
                "requested_targets": [],
            }
        now = time.time()
        deleted = 0
        tombstoned = 0
        affected_fact_ids: set[str] = set()
        placeholders = ",".join("?" for _ in targets)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT fact_id, payload_json FROM fact_records WHERE {where_field} IN ({placeholders}) AND tombstoned = 0",
                tuple(sorted(targets)),
            ).fetchall()
            for row in rows:
                record = RuntimeFactRecord.from_dict(json.loads(str(row["payload_json"] or "{}")))
                affected_fact_ids.add(record.fact_id)
                if _record_requires_tombstone(record):
                    tombstone = _record_tombstone(record, deleted_at=now, reason=reason)
                    conn.execute(
                        "UPDATE fact_records SET tombstoned = 1, deleted_at = ?, payload_json = ? WHERE fact_id = ?",
                        (now, json.dumps(tombstone.to_dict(), ensure_ascii=False, sort_keys=True), record.fact_id),
                    )
                    self._append_jsonl(self.tombstone_dir / "records.jsonl", tombstone.to_dict())
                    tombstoned += 1
                    continue
                conn.execute("DELETE FROM fact_records WHERE fact_id = ?", (record.fact_id,))
                deleted += 1
            edge_rows = conn.execute(
                "SELECT edge_id, payload_json FROM fact_edges WHERE tombstoned = 0"
            ).fetchall()
            for row in edge_rows:
                edge = RuntimeFactEdge.from_dict(json.loads(str(row["payload_json"] or "{}")))
                if edge.source_fact_id not in affected_fact_ids and edge.target_fact_id not in affected_fact_ids:
                    continue
                if edge.relation in PROTECTED_RELATIONS:
                    tombstone_edge = _edge_tombstone(edge, deleted_at=now, reason=reason)
                    conn.execute(
                        "UPDATE fact_edges SET tombstoned = 1, deleted_at = ?, payload_json = ? WHERE edge_id = ?",
                        (now, json.dumps(tombstone_edge.to_dict(), ensure_ascii=False, sort_keys=True), edge.edge_id),
                    )
                    self._append_jsonl(self.tombstone_dir / "edges.jsonl", tombstone_edge.to_dict())
                    tombstoned += 1
                    continue
                conn.execute("DELETE FROM fact_edges WHERE edge_id = ?", (edge.edge_id,))
                deleted += 1
        return {
            "authority": "runtime.fact_ledger.prune",
            "where_field": where_field,
            "requested_targets": sorted(targets),
            "deleted_count": deleted,
            "tombstoned_count": tombstoned,
        }

    def _record_by_id_or_key(self, conn: sqlite3.Connection, fact_id: str, idempotency_key: str) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT payload_json FROM fact_records WHERE fact_id = ? OR idempotency_key = ? LIMIT 1",
            (fact_id, idempotency_key),
        ).fetchone()
        return json.loads(str(row["payload_json"] or "{}")) if row is not None else None

    def _edge_by_id_or_key(self, conn: sqlite3.Connection, edge_id: str, idempotency_key: str) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT payload_json FROM fact_edges WHERE edge_id = ? OR idempotency_key = ? LIMIT 1",
            (edge_id, idempotency_key),
        ).fetchone()
        return json.loads(str(row["payload_json"] or "{}")) if row is not None else None

    def _record_row_values(self, record: RuntimeFactRecord, payload: dict[str, Any]) -> tuple[Any, ...]:
        scope = dict(record.scope or {})
        refs = dict(record.refs or {})
        return (
            record.fact_id,
            record.idempotency_key,
            record.fact_type,
            float(record.created_at),
            _field(scope, "session_id"),
            _field(scope, "turn_id"),
            _field(scope, "turn_run_id"),
            _field(scope, "task_run_id"),
            _field(scope, "graph_run_id"),
            _field(scope, "node_id"),
            _field(scope, "work_order_id"),
            _field(scope, "project_id"),
            _field(scope, "task_environment_id"),
            _field(refs, "trace_id"),
            _field(refs, "span_id"),
            _field(refs, "agent_run_ref"),
            _field(refs, "run_cell_ref"),
            _field(refs, "runtime_control_signal_ref"),
            _field(refs, "evidence_projection_ref"),
            _field(refs, "execution_id"),
            _field(refs, "usage_id"),
            _field(refs, "artifact_ref"),
            _field(refs, "memory_record_id"),
            _field(refs, "memory_version_id"),
            record.retention_class,
            record.visibility,
            record.model_visibility,
            1 if record.tombstoned else 0,
            float(record.deleted_at),
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.index_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fact_records (
                    fact_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    fact_type TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    session_id TEXT NOT NULL DEFAULT '',
                    turn_id TEXT NOT NULL DEFAULT '',
                    turn_run_id TEXT NOT NULL DEFAULT '',
                    task_run_id TEXT NOT NULL DEFAULT '',
                    graph_run_id TEXT NOT NULL DEFAULT '',
                    node_id TEXT NOT NULL DEFAULT '',
                    work_order_id TEXT NOT NULL DEFAULT '',
                    project_id TEXT NOT NULL DEFAULT '',
                    task_environment_id TEXT NOT NULL DEFAULT '',
                    trace_id TEXT NOT NULL DEFAULT '',
                    span_id TEXT NOT NULL DEFAULT '',
                    agent_run_ref TEXT NOT NULL DEFAULT '',
                    run_cell_ref TEXT NOT NULL DEFAULT '',
                    runtime_control_signal_ref TEXT NOT NULL DEFAULT '',
                    evidence_projection_ref TEXT NOT NULL DEFAULT '',
                    execution_id TEXT NOT NULL DEFAULT '',
                    usage_id TEXT NOT NULL DEFAULT '',
                    artifact_ref TEXT NOT NULL DEFAULT '',
                    memory_record_id TEXT NOT NULL DEFAULT '',
                    memory_version_id TEXT NOT NULL DEFAULT '',
                    retention_class TEXT NOT NULL,
                    visibility TEXT NOT NULL,
                    model_visibility TEXT NOT NULL,
                    tombstoned INTEGER NOT NULL DEFAULT 0,
                    deleted_at REAL NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL
                )
                """
            )
            for column, definition in {
                "agent_run_ref": "TEXT NOT NULL DEFAULT ''",
                "run_cell_ref": "TEXT NOT NULL DEFAULT ''",
                "runtime_control_signal_ref": "TEXT NOT NULL DEFAULT ''",
                "evidence_projection_ref": "TEXT NOT NULL DEFAULT ''",
            }.items():
                _ensure_column(conn, "fact_records", column, definition)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fact_edges (
                    edge_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    source_fact_id TEXT NOT NULL,
                    target_fact_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    created_at REAL NOT NULL,
                    tombstoned INTEGER NOT NULL DEFAULT 0,
                    deleted_at REAL NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL
                )
                """
            )
            for table, fields in {
                "fact_records": (
                    "session_id", "turn_id", "turn_run_id", "task_run_id", "graph_run_id",
                    "trace_id", "span_id", "agent_run_ref", "run_cell_ref",
                    "runtime_control_signal_ref", "evidence_projection_ref",
                    "execution_id", "usage_id", "memory_record_id",
                    "memory_version_id", "fact_type",
                ),
                "fact_edges": ("source_fact_id", "target_fact_id", "relation"),
            }.items():
                for field in fields:
                    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_{field} ON {table} ({field})")

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _record_requires_tombstone(record: RuntimeFactRecord) -> bool:
    return (
        record.retention_class in PROTECTED_RETENTION_CLASSES
        or record.model_visibility == "governed_memory_only"
        or record.fact_type in {"memory_commit", "memory_candidate"}
    )


def _record_tombstone(record: RuntimeFactRecord, *, deleted_at: float, reason: str) -> RuntimeFactRecord:
    refs = dict(record.refs or {})
    return RuntimeFactRecord(
        fact_id=record.fact_id,
        fact_type=record.fact_type,
        scope=_compact_scope(record.scope),
        source={"source_ref": _field(record.source, "source_ref"), "system": _field(record.source, "system")},
        refs={
            key: refs.get(key)
            for key in (
                "trace_id",
                "span_id",
                "agent_run_ref",
                "run_cell_ref",
                "runtime_control_signal_ref",
                "evidence_projection_ref",
                "execution_id",
                "usage_id",
                "memory_record_id",
                "memory_version_id",
                "artifact_ref",
            )
            if refs.get(key)
        },
        attributes={"content_hash": _field(record.attributes, "content_hash")},
        summary="",
        created_at=record.created_at,
        visibility=record.visibility,
        retention_class=record.retention_class,
        model_visibility=record.model_visibility,
        idempotency_key=record.idempotency_key,
        tombstoned=True,
        deleted_at=deleted_at,
        retention_reason=reason,
    )


def _edge_tombstone(edge: RuntimeFactEdge, *, deleted_at: float, reason: str) -> RuntimeFactEdge:
    return RuntimeFactEdge(
        edge_id=edge.edge_id,
        source_fact_id=edge.source_fact_id,
        target_fact_id=edge.target_fact_id,
        relation=edge.relation,
        confidence=edge.confidence,
        created_at=edge.created_at,
        attributes={},
        idempotency_key=edge.idempotency_key,
        tombstoned=True,
        deleted_at=deleted_at,
        retention_reason=reason,
    )


def _compact_scope(scope: dict[str, Any]) -> dict[str, Any]:
    return {key: _field(scope, key) for key in (
        "session_id", "turn_id", "turn_run_id", "task_run_id", "graph_run_id",
        "node_id", "work_order_id", "project_id", "task_environment_id",
    ) if _field(scope, key)}


def _field(payload: dict[str, Any], key: str) -> str:
    return str(dict(payload or {}).get(key) or "").strip()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _counts(values: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip() or "unknown"
        result[key] = result.get(key, 0) + 1
    return result


def safe_fact_id(value: str, *, limit: int = 180) -> str:
    raw = str(value or "")
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in raw).strip("_")
    if len(safe) <= limit:
        return safe or "runtime"
    suffix = uuid.uuid5(uuid.NAMESPACE_URL, raw).hex[:12]
    return f"{safe[: max(1, limit - 13)].rstrip('_')}_{suffix}"
