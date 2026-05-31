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
    ProjectProgressLedger,
    ProjectRuntimeStatus,
    SupervisionRecord,
    TaskRun,
    TurnRun,
)
from harness.execution.delegation_models import (
    AgentDelegationRequest,
    AgentDelegationResult,
    delegation_request_from_dict,
    delegation_result_from_dict,
)
from agent_system.registry.worker_agent_blueprints import WorkerAgentSpawnRequest, WorkerAgentSpawnResult
from harness.agent_control.models import SubagentMessage, subagent_message_from_dict
from ..shared.runtime_object_store import RuntimeObjectStore


_STATE_INDEX_WRITE_LOCK = threading.RLock()


class RuntimeStateIndex:
    """Fast lookup index for latest runtime formal objects."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.index_path = self.root_dir / "state_index.json"
        self.index_dir = self.root_dir / "state_index"
        self.meta_path = self.index_dir / "meta.json"
        self.views_dir = self.root_dir / "runtime_views" / "session_live"
        self.runtime_objects = RuntimeObjectStore(self.root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.views_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_storage_ready()

    def upsert_task_run(self, task_run: TaskRun) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            payload = self._compact_task_run_payload(task_run.to_dict())
            self._write_record("task_runs", task_run.task_run_id, payload)
            self._append_index_id("sessions", task_run.session_id, task_run.task_run_id)
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
            self._touch_meta()

    def upsert_turn_run(self, turn_run: TurnRun) -> None:
        with _STATE_INDEX_WRITE_LOCK:
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

    def upsert_agent_run(self, agent_run: AgentRun) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._write_record("agent_runs", agent_run.agent_run_id, agent_run.to_dict())
            self._append_index_id("task_agent_runs", agent_run.task_run_id, agent_run.agent_run_id)
            self._touch_meta()

    def upsert_agent_run_result(self, result: AgentRunResult) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._write_record("agent_run_results", result.agent_run_result_id, result.to_dict())
            self._append_index_id("task_agent_run_results", result.task_run_id, result.agent_run_result_id)
            self._touch_meta()

    def upsert_subagent_message(self, message: SubagentMessage) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._write_record("subagent_messages", message.message_id, message.to_dict())
            self._append_index_id("task_subagent_messages", message.task_run_id, message.message_id)
            self._append_index_id("subagent_run_messages", message.subagent_run_ref, message.message_id)
            self._touch_meta()

    def upsert_worker_spawn_request(self, request: WorkerAgentSpawnRequest) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._write_record("worker_spawn_requests", request.spawn_request_id, request.to_dict())
            self._append_index_id("task_worker_spawn_requests", request.task_run_id, request.spawn_request_id)
            self._touch_meta()

    def upsert_worker_spawn_result(self, result: WorkerAgentSpawnResult) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._write_record("worker_spawn_results", result.spawn_result_id, result.to_dict())
            self._append_index_id("task_worker_spawn_results", result.task_run_id, result.spawn_result_id)
            self._touch_meta()

    def upsert_agent_delegation_request(self, request: AgentDelegationRequest) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._write_record("agent_delegation_requests", request.request_id, request.to_dict())
            self._append_index_id("task_agent_delegation_requests", request.task_run_id, request.request_id)
            self._touch_meta()

    def upsert_agent_delegation_result(self, result: AgentDelegationResult) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._write_record("agent_delegation_results", result.result_id, result.to_dict())
            self._append_index_id("task_agent_delegation_results", result.task_run_id, result.result_id)
            self._touch_meta()

    def upsert_project_progress_ledger(self, ledger: ProjectProgressLedger) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._write_record("project_progress_ledgers", ledger.project_id, ledger.to_dict())
            self._append_index_id("session_projects", ledger.session_id, ledger.project_id)
            self._write_index_value("graph_project_index", ledger.graph_id, ledger.project_id)
            self._touch_meta(updated_at=float(ledger.updated_at or time.time()))

    def upsert_supervision_record(self, record: SupervisionRecord) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._write_record("supervision_records", record.supervision_record_id, record.to_dict())
            self._append_index_id("project_supervision_records", record.project_id, record.supervision_record_id)
            if record.observed_task_run_id:
                self._append_index_id("task_supervision_records", record.observed_task_run_id, record.supervision_record_id)
            self._touch_meta(updated_at=float(record.created_at or time.time()))

    def upsert_project_runtime_status(self, status: ProjectRuntimeStatus) -> None:
        with _STATE_INDEX_WRITE_LOCK:
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

    def list_session_task_runs(self, session_id: str) -> list[TaskRun]:
        task_runs = self._read_record_bucket("task_runs")
        ids = self._read_index_ids("sessions", session_id)
        return [_task_run_from_payload(task_runs[item]) for item in ids if item in task_runs]

    def list_session_turn_runs(self, session_id: str) -> list[TurnRun]:
        turn_runs = self._read_record_bucket("turn_runs")
        ids = self._read_index_ids("session_turn_runs", session_id)
        return [_turn_run_from_payload(turn_runs[item]) for item in ids if item in turn_runs]

    def list_task_agent_runs(self, task_run_id: str) -> list[AgentRun]:
        agent_runs = self._read_record_bucket("agent_runs")
        ids = self._read_index_ids("task_agent_runs", task_run_id)
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
        records = self._read_record_bucket("supervision_records")
        ids = self._read_index_ids("project_supervision_records", project_id)
        return [_supervision_record_from_payload(records[item]) for item in ids if item in records]

    def list_task_supervision_records(self, task_run_id: str) -> list[SupervisionRecord]:
        records = self._read_record_bucket("supervision_records")
        ids = self._read_index_ids("task_supervision_records", task_run_id)
        return [_supervision_record_from_payload(records[item]) for item in ids if item in records]

    def list_task_agent_run_results(self, task_run_id: str) -> list[AgentRunResult]:
        results = self._read_record_bucket("agent_run_results")
        ids = self._read_index_ids("task_agent_run_results", task_run_id)
        return [_agent_run_result_from_payload(results[item]) for item in ids if item in results]

    def list_task_subagent_messages(self, task_run_id: str) -> list[SubagentMessage]:
        messages = self._read_record_bucket("subagent_messages")
        ids = self._read_index_ids("task_subagent_messages", task_run_id)
        return [subagent_message_from_dict(messages[item]) for item in ids if item in messages]

    def list_subagent_run_messages(self, subagent_run_ref: str) -> list[SubagentMessage]:
        messages = self._read_record_bucket("subagent_messages")
        ids = self._read_index_ids("subagent_run_messages", subagent_run_ref)
        return [subagent_message_from_dict(messages[item]) for item in ids if item in messages]

    def list_task_worker_spawn_requests(self, task_run_id: str) -> list[WorkerAgentSpawnRequest]:
        requests = self._read_record_bucket("worker_spawn_requests")
        ids = self._read_index_ids("task_worker_spawn_requests", task_run_id)
        return [_worker_spawn_request_from_payload(requests[item]) for item in ids if item in requests]

    def list_task_worker_spawn_results(self, task_run_id: str) -> list[WorkerAgentSpawnResult]:
        results = self._read_record_bucket("worker_spawn_results")
        ids = self._read_index_ids("task_worker_spawn_results", task_run_id)
        return [_worker_spawn_result_from_payload(results[item]) for item in ids if item in results]

    def list_task_agent_delegation_requests(self, task_run_id: str) -> list[AgentDelegationRequest]:
        requests = self._read_record_bucket("agent_delegation_requests")
        ids = self._read_index_ids("task_agent_delegation_requests", task_run_id)
        return [delegation_request_from_dict(requests[item]) for item in ids if item in requests]

    def list_task_agent_delegation_results(self, task_run_id: str) -> list[AgentDelegationResult]:
        results = self._read_record_bucket("agent_delegation_results")
        ids = self._read_index_ids("task_agent_delegation_results", task_run_id)
        return [delegation_result_from_dict(results[item]) for item in ids if item in results]

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
            snapshot = self._read()
            existing = targets.intersection(set(dict(snapshot.get("task_runs") or {}).keys()))
            if not existing:
                return {
                    "authority": "orchestration.runtime_state_index.prune_task_runs",
                    "requested_task_run_ids": sorted(targets),
                    "deleted_task_run_ids": [],
                    "deleted_counts": {},
                }
            pruned, counts = self._snapshot_without_task_runs(snapshot, existing)
            pruned["updated_at"] = time.time()
            self.replace_snapshot(pruned)
            return {
                "authority": "orchestration.runtime_state_index.prune_task_runs",
                "requested_task_run_ids": sorted(targets),
                "deleted_task_run_ids": sorted(existing),
                "deleted_counts": counts,
            }

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
            "agent_delegation_requests",
            "agent_delegation_results",
            "supervision_records",
        }
        for bucket in self._record_buckets():
            source = dict(snapshot.get(bucket) or {})
            kept: dict[str, Any] = {}
            for key, value in source.items():
                if not isinstance(value, dict):
                    continue
                task_run_id = str(value.get("task_run_id") or value.get("observed_task_run_id") or "")
                should_delete = bucket in task_record_buckets and task_run_id in task_run_ids
                if should_delete:
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
        for request in dict(snapshot.get("agent_delegation_requests") or {}).values():
            if isinstance(request, dict):
                self._snapshot_append_index(snapshot, "task_agent_delegation_requests", str(request.get("task_run_id") or ""), str(request.get("request_id") or ""))
        for result in dict(snapshot.get("agent_delegation_results") or {}).values():
            if isinstance(result, dict):
                self._snapshot_append_index(snapshot, "task_agent_delegation_results", str(result.get("task_run_id") or ""), str(result.get("result_id") or ""))
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
        if graph_config := dict(diagnostics.get("graph_harness_config") or diagnostics.get("graph_harness_config_payload") or {}):
            diagnostics["graph_harness_config_ref"] = self.runtime_objects.put_json_once(
                "graph_harness_configs",
                object_id,
                graph_config,
            )
            diagnostics["graph_harness_config_summary"] = _graph_harness_config_summary(graph_config)
            diagnostics.pop("graph_harness_config", None)
            diagnostics.pop("graph_harness_config_payload", None)
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

    def _read_index_ids(self, bucket: str, index_id: str) -> list[str]:
        value = self._read_index_value(bucket, index_id)
        return [str(item) for item in list(value or []) if str(item)]

    def _append_index_id(self, bucket: str, index_id: str, value: str) -> None:
        items = self._read_index_ids(bucket, index_id)
        if value not in items:
            items.append(value)
        self._write_index_value(bucket, index_id, items)

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
            "agent_delegation_requests": "request_id",
            "agent_delegation_results": "result_id",
            "project_progress_ledgers": "project_id",
            "supervision_records": "supervision_record_id",
            "project_runtime_statuses": "project_id",
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
            "agent_delegation_requests",
            "agent_delegation_results",
            "project_progress_ledgers",
            "supervision_records",
            "project_runtime_statuses",
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
            "task_agent_delegation_requests",
            "task_agent_delegation_results",
            "session_projects",
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
            "agent_delegation_requests": {},
            "task_agent_delegation_requests": {},
            "agent_delegation_results": {},
            "task_agent_delegation_results": {},
            "project_progress_ledgers": {},
            "supervision_records": {},
            "project_runtime_statuses": {},
            "session_projects": {},
            "project_supervision_records": {},
            "task_supervision_records": {},
            "session_latest_turn_runs": {},
            "updated_at": 0.0,
        }

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

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
        status=payload.get("status", "created"),
        created_at=float(payload.get("created_at") or 0.0),
        updated_at=float(payload.get("updated_at") or 0.0),
        latest_event_offset=int(payload.get("latest_event_offset", -1)),
        latest_checkpoint_ref=str(payload.get("latest_checkpoint_ref") or ""),
        terminal_reason=payload.get("terminal_reason", ""),
        diagnostics=dict(payload.get("diagnostics") or {}),
    )


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


def _graph_harness_config_summary(payload: dict[str, Any]) -> dict[str, Any]:
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
        status=payload.get("status", "pending"),
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
        status=payload.get("status", "completed"),
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


