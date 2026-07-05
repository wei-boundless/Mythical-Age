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
    TaskCheckpoint,
    TaskCommand,
    TaskContextPackage,
    TaskControlSignal,
    TaskDispatchRecord,
    TaskEnvironmentLease,
    TaskEvent,
    TaskInstance,
    TaskPlan,
    TaskStateProposal,
    TaskTodoItem,
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

    def upsert_checkpoint(self, checkpoint: TaskCheckpoint) -> TaskCheckpoint:
        stored = replace(checkpoint, created_at=checkpoint.created_at or _now())
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO task_checkpoints (
                    checkpoint_id, task_environment_id, task_instance_id, checkpoint_kind,
                    episode_id, event_id, event_seq, context_package_id,
                    latest_work_product_ids_json, latest_artifact_refs_json,
                    continuation_hint, summary, hashes_json, payload_ref,
                    metadata_json, created_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(checkpoint_id) DO UPDATE SET
                    task_environment_id = excluded.task_environment_id,
                    task_instance_id = excluded.task_instance_id,
                    checkpoint_kind = excluded.checkpoint_kind,
                    episode_id = excluded.episode_id,
                    event_id = excluded.event_id,
                    event_seq = excluded.event_seq,
                    context_package_id = excluded.context_package_id,
                    latest_work_product_ids_json = excluded.latest_work_product_ids_json,
                    latest_artifact_refs_json = excluded.latest_artifact_refs_json,
                    continuation_hint = excluded.continuation_hint,
                    summary = excluded.summary,
                    hashes_json = excluded.hashes_json,
                    payload_ref = excluded.payload_ref,
                    metadata_json = excluded.metadata_json,
                    authority = excluded.authority
                """,
                (
                    stored.checkpoint_id,
                    stored.task_environment_id,
                    stored.task_instance_id,
                    stored.checkpoint_kind,
                    stored.episode_id,
                    stored.event_id,
                    int(stored.event_seq),
                    stored.context_package_id,
                    _json(list(stored.latest_work_product_ids)),
                    _json(list(stored.latest_artifact_refs)),
                    stored.continuation_hint,
                    stored.summary,
                    _json(stored.hashes),
                    stored.payload_ref,
                    _json(stored.metadata),
                    stored.created_at,
                    stored.authority,
                ),
            )
            conn.execute(
                """
                UPDATE task_environments
                SET latest_checkpoint_id = ?, updated_at = ?
                WHERE task_environment_id = ?
                """,
                (stored.checkpoint_id, stored.created_at, stored.task_environment_id),
            )
        return stored

    def get_checkpoint(self, checkpoint_id: str) -> TaskCheckpoint | None:
        target = str(checkpoint_id or "").strip()
        if not target:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM task_checkpoints WHERE checkpoint_id = ?", (target,)).fetchone()
        return _checkpoint_from_row(row) if row is not None else None

    def list_checkpoints(
        self,
        task_environment_id: str,
        *,
        checkpoint_kind: str = "",
        limit: int = 50,
    ) -> tuple[TaskCheckpoint, ...]:
        target = str(task_environment_id or "").strip()
        if not target:
            return ()
        filters = ["task_environment_id = ?"]
        params: list[Any] = [target]
        if checkpoint_kind:
            filters.append("checkpoint_kind = ?")
            params.append(str(checkpoint_kind))
        sql = f"""
            SELECT *
            FROM task_checkpoints
            WHERE {" AND ".join(filters)}
            ORDER BY created_at DESC, checkpoint_id ASC
            LIMIT ?
        """
        params.append(_limit(limit))
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_checkpoint_from_row(row) for row in rows)

    def upsert_task_plan(self, plan: TaskPlan) -> TaskPlan:
        now = _now()
        stored = replace(plan, created_at=plan.created_at or now, updated_at=now)
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO task_plans (
                    plan_id, task_environment_id, version, status, strategy_summary,
                    phases_json, acceptance_mapping_json, risk_notes_json,
                    created_by_episode_id, supersedes_plan_id, created_at, updated_at,
                    metadata_json, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(plan_id) DO UPDATE SET
                    task_environment_id = excluded.task_environment_id,
                    version = excluded.version,
                    status = excluded.status,
                    strategy_summary = excluded.strategy_summary,
                    phases_json = excluded.phases_json,
                    acceptance_mapping_json = excluded.acceptance_mapping_json,
                    risk_notes_json = excluded.risk_notes_json,
                    created_by_episode_id = excluded.created_by_episode_id,
                    supersedes_plan_id = excluded.supersedes_plan_id,
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json,
                    authority = excluded.authority
                """,
                (
                    stored.plan_id,
                    stored.task_environment_id,
                    int(stored.version),
                    stored.status,
                    stored.strategy_summary,
                    _json(list(stored.phases)),
                    _json(stored.acceptance_mapping),
                    _json(list(stored.risk_notes)),
                    stored.created_by_episode_id,
                    stored.supersedes_plan_id,
                    stored.created_at,
                    stored.updated_at,
                    _json(stored.metadata),
                    stored.authority,
                ),
            )
        return stored

    def get_task_plan(self, plan_id: str) -> TaskPlan | None:
        target = str(plan_id or "").strip()
        if not target:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM task_plans WHERE plan_id = ?", (target,)).fetchone()
        return _task_plan_from_row(row) if row is not None else None

    def list_task_plans(
        self,
        task_environment_id: str,
        *,
        status: str = "",
        limit: int = 50,
    ) -> tuple[TaskPlan, ...]:
        target = str(task_environment_id or "").strip()
        if not target:
            return ()
        filters = ["task_environment_id = ?"]
        params: list[Any] = [target]
        if status:
            filters.append("status = ?")
            params.append(str(status))
        sql = f"""
            SELECT *
            FROM task_plans
            WHERE {" AND ".join(filters)}
            ORDER BY version DESC, updated_at DESC, plan_id ASC
            LIMIT ?
        """
        params.append(_limit(limit))
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_task_plan_from_row(row) for row in rows)

    def upsert_todo_item(self, item: TaskTodoItem) -> TaskTodoItem:
        now = _now()
        stored = replace(item, created_at=item.created_at or now, updated_at=now)
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO task_todo_items (
                    todo_id, task_environment_id, title, status, plan_id,
                    evidence_refs_json, blocker, created_by_episode_id,
                    completed_by_episode_id, created_at, updated_at, metadata_json,
                    authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(todo_id) DO UPDATE SET
                    task_environment_id = excluded.task_environment_id,
                    title = excluded.title,
                    status = excluded.status,
                    plan_id = excluded.plan_id,
                    evidence_refs_json = excluded.evidence_refs_json,
                    blocker = excluded.blocker,
                    created_by_episode_id = excluded.created_by_episode_id,
                    completed_by_episode_id = excluded.completed_by_episode_id,
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json,
                    authority = excluded.authority
                """,
                (
                    stored.todo_id,
                    stored.task_environment_id,
                    stored.title,
                    stored.status,
                    stored.plan_id,
                    _json(list(stored.evidence_refs)),
                    stored.blocker,
                    stored.created_by_episode_id,
                    stored.completed_by_episode_id,
                    stored.created_at,
                    stored.updated_at,
                    _json(stored.metadata),
                    stored.authority,
                ),
            )
        return stored

    def get_todo_item(self, todo_id: str) -> TaskTodoItem | None:
        target = str(todo_id or "").strip()
        if not target:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM task_todo_items WHERE todo_id = ?", (target,)).fetchone()
        return _todo_item_from_row(row) if row is not None else None

    def list_todo_items(
        self,
        task_environment_id: str,
        *,
        status: str = "",
        limit: int = 200,
    ) -> tuple[TaskTodoItem, ...]:
        target = str(task_environment_id or "").strip()
        if not target:
            return ()
        filters = ["task_environment_id = ?"]
        params: list[Any] = [target]
        if status:
            filters.append("status = ?")
            params.append(str(status))
        sql = f"""
            SELECT *
            FROM task_todo_items
            WHERE {" AND ".join(filters)}
            ORDER BY updated_at DESC, todo_id ASC
            LIMIT ?
        """
        params.append(_limit(limit))
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_todo_item_from_row(row) for row in rows)

    def upsert_state_proposal(self, proposal: TaskStateProposal) -> TaskStateProposal:
        now = _now()
        stored = replace(proposal, created_at=proposal.created_at or now, updated_at=now)
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO task_state_proposals (
                    proposal_id, task_environment_id, task_instance_id, source_episode_id,
                    source_result_id, proposal_kind, state_path, operation, value_json,
                    evidence_refs_json, confidence, status, rejection_reason,
                    created_at, updated_at, metadata_json, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    task_environment_id = excluded.task_environment_id,
                    task_instance_id = excluded.task_instance_id,
                    source_episode_id = excluded.source_episode_id,
                    source_result_id = excluded.source_result_id,
                    proposal_kind = excluded.proposal_kind,
                    state_path = excluded.state_path,
                    operation = excluded.operation,
                    value_json = excluded.value_json,
                    evidence_refs_json = excluded.evidence_refs_json,
                    confidence = excluded.confidence,
                    status = excluded.status,
                    rejection_reason = excluded.rejection_reason,
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json,
                    authority = excluded.authority
                """,
                (
                    stored.proposal_id,
                    stored.task_environment_id,
                    stored.task_instance_id,
                    stored.source_episode_id,
                    stored.source_result_id,
                    stored.proposal_kind,
                    stored.state_path,
                    stored.operation,
                    _json(stored.value),
                    _json(list(stored.evidence_refs)),
                    stored.confidence,
                    stored.status,
                    stored.rejection_reason,
                    stored.created_at,
                    stored.updated_at,
                    _json(stored.metadata),
                    stored.authority,
                ),
            )
        return stored

    def get_state_proposal(self, proposal_id: str) -> TaskStateProposal | None:
        target = str(proposal_id or "").strip()
        if not target:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM task_state_proposals WHERE proposal_id = ?", (target,)).fetchone()
        return _state_proposal_from_row(row) if row is not None else None

    def list_state_proposals(
        self,
        task_environment_id: str,
        *,
        status: str = "",
        proposal_kind: str = "",
        limit: int = 200,
    ) -> tuple[TaskStateProposal, ...]:
        target = str(task_environment_id or "").strip()
        if not target:
            return ()
        filters = ["task_environment_id = ?"]
        params: list[Any] = [target]
        if status:
            filters.append("status = ?")
            params.append(str(status))
        if proposal_kind:
            filters.append("proposal_kind = ?")
            params.append(str(proposal_kind))
        sql = f"""
            SELECT *
            FROM task_state_proposals
            WHERE {" AND ".join(filters)}
            ORDER BY updated_at DESC, proposal_id ASC
            LIMIT ?
        """
        params.append(_limit(limit))
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_state_proposal_from_row(row) for row in rows)

    def get_context_package(self, package_id: str) -> TaskContextPackage | None:
        target = str(package_id or "").strip()
        if not target:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM task_context_packages WHERE package_id = ?", (target,)).fetchone()
        return _context_package_from_row(row) if row is not None else None

    def list_context_packages(self, task_environment_id: str, *, limit: int = 20) -> tuple[TaskContextPackage, ...]:
        target = str(task_environment_id or "").strip()
        if not target:
            return ()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM task_context_packages
                WHERE task_environment_id = ?
                ORDER BY created_at DESC, package_id ASC
                LIMIT ?
                """,
                (target, _limit(limit)),
            ).fetchall()
        return tuple(_context_package_from_row(row) for row in rows)

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

    def get_session_binding(self, binding_id: str) -> SessionTaskBinding | None:
        target = str(binding_id or "").strip()
        if not target:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM session_task_bindings WHERE binding_id = ?", (target,)).fetchone()
        return _session_binding_from_row(row) if row is not None else None

    def list_session_bindings(
        self,
        session_id: str,
        *,
        visibility: str = "",
        status: str = "",
        control_role: str = "",
        limit: int = 20,
    ) -> tuple[SessionTaskBinding, ...]:
        target = str(session_id or "").strip()
        if not target:
            return ()
        filters = ["session_id = ?"]
        params: list[Any] = [target]
        if visibility:
            filters.append("visibility = ?")
            params.append(str(visibility or "").strip())
        if status:
            filters.append("status = ?")
            params.append(str(status or "").strip())
        if control_role:
            filters.append("control_role = ?")
            params.append(str(control_role or "").strip())
        sql = f"""
            SELECT *
            FROM session_task_bindings
            WHERE {" AND ".join(filters)}
            ORDER BY last_focused_at DESC, updated_at DESC, binding_id ASC
            LIMIT ?
        """
        params.append(_limit(limit))
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_session_binding_from_row(row) for row in rows)

    def get_foreground_session_binding(self, session_id: str) -> SessionTaskBinding | None:
        bindings = self.list_session_bindings(
            session_id,
            visibility="foreground",
            status="active",
            control_role="controller",
            limit=1,
        )
        return bindings[0] if bindings else None

    def upsert_context_package(self, package: TaskContextPackage) -> TaskContextPackage:
        stored = replace(package, created_at=package.created_at or _now())
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO task_context_packages (
                    package_id, task_environment_id, episode_id, package_hash, role_contract,
                    goal, scope_json, acceptance_json, stable_context_ref, current_context_ref,
                    memory_refs_json, artifact_refs_json, resource_handles_json,
                    graph_context_json, project_network_handles_json, task_state_context_json, continuation_hint,
                    output_contract_json, packet_policy_json, metadata_json, created_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    task_state_context_json = excluded.task_state_context_json,
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
                    _json(stored.task_state_context),
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

    def get_lease(self, lease_id: str) -> TaskEnvironmentLease | None:
        target = str(lease_id or "").strip()
        if not target:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM task_environment_leases WHERE lease_id = ?", (target,)).fetchone()
        return _lease_from_row(row) if row is not None else None

    def list_leases(
        self,
        task_environment_id: str,
        *,
        status: str = "",
        limit: int = 50,
    ) -> tuple[TaskEnvironmentLease, ...]:
        target = str(task_environment_id or "").strip()
        if not target:
            return ()
        filters = ["task_environment_id = ?"]
        params: list[Any] = [target]
        if status:
            filters.append("status = ?")
            params.append(status)
        sql = f"""
            SELECT *
            FROM task_environment_leases
            WHERE {" AND ".join(filters)}
            ORDER BY acquired_at DESC, lease_id ASC
            LIMIT ?
        """
        params.append(_limit(limit))
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_lease_from_row(row) for row in rows)

    def list_expired_active_leases(
        self,
        *,
        now: float | None = None,
        limit: int = 200,
    ) -> tuple[TaskEnvironmentLease, ...]:
        cutoff = _now() if now is None else float(now)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM task_environment_leases
                WHERE status = 'active' AND expires_at <= ?
                ORDER BY expires_at ASC, lease_id ASC
                LIMIT ?
                """,
                (cutoff, _limit(limit)),
            ).fetchall()
        return tuple(_lease_from_row(row) for row in rows)

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

    def get_control_signal(self, signal_id: str) -> TaskControlSignal | None:
        target = str(signal_id or "").strip()
        if not target:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM task_control_signals WHERE signal_id = ?", (target,)).fetchone()
        return _control_signal_from_row(row) if row is not None else None

    def list_control_signals(
        self,
        task_environment_id: str,
        *,
        status: str = "",
        limit: int = 50,
    ) -> tuple[TaskControlSignal, ...]:
        target = str(task_environment_id or "").strip()
        if not target:
            return ()
        filters = ["task_environment_id = ?"]
        params: list[Any] = [target]
        if status:
            filters.append("status = ?")
            params.append(status)
        sql = f"""
            SELECT *
            FROM task_control_signals
            WHERE {" AND ".join(filters)}
            ORDER BY created_at DESC, signal_id ASC
            LIMIT ?
        """
        params.append(_limit(limit))
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_control_signal_from_row(row) for row in rows)

    def upsert_task_command(self, command: TaskCommand) -> TaskCommand:
        now = _now()
        stored = replace(command, created_at=command.created_at or now, updated_at=now)
        with closing(self._connect()) as conn:
            existing = conn.execute(
                """
                SELECT * FROM task_commands
                WHERE task_environment_id = ?
                  AND command_kind = ?
                  AND idempotency_key = ?
                """,
                (stored.task_environment_id, stored.command_kind, stored.idempotency_key),
            ).fetchone()
            if existing is not None:
                existing_command = _task_command_from_row(existing)
                if existing_command.command_id != stored.command_id:
                    return existing_command
                if (
                    stored.status == "queued"
                    and stored.attempt_count == 0
                    and not stored.dispatch_ref
                    and not stored.result
                    and not stored.error
                ):
                    return existing_command
            conn.execute(
                """
                INSERT INTO task_commands (
                    command_id, task_environment_id, command_kind, status, requested_by,
                    idempotency_key, payload_json, result_json, error_json, attempt_count,
                    lease_ref, dispatch_ref, created_at, updated_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(command_id) DO UPDATE SET
                    status = excluded.status,
                    result_json = excluded.result_json,
                    error_json = excluded.error_json,
                    attempt_count = excluded.attempt_count,
                    lease_ref = excluded.lease_ref,
                    dispatch_ref = excluded.dispatch_ref,
                    updated_at = excluded.updated_at,
                    authority = excluded.authority
                """,
                _task_command_values(stored),
            )
        return stored

    def get_task_command(self, command_id: str) -> TaskCommand | None:
        target = str(command_id or "").strip()
        if not target:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM task_commands WHERE command_id = ?", (target,)).fetchone()
        return _task_command_from_row(row) if row is not None else None

    def get_task_command_by_idempotency(
        self,
        *,
        task_environment_id: str,
        command_kind: str,
        idempotency_key: str,
    ) -> TaskCommand | None:
        key = str(idempotency_key or "").strip()
        if not key:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT * FROM task_commands
                WHERE task_environment_id = ?
                  AND command_kind = ?
                  AND idempotency_key = ?
                """,
                (str(task_environment_id or "").strip(), str(command_kind or "").strip(), key),
            ).fetchone()
        return _task_command_from_row(row) if row is not None else None

    def list_task_commands(
        self,
        task_environment_id: str = "",
        *,
        status: str = "",
        command_kind: str = "",
        limit: int = 100,
    ) -> tuple[TaskCommand, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if task_environment_id:
            filters.append("task_environment_id = ?")
            params.append(str(task_environment_id))
        if status:
            filters.append("status = ?")
            params.append(str(status))
        if command_kind:
            filters.append("command_kind = ?")
            params.append(str(command_kind))
        sql = "SELECT * FROM task_commands"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY created_at DESC, command_id ASC LIMIT ?"
        params.append(_limit(limit))
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_task_command_from_row(row) for row in rows)

    def upsert_task_dispatch_record(self, record: TaskDispatchRecord) -> TaskDispatchRecord:
        now = _now()
        stored = replace(record, started_at=record.started_at or now)
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO task_dispatch_records (
                    dispatch_id, command_id, task_environment_id, episode_id,
                    runtime_anchor_id, graph_run_id, work_order_id, status,
                    result_json, error_json, started_at, finished_at, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dispatch_id) DO UPDATE SET
                    status = excluded.status,
                    episode_id = excluded.episode_id,
                    runtime_anchor_id = excluded.runtime_anchor_id,
                    graph_run_id = excluded.graph_run_id,
                    work_order_id = excluded.work_order_id,
                    result_json = excluded.result_json,
                    error_json = excluded.error_json,
                    finished_at = excluded.finished_at,
                    authority = excluded.authority
                """,
                (
                    stored.dispatch_id,
                    stored.command_id,
                    stored.task_environment_id,
                    stored.episode_id,
                    stored.runtime_anchor_id,
                    stored.graph_run_id,
                    stored.work_order_id,
                    stored.status,
                    _json(stored.result),
                    _json(stored.error),
                    stored.started_at,
                    stored.finished_at,
                    stored.authority,
                ),
            )
        return stored

    def get_task_dispatch_record(self, dispatch_id: str) -> TaskDispatchRecord | None:
        target = str(dispatch_id or "").strip()
        if not target:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM task_dispatch_records WHERE dispatch_id = ?", (target,)).fetchone()
        return _task_dispatch_record_from_row(row) if row is not None else None

    def list_task_dispatch_records(
        self,
        *,
        task_environment_id: str = "",
        command_id: str = "",
        status: str = "",
        limit: int = 100,
    ) -> tuple[TaskDispatchRecord, ...]:
        filters: list[str] = []
        params: list[Any] = []
        if task_environment_id:
            filters.append("task_environment_id = ?")
            params.append(str(task_environment_id))
        if command_id:
            filters.append("command_id = ?")
            params.append(str(command_id))
        if status:
            filters.append("status = ?")
            params.append(str(status))
        sql = "SELECT * FROM task_dispatch_records"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY started_at DESC, dispatch_id ASC LIMIT ?"
        params.append(_limit(limit))
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(_task_dispatch_record_from_row(row) for row in rows)

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

                CREATE TABLE IF NOT EXISTS task_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    task_environment_id TEXT NOT NULL,
                    task_instance_id TEXT NOT NULL,
                    checkpoint_kind TEXT NOT NULL,
                    episode_id TEXT NOT NULL DEFAULT '',
                    event_id TEXT NOT NULL DEFAULT '',
                    event_seq INTEGER NOT NULL DEFAULT -1,
                    context_package_id TEXT NOT NULL DEFAULT '',
                    latest_work_product_ids_json TEXT NOT NULL DEFAULT '[]',
                    latest_artifact_refs_json TEXT NOT NULL DEFAULT '[]',
                    continuation_hint TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    hashes_json TEXT NOT NULL DEFAULT '{}',
                    payload_ref TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    authority TEXT NOT NULL DEFAULT 'task_system.task_checkpoint',
                    FOREIGN KEY(task_environment_id) REFERENCES task_environments(task_environment_id)
                );
                CREATE INDEX IF NOT EXISTS idx_task_checkpoints_env_created
                    ON task_checkpoints(task_environment_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_task_checkpoints_env_kind
                    ON task_checkpoints(task_environment_id, checkpoint_kind, created_at DESC);

                CREATE TABLE IF NOT EXISTS task_plans (
                    plan_id TEXT PRIMARY KEY,
                    task_environment_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    strategy_summary TEXT NOT NULL DEFAULT '',
                    phases_json TEXT NOT NULL DEFAULT '[]',
                    acceptance_mapping_json TEXT NOT NULL DEFAULT '{}',
                    risk_notes_json TEXT NOT NULL DEFAULT '[]',
                    created_by_episode_id TEXT NOT NULL DEFAULT '',
                    supersedes_plan_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    authority TEXT NOT NULL DEFAULT 'task_system.task_plan',
                    FOREIGN KEY(task_environment_id) REFERENCES task_environments(task_environment_id)
                );
                CREATE INDEX IF NOT EXISTS idx_task_plans_env_version
                    ON task_plans(task_environment_id, version DESC);
                CREATE INDEX IF NOT EXISTS idx_task_plans_env_status
                    ON task_plans(task_environment_id, status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS task_todo_items (
                    todo_id TEXT PRIMARY KEY,
                    task_environment_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    plan_id TEXT NOT NULL DEFAULT '',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    blocker TEXT NOT NULL DEFAULT '',
                    created_by_episode_id TEXT NOT NULL DEFAULT '',
                    completed_by_episode_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    authority TEXT NOT NULL DEFAULT 'task_system.task_todo_item',
                    FOREIGN KEY(task_environment_id) REFERENCES task_environments(task_environment_id)
                );
                CREATE INDEX IF NOT EXISTS idx_task_todo_env_status
                    ON task_todo_items(task_environment_id, status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_task_todo_env_plan
                    ON task_todo_items(task_environment_id, plan_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS task_state_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    task_environment_id TEXT NOT NULL,
                    task_instance_id TEXT NOT NULL,
                    source_episode_id TEXT NOT NULL,
                    source_result_id TEXT NOT NULL,
                    proposal_kind TEXT NOT NULL,
                    state_path TEXT NOT NULL DEFAULT '',
                    operation TEXT NOT NULL DEFAULT 'set',
                    value_json TEXT NOT NULL DEFAULT 'null',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    confidence TEXT NOT NULL DEFAULT 'agent_proposed',
                    status TEXT NOT NULL DEFAULT 'recorded',
                    rejection_reason TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    authority TEXT NOT NULL DEFAULT 'task_system.task_state_proposal',
                    FOREIGN KEY(task_environment_id) REFERENCES task_environments(task_environment_id)
                );
                CREATE INDEX IF NOT EXISTS idx_task_state_proposals_env_status
                    ON task_state_proposals(task_environment_id, status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_task_state_proposals_env_kind
                    ON task_state_proposals(task_environment_id, proposal_kind, updated_at DESC);

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
                    task_state_context_json TEXT NOT NULL DEFAULT '{}',
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

                CREATE TABLE IF NOT EXISTS task_commands (
                    command_id TEXT PRIMARY KEY,
                    task_environment_id TEXT NOT NULL DEFAULT '',
                    command_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error_json TEXT NOT NULL DEFAULT '{}',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    lease_ref TEXT NOT NULL DEFAULT '',
                    dispatch_ref TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    authority TEXT NOT NULL DEFAULT 'task_system.task_command',
                    UNIQUE(task_environment_id, command_kind, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_task_commands_env_status
                    ON task_commands(task_environment_id, status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_task_commands_status_kind
                    ON task_commands(status, command_kind, created_at ASC);

                CREATE TABLE IF NOT EXISTS task_dispatch_records (
                    dispatch_id TEXT PRIMARY KEY,
                    command_id TEXT NOT NULL,
                    task_environment_id TEXT NOT NULL DEFAULT '',
                    episode_id TEXT NOT NULL DEFAULT '',
                    runtime_anchor_id TEXT NOT NULL DEFAULT '',
                    graph_run_id TEXT NOT NULL DEFAULT '',
                    work_order_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error_json TEXT NOT NULL DEFAULT '{}',
                    started_at REAL NOT NULL,
                    finished_at REAL NOT NULL DEFAULT 0,
                    authority TEXT NOT NULL DEFAULT 'task_system.task_dispatch_record'
                );
                CREATE INDEX IF NOT EXISTS idx_task_dispatch_command
                    ON task_dispatch_records(command_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_task_dispatch_env_status
                    ON task_dispatch_records(task_environment_id, status, started_at DESC);
                """
            )
            _ensure_table_columns(
                conn,
                "task_context_packages",
                {
                    "task_state_context_json": "TEXT NOT NULL DEFAULT '{}'",
                },
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


def _task_command_values(item: TaskCommand) -> tuple[Any, ...]:
    return (
        item.command_id,
        item.task_environment_id,
        item.command_kind,
        item.status,
        item.requested_by,
        item.idempotency_key,
        _json(item.payload),
        _json(item.result),
        _json(item.error),
        int(item.attempt_count),
        item.lease_ref,
        item.dispatch_ref,
        item.created_at,
        item.updated_at,
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


def _checkpoint_from_row(row: sqlite3.Row) -> TaskCheckpoint:
    return TaskCheckpoint(
        checkpoint_id=str(row["checkpoint_id"]),
        task_environment_id=str(row["task_environment_id"]),
        task_instance_id=str(row["task_instance_id"]),
        checkpoint_kind=str(row["checkpoint_kind"]),  # type: ignore[arg-type]
        episode_id=str(row["episode_id"] or ""),
        event_id=str(row["event_id"] or ""),
        event_seq=int(row["event_seq"] if row["event_seq"] is not None else -1),
        context_package_id=str(row["context_package_id"] or ""),
        latest_work_product_ids=tuple(_strings(_loads(row["latest_work_product_ids_json"], []))),
        latest_artifact_refs=tuple(_strings(_loads(row["latest_artifact_refs_json"], []))),
        continuation_hint=str(row["continuation_hint"] or ""),
        summary=str(row["summary"] or ""),
        hashes=_loads(row["hashes_json"], {}),
        payload_ref=str(row["payload_ref"] or ""),
        metadata=_loads(row["metadata_json"], {}),
        created_at=float(row["created_at"] or 0.0),
        authority=str(row["authority"] or "task_system.task_checkpoint"),
    )


def _task_plan_from_row(row: sqlite3.Row) -> TaskPlan:
    return TaskPlan(
        plan_id=str(row["plan_id"]),
        task_environment_id=str(row["task_environment_id"]),
        version=int(row["version"] or 1),
        status=str(row["status"] or "proposed"),  # type: ignore[arg-type]
        strategy_summary=str(row["strategy_summary"] or ""),
        phases=tuple(dict(item) for item in list(_loads(row["phases_json"], [])) if isinstance(item, dict)),
        acceptance_mapping=_loads(row["acceptance_mapping_json"], {}),
        risk_notes=tuple(_strings(_loads(row["risk_notes_json"], []))),
        created_by_episode_id=str(row["created_by_episode_id"] or ""),
        supersedes_plan_id=str(row["supersedes_plan_id"] or ""),
        created_at=float(row["created_at"] or 0.0),
        updated_at=float(row["updated_at"] or 0.0),
        metadata=_loads(row["metadata_json"], {}),
        authority=str(row["authority"] or "task_system.task_plan"),
    )


def _todo_item_from_row(row: sqlite3.Row) -> TaskTodoItem:
    return TaskTodoItem(
        todo_id=str(row["todo_id"]),
        task_environment_id=str(row["task_environment_id"]),
        title=str(row["title"] or ""),
        status=str(row["status"] or "pending"),  # type: ignore[arg-type]
        plan_id=str(row["plan_id"] or ""),
        evidence_refs=tuple(_strings(_loads(row["evidence_refs_json"], []))),
        blocker=str(row["blocker"] or ""),
        created_by_episode_id=str(row["created_by_episode_id"] or ""),
        completed_by_episode_id=str(row["completed_by_episode_id"] or ""),
        created_at=float(row["created_at"] or 0.0),
        updated_at=float(row["updated_at"] or 0.0),
        metadata=_loads(row["metadata_json"], {}),
        authority=str(row["authority"] or "task_system.task_todo_item"),
    )


def _state_proposal_from_row(row: sqlite3.Row) -> TaskStateProposal:
    return TaskStateProposal(
        proposal_id=str(row["proposal_id"]),
        task_environment_id=str(row["task_environment_id"]),
        task_instance_id=str(row["task_instance_id"]),
        source_episode_id=str(row["source_episode_id"]),
        source_result_id=str(row["source_result_id"]),
        proposal_kind=str(row["proposal_kind"]),
        state_path=str(row["state_path"] or ""),
        operation=str(row["operation"] or "set"),
        value=_loads_any(row["value_json"]),
        evidence_refs=tuple(_strings(_loads(row["evidence_refs_json"], []))),
        confidence=str(row["confidence"] or "agent_proposed"),
        status=str(row["status"] or "recorded"),  # type: ignore[arg-type]
        rejection_reason=str(row["rejection_reason"] or ""),
        created_at=float(row["created_at"] or 0.0),
        updated_at=float(row["updated_at"] or 0.0),
        metadata=_loads(row["metadata_json"], {}),
        authority=str(row["authority"] or "task_system.task_state_proposal"),
    )


def _session_binding_from_row(row: sqlite3.Row) -> SessionTaskBinding:
    return SessionTaskBinding(
        binding_id=str(row["binding_id"]),
        session_id=str(row["session_id"]),
        task_environment_id=str(row["task_environment_id"]),
        task_instance_id=str(row["task_instance_id"]),
        binding_kind=str(row["binding_kind"] or "origin"),
        control_role=str(row["control_role"] or "controller"),
        visibility=str(row["visibility"] or "foreground"),
        created_from_turn_id=str(row["created_from_turn_id"] or ""),
        last_focused_at=float(row["last_focused_at"] or 0.0),
        last_user_steer_ref=str(row["last_user_steer_ref"] or ""),
        status=str(row["status"] or "active"),
        created_at=float(row["created_at"] or 0.0),
        updated_at=float(row["updated_at"] or 0.0),
        metadata=_loads(row["metadata_json"], {}),
        authority=str(row["authority"] or "task_system.session_task_binding"),
    )


def _context_package_from_row(row: sqlite3.Row) -> TaskContextPackage:
    return TaskContextPackage(
        package_id=str(row["package_id"]),
        task_environment_id=str(row["task_environment_id"]),
        episode_id=str(row["episode_id"]),
        package_hash=str(row["package_hash"]),
        role_contract=str(row["role_contract"] or ""),
        goal=str(row["goal"] or ""),
        scope=_loads(row["scope_json"], {}),
        acceptance=_loads(row["acceptance_json"], {}),
        stable_context_ref=str(row["stable_context_ref"] or ""),
        current_context_ref=str(row["current_context_ref"] or ""),
        memory_refs=tuple(_strings(_loads(row["memory_refs_json"], []))),
        artifact_refs=tuple(_strings(_loads(row["artifact_refs_json"], []))),
        resource_handles=_loads(row["resource_handles_json"], {}),
        graph_context=_loads(row["graph_context_json"], {}),
        project_network_handles=_loads(row["project_network_handles_json"], {}),
        task_state_context=_loads(row["task_state_context_json"], {}),
        continuation_hint=str(row["continuation_hint"] or ""),
        output_contract=_loads(row["output_contract_json"], {}),
        packet_policy=_loads(row["packet_policy_json"], {}),
        metadata=_loads(row["metadata_json"], {}),
        created_at=float(row["created_at"] or 0.0),
        authority=str(row["authority"] or "task_system.task_context_package"),
    )


def _lease_from_row(row: sqlite3.Row) -> TaskEnvironmentLease:
    return TaskEnvironmentLease(
        lease_id=str(row["lease_id"]),
        task_environment_id=str(row["task_environment_id"]),
        episode_id=str(row["episode_id"]),
        lease_kind=str(row["lease_kind"]),
        holder_kind=str(row["holder_kind"]),
        holder_id=str(row["holder_id"]),
        status=str(row["status"] or "active"),  # type: ignore[arg-type]
        acquired_at=float(row["acquired_at"] or 0.0),
        expires_at=float(row["expires_at"] or 0.0),
        heartbeat_at=float(row["heartbeat_at"] or 0.0),
        released_at=float(row["released_at"] or 0.0),
        release_reason=str(row["release_reason"] or ""),
        idempotency_key=str(row["idempotency_key"] or ""),
        metadata=_loads(row["metadata_json"], {}),
        authority=str(row["authority"] or "task_system.task_environment_lease"),
    )


def _control_signal_from_row(row: sqlite3.Row) -> TaskControlSignal:
    return TaskControlSignal(
        signal_id=str(row["signal_id"]),
        task_environment_id=str(row["task_environment_id"]),
        signal_kind=str(row["signal_kind"]),  # type: ignore[arg-type]
        requested_by=str(row["requested_by"]),
        status=str(row["status"] or "pending"),  # type: ignore[arg-type]
        reason=str(row["reason"] or ""),
        payload=_loads(row["payload_json"], {}),
        created_at=float(row["created_at"] or 0.0),
        handled_at=float(row["handled_at"] or 0.0),
        handler_episode_id=str(row["handler_episode_id"] or ""),
        idempotency_key=str(row["idempotency_key"] or ""),
        authority=str(row["authority"] or "task_system.task_control_signal"),
    )


def _task_command_from_row(row: sqlite3.Row) -> TaskCommand:
    return TaskCommand(
        command_id=str(row["command_id"]),
        task_environment_id=str(row["task_environment_id"] or ""),
        command_kind=str(row["command_kind"]),  # type: ignore[arg-type]
        status=str(row["status"] or "queued"),  # type: ignore[arg-type]
        requested_by=str(row["requested_by"] or "system"),
        idempotency_key=str(row["idempotency_key"] or ""),
        payload=_loads(row["payload_json"], {}),
        result=_loads(row["result_json"], {}),
        error=_loads(row["error_json"], {}),
        attempt_count=int(row["attempt_count"] or 0),
        lease_ref=str(row["lease_ref"] or ""),
        dispatch_ref=str(row["dispatch_ref"] or ""),
        created_at=float(row["created_at"] or 0.0),
        updated_at=float(row["updated_at"] or 0.0),
        authority=str(row["authority"] or "task_system.task_command"),
    )


def _task_dispatch_record_from_row(row: sqlite3.Row) -> TaskDispatchRecord:
    return TaskDispatchRecord(
        dispatch_id=str(row["dispatch_id"]),
        command_id=str(row["command_id"]),
        task_environment_id=str(row["task_environment_id"] or ""),
        episode_id=str(row["episode_id"] or ""),
        runtime_anchor_id=str(row["runtime_anchor_id"] or ""),
        graph_run_id=str(row["graph_run_id"] or ""),
        work_order_id=str(row["work_order_id"] or ""),
        status=str(row["status"] or "running"),  # type: ignore[arg-type]
        result=_loads(row["result_json"], {}),
        error=_loads(row["error_json"], {}),
        started_at=float(row["started_at"] or 0.0),
        finished_at=float(row["finished_at"] or 0.0),
        authority=str(row["authority"] or "task_system.task_dispatch_record"),
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


def _loads_any(value: Any) -> Any:
    try:
        return json.loads(str(value if value is not None else "null"))
    except (TypeError, json.JSONDecodeError):
        return None


def _ensure_table_columns(conn: sqlite3.Connection, table_name: str, columns: dict[str, str]) -> None:
    existing = {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    for column_name, column_definition in columns.items():
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def _strings(value: Any) -> list[str]:
    return [str(item).strip() for item in list(value or []) if str(item).strip()]
