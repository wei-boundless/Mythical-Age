from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from token_accounting import count_text_tokens

from .contracts import MemoryContextCandidate
from .working_memory_models import WorkingMemoryItem


TaskDurableMemoryStatus = Literal["active", "archived", "deprecated", "rejected"]
TaskDurableGlobalPromotionState = Literal[
    "not_applicable",
    "candidate",
    "needs_review",
    "approved",
    "rejected",
    "promoted_to_global",
]


@dataclass(slots=True, frozen=True)
class TaskDurableMemoryItem:
    task_memory_id: str
    namespace_id: str
    domain_id: str = ""
    task_id: str = ""
    graph_id: str = ""
    project_id: str = ""
    artifact_namespace: str = ""
    source_work_memory_ids: tuple[str, ...] = ()
    source_artifact_refs: tuple[str, ...] = ()
    memory_type: str = "project"
    memory_class: str = "work"
    kind: str = "task_memory"
    memory_semantics: str = "working_fact"
    title: str = ""
    canonical_statement: str = ""
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    retrieval_hints: tuple[str, ...] = ()
    status: TaskDurableMemoryStatus = "active"
    confidence: str = "medium"
    stability: str = "stable"
    eligible_for_task_injection: bool = True
    eligible_for_global_promotion: bool = False
    global_promotion_state: TaskDurableGlobalPromotionState = "not_applicable"
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_durable_memory.task_asset"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_work_memory_ids"] = list(self.source_work_memory_ids)
        payload["source_artifact_refs"] = list(self.source_artifact_refs)
        payload["retrieval_hints"] = list(self.retrieval_hints)
        return payload


@dataclass(slots=True, frozen=True)
class TaskDurableMemoryQuery:
    namespace_id: str = ""
    domain_id: str = ""
    task_id: str = ""
    graph_id: str = ""
    project_id: str = ""
    artifact_namespace: str = ""
    kind: str = ""
    memory_semantics: str = ""
    status: str = ""
    limit: int = 200

    def normalized_limit(self) -> int:
        return max(1, min(int(self.limit or 200), 1000))


@dataclass(slots=True, frozen=True)
class TaskDurableMemoryNamespace:
    namespace_id: str
    domain_id: str = ""
    task_id: str = ""
    graph_id: str = ""
    project_id: str = ""
    artifact_namespace: str = ""
    item_count: int = 0
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
                    task_memory_id, namespace_id, domain_id, task_id, graph_id,
                    project_id, artifact_namespace, source_work_memory_ids_json,
                    source_artifact_refs_json, memory_type, memory_class, kind, memory_semantics,
                    title, canonical_statement, summary, payload_json, retrieval_hints_json,
                    status, confidence, stability, eligible_for_task_injection,
                    eligible_for_global_promotion, global_promotion_state, created_at, updated_at,
                    metadata_json, authority
                ) VALUES (
                    :task_memory_id, :namespace_id, :domain_id, :task_id, :graph_id,
                    :project_id, :artifact_namespace, :source_work_memory_ids_json,
                    :source_artifact_refs_json, :memory_type, :memory_class, :kind, :memory_semantics,
                    :title, :canonical_statement, :summary, :payload_json, :retrieval_hints_json,
                    :status, :confidence, :stability, :eligible_for_task_injection,
                    :eligible_for_global_promotion, :global_promotion_state, :created_at, :updated_at,
                    :metadata_json, :authority
                )
                ON CONFLICT(task_memory_id) DO UPDATE SET
                    namespace_id = excluded.namespace_id,
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
                SELECT namespace_id, domain_id, task_id, graph_id, project_id,
                       artifact_namespace, COUNT(*) AS item_count, MAX(updated_at) AS updated_at
                FROM task_durable_memory_items
                GROUP BY namespace_id, domain_id, task_id, graph_id, project_id, artifact_namespace
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return tuple(
            TaskDurableMemoryNamespace(
                namespace_id=str(row["namespace_id"]),
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
                ON task_durable_memory_items(domain_id, task_id, graph_id, project_id, artifact_namespace);

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


class TaskDurableMemoryService:
    def __init__(self, root_dir: str | Path) -> None:
        self.store = TaskDurableMemoryStore(root_dir)

    def create_item(self, **payload: Any) -> TaskDurableMemoryItem:
        data = dict(payload)
        namespace_id = str(data.get("namespace_id") or "").strip() or self.build_namespace_id(**data)
        if not namespace_id:
            raise ValueError("Task durable memory requires task/domain/graph/project/artifact namespace")
        title = str(data.get("title") or data.get("summary") or data.get("canonical_statement") or "").strip()
        canonical_statement = str(data.get("canonical_statement") or data.get("summary") or title).strip()
        if not canonical_statement:
            raise ValueError("Task durable memory requires canonical_statement or summary")
        item = TaskDurableMemoryItem(
            task_memory_id=str(
                data.get("task_memory_id")
                or stable_task_memory_id(
                    namespace_id,
                    title,
                    canonical_statement,
                    ",".join(_strings(data.get("source_work_memory_ids"))),
                )
            ),
            namespace_id=namespace_id,
            domain_id=str(data.get("domain_id") or ""),
            task_id=str(data.get("task_id") or ""),
            graph_id=str(data.get("graph_id") or ""),
            project_id=str(data.get("project_id") or ""),
            artifact_namespace=str(data.get("artifact_namespace") or ""),
            source_work_memory_ids=tuple(_strings(data.get("source_work_memory_ids"))),
            source_artifact_refs=tuple(_strings(data.get("source_artifact_refs"))),
            memory_type=str(data.get("memory_type") or "project"),
            memory_class=str(data.get("memory_class") or "work"),
            kind=str(data.get("kind") or "task_memory"),
            memory_semantics=str(data.get("memory_semantics") or "working_fact"),
            title=title or canonical_statement[:120],
            canonical_statement=canonical_statement,
            summary=str(data.get("summary") or canonical_statement).strip(),
            payload=dict(data.get("payload") or {}),
            retrieval_hints=tuple(_strings(data.get("retrieval_hints"))),
            status=str(data.get("status") or "active"),  # type: ignore[arg-type]
            confidence=str(data.get("confidence") or "medium"),
            stability=str(data.get("stability") or "stable"),
            eligible_for_task_injection=bool(data.get("eligible_for_task_injection", True)),
            eligible_for_global_promotion=bool(data.get("eligible_for_global_promotion", False)),
            global_promotion_state=str(data.get("global_promotion_state") or "not_applicable"),  # type: ignore[arg-type]
            metadata=dict(data.get("metadata") or {}),
            authority=str(data.get("authority") or "task_durable_memory.task_asset"),
        )
        return self.store.upsert_item(item)

    def promote_working_memory_item(self, item: WorkingMemoryItem, **payload: Any) -> TaskDurableMemoryItem:
        if item.promotion_state not in {"candidate", "needs_review", "approved"} and item.kind != "promotion_candidate":
            raise ValueError("Working memory item is not eligible for task durable promotion")

        namespace_payload = {
            "domain_id": str(payload.get("domain_id") or item.metadata.get("domain_id") or ""),
            "task_id": str(payload.get("task_id") or item.task_id or ""),
            "graph_id": str(payload.get("graph_id") or item.graph_id or ""),
            "project_id": str(payload.get("project_id") or item.metadata.get("project_id") or ""),
            "artifact_namespace": str(payload.get("artifact_namespace") or item.metadata.get("artifact_namespace") or ""),
        }
        namespace_id = str(payload.get("namespace_id") or "").strip() or self.build_namespace_id(**namespace_payload)
        if not namespace_id:
            raise ValueError("Task durable promotion requires task_id, graph_id, project_id, domain_id or artifact_namespace")

        title = str(payload.get("title") or item.title or item.summary or item.work_memory_id).strip()
        canonical_statement = str(
            payload.get("canonical_statement")
            or item.summary
            or item.payload.get("canonical_statement")
            or item.payload.get("text")
            or item.payload.get("content")
            or item.work_memory_id
        ).strip()
        summary = str(payload.get("summary") or item.summary or canonical_statement).strip()
        retrieval_hints = _dedupe_strings(
            [
                *_strings(payload.get("retrieval_hints")),
                namespace_id,
                namespace_payload["domain_id"],
                namespace_payload["task_id"],
                namespace_payload["graph_id"],
                namespace_payload["project_id"],
                namespace_payload["artifact_namespace"],
                item.owner_node_id,
                item.writer_agent_id,
                item.kind,
                item.memory_semantics,
                *item.tags,
            ]
        )
        source_refs = {
            "work_memory_id": item.work_memory_id,
            "task_run_id": item.task_run_id,
            "task_id": item.task_id,
            "graph_id": item.graph_id,
            "owner_node_id": item.owner_node_id,
            "node_run_id": item.node_run_id,
            "writer_agent_id": item.writer_agent_id,
            "status": item.status,
            "promotion_state": item.promotion_state,
            "source_event_refs": list(item.source_event_refs),
            "source_message_refs": list(item.source_message_refs),
            "artifact_refs": list(item.artifact_refs),
            "contract_refs": list(item.contract_refs),
        }
        return self.create_item(
            namespace_id=namespace_id,
            **namespace_payload,
            source_work_memory_ids=[item.work_memory_id],
            source_artifact_refs=list(item.artifact_refs),
            memory_type=str(payload.get("memory_type") or "project"),
            memory_class=str(payload.get("memory_class") or "work"),
            kind=str(payload.get("kind") or item.kind or "task_memory"),
            memory_semantics=str(payload.get("memory_semantics") or item.memory_semantics or "working_fact"),
            title=title,
            canonical_statement=canonical_statement,
            summary=summary,
            payload={
                "source_working_memory": item.to_dict(),
                "source_refs": source_refs,
            },
            retrieval_hints=retrieval_hints[:12],
            confidence=str(payload.get("confidence") or "medium"),
            metadata={
                "actor_id": str(payload.get("actor_id") or "memory_governance_ui"),
                "promotion_reason": str(payload.get("reason") or "manual_working_memory_promotion"),
                "promotion_source": "working_memory",
                "promotion_source_refs": source_refs,
            },
        )

    def get_item(self, task_memory_id: str) -> TaskDurableMemoryItem | None:
        return self.store.get_item(task_memory_id)

    def query_items(self, **filters: Any) -> tuple[TaskDurableMemoryItem, ...]:
        return self.store.query_items(TaskDurableMemoryQuery(**filters))

    def list_namespaces(self):
        return self.store.list_namespaces()

    def context_candidates(
        self,
        *,
        namespace_id: str = "",
        domain_id: str = "",
        task_id: str = "",
        graph_id: str = "",
        project_id: str = "",
        artifact_namespace: str = "",
        requested_kinds: list[str] | tuple[str, ...] = (),
        requested_semantics: list[str] | tuple[str, ...] = (),
        limit: int = 20,
    ) -> tuple[MemoryContextCandidate, ...]:
        query_namespace = namespace_id or self.build_namespace_id(
            domain_id=domain_id,
            task_id=task_id,
            graph_id=graph_id,
            project_id=project_id,
            artifact_namespace=artifact_namespace,
        )
        if not query_namespace and not any([domain_id, task_id, graph_id, project_id, artifact_namespace]):
            return ()
        items = self.query_items(
            namespace_id=query_namespace,
            domain_id=domain_id,
            task_id=task_id,
            graph_id=graph_id,
            project_id=project_id,
            artifact_namespace=artifact_namespace,
            status="active",
            limit=max(1, min(int(limit or 20), 100)),
        )
        kind_filter = set(_strings(requested_kinds))
        semantics_filter = set(_strings(requested_semantics))
        candidates: list[MemoryContextCandidate] = []
        for item in items:
            if not item.eligible_for_task_injection:
                continue
            if kind_filter and item.kind not in kind_filter:
                continue
            if semantics_filter and item.memory_semantics not in semantics_filter:
                continue
            preview = _render_candidate_preview(item)
            if not preview:
                continue
            candidates.append(
                MemoryContextCandidate(
                    candidate_id=f"memory-context:{item.namespace_id}:task-durable:{item.task_memory_id}",
                    memory_layer="task_durable",
                    source="task_durable_memory.store",
                    content_ref=item.task_memory_id,
                    rendered_preview=preview,
                    relevance=0.82,
                    confidence=_confidence(item.confidence),
                    staleness="task_namespace_scoped",
                    owner_task_id=item.task_id,
                    token_estimate=max(1, count_text_tokens(preview)),
                    budget_class="preferred",
                    can_override_current_turn=False,
                    requires_verification_before_use=item.global_promotion_state in {"candidate", "needs_review"},
                    authority="candidate_only",
                    metadata={
                        "namespace_id": item.namespace_id,
                        "domain_id": item.domain_id,
                        "task_id": item.task_id,
                        "graph_id": item.graph_id,
                        "project_id": item.project_id,
                        "artifact_namespace": item.artifact_namespace,
                        "kind": item.kind,
                        "memory_semantics": item.memory_semantics,
                        "source_authority": item.authority,
                        "source_work_memory_ids": list(item.source_work_memory_ids),
                    },
                )
            )
        return tuple(candidates)

    @staticmethod
    def build_namespace_id(**payload: Any) -> str:
        return build_namespace_id(
            domain_id=str(payload.get("domain_id") or ""),
            task_id=str(payload.get("task_id") or ""),
            graph_id=str(payload.get("graph_id") or ""),
            project_id=str(payload.get("project_id") or ""),
            artifact_namespace=str(payload.get("artifact_namespace") or ""),
        )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_task_memory_id(*parts: Any) -> str:
    text = "|".join(str(part or "").strip() for part in parts if str(part or "").strip())
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return f"tdm:{digest}"


def build_namespace_id(
    *,
    domain_id: str = "",
    task_id: str = "",
    graph_id: str = "",
    project_id: str = "",
    artifact_namespace: str = "",
) -> str:
    parts = [
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


def _render_candidate_preview(item: TaskDurableMemoryItem) -> str:
    lines = []
    if item.title:
        lines.append(f"### {item.title}")
    lines.append(
        " / ".join(
            part
            for part in (
                f"namespace={item.namespace_id}",
                f"kind={item.kind}",
                f"semantics={item.memory_semantics}",
                f"task={item.task_id}",
                f"graph={item.graph_id}",
            )
            if part
        )
    )
    if item.summary:
        lines.append(item.summary)
    elif item.canonical_statement:
        lines.append(item.canonical_statement)
    return "\n".join(line for line in lines if line).strip()


def _confidence(value: str) -> float:
    normalized = str(value or "").lower()
    if normalized in {"high", "strong"}:
        return 0.86
    if normalized in {"low", "weak"}:
        return 0.42
    return 0.66


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


def _strings(values: Any) -> list[str]:
    return [str(item).strip() for item in list(values or []) if str(item).strip()]


def _string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in list(value or []) if str(item).strip()]


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
