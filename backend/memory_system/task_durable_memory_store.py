from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .task_durable_memory_models import (
    TaskDurableMemoryItem,
    TaskDurableMemoryNamespace,
    TaskDurableMemoryQuery,
)


class TaskDurableMemoryStore:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir = self.root_dir / "archive"
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.namespaces_dir = self.root_dir / "namespaces"
        self.namespaces_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root_dir / "task_durable_memory.sqlite"
        self._ensure_schema()

    def upsert_item(self, item: TaskDurableMemoryItem) -> TaskDurableMemoryItem:
        now = utc_now_iso()
        stored = replace(
            item,
            namespace_id=item.namespace_id or build_namespace_id(
                task_family=item.task_family,
                domain_id=item.domain_id,
                task_id=item.task_id,
                graph_id=item.graph_id,
                project_id=item.project_id,
                artifact_namespace=item.artifact_namespace,
            ),
            created_at=item.created_at or now,
            updated_at=item.updated_at or now,
        )
        if not stored.namespace_id:
            raise ValueError("Task durable memory requires a namespace")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO task_durable_memory_items (
                    task_memory_id, namespace_id, task_family, domain_id, task_id, graph_id,
                    project_id, artifact_namespace, source_work_memory_ids_json,
                    source_artifact_refs_json, memory_type, memory_class, kind, memory_semantics,
                    title, canonical_statement, summary, payload_json, retrieval_hints_json,
                    status, confidence, stability, eligible_for_task_injection,
                    eligible_for_global_promotion, global_promotion_state, created_at, updated_at,
                    metadata_json, authority
                ) VALUES (
                    :task_memory_id, :namespace_id, :task_family, :domain_id, :task_id, :graph_id,
                    :project_id, :artifact_namespace, :source_work_memory_ids_json,
                    :source_artifact_refs_json, :memory_type, :memory_class, :kind, :memory_semantics,
                    :title, :canonical_statement, :summary, :payload_json, :retrieval_hints_json,
                    :status, :confidence, :stability, :eligible_for_task_injection,
                    :eligible_for_global_promotion, :global_promotion_state, :created_at, :updated_at,
                    :metadata_json, :authority
                )
                ON CONFLICT(task_memory_id) DO UPDATE SET
                    namespace_id = excluded.namespace_id,
                    task_family = excluded.task_family,
                    domain_id = excluded.domain_id,
                    task_id = excluded.task_id,
                    graph_id = excluded.graph_id,
                    project_id = excluded.project_id,
                    artifact_namespace = excluded.artifact_namespace,
                    source_work_memory_ids_json = excluded.source_work_memory_ids_json,
                    source_artifact_refs_json = excluded.source_artifact_refs_json,
                    memory_type = excluded.memory_type,
                    memory_class = excluded.memory_class,
                    kind = excluded.kind,
                    memory_semantics = excluded.memory_semantics,
                    title = excluded.title,
                    canonical_statement = excluded.canonical_statement,
                    summary = excluded.summary,
                    payload_json = excluded.payload_json,
                    retrieval_hints_json = excluded.retrieval_hints_json,
                    status = excluded.status,
                    confidence = excluded.confidence,
                    stability = excluded.stability,
                    eligible_for_task_injection = excluded.eligible_for_task_injection,
                    eligible_for_global_promotion = excluded.eligible_for_global_promotion,
                    global_promotion_state = excluded.global_promotion_state,
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json,
                    authority = excluded.authority
                """,
                _item_row(stored),
            )
            conn.execute(
                """
                INSERT INTO task_durable_memory_events (
                    event_id, task_memory_id, namespace_id, event_type, actor_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"tdmevt:{stored.task_memory_id}:upsert:{now}",
                    stored.task_memory_id,
                    stored.namespace_id,
                    "upserted",
                    str(stored.metadata.get("actor_id") or ""),
                    _json({"status": stored.status, "global_promotion_state": stored.global_promotion_state}),
                    now,
                ),
            )
        return stored

    def get_item(self, task_memory_id: str) -> TaskDurableMemoryItem | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_durable_memory_items WHERE task_memory_id = ?",
                (task_memory_id,),
            ).fetchone()
        return _item_from_row(row) if row is not None else None

    def query_items(self, query: TaskDurableMemoryQuery | None = None) -> tuple[TaskDurableMemoryItem, ...]:
        query = query or TaskDurableMemoryQuery()
        filters: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("namespace_id", query.namespace_id),
            ("task_family", query.task_family),
            ("domain_id", query.domain_id),
            ("task_id", query.task_id),
            ("graph_id", query.graph_id),
            ("project_id", query.project_id),
            ("artifact_namespace", query.artifact_namespace),
            ("kind", query.kind),
            ("memory_semantics", query.memory_semantics),
            ("status", query.status),
        ):
            if str(value or "").strip():
                filters.append(f"{column} = ?")
                params.append(str(value).strip())
        sql = "SELECT * FROM task_durable_memory_items"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY updated_at DESC, created_at DESC LIMIT ?"
        params.append(query.normalized_limit())
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_item_from_row(row) for row in rows)

    def list_namespaces(self) -> tuple[TaskDurableMemoryNamespace, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT namespace_id, task_family, domain_id, task_id, graph_id, project_id,
                       artifact_namespace, COUNT(*) AS item_count, MAX(updated_at) AS updated_at
                FROM task_durable_memory_items
                GROUP BY namespace_id, task_family, domain_id, task_id, graph_id, project_id, artifact_namespace
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return tuple(
            TaskDurableMemoryNamespace(
                namespace_id=str(row["namespace_id"]),
                task_family=str(row["task_family"]),
                domain_id=str(row["domain_id"]),
                task_id=str(row["task_id"]),
                graph_id=str(row["graph_id"]),
                project_id=str(row["project_id"]),
                artifact_namespace=str(row["artifact_namespace"]),
                item_count=int(row["item_count"]),
                updated_at=str(row["updated_at"] or ""),
            )
            for row in rows
        )

    def update_lifecycle(
        self,
        task_memory_id: str,
        *,
        status: str | None = None,
        eligible_for_global_promotion: bool | None = None,
        global_promotion_state: str | None = None,
        actor_id: str = "",
        metadata: dict[str, Any] | None = None,
        event_type: str = "lifecycle_updated",
    ) -> TaskDurableMemoryItem:
        current = self.get_item(task_memory_id)
        if current is None:
            raise KeyError(f"Unknown task durable memory item: {task_memory_id}")
        now = utc_now_iso()
        updated = replace(
            current,
            status=(status or current.status),  # type: ignore[arg-type]
            eligible_for_global_promotion=(
                current.eligible_for_global_promotion
                if eligible_for_global_promotion is None
                else bool(eligible_for_global_promotion)
            ),
            global_promotion_state=(global_promotion_state or current.global_promotion_state),  # type: ignore[arg-type]
            metadata={**current.metadata, **dict(metadata or {})},
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE task_durable_memory_items
                SET status = ?, eligible_for_global_promotion = ?, global_promotion_state = ?,
                    updated_at = ?, metadata_json = ?
                WHERE task_memory_id = ?
                """,
                (
                    updated.status,
                    int(updated.eligible_for_global_promotion),
                    updated.global_promotion_state,
                    updated.updated_at,
                    _json(updated.metadata),
                    task_memory_id,
                ),
            )
            conn.execute(
                """
                INSERT INTO task_durable_memory_events (
                    event_id, task_memory_id, namespace_id, event_type, actor_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"tdmevt:{task_memory_id}:{event_type}:{now}",
                    task_memory_id,
                    updated.namespace_id,
                    event_type,
                    actor_id,
                    _json(
                        {
                            "status": updated.status,
                            "eligible_for_global_promotion": updated.eligible_for_global_promotion,
                            "global_promotion_state": updated.global_promotion_state,
                        }
                    ),
                    now,
                ),
            )
        return updated

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS task_durable_memory_items (
                    task_memory_id TEXT PRIMARY KEY,
                    namespace_id TEXT NOT NULL,
                    task_family TEXT NOT NULL DEFAULT '',
                    domain_id TEXT NOT NULL DEFAULT '',
                    task_id TEXT NOT NULL DEFAULT '',
                    graph_id TEXT NOT NULL DEFAULT '',
                    project_id TEXT NOT NULL DEFAULT '',
                    artifact_namespace TEXT NOT NULL DEFAULT '',
                    source_work_memory_ids_json TEXT NOT NULL DEFAULT '[]',
                    source_artifact_refs_json TEXT NOT NULL DEFAULT '[]',
                    memory_type TEXT NOT NULL DEFAULT 'project',
                    memory_class TEXT NOT NULL DEFAULT 'work',
                    kind TEXT NOT NULL DEFAULT 'task_memory',
                    memory_semantics TEXT NOT NULL DEFAULT 'working_fact',
                    title TEXT NOT NULL DEFAULT '',
                    canonical_statement TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    retrieval_hints_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'active',
                    confidence TEXT NOT NULL DEFAULT 'medium',
                    stability TEXT NOT NULL DEFAULT 'stable',
                    eligible_for_task_injection INTEGER NOT NULL DEFAULT 1,
                    eligible_for_global_promotion INTEGER NOT NULL DEFAULT 0,
                    global_promotion_state TEXT NOT NULL DEFAULT 'not_applicable',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    authority TEXT NOT NULL DEFAULT 'task_durable_memory.task_asset'
                );

                CREATE INDEX IF NOT EXISTS idx_task_durable_namespace
                ON task_durable_memory_items(namespace_id, status, kind, memory_semantics);

                CREATE INDEX IF NOT EXISTS idx_task_durable_scope
                ON task_durable_memory_items(task_family, domain_id, task_id, graph_id, project_id, artifact_namespace);

                CREATE TABLE IF NOT EXISTS task_durable_memory_events (
                    event_id TEXT PRIMARY KEY,
                    task_memory_id TEXT NOT NULL,
                    namespace_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                """
            )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_task_memory_id(*parts: Any) -> str:
    text = "|".join(str(part or "").strip() for part in parts if str(part or "").strip())
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return f"tdm:{digest}"


def build_namespace_id(
    *,
    task_family: str = "",
    domain_id: str = "",
    task_id: str = "",
    graph_id: str = "",
    project_id: str = "",
    artifact_namespace: str = "",
) -> str:
    parts = [
        ("family", task_family),
        ("domain", domain_id),
        ("task", task_id),
        ("graph", graph_id),
        ("project", project_id),
        ("artifact", artifact_namespace),
    ]
    normalized = [f"{key}:{_safe_part(value)}" for key, value in parts if str(value or "").strip()]
    if not normalized:
        return ""
    digest = hashlib.sha1("|".join(normalized).encode("utf-8")).hexdigest()[:12]
    return f"tdmns:{digest}"


def _safe_part(value: Any) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_", ".", ":"} else "_" for char in str(value or "").strip())[:120]


def _item_row(item: TaskDurableMemoryItem) -> dict[str, Any]:
    return {
        **item.to_dict(),
        "source_work_memory_ids_json": _json(item.source_work_memory_ids),
        "source_artifact_refs_json": _json(item.source_artifact_refs),
        "payload_json": _json(item.payload),
        "retrieval_hints_json": _json(item.retrieval_hints),
        "eligible_for_task_injection": int(item.eligible_for_task_injection),
        "eligible_for_global_promotion": int(item.eligible_for_global_promotion),
        "metadata_json": _json(item.metadata),
    }


def _item_from_row(row: sqlite3.Row) -> TaskDurableMemoryItem:
    return TaskDurableMemoryItem(
        task_memory_id=str(row["task_memory_id"]),
        namespace_id=str(row["namespace_id"]),
        task_family=str(row["task_family"]),
        domain_id=str(row["domain_id"]),
        task_id=str(row["task_id"]),
        graph_id=str(row["graph_id"]),
        project_id=str(row["project_id"]),
        artifact_namespace=str(row["artifact_namespace"]),
        source_work_memory_ids=tuple(_string_list(_loads(row["source_work_memory_ids_json"]))),
        source_artifact_refs=tuple(_string_list(_loads(row["source_artifact_refs_json"]))),
        memory_type=str(row["memory_type"]),
        memory_class=str(row["memory_class"]),
        kind=str(row["kind"]),
        memory_semantics=str(row["memory_semantics"]),
        title=str(row["title"]),
        canonical_statement=str(row["canonical_statement"]),
        summary=str(row["summary"]),
        payload=dict(_loads(row["payload_json"]) or {}),
        retrieval_hints=tuple(_string_list(_loads(row["retrieval_hints_json"]))),
        status=str(row["status"]),  # type: ignore[arg-type]
        confidence=str(row["confidence"]),
        stability=str(row["stability"]),
        eligible_for_task_injection=bool(row["eligible_for_task_injection"]),
        eligible_for_global_promotion=bool(row["eligible_for_global_promotion"]),
        global_promotion_state=str(row["global_promotion_state"]),  # type: ignore[arg-type]
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        metadata=dict(_loads(row["metadata_json"]) or {}),
        authority=str(row["authority"]),
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
