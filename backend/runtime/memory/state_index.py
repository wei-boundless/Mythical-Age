from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ..shared.models import (
    AgentRun,
    AgentRunResult,
    CANONICAL_AGENT_RUN_STATUSES,
    CANONICAL_TASK_RUN_STATUSES,
    ProjectProgressLedger,
    ProjectRuntimeStatus,
    SupervisionRecord,
    TaskRun,
    TurnRun,
)
from agent_system.registry.worker_agent_blueprints import WorkerAgentSpawnRequest, WorkerAgentSpawnResult
from harness.agent_control.models import SubagentMessage, subagent_message_from_dict
from ..shared.runtime_object_store import RuntimeObjectStore


_STATE_INDEX_WRITE_LOCK = threading.RLock()
GLOBAL_RECENT_TASK_RUN_INDEX_ID = "default"
GLOBAL_RECENT_TASK_RUN_LIMIT = 240
ACTIVE_EXECUTOR_TASK_RUN_INDEX_ID = "default"
TASK_RUN_SUMMARY_AUTHORITY = "orchestration.task_run.monitor_summary"

TASK_RUN_SUMMARY_DIAGNOSTIC_KEYS = {
    "active_contract_revision_count",
    "active_node_id",
    "active_node_work_order_count",
    "agent_brief_output",
    "completion_status",
    "config_snapshot_hash",
    "config_snapshot_id",
    "coordination_stage_id",
    "current_judgment",
    "executor_epoch",
    "executor_status",
    "goal",
    "graph_config_hash",
    "graph_config_id",
    "graph_id",
    "graph_node_id",
    "graph_result_ref",
    "graph_result_summary",
    "graph_run_id",
    "graph_structure_hash",
    "graph_structure_version",
    "graph_work_order_id",
    "latest_completion_status",
    "latest_contract_revision_ref",
    "latest_current_judgment",
    "latest_event_at",
    "latest_interaction_turn_id",
    "latest_next_action",
    "latest_observation",
    "latest_public_progress_note",
    "latest_step",
    "latest_step_at",
    "latest_step_status",
    "latest_step_summary",
    "latest_tool_status",
    "latest_user_steer_ref",
    "next_action",
    "next_invocation_index",
    "node_id",
    "origin_authority",
    "origin_kind",
    "origin_ref",
    "parent_run_ref",
    "pending_user_steer_count",
    "project_id",
    "project_title",
    "public_progress_note",
    "recovery_action",
    "runner_blocked_reason",
    "runner_budget_exhausted",
    "runner_dispatch_count",
    "runner_executed_work_order_count",
    "runner_status",
    "runner_terminal_reason",
    "session_scope_key",
    "source",
    "stage_idempotency_key",
    "stage_request_id",
    "summary",
    "task_environment_id",
    "task_goal",
    "task_graph_id",
    "task_graph_title",
    "title",
    "workspace_view",
}

TASK_RUN_SUMMARY_DIAGNOSTIC_DICT_KEYS = {
    "contract",
    "origin",
    "pending_approval",
    "runtime_contract",
    "runtime_control",
    "runtime_scope",
    "session_scope",
}


class RuntimeStateIndex:
    """Fast lookup index for latest runtime formal objects."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.index_path = self.root_dir / "state_index.json"
        self.index_dir = self.root_dir / "state_index"
        self.meta_path = self.index_dir / "meta.json"
        self.deleted_sessions_dir = self.index_dir / "deleted_sessions"
        self.deleted_task_runs_dir = self.index_dir / "deleted_task_runs"
        self.views_dir = self.root_dir / "runtime_views" / "session_live"
        self.runtime_objects = RuntimeObjectStore(self.root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.deleted_sessions_dir.mkdir(parents=True, exist_ok=True)
        self.deleted_task_runs_dir.mkdir(parents=True, exist_ok=True)
        self.views_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_storage_ready()

    def upsert_task_run(self, task_run: TaskRun) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._upsert_task_run_unlocked(task_run)

    def update_task_run(self, task_run_id: str, updater: Any) -> TaskRun | None:
        normalized_task_run_id = str(task_run_id or "").strip()
        if not normalized_task_run_id or not callable(updater):
            return None
        with _STATE_INDEX_WRITE_LOCK:
            if self._task_run_deleted_unlocked(normalized_task_run_id):
                return None
            payload = self._read_record("task_runs", normalized_task_run_id)
            if not payload:
                return None
            current = _task_run_from_payload(payload)
            updated = updater(current)
            if updated is None:
                return None
            if not isinstance(updated, TaskRun):
                raise TypeError("RuntimeStateIndex.update_task_run updater must return TaskRun or None")
            if updated.task_run_id != normalized_task_run_id:
                raise ValueError("RuntimeStateIndex.update_task_run cannot change task_run_id")
            if updated.session_id != current.session_id:
                raise ValueError("RuntimeStateIndex.update_task_run cannot change session_id")
            return self._upsert_task_run_unlocked(updated)

    def upsert_turn_run(self, turn_run: TurnRun) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            if self._session_deleted_unlocked(turn_run.session_id):
                return
            payload = turn_run.to_dict()
            self._write_record("turn_runs", turn_run.turn_run_id, payload)
            self._append_index_id("session_turn_runs", turn_run.session_id, turn_run.turn_run_id)
            self._maybe_write_latest_ref(
                "session_latest_turn_runs",
                turn_run.session_id,
                turn_run.turn_run_id,
                updated_at=float(payload.get("updated_at") or 0.0),
            )
            self._touch_meta()

    def _upsert_task_run_unlocked(self, task_run: TaskRun) -> TaskRun | None:
        if self._session_deleted_unlocked(task_run.session_id) or self._task_run_deleted_unlocked(task_run.task_run_id):
            return None
        payload = self._compact_task_run_payload(task_run.to_dict())
        self._write_record("task_runs", task_run.task_run_id, payload)
        self._write_record("task_run_summaries", task_run.task_run_id, _task_run_monitor_summary_payload(payload))
        self._append_index_id("sessions", task_run.session_id, task_run.task_run_id)
        self._upsert_global_recent_task_run(
            task_run.task_run_id,
            updated_at=float(payload.get("updated_at") or payload.get("created_at") or 0.0),
        )
        self._maybe_write_latest_ref(
            "session_latest_task_runs",
            task_run.session_id,
            task_run.task_run_id,
            updated_at=float(payload.get("updated_at") or 0.0),
        )
        self._upsert_session_live_view(
            session_id=task_run.session_id,
            task_run_id=task_run.task_run_id,
            updated_at=float(payload.get("updated_at") or 0.0),
        )
        self._sync_active_executor_task_run_id(task_run.task_run_id, payload)
        self._sync_graph_node_task_run_id(task_run.task_run_id, payload)
        self._touch_meta()
        return _task_run_from_payload(payload)

    def upsert_agent_run(self, agent_run: AgentRun) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            if self._task_run_deleted_unlocked(agent_run.task_run_id):
                return
            self._write_record("agent_runs", agent_run.agent_run_id, agent_run.to_dict())
            self._append_index_id("task_agent_runs", agent_run.task_run_id, agent_run.agent_run_id)
            self._touch_meta()

    def upsert_agent_run_result(self, result: AgentRunResult) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            if self._task_run_deleted_unlocked(result.task_run_id):
                return
            self._write_record("agent_run_results", result.agent_run_result_id, result.to_dict())
            self._append_index_id("task_agent_run_results", result.task_run_id, result.agent_run_result_id)
            self._touch_meta()

    def upsert_subagent_message(self, message: SubagentMessage) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            if self._task_run_deleted_unlocked(message.task_run_id):
                return
            self._write_record("subagent_messages", message.message_id, message.to_dict())
            self._append_index_id("task_subagent_messages", message.task_run_id, message.message_id)
            self._append_index_id("subagent_run_messages", message.subagent_run_ref, message.message_id)
            self._touch_meta()

    def upsert_worker_spawn_request(self, request: WorkerAgentSpawnRequest) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            if self._task_run_deleted_unlocked(request.task_run_id):
                return
            self._write_record("worker_spawn_requests", request.spawn_request_id, request.to_dict())
            self._append_index_id("task_worker_spawn_requests", request.task_run_id, request.spawn_request_id)
            self._touch_meta()

    def upsert_worker_spawn_result(self, result: WorkerAgentSpawnResult) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            if self._task_run_deleted_unlocked(result.task_run_id):
                return
            self._write_record("worker_spawn_results", result.spawn_result_id, result.to_dict())
            self._append_index_id("task_worker_spawn_results", result.task_run_id, result.spawn_result_id)
            self._touch_meta()

    def upsert_project_progress_ledger(self, ledger: ProjectProgressLedger) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            if self._session_deleted_unlocked(ledger.session_id):
                return
            self._write_record("project_progress_ledgers", ledger.project_id, ledger.to_dict())
            self._append_index_id("session_projects", ledger.session_id, ledger.project_id)
            self._write_index_value("graph_project_index", ledger.graph_id, ledger.project_id)
            self._touch_meta(updated_at=float(ledger.updated_at or time.time()))

    def upsert_supervision_record(self, record: SupervisionRecord) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            if record.observed_task_run_id and self._task_run_deleted_unlocked(record.observed_task_run_id):
                return
            self._write_record("supervision_records", record.supervision_record_id, record.to_dict())
            self._append_index_id("project_supervision_records", record.project_id, record.supervision_record_id)
            if record.observed_task_run_id:
                self._append_index_id("task_supervision_records", record.observed_task_run_id, record.supervision_record_id)
            self._touch_meta(updated_at=float(record.created_at or time.time()))

    def upsert_project_runtime_status(self, status: ProjectRuntimeStatus) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            if self._session_deleted_unlocked(status.session_id):
                return
            if status.active_task_run_id and self._task_run_deleted_unlocked(status.active_task_run_id):
                return
            self._write_record("project_runtime_statuses", status.project_id, status.to_dict())
            self._write_index_value("session_active_project_status", status.session_id, status.project_id)
            if status.active_task_run_id:
                self._write_index_value("task_project_status", status.active_task_run_id, status.project_id)
            self._touch_meta(updated_at=float(status.updated_at or time.time()))

    def get_task_run(self, task_run_id: str) -> TaskRun | None:
        task_run = self._read_record("task_runs", task_run_id)
        if not task_run:
            return None
        return _task_run_from_payload(task_run)

    def get_turn_run(self, turn_run_id: str) -> TurnRun | None:
        turn_run = self._read_record("turn_runs", turn_run_id)
        if not turn_run:
            return None
        return _turn_run_from_payload(turn_run)

    def list_task_runs(self) -> list[TaskRun]:
        task_runs = self._read_record_bucket("task_runs")
        return [_task_run_from_payload(item) for item in task_runs.values() if isinstance(item, dict)]

    def list_active_executor_task_runs(self) -> list[TaskRun]:
        ids = self._read_index_ids("active_executor_task_runs", ACTIVE_EXECUTOR_TASK_RUN_INDEX_ID)
        if not ids:
            return []
        task_runs: list[TaskRun] = []
        active_ids: list[str] = []
        for task_run_id in ids:
            payload = self._read_record("task_runs", task_run_id)
            if not payload or not _is_active_executor_task_run_payload(payload):
                continue
            task_runs.append(_task_run_from_payload(payload))
            active_ids.append(task_run_id)
        if active_ids != ids:
            self._write_index_value("active_executor_task_runs", ACTIVE_EXECUTOR_TASK_RUN_INDEX_ID, active_ids)
        return task_runs

    def get_graph_node_task_run(self, *, graph_run_id: str = "", work_order_id: str = "") -> TaskRun | None:
        normalized_work_order_id = str(work_order_id or "").strip()
        if not normalized_work_order_id:
            return None
        task_run_id = str(self._read_index_value("graph_node_task_run_by_work_order", normalized_work_order_id) or "").strip()
        if not task_run_id:
            return None
        payload = self._read_record("task_runs", task_run_id)
        identity = _graph_node_task_identity(payload)
        if not payload or not identity or identity.get("work_order_id") != normalized_work_order_id:
            self._write_index_value("graph_node_task_run_by_work_order", normalized_work_order_id, "")
            return None
        normalized_graph_run_id = str(graph_run_id or "").strip()
        if normalized_graph_run_id and identity.get("graph_run_id") != normalized_graph_run_id:
            self._write_index_value("graph_node_task_run_by_work_order", normalized_work_order_id, "")
            return None
        return _task_run_from_payload(payload)

    def list_graph_node_task_runs(self, *, graph_run_id: str) -> list[TaskRun]:
        normalized_graph_run_id = str(graph_run_id or "").strip()
        if not normalized_graph_run_id:
            return []
        ids = self._read_index_ids("graph_node_task_runs_by_graph_run", normalized_graph_run_id)
        task_runs: list[TaskRun] = []
        active_ids: list[str] = []
        for task_run_id in ids:
            payload = self._read_record("task_runs", task_run_id)
            identity = _graph_node_task_identity(payload)
            if not payload or not identity or identity.get("graph_run_id") != normalized_graph_run_id:
                continue
            task_runs.append(_task_run_from_payload(payload))
            active_ids.append(task_run_id)
        if active_ids != ids:
            self._write_index_value("graph_node_task_runs_by_graph_run", normalized_graph_run_id, active_ids)
        return task_runs

    def list_recent_task_runs(self, *, limit: int = 80) -> list[TaskRun]:
        requested = max(1, min(int(limit or 80), GLOBAL_RECENT_TASK_RUN_LIMIT))
        ids = self._read_index_ids("global_recent_task_runs", GLOBAL_RECENT_TASK_RUN_INDEX_ID)
        if not ids:
            ids = self._rebuild_global_recent_task_run_index(limit=max(requested, GLOBAL_RECENT_TASK_RUN_LIMIT))
        payloads: list[dict[str, Any]] = []
        stale = False
        for task_run_id in ids[:requested]:
            payload = self._read_record("task_runs", task_run_id)
            if payload:
                payloads.append(payload)
            else:
                stale = True
        if stale:
            self._write_global_recent_task_run_ids([str(item.get("task_run_id") or "") for item in payloads])
        return [_task_run_from_payload(item) for item in payloads if isinstance(item, dict)]

    def list_recent_task_run_summaries(self, *, limit: int = 80) -> list[TaskRun]:
        requested = max(1, min(int(limit or 80), GLOBAL_RECENT_TASK_RUN_LIMIT))
        ids = self._read_index_ids("global_recent_task_runs", GLOBAL_RECENT_TASK_RUN_INDEX_ID)
        if not ids:
            ids = self._rebuild_global_recent_task_run_index(limit=max(requested, GLOBAL_RECENT_TASK_RUN_LIMIT))
        payloads = self._read_task_run_summary_payloads(ids[:requested])
        if len(payloads) != len(ids[:requested]):
            self._write_global_recent_task_run_ids([str(item.get("task_run_id") or "") for item in payloads])
        return [_task_run_from_payload(item) for item in payloads if isinstance(item, dict)]

    def list_session_task_runs(self, session_id: str) -> list[TaskRun]:
        ids = self._read_index_ids("sessions", session_id)
        task_runs = self._read_selected_records("task_runs", ids)
        return [_task_run_from_payload(task_runs[item]) for item in ids if item in task_runs]

    def list_session_task_run_summaries(self, session_id: str, *, limit: int | None = None) -> list[TaskRun]:
        ids = self._read_index_ids("sessions", session_id)
        payloads = self._read_task_run_summary_payloads(ids)
        payload_index = {str(item.get("task_run_id") or ""): item for item in payloads if isinstance(item, dict)}
        ordered_payloads = [payload_index[item] for item in ids if item in payload_index]
        if limit is not None:
            requested = max(1, min(int(limit or 1), GLOBAL_RECENT_TASK_RUN_LIMIT))
            ordered_payloads = sorted(
                ordered_payloads,
                key=lambda item: float(item.get("updated_at") or item.get("created_at") or 0.0),
                reverse=True,
            )[:requested]
        return [_task_run_from_payload(item) for item in ordered_payloads]

    def list_session_turn_runs(self, session_id: str) -> list[TurnRun]:
        ids = self._read_index_ids("session_turn_runs", session_id)
        turn_runs = self._read_selected_records("turn_runs", ids)
        return [_turn_run_from_payload(turn_runs[item]) for item in ids if item in turn_runs]

    def list_task_agent_runs(self, task_run_id: str) -> list[AgentRun]:
        ids = self._read_index_ids("task_agent_runs", task_run_id)
        agent_runs = self._read_selected_records("agent_runs", ids)
        return [_agent_run_from_payload(agent_runs[item]) for item in ids if item in agent_runs]

    def get_project_progress_ledger(self, project_id: str) -> ProjectProgressLedger | None:
        payload = self._read_record("project_progress_ledgers", project_id)
        if not payload:
            return None
        return _project_progress_ledger_from_payload(payload)

    def get_project_runtime_status(self, project_id: str) -> ProjectRuntimeStatus | None:
        payload = self._read_record("project_runtime_statuses", project_id)
        if not payload:
            return None
        return _project_runtime_status_from_payload(payload)

    def get_session_active_project_status(self, session_id: str) -> ProjectRuntimeStatus | None:
        project_id = str(self._read_index_value("session_active_project_status", session_id) or "")
        if project_id:
            return self.get_project_runtime_status(project_id)
        project_ids = self._read_index_ids("session_projects", session_id)
        if not project_ids:
            return None
        payloads = [
            self._read_record("project_runtime_statuses", project_id)
            for project_id in project_ids
        ]
        matches = [_project_runtime_status_from_payload(item) for item in payloads if item]
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.updated_at, reverse=True)[0]

    def list_project_supervision_records(self, project_id: str) -> list[SupervisionRecord]:
        ids = self._read_index_ids("project_supervision_records", project_id)
        records = self._read_selected_records("supervision_records", ids)
        return [_supervision_record_from_payload(records[item]) for item in ids if item in records]

    def list_task_supervision_records(self, task_run_id: str) -> list[SupervisionRecord]:
        ids = self._read_index_ids("task_supervision_records", task_run_id)
        records = self._read_selected_records("supervision_records", ids)
        return [_supervision_record_from_payload(records[item]) for item in ids if item in records]

    def list_task_agent_run_results(self, task_run_id: str) -> list[AgentRunResult]:
        ids = self._read_index_ids("task_agent_run_results", task_run_id)
        results = self._read_selected_records("agent_run_results", ids)
        return [_agent_run_result_from_payload(results[item]) for item in ids if item in results]

    def list_task_subagent_messages(self, task_run_id: str) -> list[SubagentMessage]:
        ids = self._read_index_ids("task_subagent_messages", task_run_id)
        messages = self._read_selected_records("subagent_messages", ids)
        return [subagent_message_from_dict(messages[item]) for item in ids if item in messages]

    def list_subagent_run_messages(self, subagent_run_ref: str) -> list[SubagentMessage]:
        ids = self._read_index_ids("subagent_run_messages", subagent_run_ref)
        messages = self._read_selected_records("subagent_messages", ids)
        return [subagent_message_from_dict(messages[item]) for item in ids if item in messages]

    def list_task_worker_spawn_requests(self, task_run_id: str) -> list[WorkerAgentSpawnRequest]:
        ids = self._read_index_ids("task_worker_spawn_requests", task_run_id)
        requests = self._read_selected_records("worker_spawn_requests", ids)
        return [_worker_spawn_request_from_payload(requests[item]) for item in ids if item in requests]

    def list_task_worker_spawn_results(self, task_run_id: str) -> list[WorkerAgentSpawnResult]:
        ids = self._read_index_ids("task_worker_spawn_results", task_run_id)
        results = self._read_selected_records("worker_spawn_results", ids)
        return [_worker_spawn_result_from_payload(results[item]) for item in ids if item in results]

    def read_snapshot(self) -> dict[str, Any]:
        """Return one consistent read snapshot for live-monitor style queries."""
        return self._read()

    def read_session_monitor_snapshot(self, session_id: str) -> dict[str, Any]:
        session_view = self._read_session_live_view(session_id)
        task_run_ids = self._read_index_ids("sessions", session_id)
        task_run_bucket = self._read_record_bucket("task_runs")
        latest_task_run_id = str(
            session_view.get("latest_task_run_id")
            or self._read_index_value("session_latest_task_runs", session_id)
            or ""
        )
        preferred_task_run_ids = [item for item in [latest_task_run_id] if item]
        indexed_task_runs = [
            dict(task_run_bucket.get(task_run_id) or {})
            for task_run_id in task_run_ids
            if isinstance(task_run_bucket.get(task_run_id), dict)
        ]
        freshest_task_run_id = ""
        if indexed_task_runs:
            freshest_task_run = max(
                indexed_task_runs,
                key=lambda item: (
                    float(item.get("updated_at") or 0.0),
                    float(item.get("created_at") or 0.0),
                ),
            )
            freshest_task_run_id = str(freshest_task_run.get("task_run_id") or "")
            if freshest_task_run_id:
                preferred_task_run_ids.insert(0, freshest_task_run_id)
        if not preferred_task_run_ids and task_run_ids:
            preferred_task_run_ids = [task_run_ids[-1]]
        preferred_task_run_ids = list(dict.fromkeys(preferred_task_run_ids))
        task_runs = {
            task_run_id: dict(task_run_bucket.get(task_run_id) or {})
            for task_run_id in preferred_task_run_ids
            if isinstance(task_run_bucket.get(task_run_id), dict)
        }
        return {
            "task_runs": task_runs,
            "sessions": {session_id: preferred_task_run_ids},
            "project_progress_ledgers": self._read_selected_records(
                "project_progress_ledgers",
                self._read_index_ids("session_projects", session_id),
            ),
            "project_runtime_statuses": self._read_selected_records(
                "project_runtime_statuses",
                self._read_index_ids("session_projects", session_id),
            ),
            "monitor_index": {
                "session_id": session_id,
                "task_run_count": int(session_view.get("task_run_count") or len(task_run_ids)),
                "latest_task_run_id": latest_task_run_id,
                "freshest_task_run_id": freshest_task_run_id,
                "active_project_id": str(self._read_index_value("session_active_project_status", session_id) or ""),
                "updated_at": float(session_view.get("updated_at") or self._read_meta().get("updated_at") or 0.0),
            },
            "updated_at": self._read_meta().get("updated_at", 0.0),
        }

    def replace_snapshot(self, payload: dict[str, Any]) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._clear_bucket_layout()
            self._write_snapshot_payload(payload)
            self._touch_meta(updated_at=float(payload.get("updated_at") or time.time()))

    def mark_session_deleted(self, session_id: str) -> dict[str, Any]:
        normalized = str(session_id or "").strip()
        if not normalized:
            return {
                "authority": "orchestration.runtime_state_index.session_deletion_tombstone",
                "session_id": "",
                "recorded": False,
                "reason": "missing_session_id",
            }
        now = time.time()
        with _STATE_INDEX_WRITE_LOCK:
            existing = self._read_json(self._deleted_session_path(normalized), {})
            payload = {
                "session_id": normalized,
                "deleted_at": float(existing.get("deleted_at") or now),
                "updated_at": now,
                "authority": "orchestration.runtime_state_index.session_deletion_tombstone",
            }
            self._atomic_write_path(self._deleted_session_path(normalized), payload)
            self._touch_meta(updated_at=now)
        return {
            "authority": "orchestration.runtime_state_index.session_deletion_tombstone",
            "session_id": normalized,
            "recorded": True,
            "deleted_at": float(payload["deleted_at"]),
        }

    def is_session_deleted(self, session_id: str) -> bool:
        with _STATE_INDEX_WRITE_LOCK:
            return self._session_deleted_unlocked(session_id)

    def mark_task_run_deleted(self, task_run_id: str) -> dict[str, Any]:
        normalized = str(task_run_id or "").strip()
        if not normalized:
            return {
                "authority": "orchestration.runtime_state_index.task_run_deletion_tombstone",
                "task_run_id": "",
                "recorded": False,
                "reason": "missing_task_run_id",
            }
        now = time.time()
        with _STATE_INDEX_WRITE_LOCK:
            payload = self._mark_task_run_deleted_unlocked(normalized, now=now)
            self._touch_meta(updated_at=now)
        return {
            "authority": "orchestration.runtime_state_index.task_run_deletion_tombstone",
            "task_run_id": normalized,
            "recorded": True,
            "deleted_at": float(payload["deleted_at"]),
        }

    def prune_task_runs(self, task_run_ids: set[str]) -> dict[str, Any]:
        targets = {str(item).strip() for item in task_run_ids if str(item).strip()}
        if not targets:
            return {
                "authority": "orchestration.runtime_state_index.prune_task_runs",
                "requested_task_run_ids": [],
                "deleted_task_run_ids": [],
                "deleted_counts": {},
            }
        with _STATE_INDEX_WRITE_LOCK:
            now = time.time()
            deleted_task_run_ids: list[str] = []
            deleted_counts: dict[str, int] = {}
            affected_sessions: set[str] = set()
            for task_run_id in sorted(targets):
                self._mark_task_run_deleted_unlocked(task_run_id, now=now)
                payload = self._read_record("task_runs", task_run_id)
                session_id = str(payload.get("session_id") or "").strip()
                if session_id:
                    affected_sessions.add(session_id)
                    self._remove_index_id("sessions", session_id, task_run_id)
                if payload and self._delete_record("task_runs", task_run_id):
                    deleted_task_run_ids.append(task_run_id)
                    deleted_counts["task_runs"] = deleted_counts.get("task_runs", 0) + 1
                    self._delete_runtime_object_refs(payload, deleted_counts)
                    self._remove_global_task_refs(task_run_id, payload)
                if self._delete_record("task_run_summaries", task_run_id):
                    deleted_counts["task_run_summaries"] = deleted_counts.get("task_run_summaries", 0) + 1
                self._delete_task_scoped_records(task_run_id, deleted_counts)
                self._reset_project_runtime_status_for_task(task_run_id, deleted_counts)
            for session_id in sorted(affected_sessions):
                self._refresh_session_task_indexes(session_id)
            self._touch_meta(updated_at=time.time())
            return {
                "authority": "orchestration.runtime_state_index.prune_task_runs",
                "requested_task_run_ids": sorted(targets),
                "deleted_task_run_ids": sorted(deleted_task_run_ids),
                "deleted_counts": deleted_counts,
            }

    def prune_turn_runs(self, turn_run_ids: set[str]) -> dict[str, Any]:
        targets = {str(item).strip() for item in turn_run_ids if str(item).strip()}
        if not targets:
            return {
                "authority": "orchestration.runtime_state_index.prune_turn_runs",
                "requested_turn_run_ids": [],
                "deleted_turn_run_ids": [],
                "deleted_counts": {},
            }
        with _STATE_INDEX_WRITE_LOCK:
            deleted_turn_run_ids: list[str] = []
            deleted_counts: dict[str, int] = {}
            affected_sessions: set[str] = set()
            for turn_run_id in sorted(targets):
                payload = self._read_record("turn_runs", turn_run_id)
                session_id = str(payload.get("session_id") or "").strip()
                if session_id:
                    affected_sessions.add(session_id)
                    self._remove_index_id("session_turn_runs", session_id, turn_run_id)
                if payload and self._delete_record("turn_runs", turn_run_id):
                    deleted_turn_run_ids.append(turn_run_id)
                    deleted_counts["turn_runs"] = deleted_counts.get("turn_runs", 0) + 1
            for session_id in sorted(affected_sessions):
                self._refresh_session_turn_indexes(session_id)
            self._touch_meta(updated_at=time.time())
            return {
                "authority": "orchestration.runtime_state_index.prune_turn_runs",
                "requested_turn_run_ids": sorted(targets),
                "deleted_turn_run_ids": sorted(deleted_turn_run_ids),
                "deleted_counts": deleted_counts,
            }

    def prune_session_runtime_records(self, session_id: str) -> dict[str, Any]:
        normalized = str(session_id or "").strip()
        if not normalized:
            return {
                "authority": "orchestration.runtime_state_index.prune_session_runtime_records",
                "session_id": "",
                "deleted_counts": {},
            }
        task_run_ids = {item.task_run_id for item in self.list_session_task_runs(normalized) if item.task_run_id}
        turn_run_ids = {item.turn_run_id for item in self.list_session_turn_runs(normalized) if item.turn_run_id}
        task_effect = self.prune_task_runs(task_run_ids)
        turn_effect = self.prune_turn_runs(turn_run_ids)
        return {
            "authority": "orchestration.runtime_state_index.prune_session_runtime_records",
            "session_id": normalized,
            "task_run_ids": sorted(task_run_ids),
            "turn_run_ids": sorted(turn_run_ids),
            "effects": {
                "task_runs": task_effect,
                "turn_runs": turn_effect,
            },
        }

    def _mark_task_run_deleted_unlocked(self, task_run_id: str, *, now: float) -> dict[str, Any]:
        existing = self._read_json(self._deleted_task_run_path(task_run_id), {})
        payload = {
            "task_run_id": task_run_id,
            "deleted_at": float(existing.get("deleted_at") or now),
            "updated_at": now,
            "authority": "orchestration.runtime_state_index.task_run_deletion_tombstone",
        }
        self._atomic_write_path(self._deleted_task_run_path(task_run_id), payload)
        return payload

    def _delete_task_scoped_records(self, task_run_id: str, counts: dict[str, int]) -> None:
        scoped_record_indexes = (
            ("task_agent_runs", "agent_runs"),
            ("task_agent_run_results", "agent_run_results"),
            ("task_worker_spawn_requests", "worker_spawn_requests"),
            ("task_worker_spawn_results", "worker_spawn_results"),
        )
        for index_bucket, record_bucket in scoped_record_indexes:
            record_ids = self._read_index_ids(index_bucket, task_run_id)
            for record_id in record_ids:
                if self._delete_record(record_bucket, record_id):
                    counts[record_bucket] = counts.get(record_bucket, 0) + 1
            self._delete_index_value(index_bucket, task_run_id)

        message_ids = self._read_index_ids("task_subagent_messages", task_run_id)
        for message_id in message_ids:
            payload = self._read_record("subagent_messages", message_id)
            subagent_run_ref = str(payload.get("subagent_run_ref") or "").strip()
            if subagent_run_ref:
                self._remove_index_id("subagent_run_messages", subagent_run_ref, message_id)
            if self._delete_record("subagent_messages", message_id):
                counts["subagent_messages"] = counts.get("subagent_messages", 0) + 1
        self._delete_index_value("task_subagent_messages", task_run_id)

        supervision_ids = self._read_index_ids("task_supervision_records", task_run_id)
        for supervision_id in supervision_ids:
            payload = self._read_record("supervision_records", supervision_id)
            project_id = str(payload.get("project_id") or "").strip()
            if project_id:
                self._remove_index_id("project_supervision_records", project_id, supervision_id)
            if self._delete_record("supervision_records", supervision_id):
                counts["supervision_records"] = counts.get("supervision_records", 0) + 1
        self._delete_index_value("task_supervision_records", task_run_id)

    def _remove_global_task_refs(self, task_run_id: str, payload: dict[str, Any]) -> None:
        self._remove_index_id("global_recent_task_runs", GLOBAL_RECENT_TASK_RUN_INDEX_ID, task_run_id)
        self._remove_index_id("active_executor_task_runs", ACTIVE_EXECUTOR_TASK_RUN_INDEX_ID, task_run_id)
        identity = _graph_node_task_identity(payload)
        graph_run_id = str(identity.get("graph_run_id") or "").strip()
        work_order_id = str(identity.get("work_order_id") or "").strip()
        if graph_run_id:
            self._remove_index_id("graph_node_task_runs_by_graph_run", graph_run_id, task_run_id)
        if work_order_id and str(self._read_index_value("graph_node_task_run_by_work_order", work_order_id) or "") == task_run_id:
            self._delete_index_value("graph_node_task_run_by_work_order", work_order_id)

    def _reset_project_runtime_status_for_task(self, task_run_id: str, counts: dict[str, int]) -> None:
        project_id = str(self._read_index_value("task_project_status", task_run_id) or "").strip()
        if not project_id:
            return
        payload = self._read_record("project_runtime_statuses", project_id)
        if str(payload.get("active_task_run_id") or "").strip() == task_run_id:
            updated = {
                **payload,
                "active_task_run_id": "",
                "active_run_status": "",
                "project_runtime_status": "watching",
                "active_blocker": {},
                "recovery_state": {},
                "updated_at": time.time(),
            }
            self._write_record("project_runtime_statuses", project_id, updated)
            counts["project_runtime_status_task_refs"] = counts.get("project_runtime_status_task_refs", 0) + 1
        self._delete_index_value("task_project_status", task_run_id)

    def _delete_runtime_object_refs(self, payload: dict[str, Any], counts: dict[str, int]) -> None:
        diagnostics = dict(payload.get("diagnostics") or {})
        for key in ("graph_result_ref", "graph_config_ref"):
            ref = str(diagnostics.get(key) or "").strip()
            if not ref:
                continue
            try:
                deleted = self.runtime_objects.delete_ref(ref)
            except ValueError:
                deleted = False
            if deleted:
                counts["runtime_objects"] = counts.get("runtime_objects", 0) + 1

    def _refresh_session_task_indexes(self, session_id: str) -> None:
        task_ids = []
        task_payloads: list[dict[str, Any]] = []
        for task_run_id in self._read_index_ids("sessions", session_id):
            payload = self._read_record("task_runs", task_run_id)
            if not payload:
                continue
            task_ids.append(task_run_id)
            task_payloads.append(payload)
        self._write_or_delete_index_ids("sessions", session_id, task_ids)
        latest = self._latest_record(task_payloads, id_field="task_run_id")
        if latest:
            latest_id = str(latest.get("task_run_id") or "")
            self._write_index_value("session_latest_task_runs", session_id, latest_id)
            self._upsert_session_live_view(
                session_id=session_id,
                task_run_id=latest_id,
                updated_at=float(latest.get("updated_at") or latest.get("created_at") or time.time()),
            )
            return
        self._delete_index_value("session_latest_task_runs", session_id)
        self._delete_session_live_view(session_id)

    def _refresh_session_turn_indexes(self, session_id: str) -> None:
        turn_ids = []
        turn_payloads: list[dict[str, Any]] = []
        for turn_run_id in self._read_index_ids("session_turn_runs", session_id):
            payload = self._read_record("turn_runs", turn_run_id)
            if not payload:
                continue
            turn_ids.append(turn_run_id)
            turn_payloads.append(payload)
        self._write_or_delete_index_ids("session_turn_runs", session_id, turn_ids)
        latest = self._latest_record(turn_payloads, id_field="turn_run_id")
        if latest:
            self._write_index_value("session_latest_turn_runs", session_id, str(latest.get("turn_run_id") or ""))
            return
        self._delete_index_value("session_latest_turn_runs", session_id)

    @staticmethod
    def _latest_record(payloads: list[dict[str, Any]], *, id_field: str) -> dict[str, Any]:
        candidates = [payload for payload in payloads if str(payload.get(id_field) or "").strip()]
        if not candidates:
            return {}
        return max(
            candidates,
            key=lambda payload: (
                float(payload.get("updated_at") or 0.0),
                float(payload.get("created_at") or 0.0),
            ),
        )

    def _snapshot_without_task_runs(self, snapshot: dict[str, Any], task_run_ids: set[str]) -> tuple[dict[str, Any], dict[str, int]]:
        pruned = self._empty_snapshot()
        counts: dict[str, int] = {}
        task_record_buckets = {
            "task_runs",
            "agent_runs",
            "agent_run_results",
            "subagent_messages",
            "worker_spawn_requests",
            "worker_spawn_results",
            "supervision_records",
            "task_run_summaries",
        }
        for bucket in self._record_buckets():
            source = dict(snapshot.get(bucket) or {})
            kept: dict[str, Any] = {}
            for key, value in source.items():
                if not isinstance(value, dict):
                    continue
                task_run_id = str(value.get("task_run_id") or value.get("observed_task_run_id") or "")
                if bucket == "project_runtime_statuses":
                    active_task_run_id = str(value.get("active_task_run_id") or "")
                    if active_task_run_id in task_run_ids:
                        value = {
                            **value,
                            "active_task_run_id": "",
                            "active_run_status": "",
                            "project_runtime_status": "watching",
                            "active_blocker": {},
                            "recovery_state": {},
                        }
                        counts["project_runtime_status_task_refs"] = counts.get("project_runtime_status_task_refs", 0) + 1
                should_delete = bucket in task_record_buckets and task_run_id in task_run_ids
                if should_delete:
                    counts[bucket] = counts.get(bucket, 0) + 1
                    continue
                kept[str(key)] = value
            pruned[bucket] = kept
        self._rebuild_indexes(pruned)
        return pruned, counts

    def _snapshot_without_turn_runs(self, snapshot: dict[str, Any], turn_run_ids: set[str]) -> tuple[dict[str, Any], dict[str, int]]:
        pruned = self._empty_snapshot()
        counts: dict[str, int] = {}
        for bucket in self._record_buckets():
            source = dict(snapshot.get(bucket) or {})
            kept: dict[str, Any] = {}
            for key, value in source.items():
                if not isinstance(value, dict):
                    continue
                turn_run_id = str(value.get("turn_run_id") or "")
                if bucket == "turn_runs" and turn_run_id in turn_run_ids:
                    counts[bucket] = counts.get(bucket, 0) + 1
                    continue
                kept[str(key)] = value
            pruned[bucket] = kept
        self._rebuild_indexes(pruned)
        return pruned, counts

    def _rebuild_indexes(self, snapshot: dict[str, Any]) -> None:
        for bucket in self._list_index_buckets():
            snapshot[bucket] = {}
        for bucket in self._value_index_buckets():
            snapshot[bucket] = {}
        for task_run in dict(snapshot.get("task_runs") or {}).values():
            if not isinstance(task_run, dict):
                continue
            task_run_id = str(task_run.get("task_run_id") or "")
            session_id = str(task_run.get("session_id") or "")
            if task_run_id and session_id:
                self._snapshot_append_index(snapshot, "sessions", session_id, task_run_id)
                self._snapshot_maybe_latest_task(snapshot, "session_latest_task_runs", session_id, task_run_id, float(task_run.get("updated_at") or 0.0), "task_runs")
        for turn_run in dict(snapshot.get("turn_runs") or {}).values():
            if not isinstance(turn_run, dict):
                continue
            turn_run_id = str(turn_run.get("turn_run_id") or "")
            session_id = str(turn_run.get("session_id") or "")
            if turn_run_id and session_id:
                self._snapshot_append_index(snapshot, "session_turn_runs", session_id, turn_run_id)
                self._snapshot_maybe_latest_task(snapshot, "session_latest_turn_runs", session_id, turn_run_id, float(turn_run.get("updated_at") or 0.0), "turn_runs")
        for agent_run in dict(snapshot.get("agent_runs") or {}).values():
            if isinstance(agent_run, dict):
                self._snapshot_append_index(snapshot, "task_agent_runs", str(agent_run.get("task_run_id") or ""), str(agent_run.get("agent_run_id") or ""))
        for result in dict(snapshot.get("agent_run_results") or {}).values():
            if isinstance(result, dict):
                self._snapshot_append_index(snapshot, "task_agent_run_results", str(result.get("task_run_id") or ""), str(result.get("agent_run_result_id") or ""))
        for message in dict(snapshot.get("subagent_messages") or {}).values():
            if isinstance(message, dict):
                self._snapshot_append_index(snapshot, "task_subagent_messages", str(message.get("task_run_id") or ""), str(message.get("message_id") or ""))
                self._snapshot_append_index(snapshot, "subagent_run_messages", str(message.get("subagent_run_ref") or ""), str(message.get("message_id") or ""))
        for request in dict(snapshot.get("worker_spawn_requests") or {}).values():
            if isinstance(request, dict):
                self._snapshot_append_index(snapshot, "task_worker_spawn_requests", str(request.get("task_run_id") or ""), str(request.get("spawn_request_id") or ""))
        for result in dict(snapshot.get("worker_spawn_results") or {}).values():
            if isinstance(result, dict):
                self._snapshot_append_index(snapshot, "task_worker_spawn_results", str(result.get("task_run_id") or ""), str(result.get("spawn_result_id") or ""))
        for ledger in dict(snapshot.get("project_progress_ledgers") or {}).values():
            if isinstance(ledger, dict):
                self._snapshot_append_index(snapshot, "session_projects", str(ledger.get("session_id") or ""), str(ledger.get("project_id") or ""))
                self._snapshot_set_value(snapshot, "graph_project_index", str(ledger.get("graph_id") or ""), str(ledger.get("project_id") or ""))
        for record in dict(snapshot.get("supervision_records") or {}).values():
            if isinstance(record, dict):
                self._snapshot_append_index(snapshot, "project_supervision_records", str(record.get("project_id") or ""), str(record.get("supervision_record_id") or ""))
                self._snapshot_append_index(snapshot, "task_supervision_records", str(record.get("observed_task_run_id") or ""), str(record.get("supervision_record_id") or ""))
        for status in dict(snapshot.get("project_runtime_statuses") or {}).values():
            if isinstance(status, dict):
                self._snapshot_set_value(snapshot, "session_active_project_status", str(status.get("session_id") or ""), str(status.get("project_id") or ""))
                self._snapshot_set_value(snapshot, "task_project_status", str(status.get("active_task_run_id") or ""), str(status.get("project_id") or ""))

    @staticmethod
    def _snapshot_append_index(snapshot: dict[str, Any], bucket: str, index_id: str, value: str) -> None:
        if not index_id or not value:
            return
        items = list(dict(snapshot.get(bucket) or {}).get(index_id) or [])
        if value not in items:
            items.append(value)
        snapshot.setdefault(bucket, {})[index_id] = items

    @staticmethod
    def _snapshot_set_value(snapshot: dict[str, Any], bucket: str, index_id: str, value: str) -> None:
        if index_id and value:
            snapshot.setdefault(bucket, {})[index_id] = value

    def _snapshot_maybe_latest_task(
        self,
        snapshot: dict[str, Any],
        bucket: str,
        index_id: str,
        record_id: str,
        updated_at: float,
        record_bucket: str,
    ) -> None:
        if not index_id or not record_id:
            return
        current_id = str(dict(snapshot.get(bucket) or {}).get(index_id) or "")
        current = dict(snapshot.get(record_bucket) or {}).get(current_id) or {}
        current_updated = float(current.get("updated_at") or current.get("created_at") or 0.0)
        if not current_id or updated_at >= current_updated:
            snapshot.setdefault(bucket, {})[index_id] = record_id

    def _compact_task_run_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        compacted = dict(payload)
        diagnostics = dict(compacted.get("diagnostics") or {})
        object_id = str(compacted.get("task_run_id") or "")
        if graph_config := dict(diagnostics.get("graph_config") or diagnostics.get("graph_config_payload") or {}):
            diagnostics["graph_config_ref"] = self.runtime_objects.put_json_once(
                "graph_configs",
                object_id,
                graph_config,
            )
            diagnostics["graph_config_summary"] = _graph_config_summary(graph_config)
            diagnostics.pop("graph_config", None)
            diagnostics.pop("graph_config_payload", None)
        if graph_result := dict(diagnostics.get("graph_result") or {}):
            diagnostics["graph_result_ref"] = self.runtime_objects.put_json_once(
                "graph_results",
                object_id,
                graph_result,
            )
            diagnostics["graph_result_summary"] = _graph_result_summary(graph_result)
            diagnostics.pop("graph_result", None)
        compacted["diagnostics"] = diagnostics
        return compacted

    def _read(self) -> dict[str, Any]:
        snapshot = self._empty_snapshot()
        for bucket in self._record_buckets():
            snapshot[bucket] = self._read_record_bucket(bucket)
        for bucket in self._list_index_buckets():
            snapshot[bucket] = self._read_index_bucket(bucket)
        for bucket in self._value_index_buckets():
            snapshot[bucket] = self._read_index_bucket(bucket)
        snapshot["updated_at"] = float(self._read_meta().get("updated_at") or 0.0)
        return snapshot

    def _write_snapshot_payload(self, payload: dict[str, Any]) -> None:
        for bucket in self._record_buckets():
            for key, value in dict(payload.get(bucket) or {}).items():
                if isinstance(value, dict):
                    self._write_record(bucket, str(key), value)
        for key, value in dict(payload.get("task_runs") or {}).items():
            if isinstance(value, dict):
                self._write_record("task_run_summaries", str(key), _task_run_monitor_summary_payload(value))
        for bucket in self._list_index_buckets():
            for key, value in dict(payload.get(bucket) or {}).items():
                if isinstance(value, list):
                    self._write_index_value(bucket, str(key), list(value))
        for bucket in self._value_index_buckets():
            for key, value in dict(payload.get(bucket) or {}).items():
                if value:
                    self._write_index_value(bucket, str(key), str(value))
        if not dict(payload.get("session_latest_task_runs") or {}):
            latest_task_runs: dict[str, dict[str, Any]] = {}
            for value in dict(payload.get("task_runs") or {}).values():
                if not isinstance(value, dict):
                    continue
                session_id = str(value.get("session_id") or "")
                task_run_id = str(value.get("task_run_id") or "")
                if not session_id or not task_run_id:
                    continue
                created = float(value.get("updated_at") or 0.0)
                current = latest_task_runs.get(session_id)
                if current is None or created >= float(current.get("updated_at") or 0.0):
                    latest_task_runs[session_id] = {"task_run_id": task_run_id, "updated_at": created}
            for session_id, value in latest_task_runs.items():
                self._write_index_value("session_latest_task_runs", session_id, str(value.get("task_run_id") or ""))
    def _ensure_storage_ready(self) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            meta = self._read_json(self.meta_path, {})
            if meta:
                return
            has_sharded_state = any((self.index_dir / bucket).exists() for bucket in self._all_bucket_names())
            if self.index_path.exists():
                payload = self._read_json(self.index_path, self._empty_snapshot())
                self._write_snapshot_payload(payload)
                backup_dir = self.root_dir / "migration_backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup_path = backup_dir / f"state_index.pre_shard.{time.strftime('%Y%m%d-%H%M%S')}.json"
                os.replace(self.index_path, backup_path)
                self._touch_meta(
                    updated_at=float(payload.get("updated_at") or time.time()),
                    migrated_from=str(backup_path),
                )
                return
            if has_sharded_state:
                self._touch_meta()
                return
            self._touch_meta()

    def _touch_meta(self, *, updated_at: float | None = None, migrated_from: str = "") -> None:
        current = self._read_json(self.meta_path, {})
        payload = {
            "version": 2,
            "storage_mode": "sharded_runtime_state_index",
            "updated_at": float(updated_at if updated_at is not None else time.time()),
            "migrated_from": migrated_from or str(current.get("migrated_from") or ""),
            "authority": "orchestration.runtime_state_index",
        }
        self._atomic_write_path(self.meta_path, payload)

    def _read_meta(self) -> dict[str, Any]:
        return self._read_json(self.meta_path, {})

    def _read_record(self, bucket: str, record_id: str) -> dict[str, Any]:
        return self._read_json(self._bucket_record_path(bucket, record_id), {})

    def _read_selected_records(self, bucket: str, record_ids: list[str]) -> dict[str, Any]:
        return {
            record_id: payload
            for record_id in record_ids
            if (payload := self._read_record(bucket, record_id))
        }

    def _read_task_run_summary_payloads(self, task_run_ids: list[str]) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for task_run_id in task_run_ids:
            normalized = str(task_run_id or "").strip()
            if not normalized:
                continue
            summary = self._read_record("task_run_summaries", normalized)
            if summary:
                payloads.append(summary)
                continue
            source = self._read_record("task_runs", normalized)
            if not source:
                continue
            summary = _task_run_monitor_summary_payload(source)
            if summary:
                self._write_record("task_run_summaries", normalized, summary)
                payloads.append(summary)
        return payloads

    def _read_record_bucket(self, bucket: str) -> dict[str, Any]:
        base = self.index_dir / bucket
        if not base.exists():
            return {}
        results: dict[str, Any] = {}
        for path in sorted(base.glob("*.json")):
            if path.name == "meta.json":
                continue
            payload = self._read_json(path, {})
            if payload:
                results[self._record_identity(bucket, payload, path.stem)] = payload
        return results

    def _write_record(self, bucket: str, record_id: str, payload: dict[str, Any]) -> None:
        self._atomic_write_path(self._bucket_record_path(bucket, record_id), payload)

    def _delete_record(self, bucket: str, record_id: str) -> bool:
        path = self._bucket_record_path(bucket, record_id)
        if not path.exists():
            return False
        path.unlink(missing_ok=True)
        return True

    def _read_index_ids(self, bucket: str, index_id: str) -> list[str]:
        value = self._read_index_value(bucket, index_id)
        return [str(item) for item in list(value or []) if str(item)]

    def _append_index_id(self, bucket: str, index_id: str, value: str) -> None:
        items = self._read_index_ids(bucket, index_id)
        if value not in items:
            items.append(value)
        self._write_index_value(bucket, index_id, items)

    def _write_or_delete_index_ids(self, bucket: str, index_id: str, values: list[str]) -> None:
        deduped = [item for item in dict.fromkeys(str(value).strip() for value in values) if item]
        if deduped:
            self._write_index_value(bucket, index_id, deduped)
            return
        self._delete_index_value(bucket, index_id)

    def _remove_index_id(self, bucket: str, index_id: str, value: str) -> None:
        normalized = str(value or "").strip()
        if not normalized:
            return
        items = self._read_index_ids(bucket, index_id)
        next_items = [item for item in items if item != normalized]
        if next_items != items:
            self._write_or_delete_index_ids(bucket, index_id, next_items)

    def _delete_index_value(self, bucket: str, index_id: str) -> bool:
        path = self._bucket_record_path(bucket, index_id)
        if not path.exists():
            return False
        path.unlink(missing_ok=True)
        return True

    def _sync_active_executor_task_run_id(self, task_run_id: str, payload: dict[str, Any]) -> None:
        if _is_active_executor_task_run_payload(payload):
            self._append_index_id("active_executor_task_runs", ACTIVE_EXECUTOR_TASK_RUN_INDEX_ID, task_run_id)
            return
        self._remove_index_id("active_executor_task_runs", ACTIVE_EXECUTOR_TASK_RUN_INDEX_ID, task_run_id)

    def _sync_graph_node_task_run_id(self, task_run_id: str, payload: dict[str, Any]) -> None:
        identity = _graph_node_task_identity(payload)
        if not identity:
            return
        graph_run_id = str(identity.get("graph_run_id") or "").strip()
        work_order_id = str(identity.get("work_order_id") or "").strip()
        if graph_run_id:
            self._append_index_id("graph_node_task_runs_by_graph_run", graph_run_id, task_run_id)
        if work_order_id:
            self._write_index_value("graph_node_task_run_by_work_order", work_order_id, task_run_id)

    def _upsert_global_recent_task_run(self, task_run_id: str, *, updated_at: float) -> None:
        normalized = str(task_run_id or "").strip()
        if not normalized:
            return
        existing_ids = [item for item in self._read_index_ids("global_recent_task_runs", GLOBAL_RECENT_TASK_RUN_INDEX_ID) if item != normalized]
        candidates = [normalized, *existing_ids[: GLOBAL_RECENT_TASK_RUN_LIMIT - 1]]
        scored: list[tuple[float, str]] = []
        for candidate in candidates:
            if candidate == normalized:
                scored.append((float(updated_at or time.time()), candidate))
                continue
            payload = self._read_record("task_runs", candidate)
            if not payload:
                continue
            scored.append((float(payload.get("updated_at") or payload.get("created_at") or 0.0), candidate))
        scored.sort(key=lambda item: item[0], reverse=True)
        self._write_global_recent_task_run_ids([item[1] for item in scored[:GLOBAL_RECENT_TASK_RUN_LIMIT]])

    def _rebuild_global_recent_task_run_index(self, *, limit: int = GLOBAL_RECENT_TASK_RUN_LIMIT) -> list[str]:
        requested = max(1, min(int(limit or GLOBAL_RECENT_TASK_RUN_LIMIT), GLOBAL_RECENT_TASK_RUN_LIMIT))
        base = self.index_dir / "task_runs"
        if not base.exists():
            self._write_global_recent_task_run_ids([])
            return []
        candidates: list[tuple[float, Path]] = []
        for path in base.glob("*.json"):
            if path.name == "meta.json":
                continue
            try:
                candidates.append((float(path.stat().st_mtime), path))
            except OSError:
                continue
        candidates.sort(key=lambda item: item[0], reverse=True)
        ids: list[str] = []
        for _mtime, path in candidates[:requested]:
            payload = self._read_json(path, {})
            task_run_id = str(payload.get("task_run_id") or "")
            if task_run_id:
                ids.append(task_run_id)
        self._write_global_recent_task_run_ids(ids)
        return ids

    def _write_global_recent_task_run_ids(self, task_run_ids: list[str]) -> None:
        deduped = [item for item in dict.fromkeys(str(value).strip() for value in task_run_ids) if item]
        self._write_index_value("global_recent_task_runs", GLOBAL_RECENT_TASK_RUN_INDEX_ID, deduped[:GLOBAL_RECENT_TASK_RUN_LIMIT])

    def _maybe_write_latest_ref(self, bucket: str, index_id: str, record_id: str, *, updated_at: float) -> None:
        current_id = str(self._read_index_value(bucket, index_id) or "")
        if current_id:
            record_bucket = "turn_runs" if bucket == "session_latest_turn_runs" else "task_runs"
            current_payload = self._read_record(record_bucket, current_id) if bucket.startswith("session_") else {}
            if float(current_payload.get("updated_at") or 0.0) > updated_at:
                return
        self._write_index_value(bucket, index_id, record_id)

    def _read_index_bucket(self, bucket: str) -> dict[str, Any]:
        base = self.index_dir / bucket
        if not base.exists():
            return {}
        results: dict[str, Any] = {}
        for path in sorted(base.glob("*.json")):
            if path.name == "meta.json":
                continue
            results[path.stem] = self._read_json(path, [])
        return results

    def _read_index_value(self, bucket: str, index_id: str) -> Any:
        default: Any = [] if bucket in self._list_index_buckets() else ""
        if bucket in self._value_index_buckets():
            default = ""
        return self._read_json(self._bucket_record_path(bucket, index_id), default)

    def _write_index_value(self, bucket: str, index_id: str, payload: Any) -> None:
        self._atomic_write_path(self._bucket_record_path(bucket, index_id), payload)

    def _deleted_session_path(self, session_id: str) -> Path:
        return self.deleted_sessions_dir / f"{_safe_index_key(session_id)}.json"

    def _deleted_task_run_path(self, task_run_id: str) -> Path:
        return self.deleted_task_runs_dir / f"{_safe_index_key(task_run_id)}.json"

    def _session_deleted_unlocked(self, session_id: str) -> bool:
        normalized = str(session_id or "").strip()
        return bool(normalized) and self._deleted_session_path(normalized).exists()

    def _task_run_deleted_unlocked(self, task_run_id: str) -> bool:
        normalized = str(task_run_id or "").strip()
        return bool(normalized) and self._deleted_task_run_path(normalized).exists()

    def _clear_bucket_layout(self) -> None:
        for bucket in self._all_bucket_names():
            bucket_dir = self.index_dir / bucket
            if not bucket_dir.exists():
                continue
            for path in bucket_dir.glob("*.json"):
                path.unlink(missing_ok=True)
        for path in self.views_dir.glob("*.json"):
            path.unlink(missing_ok=True)

    def _bucket_record_path(self, bucket: str, record_id: str) -> Path:
        return self.index_dir / bucket / f"{_safe_index_key(record_id)}.json"

    def _session_live_view_path(self, session_id: str) -> Path:
        return self.views_dir / f"{_safe_index_key(session_id)}.json"

    def _read_session_live_view(self, session_id: str) -> dict[str, Any]:
        return self._read_json(self._session_live_view_path(session_id), {})

    def _delete_session_live_view(self, session_id: str) -> bool:
        path = self._session_live_view_path(session_id)
        if not path.exists():
            return False
        path.unlink(missing_ok=True)
        return True

    def _upsert_session_live_view(
        self,
        *,
        session_id: str,
        task_run_id: str,
        updated_at: float,
    ) -> None:
        current = self._read_session_live_view(session_id)
        task_run_count = len(self._read_index_ids("sessions", session_id))
        latest_task_run_id = str(
            task_run_id
            or current.get("latest_task_run_id")
            or self._read_index_value("session_latest_task_runs", session_id)
            or ""
        )
        payload = {
            "session_id": session_id,
            "task_run_count": task_run_count,
            "latest_task_run_id": latest_task_run_id,
            "updated_at": float(updated_at or current.get("updated_at") or time.time()),
            "authority": "orchestration.runtime_state_index.session_live_view",
        }
        self._atomic_write_path(self._session_live_view_path(session_id), payload)

    @staticmethod
    def _record_identity(bucket: str, payload: dict[str, Any], fallback: str) -> str:
        key_field_by_bucket = {
            "task_runs": "task_run_id",
            "turn_runs": "turn_run_id",
            "agent_runs": "agent_run_id",
            "agent_run_results": "agent_run_result_id",
            "subagent_messages": "message_id",
            "worker_spawn_requests": "spawn_request_id",
            "worker_spawn_results": "spawn_result_id",
            "project_progress_ledgers": "project_id",
            "supervision_records": "supervision_record_id",
            "project_runtime_statuses": "project_id",
            "task_run_summaries": "task_run_id",
        }
        field = key_field_by_bucket.get(bucket, "")
        return str(payload.get(field) or fallback)

    @staticmethod
    def _record_buckets() -> tuple[str, ...]:
        return (
            "task_runs",
            "turn_runs",
            "agent_runs",
            "agent_run_results",
            "subagent_messages",
            "worker_spawn_requests",
            "worker_spawn_results",
            "project_progress_ledgers",
            "supervision_records",
            "project_runtime_statuses",
            "task_run_summaries",
        )

    @staticmethod
    def _list_index_buckets() -> tuple[str, ...]:
        return (
            "sessions",
            "session_turn_runs",
            "task_agent_runs",
            "task_agent_run_results",
            "task_subagent_messages",
            "subagent_run_messages",
            "task_worker_spawn_requests",
            "task_worker_spawn_results",
            "session_projects",
            "global_recent_task_runs",
            "active_executor_task_runs",
            "graph_node_task_runs_by_graph_run",
            "project_supervision_records",
            "task_supervision_records",
        )

    @staticmethod
    def _value_index_buckets() -> tuple[str, ...]:
        return (
            "session_latest_task_runs",
            "session_latest_turn_runs",
            "graph_project_index",
            "session_active_project_status",
            "task_project_status",
            "graph_node_task_run_by_work_order",
        )

    @classmethod
    def _all_bucket_names(cls) -> tuple[str, ...]:
        return cls._record_buckets() + cls._list_index_buckets() + cls._value_index_buckets()

    @staticmethod
    def _empty_snapshot() -> dict[str, Any]:
        return {
            "task_runs": {},
            "turn_runs": {},
            "sessions": {},
            "session_turn_runs": {},
            "agent_runs": {},
            "task_agent_runs": {},
            "agent_run_results": {},
            "task_agent_run_results": {},
            "subagent_messages": {},
            "task_subagent_messages": {},
            "subagent_run_messages": {},
            "worker_spawn_requests": {},
            "task_worker_spawn_requests": {},
            "worker_spawn_results": {},
            "task_worker_spawn_results": {},
            "project_progress_ledgers": {},
            "supervision_records": {},
            "project_runtime_statuses": {},
            "task_run_summaries": {},
            "session_projects": {},
            "global_recent_task_runs": {},
            "active_executor_task_runs": {},
            "graph_node_task_runs_by_graph_run": {},
            "project_supervision_records": {},
            "task_supervision_records": {},
            "session_latest_task_runs": {},
            "session_latest_turn_runs": {},
            "graph_project_index": {},
            "session_active_project_status": {},
            "task_project_status": {},
            "graph_node_task_run_by_work_order": {},
            "updated_at": 0.0,
        }

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return default

    def _atomic_write(self, payload: dict[str, Any]) -> None:
        self.replace_snapshot(payload)

    @staticmethod
    def _atomic_write_path(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        with _STATE_INDEX_WRITE_LOCK:
            tmp.write_text(text, encoding="utf-8")
            last_error: OSError | None = None
            for attempt in range(16):
                try:
                    os.replace(tmp, path)
                    return
                except PermissionError as exc:
                    last_error = exc
                    time.sleep(min(0.75, 0.05 * (attempt + 1)))
            try:
                path.write_text(text, encoding="utf-8")
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                return
            except OSError as exc:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                if last_error is not None:
                    raise last_error from exc
                raise


def _task_run_from_payload(payload: dict[str, Any]) -> TaskRun:
    return TaskRun(
        task_run_id=str(payload.get("task_run_id") or ""),
        session_id=str(payload.get("session_id") or ""),
        task_id=str(payload.get("task_id") or ""),
        task_contract_ref=str(payload.get("task_contract_ref") or ""),
        owner_agent_seat_id=str(payload.get("owner_agent_seat_id") or "main"),
        agent_id=str(payload.get("agent_id") or "agent:0"),
        agent_profile_id=str(payload.get("agent_profile_id") or "main_interactive_agent"),
        execution_runtime_kind=str(payload.get("execution_runtime_kind") or ""),
        status=_canonical_task_run_status(payload.get("status", "created")),
        created_at=float(payload.get("created_at") or 0.0),
        updated_at=float(payload.get("updated_at") or 0.0),
        latest_event_offset=int(payload.get("latest_event_offset", -1)),
        latest_checkpoint_ref=str(payload.get("latest_checkpoint_ref") or ""),
        terminal_reason=payload.get("terminal_reason", ""),
        diagnostics=dict(payload.get("diagnostics") or {}),
    )


def _canonical_task_run_status(value: Any) -> str:
    status = str(value or "created").strip()
    if status not in CANONICAL_TASK_RUN_STATUSES:
        raise ValueError(f"TaskRun status is not canonical: {status}")
    return status


def _canonical_agent_run_status(value: Any) -> str:
    status = str(value or "pending").strip()
    if status not in CANONICAL_AGENT_RUN_STATUSES:
        raise ValueError(f"AgentRun status is not canonical: {status}")
    return status


def _task_run_monitor_summary_payload(payload: dict[str, Any]) -> dict[str, Any]:
    diagnostics = _task_run_monitor_diagnostics(dict(payload.get("diagnostics") or {}))
    return {
        "task_run_id": str(payload.get("task_run_id") or ""),
        "session_id": str(payload.get("session_id") or ""),
        "task_id": str(payload.get("task_id") or ""),
        "task_contract_ref": str(payload.get("task_contract_ref") or ""),
        "owner_agent_seat_id": str(payload.get("owner_agent_seat_id") or "main"),
        "agent_id": str(payload.get("agent_id") or "agent:0"),
        "agent_profile_id": str(payload.get("agent_profile_id") or "main_interactive_agent"),
        "execution_runtime_kind": str(payload.get("execution_runtime_kind") or ""),
        "status": _canonical_task_run_status(payload.get("status", "created")),
        "created_at": float(payload.get("created_at") or 0.0),
        "updated_at": float(payload.get("updated_at") or 0.0),
        "latest_event_offset": int(payload.get("latest_event_offset", -1)),
        "latest_checkpoint_ref": str(payload.get("latest_checkpoint_ref") or ""),
        "terminal_reason": payload.get("terminal_reason", ""),
        "diagnostics": diagnostics,
        "authority": str(payload.get("authority") or "orchestration.task_run"),
        "summary_authority": TASK_RUN_SUMMARY_AUTHORITY,
    }


def _task_run_monitor_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in sorted(TASK_RUN_SUMMARY_DIAGNOSTIC_KEYS):
        if key in diagnostics:
            result[key] = _monitor_summary_value(diagnostics.get(key))
    for key in sorted(TASK_RUN_SUMMARY_DIAGNOSTIC_DICT_KEYS):
        if key not in diagnostics:
            continue
        if key == "contract":
            value = _monitor_contract_summary(dict(diagnostics.get(key) or {}))
        else:
            value = _monitor_summary_dict(dict(diagnostics.get(key) or {}))
        if value:
            result[key] = value
    return result


def _monitor_contract_summary(contract: dict[str, Any]) -> dict[str, Any]:
    allowed = ("user_visible_goal", "task_run_goal", "goal", "title")
    return {
        key: _monitor_summary_text(contract.get(key), limit=800)
        for key in allowed
        if _monitor_summary_text(contract.get(key), limit=800)
    }


def _monitor_summary_dict(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in payload.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        compacted = _monitor_summary_value(value)
        if compacted in ("", None, [], {}):
            continue
        result[normalized_key] = compacted
        if len(result) >= 40:
            break
    return result


def _monitor_summary_value(value: Any) -> Any:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return _monitor_summary_text(value, limit=1200)
    if isinstance(value, dict):
        return _monitor_summary_dict(value)
    if isinstance(value, (list, tuple)):
        result: list[Any] = []
        for item in value[:20]:
            compacted = _monitor_summary_value(item)
            if compacted not in ("", None, [], {}):
                result.append(compacted)
        return result
    return _monitor_summary_text(value, limit=400)


def _monitor_summary_text(value: Any, *, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _is_active_executor_task_run_payload(payload: dict[str, Any]) -> bool:
    if str(payload.get("execution_runtime_kind") or "") not in {"single_agent_task", "subagent_task"}:
        return False
    status = _canonical_task_run_status(payload.get("status") or "")
    if status in {"completed", "failed", "aborted"}:
        return False
    diagnostics = dict(payload.get("diagnostics") or {})
    origin = dict(diagnostics.get("origin") or {}) if isinstance(diagnostics.get("origin"), dict) else {}
    origin_kind = str(origin.get("origin_kind") or diagnostics.get("origin_kind") or "").strip()
    if origin_kind == "graph_node_assigned":
        return False
    if diagnostics.get("graph_run_id") or diagnostics.get("graph_config_id") or diagnostics.get("graph_node_id"):
        return False
    executor_status = str(diagnostics.get("executor_status") or "").strip()
    if executor_status in {"scheduled", "running", "retrying", "recovering"}:
        return True
    return status == "running"


def _graph_node_task_identity(payload: dict[str, Any]) -> dict[str, str]:
    if not isinstance(payload, dict) or str(payload.get("execution_runtime_kind") or "") not in {"single_agent_task", "subagent_task"}:
        return {}
    diagnostics = dict(payload.get("diagnostics") or {})
    origin = dict(diagnostics.get("origin") or {}) if isinstance(diagnostics.get("origin"), dict) else {}
    origin_kind = str(payload.get("origin_kind") or diagnostics.get("origin_kind") or origin.get("origin_kind") or "").strip()
    if origin_kind != "graph_node_assigned":
        return {}
    graph_run_id = str(
        payload.get("graph_run_id")
        or diagnostics.get("graph_run_id")
        or origin.get("graph_run_id")
        or origin.get("parent_run_ref")
        or ""
    ).strip()
    work_order_id = str(
        payload.get("graph_work_order_id")
        or diagnostics.get("graph_work_order_id")
        or origin.get("origin_ref")
        or ""
    ).strip()
    node_id = str(payload.get("graph_node_id") or diagnostics.get("graph_node_id") or diagnostics.get("node_id") or origin.get("node_id") or "").strip()
    if not graph_run_id or not work_order_id:
        return {}
    return {
        "graph_run_id": graph_run_id,
        "work_order_id": work_order_id,
        "node_id": node_id,
    }


def _turn_run_from_payload(payload: dict[str, Any]) -> TurnRun:
    return TurnRun(
        turn_run_id=str(payload.get("turn_run_id") or ""),
        session_id=str(payload.get("session_id") or ""),
        turn_id=str(payload.get("turn_id") or ""),
        agent_profile_id=str(payload.get("agent_profile_id") or "main_interactive_agent"),
        execution_runtime_kind=str(payload.get("execution_runtime_kind") or "single_agent_turn"),
        status=payload.get("status", "running"),
        created_at=float(payload.get("created_at") or 0.0),
        updated_at=float(payload.get("updated_at") or 0.0),
        latest_event_offset=int(payload.get("latest_event_offset", -1)),
        terminal_reason=payload.get("terminal_reason", ""),
        diagnostics=dict(payload.get("diagnostics") or {}),
    )


def _graph_config_summary(payload: dict[str, Any]) -> dict[str, Any]:
    nodes = list(payload.get("nodes") or [])
    edges = list(payload.get("edges") or [])
    modules = list(payload.get("modules") or [])
    return {
        "config_id": str(payload.get("config_id") or ""),
        "graph_id": str(payload.get("graph_id") or ""),
        "graph_title": str(payload.get("graph_title") or ""),
        "schema_version": str(payload.get("config_schema_version") or ""),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "module_count": len(modules),
        "content_hash": str(payload.get("content_hash") or ""),
        "status": str(payload.get("status") or ""),
    }


def _graph_result_summary(payload: dict[str, Any]) -> dict[str, Any]:
    outputs = dict(payload.get("outputs") or {})
    artifact_refs = list(payload.get("artifact_refs") or [])
    node_result_refs = list(payload.get("node_result_refs") or [])
    diagnostics = dict(payload.get("diagnostics") or {})
    return {
        "result_id": str(payload.get("result_id") or ""),
        "graph_run_id": str(payload.get("graph_run_id") or ""),
        "task_run_id": str(payload.get("task_run_id") or ""),
        "graph_id": str(payload.get("graph_id") or ""),
        "config_id": str(payload.get("config_id") or ""),
        "status": str(payload.get("status") or ""),
        "terminal_reason": str(payload.get("terminal_reason") or ""),
        "output_count": len(outputs),
        "artifact_ref_count": len(artifact_refs),
        "node_result_ref_count": len(node_result_refs),
        "diagnostic_keys": sorted(str(key) for key in diagnostics.keys())[:20],
        "created_at": float(payload.get("created_at") or 0.0),
    }


def _agent_run_from_payload(payload: dict[str, Any]) -> AgentRun:
    return AgentRun(
        agent_run_id=str(payload.get("agent_run_id") or ""),
        task_run_id=str(payload.get("task_run_id") or ""),
        agent_id=str(payload.get("agent_id") or ""),
        agent_profile_id=str(payload.get("agent_profile_id") or ""),
        role=str(payload.get("role") or "main_executor"),
        spawn_mode=str(payload.get("spawn_mode") or "single_agent"),
        context_scope=str(payload.get("context_scope") or "task_default"),
        execution_runtime_kind=str(payload.get("execution_runtime_kind") or ""),
        parent_agent_run_ref=str(payload.get("parent_agent_run_ref") or ""),
        status=_canonical_agent_run_status(payload.get("status", "pending")),
        latest_checkpoint_ref=str(payload.get("latest_checkpoint_ref") or ""),
        result_ref=str(payload.get("result_ref") or ""),
        created_at=float(payload.get("created_at") or 0.0),
        updated_at=float(payload.get("updated_at") or 0.0),
        diagnostics=dict(payload.get("diagnostics") or {}),
    )


def _agent_run_result_from_payload(payload: dict[str, Any]) -> AgentRunResult:
    return AgentRunResult(
        agent_run_result_id=str(payload.get("agent_run_result_id") or ""),
        agent_run_id=str(payload.get("agent_run_id") or ""),
        task_run_id=str(payload.get("task_run_id") or ""),
        agent_id=str(payload.get("agent_id") or ""),
        status=_canonical_agent_run_status(payload.get("status", "completed")),
        output_ref=str(payload.get("output_ref") or ""),
        summary=str(payload.get("summary") or ""),
        artifact_refs=tuple(str(item) for item in list(payload.get("artifact_refs") or []) if str(item)),
        created_at=float(payload.get("created_at") or 0.0),
        diagnostics=dict(payload.get("diagnostics") or {}),
    )


def _project_progress_ledger_from_payload(payload: dict[str, Any]) -> ProjectProgressLedger:
    committed_unit_refs = payload.get("committed_unit_refs")
    metric_receipts = payload.get("metric_receipts")
    return ProjectProgressLedger(
        ledger_id=str(payload.get("ledger_id") or payload.get("project_id") or ""),
        project_id=str(payload.get("project_id") or ""),
        session_id=str(payload.get("session_id") or ""),
        graph_id=str(payload.get("graph_id") or ""),
        project_title=str(payload.get("project_title") or ""),
        metric_label=str(payload.get("metric_label") or "units"),
        target_metric_total=int(payload.get("target_metric_total") or payload.get("target_words") or 0),
        committed_metric_total=int(payload.get("committed_metric_total") or payload.get("committed_words_total") or 0),
        committed_unit_count=int(payload.get("committed_unit_count") or 0),
        last_committed_unit_index=int(payload.get("last_committed_unit_index") or 0),
        committed_unit_refs=tuple(str(item) for item in list(committed_unit_refs or []) if str(item)),
        metric_receipts=tuple(dict(item) for item in list(metric_receipts or []) if isinstance(item, dict)),
        run_chain=tuple(str(item) for item in list(payload.get("run_chain") or []) if str(item)),
        latest_delivery_state=str(payload.get("latest_delivery_state") or ""),
        last_failure=dict(payload.get("last_failure") or {}),
        last_repair_action=dict(payload.get("last_repair_action") or {}),
        updated_at=float(payload.get("updated_at") or 0.0),
        created_at=float(payload.get("created_at") or 0.0),
    )


def _supervision_record_from_payload(payload: dict[str, Any]) -> SupervisionRecord:
    return SupervisionRecord(
        supervision_record_id=str(payload.get("supervision_record_id") or ""),
        supervision_session_id=str(payload.get("supervision_session_id") or ""),
        project_id=str(payload.get("project_id") or ""),
        observed_task_run_id=str(payload.get("observed_task_run_id") or ""),
        issue_type=str(payload.get("issue_type") or ""),
        issue_summary=str(payload.get("issue_summary") or ""),
        root_cause=str(payload.get("root_cause") or ""),
        repair_action=str(payload.get("repair_action") or ""),
        repair_result=str(payload.get("repair_result") or ""),
        followup_status=str(payload.get("followup_status") or "recorded"),
        created_at=float(payload.get("created_at") or 0.0),
        diagnostics=dict(payload.get("diagnostics") or {}),
    )


def _project_runtime_status_from_payload(payload: dict[str, Any]) -> ProjectRuntimeStatus:
    return ProjectRuntimeStatus(
        project_id=str(payload.get("project_id") or ""),
        session_id=str(payload.get("session_id") or ""),
        graph_id=str(payload.get("graph_id") or ""),
        project_title=str(payload.get("project_title") or ""),
        active_task_run_id=str(payload.get("active_task_run_id") or ""),
        active_run_status=str(payload.get("active_run_status") or ""),
        project_runtime_status=str(payload.get("project_runtime_status") or "watching"),
        metric_label=str(payload.get("metric_label") or "units"),
        completed_metric_total=int(payload.get("completed_metric_total") or payload.get("completed_words_total") or 0),
        target_metric_total=int(payload.get("target_metric_total") or payload.get("target_words") or 0),
        committed_unit_count=int(payload.get("committed_unit_count") or 0),
        last_committed_unit_index=int(payload.get("last_committed_unit_index") or 0),
        active_blocker=dict(payload.get("active_blocker") or {}),
        recovery_state=dict(payload.get("recovery_state") or {}),
        delivery_state=str(payload.get("delivery_state") or ""),
        latest_artifact_root=str(payload.get("latest_artifact_root") or ""),
        latest_event_offset=int(payload.get("latest_event_offset") or 0),
        latest_event_at=float(payload.get("latest_event_at") or 0.0),
        last_effective_output_at=float(payload.get("last_effective_output_at") or 0.0),
        updated_at=float(payload.get("updated_at") or 0.0),
    )


def _worker_spawn_request_from_payload(payload: dict[str, Any]) -> WorkerAgentSpawnRequest:
    return WorkerAgentSpawnRequest(
        spawn_request_id=str(payload.get("spawn_request_id") or ""),
        task_run_id=str(payload.get("task_run_id") or ""),
        parent_agent_run_ref=str(payload.get("parent_agent_run_ref") or ""),
        blueprint_id=str(payload.get("blueprint_id") or ""),
        requested_agent_name=str(payload.get("requested_agent_name") or ""),
        execution_runtime_kind=str(payload.get("execution_runtime_kind") or ""),
        context_scope=str(payload.get("context_scope") or ""),
        requested_by_agent_id=str(payload.get("requested_by_agent_id") or ""),
        spawn_reason=str(payload.get("spawn_reason") or ""),
        requested_at=float(payload.get("requested_at") or 0.0),
        diagnostics=dict(payload.get("diagnostics") or {}),
    )


def _worker_spawn_result_from_payload(payload: dict[str, Any]) -> WorkerAgentSpawnResult:
    return WorkerAgentSpawnResult(
        spawn_result_id=str(payload.get("spawn_result_id") or ""),
        spawn_request_id=str(payload.get("spawn_request_id") or ""),
        task_run_id=str(payload.get("task_run_id") or ""),
        parent_agent_run_ref=str(payload.get("parent_agent_run_ref") or ""),
        blueprint_id=str(payload.get("blueprint_id") or ""),
        spawned_agent_id=str(payload.get("spawned_agent_id") or ""),
        spawned_agent_run_ref=str(payload.get("spawned_agent_run_ref") or ""),
        spawned_agent_profile_id=str(payload.get("spawned_agent_profile_id") or ""),
        status=payload.get("status", "spawned"),
        created_at=float(payload.get("created_at") or 0.0),
        diagnostics=dict(payload.get("diagnostics") or {}),
    )


def _safe_index_key(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))[:180]
