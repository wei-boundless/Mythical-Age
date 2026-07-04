from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

from core.project_layout import ProjectLayout

from .models import GraphNodeTaskBinding


class GraphNodeTaskBindingRepository:
    authority = "task_system.graph_node_task_binding_repository"

    def __init__(self, base_dir: str | Path) -> None:
        layout = ProjectLayout.from_backend_dir(base_dir)
        self.root = layout.tasks_dir
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "task_environment.sqlite"
        self._ensure_schema()

    def upsert_binding(self, binding: GraphNodeTaskBinding) -> GraphNodeTaskBinding:
        now = _now()
        stored = replace(binding, created_at=binding.created_at or now, updated_at=now)
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO graph_node_task_bindings (
                    binding_id, graph_run_id, graph_id, config_id, structure_hash, node_id,
                    work_order_id, parent_task_environment_id, node_task_environment_id,
                    task_instance_id, task_ref, agent_profile_id, input_package_ref,
                    expected_result_contract_ref, lease_policy_json, result_projection_policy_json,
                    idempotency_key, status, created_at, updated_at, metadata_json, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(binding_id) DO UPDATE SET
                    graph_run_id = excluded.graph_run_id,
                    graph_id = excluded.graph_id,
                    config_id = excluded.config_id,
                    structure_hash = excluded.structure_hash,
                    node_id = excluded.node_id,
                    work_order_id = excluded.work_order_id,
                    parent_task_environment_id = excluded.parent_task_environment_id,
                    node_task_environment_id = excluded.node_task_environment_id,
                    task_instance_id = excluded.task_instance_id,
                    task_ref = excluded.task_ref,
                    agent_profile_id = excluded.agent_profile_id,
                    input_package_ref = excluded.input_package_ref,
                    expected_result_contract_ref = excluded.expected_result_contract_ref,
                    lease_policy_json = excluded.lease_policy_json,
                    result_projection_policy_json = excluded.result_projection_policy_json,
                    idempotency_key = excluded.idempotency_key,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json,
                    authority = excluded.authority
                """,
                (
                    stored.binding_id,
                    stored.graph_run_id,
                    stored.graph_id,
                    stored.config_id,
                    stored.structure_hash,
                    stored.node_id,
                    stored.work_order_id,
                    stored.parent_task_environment_id,
                    stored.node_task_environment_id,
                    stored.task_instance_id,
                    stored.task_ref,
                    stored.agent_profile_id,
                    stored.input_package_ref,
                    stored.expected_result_contract_ref,
                    _json(stored.lease_policy),
                    _json(stored.result_projection_policy),
                    stored.idempotency_key,
                    stored.status,
                    stored.created_at,
                    stored.updated_at,
                    _json(stored.metadata),
                    stored.authority,
                ),
            )
        return stored

    def get_by_work_order(self, graph_run_id: str, work_order_id: str) -> GraphNodeTaskBinding | None:
        if not str(graph_run_id or "").strip() or not str(work_order_id or "").strip():
            return None
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT * FROM graph_node_task_bindings
                WHERE graph_run_id = ? AND work_order_id = ?
                """,
                (graph_run_id, work_order_id),
            ).fetchone()
        return _binding_from_row(row) if row is not None else None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS graph_node_task_bindings (
                    binding_id TEXT PRIMARY KEY,
                    graph_run_id TEXT NOT NULL,
                    graph_id TEXT NOT NULL,
                    config_id TEXT NOT NULL,
                    structure_hash TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    work_order_id TEXT NOT NULL,
                    parent_task_environment_id TEXT NOT NULL DEFAULT '',
                    node_task_environment_id TEXT NOT NULL,
                    task_instance_id TEXT NOT NULL,
                    task_ref TEXT NOT NULL,
                    agent_profile_id TEXT NOT NULL DEFAULT '',
                    input_package_ref TEXT NOT NULL DEFAULT '',
                    expected_result_contract_ref TEXT NOT NULL DEFAULT '',
                    lease_policy_json TEXT NOT NULL DEFAULT '{}',
                    result_projection_policy_json TEXT NOT NULL DEFAULT '{}',
                    idempotency_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    authority TEXT NOT NULL DEFAULT 'task_system.graph_node_task_binding',
                    UNIQUE(graph_run_id, work_order_id),
                    UNIQUE(idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_graph_bindings_node_env
                    ON graph_node_task_bindings(graph_run_id, node_id, status);
                CREATE INDEX IF NOT EXISTS idx_graph_bindings_task_env
                    ON graph_node_task_bindings(node_task_environment_id);
                """
            )


def _binding_from_row(row: sqlite3.Row) -> GraphNodeTaskBinding:
    return GraphNodeTaskBinding(
        binding_id=str(row["binding_id"]),
        graph_run_id=str(row["graph_run_id"]),
        graph_id=str(row["graph_id"] or ""),
        config_id=str(row["config_id"]),
        structure_hash=str(row["structure_hash"] or ""),
        node_id=str(row["node_id"]),
        work_order_id=str(row["work_order_id"]),
        parent_task_environment_id=str(row["parent_task_environment_id"] or ""),
        node_task_environment_id=str(row["node_task_environment_id"]),
        task_instance_id=str(row["task_instance_id"]),
        task_ref=str(row["task_ref"]),
        agent_profile_id=str(row["agent_profile_id"] or ""),
        input_package_ref=str(row["input_package_ref"] or ""),
        expected_result_contract_ref=str(row["expected_result_contract_ref"] or ""),
        lease_policy=_loads(row["lease_policy_json"], {}),
        result_projection_policy=_loads(row["result_projection_policy_json"], {}),
        idempotency_key=str(row["idempotency_key"] or ""),
        status=str(row["status"] or "created"),  # type: ignore[arg-type]
        created_at=float(row["created_at"] or 0.0),
        updated_at=float(row["updated_at"] or 0.0),
        metadata=_loads(row["metadata_json"], {}),
        authority=str(row["authority"] or "task_system.graph_node_task_binding"),
    )


def _now() -> float:
    return time.time()


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _loads(value: Any, default: Any) -> Any:
    try:
        loaded = json.loads(str(value or ""))
    except (TypeError, json.JSONDecodeError):
        return default
    return loaded if isinstance(loaded, type(default)) else default
