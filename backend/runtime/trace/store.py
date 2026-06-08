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

from .schema import RuntimeTraceEvent, RuntimeTraceRun, RuntimeTraceSpan


class RuntimeTraceStore:
    authority = "runtime.trace.store"

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.store_dir = self.root_dir / "traces"
        self.runs_dir = self.store_dir / "runs"
        self.spans_dir = self.store_dir / "spans"
        self.events_dir = self.store_dir / "events"
        self.index_dir = self.store_dir / "index"
        self.index_path = self.index_dir / "by_scope.sqlite"
        self._lock = threading.RLock()
        for path in (self.runs_dir, self.spans_dir, self.events_dir, self.index_dir):
            path.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def upsert_run(self, run: RuntimeTraceRun) -> RuntimeTraceRun:
        payload = run.to_dict()
        with self._lock, self._connect() as conn:
            existing = self._row_by_id_or_key(
                conn,
                table="trace_runs",
                id_field="trace_id",
                object_id=run.trace_id,
                idempotency_key=run.idempotency_key,
            )
            if existing is not None and str(existing["object_id"] or "") != run.trace_id:
                return RuntimeTraceRun.from_dict(json.loads(str(existing["payload_json"] or "{}")))
            conn.execute(
                """
                INSERT INTO trace_runs (
                    trace_id, idempotency_key, run_kind, root_run_id, status,
                    session_id, turn_id, turn_run_id, task_run_id, graph_run_id,
                    started_at, ended_at, tombstoned, deleted_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trace_id) DO UPDATE SET
                    status=excluded.status,
                    ended_at=excluded.ended_at,
                    tombstoned=excluded.tombstoned,
                    deleted_at=excluded.deleted_at,
                    payload_json=excluded.payload_json
                """,
                self._run_row_values(run, payload),
            )
            self._append_jsonl(self.runs_dir / "runs.jsonl", payload)
        return run

    def upsert_span(self, span: RuntimeTraceSpan) -> RuntimeTraceSpan:
        payload = span.to_dict()
        with self._lock, self._connect() as conn:
            existing = self._row_by_id_or_key(
                conn,
                table="trace_spans",
                id_field="span_id",
                object_id=span.span_id,
                idempotency_key=span.idempotency_key,
            )
            if existing is not None and str(existing["object_id"] or "") != span.span_id:
                return RuntimeTraceSpan.from_dict(json.loads(str(existing["payload_json"] or "{}")))
            conn.execute(
                """
                INSERT INTO trace_spans (
                    trace_id, span_id, idempotency_key, parent_span_id, name,
                    span_kind, status, session_id, turn_id, turn_run_id,
                    task_run_id, graph_run_id, started_at, ended_at, tombstoned,
                    deleted_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(span_id) DO UPDATE SET
                    status=excluded.status,
                    ended_at=excluded.ended_at,
                    tombstoned=excluded.tombstoned,
                    deleted_at=excluded.deleted_at,
                    payload_json=excluded.payload_json
                """,
                self._span_row_values(span, payload),
            )
            self._append_jsonl(self.spans_dir / f"{_safe_id(span.trace_id)}.jsonl", payload)
        return span

    def append_event(self, event: RuntimeTraceEvent) -> RuntimeTraceEvent:
        payload = event.to_dict()
        with self._lock, self._connect() as conn:
            existing = self._row_by_id_or_key(
                conn,
                table="trace_events",
                id_field="event_id",
                object_id=event.event_id,
                idempotency_key=event.idempotency_key,
            )
            if existing is not None:
                return RuntimeTraceEvent.from_dict(json.loads(str(existing["payload_json"] or "{}")))
            conn.execute(
                """
                INSERT INTO trace_events (
                    trace_id, event_id, idempotency_key, span_id, name,
                    session_id, turn_id, turn_run_id, task_run_id, graph_run_id,
                    created_at, tombstoned, deleted_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._event_row_values(event, payload),
            )
            self._append_jsonl(self.events_dir / f"{_safe_id(event.trace_id)}.jsonl", payload)
        return event

    def get_run(self, trace_id: str, *, include_tombstones: bool = False) -> RuntimeTraceRun | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json, tombstoned FROM trace_runs WHERE trace_id = ?",
                (str(trace_id or ""),),
            ).fetchone()
        if row is None or (bool(row["tombstoned"]) and not include_tombstones):
            return None
        return RuntimeTraceRun.from_dict(json.loads(str(row["payload_json"] or "{}")))

    def get_run_by_id_or_key(
        self,
        *,
        trace_id: str,
        idempotency_key: str,
        include_tombstones: bool = False,
    ) -> RuntimeTraceRun | None:
        with self._lock, self._connect() as conn:
            row = self._row_by_id_or_key(
                conn,
                table="trace_runs",
                id_field="trace_id",
                object_id=trace_id,
                idempotency_key=idempotency_key,
            )
        if row is None or (bool(row["tombstoned"]) and not include_tombstones):
            return None
        return RuntimeTraceRun.from_dict(json.loads(str(row["payload_json"] or "{}")))

    def get_span_by_id_or_key(
        self,
        *,
        span_id: str,
        idempotency_key: str,
        include_tombstones: bool = False,
    ) -> RuntimeTraceSpan | None:
        with self._lock, self._connect() as conn:
            row = self._row_by_id_or_key(
                conn,
                table="trace_spans",
                id_field="span_id",
                object_id=span_id,
                idempotency_key=idempotency_key,
            )
        if row is None or (bool(row["tombstoned"]) and not include_tombstones):
            return None
        return RuntimeTraceSpan.from_dict(json.loads(str(row["payload_json"] or "{}")))

    def list_spans(
        self,
        *,
        trace_id: str = "",
        task_run_id: str = "",
        session_id: str = "",
        graph_run_id: str = "",
        include_tombstones: bool = False,
        limit: int = 1000,
    ) -> list[RuntimeTraceSpan]:
        rows = self._query(
            "trace_spans",
            filters={"trace_id": trace_id, "task_run_id": task_run_id, "session_id": session_id, "graph_run_id": graph_run_id},
            include_tombstones=include_tombstones,
            limit=limit,
            order_field="started_at",
        )
        return [RuntimeTraceSpan.from_dict(json.loads(str(row["payload_json"] or "{}"))) for row in rows]

    def list_events(
        self,
        *,
        trace_id: str = "",
        task_run_id: str = "",
        session_id: str = "",
        graph_run_id: str = "",
        include_tombstones: bool = False,
        limit: int = 1000,
    ) -> list[RuntimeTraceEvent]:
        rows = self._query(
            "trace_events",
            filters={"trace_id": trace_id, "task_run_id": task_run_id, "session_id": session_id, "graph_run_id": graph_run_id},
            include_tombstones=include_tombstones,
            limit=limit,
            order_field="created_at",
        )
        return [RuntimeTraceEvent.from_dict(json.loads(str(row["payload_json"] or "{}"))) for row in rows]

    def prune_task_runs(self, task_run_ids: set[str] | list[str] | tuple[str, ...]) -> dict[str, Any]:
        targets = {str(item).strip() for item in list(task_run_ids or []) if str(item).strip()}
        return self._delete_by_field("task_run_id", targets)

    def prune_session(self, session_id: str) -> dict[str, Any]:
        target = str(session_id or "").strip()
        return self._delete_by_field("session_id", {target} if target else set())

    def summarize_trace(self, trace_id: str) -> dict[str, Any]:
        run = self.get_run(trace_id)
        spans = self.list_spans(trace_id=trace_id, limit=5000)
        events = self.list_events(trace_id=trace_id, limit=5000)
        return {
            "authority": "runtime.trace.summary",
            "trace_id": trace_id,
            "available": run is not None,
            "run": run.to_dict() if run is not None else None,
            "span_count": len(spans),
            "event_count": len(events),
            "error_span_count": sum(1 for item in spans if item.status == "error"),
            "latest_span": spans[-1].to_dict() if spans else None,
        }

    def _delete_by_field(self, field: str, targets: set[str]) -> dict[str, Any]:
        if not targets:
            return {"authority": "runtime.trace.store.prune", "deleted_counts": {}, "requested_targets": []}
        placeholders = ",".join("?" for _ in targets)
        counts: dict[str, int] = {}
        with self._lock, self._connect() as conn:
            for table in ("trace_runs", "trace_spans", "trace_events"):
                before = int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {field} IN ({placeholders})", tuple(sorted(targets))).fetchone()[0])
                if before:
                    conn.execute(f"DELETE FROM {table} WHERE {field} IN ({placeholders})", tuple(sorted(targets)))
                    counts[table] = before
        return {
            "authority": "runtime.trace.store.prune",
            "where_field": field,
            "requested_targets": sorted(targets),
            "deleted_counts": counts,
        }

    def _query(self, table: str, *, filters: dict[str, str], include_tombstones: bool, limit: int, order_field: str) -> list[sqlite3.Row]:
        clauses: list[str] = []
        params: list[Any] = []
        for field, value in filters.items():
            normalized = str(value or "").strip()
            if normalized:
                clauses.append(f"{field} = ?")
                params.append(normalized)
        if not include_tombstones:
            clauses.append("tombstoned = 0")
        sql = f"SELECT payload_json FROM {table}"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += f" ORDER BY {order_field} ASC LIMIT ?"
        params.append(max(1, min(int(limit or 1000), 10000)))
        with self._lock, self._connect() as conn:
            return list(conn.execute(sql, tuple(params)).fetchall())

    def _run_row_values(self, run: RuntimeTraceRun, payload: dict[str, Any]) -> tuple[Any, ...]:
        scope = dict(run.scope or {})
        return (
            run.trace_id, run.idempotency_key, run.run_kind, run.root_run_id, run.status,
            _field(scope, "session_id"), _field(scope, "turn_id"), _field(scope, "turn_run_id"),
            _field(scope, "task_run_id"), _field(scope, "graph_run_id"),
            float(run.started_at), float(run.ended_at), 1 if run.tombstoned else 0,
            float(run.deleted_at), json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )

    def _span_row_values(self, span: RuntimeTraceSpan, payload: dict[str, Any]) -> tuple[Any, ...]:
        scope = dict(span.scope or {})
        return (
            span.trace_id, span.span_id, span.idempotency_key, span.parent_span_id, span.name,
            span.span_kind, span.status, _field(scope, "session_id"), _field(scope, "turn_id"),
            _field(scope, "turn_run_id"), _field(scope, "task_run_id"), _field(scope, "graph_run_id"),
            float(span.started_at), float(span.ended_at), 1 if span.tombstoned else 0,
            float(span.deleted_at), json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )

    def _event_row_values(self, event: RuntimeTraceEvent, payload: dict[str, Any]) -> tuple[Any, ...]:
        scope = dict(event.scope or {})
        return (
            event.trace_id, event.event_id, event.idempotency_key, event.span_id, event.name,
            _field(scope, "session_id"), _field(scope, "turn_id"), _field(scope, "turn_run_id"),
            _field(scope, "task_run_id"), _field(scope, "graph_run_id"),
            float(event.created_at), 1 if event.tombstoned else 0, float(event.deleted_at),
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

    def _row_by_id_or_key(
        self,
        conn: sqlite3.Connection,
        *,
        table: str,
        id_field: str,
        object_id: str,
        idempotency_key: str,
    ) -> sqlite3.Row | None:
        normalized_id = str(object_id or "")
        if normalized_id:
            row = conn.execute(
                f"SELECT {id_field} AS object_id, tombstoned, payload_json FROM {table} WHERE {id_field} = ? LIMIT 1",
                (normalized_id,),
            ).fetchone()
            if row is not None:
                return row
        normalized_key = str(idempotency_key or "")
        if not normalized_key:
            return None
        return conn.execute(
            f"SELECT {id_field} AS object_id, tombstoned, payload_json FROM {table} WHERE idempotency_key = ? LIMIT 1",
            (normalized_key,),
        ).fetchone()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trace_runs (
                    trace_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    run_kind TEXT NOT NULL,
                    root_run_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    session_id TEXT NOT NULL DEFAULT '',
                    turn_id TEXT NOT NULL DEFAULT '',
                    turn_run_id TEXT NOT NULL DEFAULT '',
                    task_run_id TEXT NOT NULL DEFAULT '',
                    graph_run_id TEXT NOT NULL DEFAULT '',
                    started_at REAL NOT NULL,
                    ended_at REAL NOT NULL DEFAULT 0,
                    tombstoned INTEGER NOT NULL DEFAULT 0,
                    deleted_at REAL NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trace_spans (
                    trace_id TEXT NOT NULL,
                    span_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    parent_span_id TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL,
                    span_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    session_id TEXT NOT NULL DEFAULT '',
                    turn_id TEXT NOT NULL DEFAULT '',
                    turn_run_id TEXT NOT NULL DEFAULT '',
                    task_run_id TEXT NOT NULL DEFAULT '',
                    graph_run_id TEXT NOT NULL DEFAULT '',
                    started_at REAL NOT NULL,
                    ended_at REAL NOT NULL DEFAULT 0,
                    tombstoned INTEGER NOT NULL DEFAULT 0,
                    deleted_at REAL NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trace_events (
                    trace_id TEXT NOT NULL,
                    event_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    span_id TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL,
                    session_id TEXT NOT NULL DEFAULT '',
                    turn_id TEXT NOT NULL DEFAULT '',
                    turn_run_id TEXT NOT NULL DEFAULT '',
                    task_run_id TEXT NOT NULL DEFAULT '',
                    graph_run_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    tombstoned INTEGER NOT NULL DEFAULT 0,
                    deleted_at REAL NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL
                )
                """
            )
            for table, fields in {
                "trace_runs": ("session_id", "turn_run_id", "task_run_id", "graph_run_id", "status"),
                "trace_spans": ("trace_id", "session_id", "turn_run_id", "task_run_id", "graph_run_id", "status"),
                "trace_events": ("trace_id", "session_id", "turn_run_id", "task_run_id", "graph_run_id"),
            }.items():
                for field in fields:
                    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_{field} ON {table} ({field})")

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _field(payload: dict[str, Any], key: str) -> str:
    return str(dict(payload or {}).get(key) or "").strip()


def _safe_id(value: str, *, limit: int = 180) -> str:
    raw = str(value or "")
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in raw).strip("_")
    if len(safe) <= limit:
        return safe or "trace"
    suffix = uuid.uuid5(uuid.NAMESPACE_URL, raw).hex[:12]
    return f"{safe[: max(1, limit - 13)].rstrip('_')}_{suffix}"
