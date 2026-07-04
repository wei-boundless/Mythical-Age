from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

from core.project_layout import ProjectLayout

from .models import (
    SessionTaskBinding,
    TaskContextPackage,
    TaskControlSignal,
    TaskEnvironmentLease,
    TaskEvent,
    TaskInstance,
    TaskWorkEnvironment,
)


class TaskEnvironmentRepository:
    authority = "task_system.task_environment_repository"

    def __init__(self, base_dir: str | Path) -> None:
        layout = ProjectLayout.from_backend_dir(base_dir)
        self.root = layout.tasks_dir
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "task_environment.sqlite"
        self._ensure_schema()

    def upsert_task_instance(self, instance: TaskInstance) -> TaskInstance:
        now = _now()
        stored = replace(instance, created_at=instance.created_at or now, updated_at=now)
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO task_instances (
                    task_instance_id, task_kind, title, goal, owner_agent_id, owner_user_id,
                    project_id, workspace_view, status, priority, acceptance_contract_ref,
                    root_task_environment_id, created_at, updated_at, archived_at,
                    metadata_json, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_instance_id) DO UPDATE SET
                    task_kind = excluded.task_kind,
                    title = excluded.title,
                    goal = excluded.goal,
                    owner_agent_id = excluded.owner_agent_id,
                    owner_user_id = excluded.owner_user_id,
                    project_id = excluded.project_id,
                    workspace_view = excluded.workspace_view,
                    status = excluded.status,
                    priority = excluded.priority,
                    acceptance_contract_ref = excluded.acceptance_contract_ref,
                    root_task_environment_id = excluded.root_task_environment_id,
                    updated_at = excluded.updated_at,
                    archived_at = excluded.archived_at,
                    metadata_json = excluded.metadata_json,
                    authority = excluded.authority
                """,
                (
                    stored.task_instance_id,
                    stored.task_kind,
                    stored.title,
                    stored.goal,
                    stored.owner_agent_id,
                    stored.owner_user_id,
                    stored.project_id,
                    stored.workspace_view,
                    stored.status,
                    stored.priority,
                    stored.acceptance_contract_ref,
                    stored.root_task_environment_id,
                    stored.created_at,
                    stored.updated_at,
                    stored.archived_at,
                    _json(stored.metadata),
                    stored.authority,
                ),
            )
        return stored

    def get_task_instance(self, task_instance_id: str) -> TaskInstance | None:
        target = str(task_instance_id or "").strip()
        if not target:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM task_instances WHERE task_instance_id = ?", (target,)).fetchone()
        return _task_instance_from_row(row) if row is not None else None

    def upsert_task_environment(self, environment: TaskWorkEnvironment) -> TaskWorkEnvironment:
        now = _now()
        stored = replace(environment, created_at=environment.created_at or now, updated_at=now)
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO task_environments (
                    task_environment_id, task_instance_id, environment_kind, caller_kind, status,
                    revision, current_phase, current_step, progress_current, progress_total,
                    progress_label, active_episode_id, active_lease_id, latest_event_id,
                    latest_checkpoint_id, latest_context_package_id, latest_work_product_id,
                    continuation_hint, blocked_reason, recovery_action, created_at, updated_at,
                    metadata_json, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_environment_id) DO UPDATE SET
                    task_instance_id = excluded.task_instance_id,
                    environment_kind = excluded.environment_kind,
                    caller_kind = excluded.caller_kind,
                    status = excluded.status,
                    revision = excluded.revision,
                    current_phase = excluded.current_phase,
                    current_step = excluded.current_step,
                    progress_current = excluded.progress_current,
                    progress_total = excluded.progress_total,
                    progress_label = excluded.progress_label,
                    active_episode_id = excluded.active_episode_id,
                    active_lease_id = excluded.active_lease_id,
                    latest_event_id = excluded.latest_event_id,
                    latest_checkpoint_id = excluded.latest_checkpoint_id,
                    latest_context_package_id = excluded.latest_context_package_id,
                    latest_work_product_id = excluded.latest_work_product_id,
                    continuation_hint = excluded.continuation_hint,
                    blocked_reason = excluded.blocked_reason,
                    recovery_action = excluded.recovery_action,
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json,
                    authority = excluded.authority
                """,
                _task_environment_values(stored),
            )
        return stored

    def get_task_environment(self, task_environment_id: str) -> TaskWorkEnvironment | None:
        target = str(task_environment_id or "").strip()
        if not target:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM task_environments WHERE task_environment_id = ?", (target,)).fetchone()
        return _task_environment_from_row(row) if row is not None else None

    def list_task_environments(
        self,
        *,
        status: str = "",
        task_kind: str = "",
        project_id: str = "",
        caller_kind: str = "",
        limit: int = 200,
    ) -> tuple[TaskWorkEnvironment, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if status:
            filters.append("env.status = ?")
            params.append(status)
        if caller_kind:
            filters.append("env.caller_kind = ?")
            params.append(caller_kind)
        if task_kind:
            filters.append("inst.task_kind = ?")
            params.append(task_kind)
        if project_id:
            filters.append("inst.project_id = ?")
            params.append(project_id)
        sql = """
            SELECT env.*
            FROM task_environments env
            JOIN task_instances inst ON inst.task_instance_id = env.task_instance_id
        """
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY env.updated_at DESC, env.task_environment_id ASC LIMIT ?"
        params.append(_limit(limit))
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_task_environment_from_row(row) for row in rows)

    def list_resumable(self, *, limit: int = 200) -> tuple[TaskWorkEnvironment, ...]:
        sql = """
            SELECT *
            FROM task_environments
            WHERE status IN ('ready', 'paused', 'blocked')
              AND task_environment_id NOT IN (
                SELECT task_environment_id
                FROM task_environment_leases
                WHERE status = 'active' AND expires_at > ?
              )
            ORDER BY updated_at DESC, task_environment_id ASC
            LIMIT ?
        """
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, (_now(), _limit(limit))).fetchall()
        return tuple(_task_environment_from_row(row) for row in rows)

    def append_event(
        self,
        event: TaskEvent,
        *,
        expected_revision: int | None = None,
        snapshot_patch: dict[str, Any] | None = None,
    ) -> TaskEvent:
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if event.idempotency_key:
                existing = conn.execute(
                    """
                    SELECT * FROM task_events
                    WHERE task_environment_id = ? AND idempotency_key = ?
                    """,
                    (event.task_environment_id, event.idempotency_key),
                ).fetchone()
                if existing is not None:
                    conn.commit()
                    return _task_event_from_row(existing)
            env = conn.execute(
                "SELECT * FROM task_environments WHERE task_environment_id = ?",
                (event.task_environment_id,),
            ).fetchone()
            if env is None:
                conn.rollback()
                raise KeyError(f"task environment not found: {event.task_environment_id}")
            current_revision = int(env["revision"] or 0)
            if expected_revision is not None and current_revision != int(expected_revision):
                conn.rollback()
                raise ValueError("TaskWorkEnvironment revision conflict")
            next_seq = int(
                conn.execute(
                    "SELECT COALESCE(MAX(event_seq), -1) + 1 FROM task_events WHERE task_environment_id = ?",
                    (event.task_environment_id,),
                ).fetchone()[0]
            )
            stored = replace(
                event,
                event_seq=next_seq,
                idempotency_key=event.idempotency_key or event.event_id,
                created_at=event.created_at or _now(),
            )
            conn.execute(
                """
                INSERT INTO task_events (
                    event_id, task_environment_id, task_instance_id, event_seq, event_type,
                    actor_kind, actor_id, source_episode_id, source_graph_run_id,
                    source_work_order_id, idempotency_key, payload_json, refs_json,
                    created_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stored.event_id,
                    stored.task_environment_id,
                    stored.task_instance_id,
                    stored.event_seq,
                    stored.event_type,
                    stored.actor_kind,
                    stored.actor_id,
                    stored.source_episode_id,
                    stored.source_graph_run_id,
                    stored.source_work_order_id,
                    stored.idempotency_key,
                    _json(stored.payload),
                    _json(stored.refs),
                    stored.created_at,
                    stored.authority,
                ),
            )
            patch = dict(snapshot_patch or {})
            patch.update(
                {
                    "revision": current_revision + 1,
                    "latest_event_id": stored.event_id,
                    "updated_at": stored.created_at,
                }
            )
            _update_task_environment_snapshot(conn, stored.task_environment_id, patch)
            conn.commit()
        return stored

    def list_events(self, task_environment_id: str, *, limit: int = 200) -> tuple[TaskEvent, ...]:
        target = str(task_environment_id or "").strip()
        if not target:
            return ()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM task_events
                WHERE task_environment_id = ?
                ORDER BY event_seq ASC
                LIMIT ?
                """,
                (target, _limit(limit)),
            ).fetchall()
        return tuple(_task_event_from_row(row) for row in rows)

    def upsert_session_binding(self, binding: SessionTaskBinding) -> SessionTaskBinding:
        now = _now()
        stored = replace(binding, created_at=binding.created_at or now, updated_at=now)
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO session_task_bindings (
                    binding_id, session_id, task_environment_id, task_instance_id, binding_kind,
                    control_role, visibility, created_from_turn_id, last_focused_at,
                    last_user_steer_ref, status, created_at, updated_at, metadata_json, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(binding_id) DO UPDATE SET
                    session_id = excluded.session_id,
                    task_environment_id = excluded.task_environment_id,
                    task_instance_id = excluded.task_instance_id,
                    binding_kind = excluded.binding_kind,
                    control_role = excluded.control_role,
                    visibility = excluded.visibility,
                    created_from_turn_id = excluded.created_from_turn_id,
                    last_focused_at = excluded.last_focused_at,
                    last_user_steer_ref = excluded.last_user_steer_ref,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json,
                    authority = excluded.authority
                """,
                (
                    stored.binding_id,
                    stored.session_id,
                    stored.task_environment_id,
                    stored.task_instance_id,
                    stored.binding_kind,
                    stored.control_role,
                    stored.visibility,
                    stored.created_from_turn_id,
                    stored.last_focused_at,
                    stored.last_user_steer_ref,
                    stored.status,
                    stored.created_at,
                    stored.updated_at,
                    _json(stored.metadata),
                    stored.authority,
                ),
            )
        return stored

    def upsert_context_package(self, package: TaskContextPackage) -> TaskContextPackage:
        stored = replace(package, created_at=package.created_at or _now())
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO task_context_packages (
                    package_id, task_environment_id, episode_id, package_hash, role_contract,
                    goal, scope_json, acceptance_json, stable_context_ref, current_context_ref,
                    memory_refs_json, artifact_refs_json, resource_handles_json,
                    graph_context_json, project_network_handles_json, continuation_hint,
                    output_contract_json, packet_policy_json, metadata_json, created_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(package_id) DO UPDATE SET
                    task_environment_id = excluded.task_environment_id,
                    episode_id = excluded.episode_id,
                    package_hash = excluded.package_hash,
                    role_contract = excluded.role_contract,
                    goal = excluded.goal,
                    scope_json = excluded.scope_json,
                    acceptance_json = excluded.acceptance_json,
                    stable_context_ref = excluded.stable_context_ref,
                    current_context_ref = excluded.current_context_ref,
                    memory_refs_json = excluded.memory_refs_json,
                    artifact_refs_json = excluded.artifact_refs_json,
                    resource_handles_json = excluded.resource_handles_json,
                    graph_context_json = excluded.graph_context_json,
                    project_network_handles_json = excluded.project_network_handles_json,
                    continuation_hint = excluded.continuation_hint,
                    output_contract_json = excluded.output_contract_json,
                    packet_policy_json = excluded.packet_policy_json,
                    metadata_json = excluded.metadata_json,
                    authority = excluded.authority
                """,
                (
                    stored.package_id,
                    stored.task_environment_id,
                    stored.episode_id,
                    stored.package_hash,
                    stored.role_contract,
                    stored.goal,
                    _json(stored.scope),
                    _json(stored.acceptance),
                    stored.stable_context_ref,
                    stored.current_context_ref,
                    _json(list(stored.memory_refs)),
                    _json(list(stored.artifact_refs)),
                    _json(stored.resource_handles),
                    _json(stored.graph_context),
                    _json(stored.project_network_handles),
                    stored.continuation_hint,
                    _json(stored.output_contract),
                    _json(stored.packet_policy),
                    _json(stored.metadata),
                    stored.created_at,
                    stored.authority,
                ),
            )
            conn.execute(
                """
                UPDATE task_environments
                SET latest_context_package_id = ?, updated_at = ?
                WHERE task_environment_id = ?
                """,
                (stored.package_id, stored.created_at, stored.task_environment_id),
            )
        return stored

    def upsert_lease(self, lease: TaskEnvironmentLease) -> TaskEnvironmentLease:
        stored = replace(lease, acquired_at=lease.acquired_at or _now(), heartbeat_at=lease.heartbeat_at or lease.acquired_at or _now())
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO task_environment_leases (
                    lease_id, task_environment_id, episode_id, lease_kind, holder_kind, holder_id,
                    status, acquired_at, expires_at, heartbeat_at, released_at, release_reason,
                    idempotency_key, metadata_json, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lease_id) DO UPDATE SET
                    status = excluded.status,
                    expires_at = excluded.expires_at,
                    heartbeat_at = excluded.heartbeat_at,
                    released_at = excluded.released_at,
                    release_reason = excluded.release_reason,
                    metadata_json = excluded.metadata_json,
                    authority = excluded.authority
                """,
                (
                    stored.lease_id,
                    stored.task_environment_id,
                    stored.episode_id,
                    stored.lease_kind,
                    stored.holder_kind,
                    stored.holder_id,
                    stored.status,
                    stored.acquired_at,
                    stored.expires_at,
                    stored.heartbeat_at,
                    stored.released_at,
                    stored.release_reason,
                    stored.idempotency_key,
                    _json(stored.metadata),
                    stored.authority,
                ),
            )
        return stored

    def upsert_control_signal(self, signal: TaskControlSignal) -> TaskControlSignal:
        stored = replace(signal, created_at=signal.created_at or _now())
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO task_control_signals (
                    signal_id, task_environment_id, signal_kind, requested_by, reason,
                    payload_json, status, created_at, handled_at, handler_episode_id,
                    idempotency_key, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(signal_id) DO UPDATE SET
                    signal_kind = excluded.signal_kind,
                    requested_by = excluded.requested_by,
                    reason = excluded.reason,
                    payload_json = excluded.payload_json,
                    status = excluded.status,
                    handled_at = excluded.handled_at,
                    handler_episode_id = excluded.handler_episode_id,
                    authority = excluded.authority
                """,
                (
                    stored.signal_id,
                    stored.task_environment_id,
                    stored.signal_kind,
                    stored.requested_by,
                    stored.reason,
                    _json(stored.payload),
                    stored.status,
                    stored.created_at,
                    stored.handled_at,
                    stored.handler_episode_id,
                    stored.idempotency_key,
                    stored.authority,
                ),
            )
        return stored

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS task_instances (
                    task_instance_id TEXT PRIMARY KEY,
                    task_kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    owner_agent_id TEXT NOT NULL DEFAULT '',
                    owner_user_id TEXT NOT NULL DEFAULT '',
                    project_id TEXT NOT NULL DEFAULT '',
                    workspace_view TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    priority TEXT NOT NULL DEFAULT 'normal',
                    acceptance_contract_ref TEXT NOT NULL DEFAULT '',
                    root_task_environment_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    archived_at REAL NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    authority TEXT NOT NULL DEFAULT 'task_system.task_instance'
                );
                CREATE INDEX IF NOT EXISTS idx_task_instances_status_updated
                    ON task_instances(status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_task_instances_project_status
                    ON task_instances(project_id, status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS task_environments (
                    task_environment_id TEXT PRIMARY KEY,
                    task_instance_id TEXT NOT NULL,
                    environment_kind TEXT NOT NULL,
                    caller_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0,
                    current_phase TEXT NOT NULL DEFAULT '',
                    current_step TEXT NOT NULL DEFAULT '',
                    progress_current INTEGER NOT NULL DEFAULT 0,
                    progress_total INTEGER NOT NULL DEFAULT 0,
                    progress_label TEXT NOT NULL DEFAULT '',
                    active_episode_id TEXT NOT NULL DEFAULT '',
                    active_lease_id TEXT NOT NULL DEFAULT '',
                    latest_event_id TEXT NOT NULL DEFAULT '',
                    latest_checkpoint_id TEXT NOT NULL DEFAULT '',
                    latest_context_package_id TEXT NOT NULL DEFAULT '',
                    latest_work_product_id TEXT NOT NULL DEFAULT '',
                    continuation_hint TEXT NOT NULL DEFAULT '',
                    blocked_reason TEXT NOT NULL DEFAULT '',
                    recovery_action TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    authority TEXT NOT NULL DEFAULT 'task_system.task_environment',
                    FOREIGN KEY(task_instance_id) REFERENCES task_instances(task_instance_id)
                );
                CREATE INDEX IF NOT EXISTS idx_task_env_instance
                    ON task_environments(task_instance_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_task_env_status_updated
                    ON task_environments(status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_task_env_recovery
                    ON task_environments(recovery_action, status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS task_events (
                    event_id TEXT PRIMARY KEY,
                    task_environment_id TEXT NOT NULL,
                    task_instance_id TEXT NOT NULL,
                    event_seq INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_kind TEXT NOT NULL,
                    actor_id TEXT NOT NULL DEFAULT '',
                    source_episode_id TEXT NOT NULL DEFAULT '',
                    source_graph_run_id TEXT NOT NULL DEFAULT '',
                    source_work_order_id TEXT NOT NULL DEFAULT '',
                    idempotency_key TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    refs_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    authority TEXT NOT NULL DEFAULT 'task_system.task_event',
                    UNIQUE(task_environment_id, event_seq),
                    UNIQUE(task_environment_id, idempotency_key),
                    FOREIGN KEY(task_environment_id) REFERENCES task_environments(task_environment_id)
                );
                CREATE INDEX IF NOT EXISTS idx_task_events_env_seq
                    ON task_events(task_environment_id, event_seq);
                CREATE INDEX IF NOT EXISTS idx_task_events_graph_work_order
                    ON task_events(source_graph_run_id, source_work_order_id);

                CREATE TABLE IF NOT EXISTS session_task_bindings (
                    binding_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    task_environment_id TEXT NOT NULL,
                    task_instance_id TEXT NOT NULL,
                    binding_kind TEXT NOT NULL DEFAULT 'origin',
                    control_role TEXT NOT NULL DEFAULT 'controller',
                    visibility TEXT NOT NULL DEFAULT 'foreground',
                    created_from_turn_id TEXT NOT NULL DEFAULT '',
                    last_focused_at REAL NOT NULL DEFAULT 0,
                    last_user_steer_ref TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    authority TEXT NOT NULL DEFAULT 'task_system.session_task_binding'
                );
                CREATE INDEX IF NOT EXISTS idx_session_task_bindings_session
                    ON session_task_bindings(session_id, visibility, status, last_focused_at DESC);

                CREATE TABLE IF NOT EXISTS task_environment_leases (
                    lease_id TEXT PRIMARY KEY,
                    task_environment_id TEXT NOT NULL,
                    episode_id TEXT NOT NULL,
                    lease_kind TEXT NOT NULL,
                    holder_kind TEXT NOT NULL,
                    holder_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    acquired_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    heartbeat_at REAL NOT NULL,
                    released_at REAL NOT NULL DEFAULT 0,
                    release_reason TEXT NOT NULL DEFAULT '',
                    idempotency_key TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    authority TEXT NOT NULL DEFAULT 'task_system.task_environment_lease',
                    UNIQUE(task_environment_id, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_task_leases_active
                    ON task_environment_leases(task_environment_id, status, expires_at);
                CREATE INDEX IF NOT EXISTS idx_task_leases_holder
                    ON task_environment_leases(holder_kind, holder_id, status);

                CREATE TABLE IF NOT EXISTS task_context_packages (
                    package_id TEXT PRIMARY KEY,
                    task_environment_id TEXT NOT NULL,
                    episode_id TEXT NOT NULL,
                    package_hash TEXT NOT NULL,
                    role_contract TEXT NOT NULL DEFAULT '',
                    goal TEXT NOT NULL DEFAULT '',
                    scope_json TEXT NOT NULL DEFAULT '{}',
                    acceptance_json TEXT NOT NULL DEFAULT '{}',
                    stable_context_ref TEXT NOT NULL DEFAULT '',
                    current_context_ref TEXT NOT NULL DEFAULT '',
                    memory_refs_json TEXT NOT NULL DEFAULT '[]',
                    artifact_refs_json TEXT NOT NULL DEFAULT '[]',
                    resource_handles_json TEXT NOT NULL DEFAULT '{}',
                    graph_context_json TEXT NOT NULL DEFAULT '{}',
                    project_network_handles_json TEXT NOT NULL DEFAULT '{}',
                    continuation_hint TEXT NOT NULL DEFAULT '',
                    output_contract_json TEXT NOT NULL DEFAULT '{}',
                    packet_policy_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    authority TEXT NOT NULL DEFAULT 'task_system.task_context_package'
                );
                CREATE INDEX IF NOT EXISTS idx_context_packages_env
                    ON task_context_packages(task_environment_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS task_control_signals (
                    signal_id TEXT PRIMARY KEY,
                    task_environment_id TEXT NOT NULL,
                    signal_kind TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    handled_at REAL NOT NULL DEFAULT 0,
                    handler_episode_id TEXT NOT NULL DEFAULT '',
                    idempotency_key TEXT NOT NULL,
                    authority TEXT NOT NULL DEFAULT 'task_system.task_control_signal',
                    UNIQUE(task_environment_id, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_control_signals_pending
                    ON task_control_signals(task_environment_id, status, created_at);
                """
            )


def _update_task_environment_snapshot(conn: sqlite3.Connection, task_environment_id: str, patch: dict[str, Any]) -> None:
    allowed = {
        "status",
        "revision",
        "current_phase",
        "current_step",
        "progress_current",
        "progress_total",
        "progress_label",
        "active_episode_id",
        "active_lease_id",
        "latest_event_id",
        "latest_checkpoint_id",
        "latest_context_package_id",
        "latest_work_product_id",
        "continuation_hint",
        "blocked_reason",
        "recovery_action",
        "updated_at",
    }
    updates = {key: value for key, value in dict(patch or {}).items() if key in allowed}
    if not updates:
        return
    assignments = ", ".join(f"{key} = ?" for key in updates)
    conn.execute(
        f"UPDATE task_environments SET {assignments} WHERE task_environment_id = ?",
        (*updates.values(), task_environment_id),
    )


def _task_environment_values(item: TaskWorkEnvironment) -> tuple[Any, ...]:
    return (
        item.task_environment_id,
        item.task_instance_id,
        item.environment_kind,
        item.caller_kind,
        item.status,
        item.revision,
        item.current_phase,
        item.current_step,
        item.progress_current,
        item.progress_total,
        item.progress_label,
        item.active_episode_id,
        item.active_lease_id,
        item.latest_event_id,
        item.latest_checkpoint_id,
        item.latest_context_package_id,
        item.latest_work_product_id,
        item.continuation_hint,
        item.blocked_reason,
        item.recovery_action,
        item.created_at,
        item.updated_at,
        _json(item.metadata),
        item.authority,
    )


def _task_instance_from_row(row: sqlite3.Row) -> TaskInstance:
    return TaskInstance(
        task_instance_id=str(row["task_instance_id"]),
        task_kind=str(row["task_kind"]),
        title=str(row["title"]),
        goal=str(row["goal"]),
        status=str(row["status"] or "draft"),  # type: ignore[arg-type]
        owner_agent_id=str(row["owner_agent_id"] or ""),
        owner_user_id=str(row["owner_user_id"] or ""),
        project_id=str(row["project_id"] or ""),
        workspace_view=str(row["workspace_view"] or ""),
        priority=str(row["priority"] or "normal"),
        acceptance_contract_ref=str(row["acceptance_contract_ref"] or ""),
        root_task_environment_id=str(row["root_task_environment_id"] or ""),
        created_at=float(row["created_at"] or 0.0),
        updated_at=float(row["updated_at"] or 0.0),
        archived_at=float(row["archived_at"] or 0.0),
        metadata=_loads(row["metadata_json"], {}),
        authority=str(row["authority"] or "task_system.task_instance"),
    )


def _task_environment_from_row(row: sqlite3.Row) -> TaskWorkEnvironment:
    return TaskWorkEnvironment(
        task_environment_id=str(row["task_environment_id"]),
        task_instance_id=str(row["task_instance_id"]),
        environment_kind=str(row["environment_kind"]),
        caller_kind=str(row["caller_kind"]),
        status=str(row["status"] or "created"),  # type: ignore[arg-type]
        revision=int(row["revision"] or 0),
        current_phase=str(row["current_phase"] or ""),
        current_step=str(row["current_step"] or ""),
        progress_current=int(row["progress_current"] or 0),
        progress_total=int(row["progress_total"] or 0),
        progress_label=str(row["progress_label"] or ""),
        active_episode_id=str(row["active_episode_id"] or ""),
        active_lease_id=str(row["active_lease_id"] or ""),
        latest_event_id=str(row["latest_event_id"] or ""),
        latest_checkpoint_id=str(row["latest_checkpoint_id"] or ""),
        latest_context_package_id=str(row["latest_context_package_id"] or ""),
        latest_work_product_id=str(row["latest_work_product_id"] or ""),
        continuation_hint=str(row["continuation_hint"] or ""),
        blocked_reason=str(row["blocked_reason"] or ""),
        recovery_action=str(row["recovery_action"] or ""),
        created_at=float(row["created_at"] or 0.0),
        updated_at=float(row["updated_at"] or 0.0),
        metadata=_loads(row["metadata_json"], {}),
        authority=str(row["authority"] or "task_system.task_environment"),
    )


def _task_event_from_row(row: sqlite3.Row) -> TaskEvent:
    return TaskEvent(
        event_id=str(row["event_id"]),
        task_environment_id=str(row["task_environment_id"]),
        task_instance_id=str(row["task_instance_id"]),
        event_seq=int(row["event_seq"] or 0),
        event_type=str(row["event_type"]),
        actor_kind=str(row["actor_kind"]),
        actor_id=str(row["actor_id"] or ""),
        source_episode_id=str(row["source_episode_id"] or ""),
        source_graph_run_id=str(row["source_graph_run_id"] or ""),
        source_work_order_id=str(row["source_work_order_id"] or ""),
        idempotency_key=str(row["idempotency_key"] or ""),
        payload=_loads(row["payload_json"], {}),
        refs=_loads(row["refs_json"], {}),
        created_at=float(row["created_at"] or 0.0),
        authority=str(row["authority"] or "task_system.task_event"),
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
