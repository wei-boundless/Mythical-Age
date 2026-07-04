from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

from core.project_layout import ProjectLayout

from .models import WorkProduct


class WorkProductRepository:
    authority = "task_system.work_product_repository"

    def __init__(self, base_dir: str | Path) -> None:
        layout = ProjectLayout.from_backend_dir(base_dir)
        self.root = layout.tasks_dir
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "task_environment.sqlite"
        self._ensure_schema()

    def upsert_work_product(self, product: WorkProduct) -> WorkProduct:
        now = _now()
        stored = replace(product, created_at=product.created_at or now, updated_at=now)
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO task_work_products (
                    work_product_id, task_environment_id, task_instance_id, source_episode_id,
                    product_domain, product_kind, stable_ref, payload_ref, payload_json,
                    evidence_refs_json, anchor_refs_json, artifact_refs_json,
                    acceptance_claims_json, downstream_refs_json, confidence, status,
                    generation, created_at, updated_at, metadata_json, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(work_product_id) DO UPDATE SET
                    task_environment_id = excluded.task_environment_id,
                    task_instance_id = excluded.task_instance_id,
                    source_episode_id = excluded.source_episode_id,
                    product_domain = excluded.product_domain,
                    product_kind = excluded.product_kind,
                    stable_ref = excluded.stable_ref,
                    payload_ref = excluded.payload_ref,
                    payload_json = excluded.payload_json,
                    evidence_refs_json = excluded.evidence_refs_json,
                    anchor_refs_json = excluded.anchor_refs_json,
                    artifact_refs_json = excluded.artifact_refs_json,
                    acceptance_claims_json = excluded.acceptance_claims_json,
                    downstream_refs_json = excluded.downstream_refs_json,
                    confidence = excluded.confidence,
                    status = excluded.status,
                    generation = excluded.generation,
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json,
                    authority = excluded.authority
                """,
                (
                    stored.work_product_id,
                    stored.task_environment_id,
                    stored.task_instance_id,
                    stored.source_episode_id,
                    stored.product_domain,
                    stored.product_kind,
                    stored.stable_ref,
                    stored.payload_ref,
                    _json(stored.payload),
                    _json(list(stored.evidence_refs)),
                    _json(list(stored.anchor_refs)),
                    _json(list(stored.artifact_refs)),
                    _json(list(stored.acceptance_claims)),
                    _json(stored.downstream_refs),
                    stored.confidence,
                    stored.status,
                    int(stored.generation or 0),
                    stored.created_at,
                    stored.updated_at,
                    _json(stored.metadata),
                    stored.authority,
                ),
            )
            conn.execute(
                """
                UPDATE task_environments
                SET latest_work_product_id = ?, updated_at = ?
                WHERE task_environment_id = ?
                """,
                (stored.work_product_id, stored.updated_at, stored.task_environment_id),
            )
        return stored

    def get_work_product(self, work_product_id: str) -> WorkProduct | None:
        target = str(work_product_id or "").strip()
        if not target:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM task_work_products WHERE work_product_id = ?", (target,)).fetchone()
        return _work_product_from_row(row) if row is not None else None

    def list_work_products(
        self,
        *,
        task_environment_id: str = "",
        product_domain: str = "",
        product_kind: str = "",
        status: str = "",
        limit: int = 200,
    ) -> tuple[WorkProduct, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if task_environment_id:
            filters.append("task_environment_id = ?")
            params.append(task_environment_id)
        if product_domain:
            filters.append("product_domain = ?")
            params.append(product_domain)
        if product_kind:
            filters.append("product_kind = ?")
            params.append(product_kind)
        if status:
            filters.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM task_work_products"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY updated_at DESC, work_product_id ASC LIMIT ?"
        params.append(_limit(limit))
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_work_product_from_row(row) for row in rows)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS task_work_products (
                    work_product_id TEXT PRIMARY KEY,
                    task_environment_id TEXT NOT NULL,
                    task_instance_id TEXT NOT NULL,
                    source_episode_id TEXT NOT NULL,
                    product_domain TEXT NOT NULL,
                    product_kind TEXT NOT NULL,
                    stable_ref TEXT NOT NULL DEFAULT '',
                    payload_ref TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    anchor_refs_json TEXT NOT NULL DEFAULT '[]',
                    artifact_refs_json TEXT NOT NULL DEFAULT '[]',
                    acceptance_claims_json TEXT NOT NULL DEFAULT '[]',
                    downstream_refs_json TEXT NOT NULL DEFAULT '{}',
                    confidence TEXT NOT NULL,
                    status TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    authority TEXT NOT NULL DEFAULT 'task_system.work_product'
                );
                CREATE INDEX IF NOT EXISTS idx_work_products_env
                    ON task_work_products(task_environment_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_work_products_domain_kind_status
                    ON task_work_products(product_domain, product_kind, status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_work_products_stable_ref
                    ON task_work_products(product_domain, stable_ref, status);
                """
            )


def _work_product_from_row(row: sqlite3.Row) -> WorkProduct:
    return WorkProduct(
        work_product_id=str(row["work_product_id"]),
        task_environment_id=str(row["task_environment_id"]),
        task_instance_id=str(row["task_instance_id"]),
        source_episode_id=str(row["source_episode_id"]),
        product_domain=str(row["product_domain"]),
        product_kind=str(row["product_kind"]),
        confidence=str(row["confidence"] or "derived"),  # type: ignore[arg-type]
        status=str(row["status"] or "candidate"),  # type: ignore[arg-type]
        stable_ref=str(row["stable_ref"] or ""),
        payload_ref=str(row["payload_ref"] or ""),
        payload=_loads(row["payload_json"], {}),
        evidence_refs=tuple(_strings(_loads(row["evidence_refs_json"], []))),
        anchor_refs=tuple(_strings(_loads(row["anchor_refs_json"], []))),
        artifact_refs=tuple(_strings(_loads(row["artifact_refs_json"], []))),
        acceptance_claims=tuple(dict(item) for item in list(_loads(row["acceptance_claims_json"], [])) if isinstance(item, dict)),
        downstream_refs=_loads(row["downstream_refs_json"], {}),
        generation=int(row["generation"] or 0),
        created_at=float(row["created_at"] or 0.0),
        updated_at=float(row["updated_at"] or 0.0),
        metadata=_loads(row["metadata_json"], {}),
        authority=str(row["authority"] or "task_system.work_product"),
    )


def _now() -> float:
    return time.time()


def _limit(value: int) -> int:
    return max(1, min(int(value or 200), 10000))


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
