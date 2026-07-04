from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

from core.project_layout import ProjectLayout

from .models import AgentExecutionEpisode, EpisodeResult


class EpisodeRepository:
    authority = "task_system.episode_repository"

    def __init__(self, base_dir: str | Path) -> None:
        layout = ProjectLayout.from_backend_dir(base_dir)
        self.root = layout.tasks_dir
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "task_environment.sqlite"
        self._ensure_schema()

    def upsert_episode(self, episode: AgentExecutionEpisode) -> AgentExecutionEpisode:
        now = _now()
        stored = replace(episode, started_at=episode.started_at or now)
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO agent_execution_episodes (
                    episode_id, task_environment_id, task_instance_id, agent_id, agent_profile_id,
                    invocation_kind, caller_kind, graph_binding_id, input_context_package_id,
                    lease_id, runtime_trace_ref, status, terminal_reason, continuation_hint,
                    started_at, ended_at, diagnostics_json, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(episode_id) DO UPDATE SET
                    task_environment_id = excluded.task_environment_id,
                    task_instance_id = excluded.task_instance_id,
                    agent_id = excluded.agent_id,
                    agent_profile_id = excluded.agent_profile_id,
                    invocation_kind = excluded.invocation_kind,
                    caller_kind = excluded.caller_kind,
                    graph_binding_id = excluded.graph_binding_id,
                    input_context_package_id = excluded.input_context_package_id,
                    lease_id = excluded.lease_id,
                    runtime_trace_ref = excluded.runtime_trace_ref,
                    status = excluded.status,
                    terminal_reason = excluded.terminal_reason,
                    continuation_hint = excluded.continuation_hint,
                    ended_at = excluded.ended_at,
                    diagnostics_json = excluded.diagnostics_json,
                    authority = excluded.authority
                """,
                (
                    stored.episode_id,
                    stored.task_environment_id,
                    stored.task_instance_id,
                    stored.agent_id,
                    stored.agent_profile_id,
                    stored.invocation_kind,
                    stored.caller_kind,
                    stored.graph_binding_id,
                    stored.input_context_package_id,
                    stored.lease_id,
                    stored.runtime_trace_ref,
                    stored.status,
                    stored.terminal_reason,
                    stored.continuation_hint,
                    stored.started_at,
                    stored.ended_at,
                    _json(stored.diagnostics),
                    stored.authority,
                ),
            )
        return stored

    def get_episode(self, episode_id: str) -> AgentExecutionEpisode | None:
        target = str(episode_id or "").strip()
        if not target:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM agent_execution_episodes WHERE episode_id = ?", (target,)).fetchone()
        return _episode_from_row(row) if row is not None else None

    def upsert_episode_result(self, result: EpisodeResult) -> EpisodeResult:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO episode_results (
                    result_id, episode_id, task_environment_id, status, summary,
                    work_product_candidates_json, state_update_proposals_json,
                    plan_patch_json, todo_patch_json, memory_candidates_json,
                    artifact_refs_json, evidence_refs_json, blocker, continuation_hint,
                    output_contract_version, diagnostics_json, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(result_id) DO UPDATE SET
                    episode_id = excluded.episode_id,
                    task_environment_id = excluded.task_environment_id,
                    status = excluded.status,
                    summary = excluded.summary,
                    work_product_candidates_json = excluded.work_product_candidates_json,
                    state_update_proposals_json = excluded.state_update_proposals_json,
                    plan_patch_json = excluded.plan_patch_json,
                    todo_patch_json = excluded.todo_patch_json,
                    memory_candidates_json = excluded.memory_candidates_json,
                    artifact_refs_json = excluded.artifact_refs_json,
                    evidence_refs_json = excluded.evidence_refs_json,
                    blocker = excluded.blocker,
                    continuation_hint = excluded.continuation_hint,
                    output_contract_version = excluded.output_contract_version,
                    diagnostics_json = excluded.diagnostics_json,
                    authority = excluded.authority
                """,
                (
                    result.result_id,
                    result.episode_id,
                    result.task_environment_id,
                    result.status,
                    result.summary,
                    _json(list(result.work_product_candidates)),
                    _json(list(result.state_update_proposals)),
                    _json(result.plan_patch),
                    _json(result.todo_patch),
                    _json(list(result.memory_candidates)),
                    _json(list(result.artifact_refs)),
                    _json(list(result.evidence_refs)),
                    result.blocker,
                    result.continuation_hint,
                    result.output_contract_version,
                    _json(result.diagnostics),
                    result.authority,
                ),
            )
        return result

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_execution_episodes (
                    episode_id TEXT PRIMARY KEY,
                    task_environment_id TEXT NOT NULL,
                    task_instance_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    agent_profile_id TEXT NOT NULL,
                    invocation_kind TEXT NOT NULL,
                    caller_kind TEXT NOT NULL,
                    graph_binding_id TEXT NOT NULL DEFAULT '',
                    input_context_package_id TEXT NOT NULL DEFAULT '',
                    lease_id TEXT NOT NULL DEFAULT '',
                    runtime_trace_ref TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    terminal_reason TEXT NOT NULL DEFAULT '',
                    continuation_hint TEXT NOT NULL DEFAULT '',
                    started_at REAL NOT NULL,
                    ended_at REAL NOT NULL DEFAULT 0,
                    diagnostics_json TEXT NOT NULL DEFAULT '{}',
                    authority TEXT NOT NULL DEFAULT 'task_system.agent_execution_episode'
                );
                CREATE INDEX IF NOT EXISTS idx_episodes_env_started
                    ON agent_execution_episodes(task_environment_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_episodes_status
                    ON agent_execution_episodes(status, started_at DESC);

                CREATE TABLE IF NOT EXISTS episode_results (
                    result_id TEXT PRIMARY KEY,
                    episode_id TEXT NOT NULL,
                    task_environment_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    work_product_candidates_json TEXT NOT NULL DEFAULT '[]',
                    state_update_proposals_json TEXT NOT NULL DEFAULT '[]',
                    plan_patch_json TEXT NOT NULL DEFAULT '{}',
                    todo_patch_json TEXT NOT NULL DEFAULT '{}',
                    memory_candidates_json TEXT NOT NULL DEFAULT '[]',
                    artifact_refs_json TEXT NOT NULL DEFAULT '[]',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    blocker TEXT NOT NULL DEFAULT '',
                    continuation_hint TEXT NOT NULL DEFAULT '',
                    output_contract_version TEXT NOT NULL DEFAULT '',
                    diagnostics_json TEXT NOT NULL DEFAULT '{}',
                    authority TEXT NOT NULL DEFAULT 'task_system.episode_result'
                );
                CREATE INDEX IF NOT EXISTS idx_episode_results_episode
                    ON episode_results(episode_id);
                """
            )


def _episode_from_row(row: sqlite3.Row) -> AgentExecutionEpisode:
    return AgentExecutionEpisode(
        episode_id=str(row["episode_id"]),
        task_environment_id=str(row["task_environment_id"]),
        task_instance_id=str(row["task_instance_id"]),
        agent_id=str(row["agent_id"]),
        agent_profile_id=str(row["agent_profile_id"]),
        invocation_kind=str(row["invocation_kind"]),
        caller_kind=str(row["caller_kind"]),
        graph_binding_id=str(row["graph_binding_id"] or ""),
        input_context_package_id=str(row["input_context_package_id"] or ""),
        lease_id=str(row["lease_id"] or ""),
        runtime_trace_ref=str(row["runtime_trace_ref"] or ""),
        status=str(row["status"] or "scheduled"),  # type: ignore[arg-type]
        terminal_reason=str(row["terminal_reason"] or ""),
        continuation_hint=str(row["continuation_hint"] or ""),
        started_at=float(row["started_at"] or 0.0),
        ended_at=float(row["ended_at"] or 0.0),
        diagnostics=_loads(row["diagnostics_json"], {}),
        authority=str(row["authority"] or "task_system.agent_execution_episode"),
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
