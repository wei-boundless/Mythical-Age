from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ..shared.models import (
    AgentHandoffEnvelope,
    AgentRun,
    AgentRunResult,
    CoordinationMergeResult,
    CoordinationNodeRun,
    CoordinationRun,
    ProjectProgressLedger,
    ProjectRuntimeStatus,
    SupervisionRecord,
    TaskRun,
)
from ..execution.delegation_models import (
    AgentDelegationRequest,
    AgentDelegationResult,
    delegation_request_from_dict,
    delegation_result_from_dict,
)
from agent_system.registry.worker_agent_blueprints import WorkerAgentSpawnRequest, WorkerAgentSpawnResult
from ..shared.runtime_object_store import RuntimeObjectStore
from task_system.orders.models import (
    ConversationTurn,
    ExecutionChannel,
    TaskExecutionEnvelope,
    TaskIntentDecision,
    TaskOrder,
    TaskOrderDraft,
    TaskOrderRun,
    conversation_turn_from_dict,
    execution_channel_from_dict,
    task_execution_envelope_from_dict,
    task_intent_decision_from_dict,
    task_order_draft_from_dict,
    task_order_from_dict,
    task_order_run_from_dict,
)


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

    def upsert_coordination_run(self, coordination_run: CoordinationRun) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            payload = self._compact_coordination_run_payload(coordination_run.to_dict())
            self._write_record("coordination_runs", coordination_run.coordination_run_id, payload)
            self._append_index_id(
                "task_coordination_runs",
                coordination_run.task_run_id,
                coordination_run.coordination_run_id,
            )
            task_run_payload = self._read_record("task_runs", coordination_run.task_run_id)
            session_id = str(task_run_payload.get("session_id") or "")
            if session_id:
                self._maybe_write_latest_ref(
                    "session_latest_coordination_task_runs",
                    session_id,
                    coordination_run.task_run_id,
                    updated_at=float(payload.get("updated_at") or 0.0),
                )
                self._upsert_session_live_view(
                    session_id=session_id,
                    task_run_id=coordination_run.task_run_id,
                    coordination_run_id=coordination_run.coordination_run_id,
                    updated_at=float(payload.get("updated_at") or 0.0),
                )
            self._maybe_write_latest_ref(
                "task_latest_coordination_runs",
                coordination_run.task_run_id,
                coordination_run.coordination_run_id,
                updated_at=float(payload.get("updated_at") or 0.0),
            )
            self._touch_meta()

    def upsert_coordination_node_run(self, node_run: CoordinationNodeRun) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._write_record("coordination_node_runs", node_run.node_run_id, node_run.to_dict())
            self._append_index_id(
                "coordination_node_run_index",
                node_run.coordination_run_id,
                node_run.node_run_id,
            )
            self._touch_session_live_view_by_coordination(
                coordination_run_id=node_run.coordination_run_id,
                updated_at=float(node_run.updated_at or 0.0),
            )
            self._touch_meta()

    def upsert_handoff_envelope(self, handoff: AgentHandoffEnvelope) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._write_record("handoff_envelopes", handoff.handoff_id, handoff.to_dict())
            self._append_index_id("coordination_handoffs", handoff.coordination_run_id, handoff.handoff_id)
            self._touch_session_live_view_by_coordination(
                coordination_run_id=handoff.coordination_run_id,
                updated_at=float(handoff.created_at or 0.0),
            )
            self._touch_meta()

    def upsert_coordination_merge_result(self, result: CoordinationMergeResult) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._write_record("coordination_merge_results", result.merge_result_id, result.to_dict())
            self._write_index_value(
                "coordination_latest_merge_results",
                result.coordination_run_id,
                result.merge_result_id,
            )
            self._touch_session_live_view_by_coordination(
                coordination_run_id=result.coordination_run_id,
                updated_at=float(result.created_at or 0.0),
            )
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

    def upsert_conversation_turn(self, turn: ConversationTurn) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._write_record("conversation_turns", turn.turn_id, turn.to_dict())
            self._append_index_id("conversation_turns_by_session", turn.session_id, turn.turn_id)
            if turn.task_order_ref:
                self._write_index_value("turn_by_order", turn.task_order_ref, turn.turn_id)
            self._touch_meta(updated_at=float(turn.created_at or time.time()))

    def upsert_task_intent_decision(self, decision: TaskIntentDecision) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._write_record("task_intent_decisions", decision.decision_id, decision.to_dict())
            self._append_index_id("intent_decisions_by_turn", decision.turn_id, decision.decision_id)
            if decision.created_order_id:
                self._write_index_value("intent_decision_by_order", decision.created_order_id, decision.decision_id)
            self._touch_meta(updated_at=float(decision.created_at or time.time()))

    def upsert_task_order_draft(self, draft: TaskOrderDraft) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._write_record("task_order_drafts", draft.draft_id, draft.to_dict())
            self._append_index_id("task_order_drafts_by_turn", draft.turn_id, draft.draft_id)
            self._append_index_id("task_order_drafts_by_session", draft.session_id, draft.draft_id)
            self._touch_meta(updated_at=float(draft.updated_at or draft.created_at or time.time()))

    def upsert_task_order(self, order: TaskOrder) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._write_record("task_orders", order.order_id, order.to_dict())
            self._append_index_id("task_orders_by_session", order.session_id, order.order_id)
            if order.source_ref.startswith("conversation.turn:"):
                self._write_index_value("order_by_turn", order.source_ref.split(":", 2)[-1], order.order_id)
            if order.task_id:
                self._append_index_id("task_orders_by_task", order.task_id, order.order_id)
            self._touch_meta(updated_at=float(order.updated_at or order.created_at or time.time()))

    def upsert_task_order_run(self, run: TaskOrderRun) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._write_record("task_order_runs", run.run_id, run.to_dict())
            self._append_index_id("task_order_runs_by_order", run.order_id, run.run_id)
            self._append_index_id("task_order_runs_by_session", run.session_id, run.run_id)
            if run.task_run_id:
                self._write_index_value("order_run_by_task_run", run.task_run_id, run.run_id)
            if run.primary_execution_channel_id:
                self._write_index_value("channel_by_order_run", run.run_id, run.primary_execution_channel_id)
            self._touch_meta(updated_at=float(run.updated_at or run.created_at or time.time()))

    def upsert_execution_channel(self, channel: ExecutionChannel) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._write_record("execution_channels", channel.channel_id, channel.to_dict())
            self._write_index_value("channel_by_order_run", channel.order_run_id, channel.channel_id)
            self._append_index_id("execution_channels_by_order", channel.order_id, channel.channel_id)
            self._append_index_id("execution_channels_by_session", channel.session_id, channel.channel_id)
            if channel.task_run_id:
                self._write_index_value("channel_by_task_run", channel.task_run_id, channel.channel_id)
            self._touch_meta(updated_at=float(channel.updated_at or channel.created_at or time.time()))

    def upsert_task_execution_envelope(self, envelope: TaskExecutionEnvelope) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            self._write_record("task_execution_envelopes", envelope.envelope_id, envelope.to_dict())
            self._write_index_value("task_execution_envelope_by_order_run", envelope.order_run_id, envelope.envelope_id)
            self._append_index_id("task_execution_envelopes_by_order", envelope.order_id, envelope.envelope_id)
            self._touch_meta(updated_at=float(envelope.created_at or time.time()))

    def bind_task_order_run_to_task_run(
        self,
        *,
        order_run_id: str,
        task_run_id: str,
        execution_channel_id: str = "",
        coordination_run_id: str = "",
        agent_run_id: str = "",
        status: str = "running",
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            run_payload = self._read_record("task_order_runs", order_run_id)
            if not run_payload:
                return
            now = time.time()
            run_status = status or str(run_payload.get("status") or "running")
            run_payload.update(
                {
                    "task_run_id": task_run_id,
                    "coordination_run_id": coordination_run_id or str(run_payload.get("coordination_run_id") or ""),
                    "status": run_status,
                    "updated_at": now,
                    "diagnostics": {
                        **dict(run_payload.get("diagnostics") or {}),
                        **dict(diagnostics or {}),
                    },
                }
            )
            if execution_channel_id:
                run_payload["primary_execution_channel_id"] = execution_channel_id
            self._write_record("task_order_runs", order_run_id, run_payload)
            if task_run_id:
                self._write_index_value("order_run_by_task_run", task_run_id, order_run_id)
            channel_id = execution_channel_id or str(run_payload.get("primary_execution_channel_id") or "")
            if channel_id:
                self._write_index_value("channel_by_order_run", order_run_id, channel_id)
                channel_payload = self._read_record("execution_channels", channel_id)
                if channel_payload:
                    channel_payload.update(
                        {
                            "task_run_id": task_run_id,
                            "status": run_status,
                            "updated_at": now,
                            "diagnostics": {
                                **dict(channel_payload.get("diagnostics") or {}),
                                **({"agent_run_id": agent_run_id} if agent_run_id else {}),
                                **dict(diagnostics or {}),
                            },
                        }
                    )
                    self._write_record("execution_channels", channel_id, channel_payload)
                    if task_run_id:
                        self._write_index_value("channel_by_task_run", task_run_id, channel_id)
            self._update_order_status_for_run_payload(run_payload, run_status, now)
            self._touch_meta(updated_at=now)

    def claim_task_order_run_for_execution(
        self,
        *,
        order_run_id: str,
        diagnostics: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        with _STATE_INDEX_WRITE_LOCK:
            run_payload = self._read_record("task_order_runs", order_run_id)
            if not run_payload:
                return False, "missing"
            current_status = str(run_payload.get("status") or "created")
            if current_status != "created" or str(run_payload.get("task_run_id") or "").strip():
                return False, current_status
            now = time.time()
            run_payload.update(
                {
                    "status": "running",
                    "updated_at": now,
                    "diagnostics": {
                        **dict(run_payload.get("diagnostics") or {}),
                        "claimed_by": "task_order_run_execution_claim",
                        **dict(diagnostics or {}),
                    },
                }
            )
            self._write_record("task_order_runs", order_run_id, run_payload)
            channel_id = str(run_payload.get("primary_execution_channel_id") or "")
            if channel_id:
                channel_payload = self._read_record("execution_channels", channel_id)
                if channel_payload:
                    channel_payload.update(
                        {
                            "status": "running",
                            "updated_at": now,
                            "diagnostics": {
                                **dict(channel_payload.get("diagnostics") or {}),
                                "claimed_by": "task_order_run_execution_claim",
                                **dict(diagnostics or {}),
                            },
                        }
                    )
                    self._write_record("execution_channels", channel_id, channel_payload)
            self._update_order_status_for_run_payload(run_payload, "running", now)
            self._touch_meta(updated_at=now)
            return True, current_status

    def update_task_order_run_status(
        self,
        *,
        order_run_id: str,
        status: str,
        terminal_reason: str = "",
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        with _STATE_INDEX_WRITE_LOCK:
            run_payload = self._read_record("task_order_runs", order_run_id)
            if not run_payload:
                return
            now = time.time()
            next_status = str(status or run_payload.get("status") or "running")
            run_payload.update(
                {
                    "status": next_status,
                    "updated_at": now,
                    "terminal_reason": terminal_reason or str(run_payload.get("terminal_reason") or ""),
                    "diagnostics": {
                        **dict(run_payload.get("diagnostics") or {}),
                        **dict(diagnostics or {}),
                    },
                }
            )
            self._write_record("task_order_runs", order_run_id, run_payload)
            channel_id = str(run_payload.get("primary_execution_channel_id") or "")
            if channel_id:
                channel_payload = self._read_record("execution_channels", channel_id)
                if channel_payload:
                    channel_payload.update(
                        {
                            "status": next_status,
                            "updated_at": now,
                            "terminal_reason": terminal_reason or str(channel_payload.get("terminal_reason") or ""),
                            "diagnostics": {
                                **dict(channel_payload.get("diagnostics") or {}),
                                **dict(diagnostics or {}),
                            },
                        }
                    )
                    self._write_record("execution_channels", channel_id, channel_payload)
            self._update_order_status_for_run_payload(run_payload, next_status, now)
            self._touch_meta(updated_at=now)

    def update_task_order_runtime_status(
        self,
        *,
        task_run_id: str,
        status: str,
        terminal_reason: str = "",
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        order_run = self.get_task_order_run_by_task_run(task_run_id)
        if order_run is None:
            return
        self.update_task_order_run_status(
            order_run_id=order_run.run_id,
            status=status,
            terminal_reason=terminal_reason,
            diagnostics=diagnostics,
        )

    def _update_order_status_for_run_payload(
        self,
        run_payload: dict[str, Any],
        run_status: str,
        updated_at: float,
    ) -> None:
        order_id = str(run_payload.get("order_id") or "")
        if not order_id:
            return
        order_payload = self._read_record("task_orders", order_id)
        if not order_payload:
            return
        order_status_by_run = {
            "created": "accepted",
            "running": "running",
            "waiting_approval": "running",
            "paused": "running",
            "completed": "completed",
            "failed": "failed",
            "cancelled": "cancelled",
        }
        next_order_status = order_status_by_run.get(run_status)
        if not next_order_status:
            return
        order_payload.update(
            {
                "status": next_order_status,
                "updated_at": updated_at,
            }
        )
        self._write_record("task_orders", order_id, order_payload)

    def get_task_run(self, task_run_id: str) -> TaskRun | None:
        task_run = self._read_record("task_runs", task_run_id)
        if not task_run:
            return None
        return _task_run_from_payload(task_run)

    def list_task_runs(self) -> list[TaskRun]:
        task_runs = self._read_record_bucket("task_runs")
        return [_task_run_from_payload(item) for item in task_runs.values() if isinstance(item, dict)]

    def list_session_task_runs(self, session_id: str) -> list[TaskRun]:
        task_runs = self._read_record_bucket("task_runs")
        ids = self._read_index_ids("sessions", session_id)
        return [_task_run_from_payload(task_runs[item]) for item in ids if item in task_runs]

    def list_task_agent_runs(self, task_run_id: str) -> list[AgentRun]:
        agent_runs = self._read_record_bucket("agent_runs")
        ids = self._read_index_ids("task_agent_runs", task_run_id)
        return [_agent_run_from_payload(agent_runs[item]) for item in ids if item in agent_runs]

    def list_task_coordination_runs(self, task_run_id: str) -> list[CoordinationRun]:
        coordination_runs = self._read_record_bucket("coordination_runs")
        ids = self._read_index_ids("task_coordination_runs", task_run_id)
        return [_coordination_run_from_payload(coordination_runs[item]) for item in ids if item in coordination_runs]

    def get_coordination_run(self, coordination_run_id: str) -> CoordinationRun | None:
        coordination_run = self._read_record("coordination_runs", coordination_run_id)
        if not coordination_run:
            return None
        return _coordination_run_from_payload(coordination_run)

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

    def list_coordination_node_runs(self, coordination_run_id: str) -> list[CoordinationNodeRun]:
        node_runs = self._read_record_bucket("coordination_node_runs")
        ids = self._read_index_ids("coordination_node_run_index", coordination_run_id)
        return [_coordination_node_run_from_payload(node_runs[item]) for item in ids if item in node_runs]

    def list_coordination_handoffs(self, coordination_run_id: str) -> list[AgentHandoffEnvelope]:
        handoffs = self._read_record_bucket("handoff_envelopes")
        ids = self._read_index_ids("coordination_handoffs", coordination_run_id)
        return [_handoff_from_payload(handoffs[item]) for item in ids if item in handoffs]

    def get_latest_coordination_merge_result(self, coordination_run_id: str) -> CoordinationMergeResult | None:
        latest_id = self._read_index_value("coordination_latest_merge_results", coordination_run_id)
        if latest_id:
            payload = self._read_record("coordination_merge_results", latest_id)
            if payload:
                return _coordination_merge_result_from_payload(payload)
        results = self._read_record_bucket("coordination_merge_results")
        matches = [
            _coordination_merge_result_from_payload(item)
            for item in results.values()
            if isinstance(item, dict) and str(item.get("coordination_run_id") or "") == coordination_run_id
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.created_at, reverse=True)[0]

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

    def get_conversation_turn(self, turn_id: str) -> ConversationTurn | None:
        payload = self._read_record("conversation_turns", turn_id)
        return conversation_turn_from_dict(payload) if payload else None

    def list_session_conversation_turns(self, session_id: str) -> list[ConversationTurn]:
        turns = self._read_record_bucket("conversation_turns")
        ids = self._read_index_ids("conversation_turns_by_session", session_id)
        return [conversation_turn_from_dict(turns[item]) for item in ids if item in turns]

    def get_conversation_turn_by_order(self, order_id: str) -> ConversationTurn | None:
        turn_id = str(self._read_index_value("turn_by_order", order_id) or "")
        return self.get_conversation_turn(turn_id) if turn_id else None

    def get_task_intent_decision(self, decision_id: str) -> TaskIntentDecision | None:
        payload = self._read_record("task_intent_decisions", decision_id)
        return task_intent_decision_from_dict(payload) if payload else None

    def list_turn_intent_decisions(self, turn_id: str) -> list[TaskIntentDecision]:
        decisions = self._read_record_bucket("task_intent_decisions")
        ids = self._read_index_ids("intent_decisions_by_turn", turn_id)
        return [task_intent_decision_from_dict(decisions[item]) for item in ids if item in decisions]

    def get_task_intent_decision_by_order(self, order_id: str) -> TaskIntentDecision | None:
        decision_id = str(self._read_index_value("intent_decision_by_order", order_id) or "")
        return self.get_task_intent_decision(decision_id) if decision_id else None

    def get_task_order_draft(self, draft_id: str) -> TaskOrderDraft | None:
        payload = self._read_record("task_order_drafts", draft_id)
        return task_order_draft_from_dict(payload) if payload else None

    def list_session_task_order_drafts(self, session_id: str) -> list[TaskOrderDraft]:
        drafts = self._read_record_bucket("task_order_drafts")
        ids = self._read_index_ids("task_order_drafts_by_session", session_id)
        return [task_order_draft_from_dict(drafts[item]) for item in ids if item in drafts]

    def get_task_order(self, order_id: str) -> TaskOrder | None:
        payload = self._read_record("task_orders", order_id)
        return task_order_from_dict(payload) if payload else None

    def list_task_orders(self) -> list[TaskOrder]:
        orders = self._read_record_bucket("task_orders")
        return [task_order_from_dict(item) for item in orders.values() if isinstance(item, dict)]

    def list_session_task_orders(self, session_id: str) -> list[TaskOrder]:
        orders = self._read_record_bucket("task_orders")
        ids = self._read_index_ids("task_orders_by_session", session_id)
        return [task_order_from_dict(orders[item]) for item in ids if item in orders]

    def get_task_order_run(self, run_id: str) -> TaskOrderRun | None:
        payload = self._read_record("task_order_runs", run_id)
        return task_order_run_from_dict(payload) if payload else None

    def get_task_order_run_by_task_run(self, task_run_id: str) -> TaskOrderRun | None:
        order_run_id = str(self._read_index_value("order_run_by_task_run", task_run_id) or "")
        return self.get_task_order_run(order_run_id) if order_run_id else None

    def list_order_runs(self, order_id: str) -> list[TaskOrderRun]:
        runs = self._read_record_bucket("task_order_runs")
        ids = self._read_index_ids("task_order_runs_by_order", order_id)
        return [task_order_run_from_dict(runs[item]) for item in ids if item in runs]

    def list_session_task_order_runs(self, session_id: str) -> list[TaskOrderRun]:
        runs = self._read_record_bucket("task_order_runs")
        ids = self._read_index_ids("task_order_runs_by_session", session_id)
        return [task_order_run_from_dict(runs[item]) for item in ids if item in runs]

    def get_execution_channel(self, channel_id: str) -> ExecutionChannel | None:
        payload = self._read_record("execution_channels", channel_id)
        return execution_channel_from_dict(payload) if payload else None

    def get_execution_channel_by_order_run(self, order_run_id: str) -> ExecutionChannel | None:
        channel_id = str(self._read_index_value("channel_by_order_run", order_run_id) or "")
        return self.get_execution_channel(channel_id) if channel_id else None

    def get_execution_channel_by_task_run(self, task_run_id: str) -> ExecutionChannel | None:
        channel_id = str(self._read_index_value("channel_by_task_run", task_run_id) or "")
        return self.get_execution_channel(channel_id) if channel_id else None

    def get_task_execution_envelope(self, envelope_id: str) -> TaskExecutionEnvelope | None:
        payload = self._read_record("task_execution_envelopes", envelope_id)
        return task_execution_envelope_from_dict(payload) if payload else None

    def get_task_execution_envelope_by_order_run(self, order_run_id: str) -> TaskExecutionEnvelope | None:
        envelope_id = str(self._read_index_value("task_execution_envelope_by_order_run", order_run_id) or "")
        return self.get_task_execution_envelope(envelope_id) if envelope_id else None

    def task_order_projection_for_task_run(self, task_run_id: str) -> dict[str, Any] | None:
        order_run = self.get_task_order_run_by_task_run(task_run_id)
        if order_run is None:
            return None
        order = self.get_task_order(order_run.order_id)
        channel = (
            self.get_execution_channel(order_run.primary_execution_channel_id)
            if order_run.primary_execution_channel_id
            else self.get_execution_channel_by_order_run(order_run.run_id)
        )
        envelope = self.get_task_execution_envelope_by_order_run(order_run.run_id)
        turn_id = str(self._read_index_value("turn_by_order", order_run.order_id) or "")
        decision_id = str(self._read_index_value("intent_decision_by_order", order_run.order_id) or "")
        return {
            "projection_kind": "task_order",
            "task_order": order.to_dict() if order is not None else None,
            "task_order_run": order_run.to_dict(),
            "execution_channel": channel.to_dict() if channel is not None else None,
            "task_execution_envelope": envelope.to_dict() if envelope is not None else None,
            "conversation_turn_id": turn_id,
            "task_intent_decision_id": decision_id,
            "task_run_id": task_run_id,
            "authority": "task_system.task_order_projection",
        }

    def read_snapshot(self) -> dict[str, Any]:
        """Return one consistent read snapshot for live-monitor style queries."""
        return self._read()

    def read_session_monitor_snapshot(self, session_id: str) -> dict[str, Any]:
        session_view = self._read_session_live_view(session_id)
        task_run_ids = self._read_index_ids("sessions", session_id)
        task_run_bucket = self._read_record_bucket("task_runs")
        latest_coordination_task_run_id = str(
            session_view.get("latest_coordination_task_run_id")
            or self._read_index_value("session_latest_coordination_task_runs", session_id)
            or ""
        )
        latest_task_run_id = str(
            session_view.get("latest_task_run_id")
            or self._read_index_value("session_latest_task_runs", session_id)
            or ""
        )
        preferred_task_run_ids = [
            item
            for item in [latest_coordination_task_run_id, latest_task_run_id]
            if item
        ]
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
        task_coordination_runs = {}
        for task_run_id in preferred_task_run_ids:
            latest_coordination_run_id = str(
                self._read_index_value("task_latest_coordination_runs", task_run_id) or ""
            )
            if latest_coordination_run_id:
                task_coordination_runs[task_run_id] = [latest_coordination_run_id]
            else:
                task_coordination_runs[task_run_id] = self._read_index_ids("task_coordination_runs", task_run_id)
        coordination_run_ids = list(
            dict.fromkeys(
                coordination_run_id
                for ids in task_coordination_runs.values()
                for coordination_run_id in ids
            )
        )
        coordination_runs = self._read_selected_records("coordination_runs", coordination_run_ids)
        coordination_node_run_index = {
            coordination_run_id: self._read_index_ids("coordination_node_run_index", coordination_run_id)
            for coordination_run_id in coordination_run_ids
        }
        node_run_ids = list(
            dict.fromkeys(
                node_run_id
                for ids in coordination_node_run_index.values()
                for node_run_id in ids
            )
        )
        coordination_node_runs = self._read_selected_records("coordination_node_runs", node_run_ids)
        coordination_handoffs = {
            coordination_run_id: self._read_index_ids("coordination_handoffs", coordination_run_id)
            for coordination_run_id in coordination_run_ids
        }
        handoff_ids = list(
            dict.fromkeys(
                handoff_id
                for ids in coordination_handoffs.values()
                for handoff_id in ids
            )
        )
        handoff_envelopes = self._read_selected_records("handoff_envelopes", handoff_ids)
        latest_merge_ids = {
            coordination_run_id: self._read_index_value("coordination_latest_merge_results", coordination_run_id)
            for coordination_run_id in coordination_run_ids
        }
        coordination_merge_results = self._read_selected_records(
            "coordination_merge_results",
            [item for item in latest_merge_ids.values() if item],
        )
        order_run_ids = list(
            dict.fromkeys(
                str(self._read_index_value("order_run_by_task_run", task_run_id) or "")
                for task_run_id in preferred_task_run_ids
            )
        )
        order_run_ids = [item for item in order_run_ids if item]
        session_order_ids = self._read_index_ids("task_orders_by_session", session_id)
        order_runs = self._read_selected_records(
            "task_order_runs",
            list(dict.fromkeys([*order_run_ids, *self._read_index_ids("task_order_runs_by_session", session_id)])),
        )
        order_ids = list(
            dict.fromkeys(
                [
                    *session_order_ids,
                    *[
                        str(dict(item).get("order_id") or "")
                        for item in order_runs.values()
                        if isinstance(item, dict)
                    ],
                ]
            )
        )
        order_ids = [item for item in order_ids if item]
        channel_ids = list(
            dict.fromkeys(
                [
                    str(self._read_index_value("channel_by_task_run", task_run_id) or "")
                    for task_run_id in preferred_task_run_ids
                ]
                + [
                    str(dict(item).get("primary_execution_channel_id") or "")
                    for item in order_runs.values()
                    if isinstance(item, dict)
                ]
                + self._read_index_ids("execution_channels_by_session", session_id)
            )
        )
        channel_ids = [item for item in channel_ids if item]
        turn_ids = self._read_index_ids("conversation_turns_by_session", session_id)
        return {
            "task_runs": task_runs,
            "sessions": {session_id: preferred_task_run_ids},
            "coordination_runs": coordination_runs,
            "task_coordination_runs": task_coordination_runs,
            "coordination_node_runs": coordination_node_runs,
            "coordination_node_run_index": coordination_node_run_index,
            "handoff_envelopes": handoff_envelopes,
            "coordination_handoffs": coordination_handoffs,
            "coordination_merge_results": coordination_merge_results,
            "project_progress_ledgers": self._read_selected_records(
                "project_progress_ledgers",
                self._read_index_ids("session_projects", session_id),
            ),
            "project_runtime_statuses": self._read_selected_records(
                "project_runtime_statuses",
                self._read_index_ids("session_projects", session_id),
            ),
            "conversation_turns": self._read_selected_records("conversation_turns", turn_ids),
            "task_orders": self._read_selected_records("task_orders", order_ids),
            "task_order_runs": order_runs,
            "execution_channels": self._read_selected_records("execution_channels", channel_ids),
            "monitor_index": {
                "session_id": session_id,
                "task_run_count": int(session_view.get("task_run_count") or len(task_run_ids)),
                "latest_task_run_id": latest_task_run_id,
                "latest_coordination_task_run_id": latest_coordination_task_run_id,
                "freshest_task_run_id": freshest_task_run_id,
                "latest_coordination_run_id": str(session_view.get("latest_coordination_run_id") or ""),
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

    def _compact_task_run_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        compacted = dict(payload)
        diagnostics = dict(compacted.get("diagnostics") or {})
        object_id = str(compacted.get("task_run_id") or "")
        if definition := dict(diagnostics.get("task_graph_definition") or {}):
            diagnostics["task_graph_definition_ref"] = self.runtime_objects.put_json_once(
                "task_graph_definitions",
                object_id,
                definition,
            )
            diagnostics.pop("task_graph_definition", None)
        if runtime_spec := dict(diagnostics.get("task_graph_runtime_spec") or {}):
            diagnostics["task_graph_runtime_spec_ref"] = self.runtime_objects.put_json_once(
                "task_graph_runtime_specs",
                object_id,
                runtime_spec,
            )
            diagnostics.pop("task_graph_runtime_spec", None)
        if dispatch_plan := dict(diagnostics.get("agent_dispatch_plan") or {}):
            diagnostics["agent_dispatch_plan_ref"] = self.runtime_objects.put_object(
                "dispatch_plans",
                object_id,
                dispatch_plan,
            )
            diagnostics["agent_dispatch_plan_summary"] = _dispatch_plan_summary(dispatch_plan)
            diagnostics.pop("agent_dispatch_plan", None)
        compacted["diagnostics"] = diagnostics
        return compacted

    def _compact_coordination_run_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        compacted = dict(payload)
        diagnostics = dict(compacted.get("diagnostics") or {})
        object_id = str(compacted.get("coordination_run_id") or "")
        if definition := dict(diagnostics.get("task_graph_definition") or {}):
            diagnostics["task_graph_definition_ref"] = self.runtime_objects.put_json_once(
                "task_graph_definitions",
                object_id,
                definition,
            )
            diagnostics.pop("task_graph_definition", None)
        if runtime_spec := dict(diagnostics.get("task_graph_runtime_spec") or {}):
            diagnostics["task_graph_runtime_spec_ref"] = self.runtime_objects.put_json_once(
                "task_graph_runtime_specs",
                object_id,
                runtime_spec,
            )
            diagnostics.pop("task_graph_runtime_spec", None)
        if dispatch_plan := dict(diagnostics.get("agent_dispatch_plan") or {}):
            diagnostics["agent_dispatch_plan_ref"] = self.runtime_objects.put_object(
                "dispatch_plans",
                object_id,
                dispatch_plan,
            )
            diagnostics["agent_dispatch_plan_summary"] = _dispatch_plan_summary(dispatch_plan)
            diagnostics.pop("agent_dispatch_plan", None)
        if runtime_state := dict(diagnostics.get("langgraph_runtime_state") or {}):
            diagnostics["langgraph_runtime_state_summary"] = _langgraph_runtime_state_summary(runtime_state)
            diagnostics.pop("langgraph_runtime_state", None)
        if graph_spec := dict(diagnostics.get("coordination_graph_spec") or {}):
            diagnostics["coordination_graph_spec_ref"] = self.runtime_objects.put_json_once(
                "coordination_graph_specs",
                object_id,
                graph_spec,
            )
            diagnostics["coordination_graph_spec_summary"] = _coordination_graph_spec_summary(graph_spec)
            diagnostics.pop("coordination_graph_spec", None)
        if scheduler_state := dict(diagnostics.get("task_graph_scheduler_state") or {}):
            diagnostics["task_graph_scheduler_state_summary"] = _scheduler_state_summary(scheduler_state)
            diagnostics.pop("task_graph_scheduler_state", None)
        if flow := dict(diagnostics.get("coordination_flow") or {}):
            diagnostics["coordination_flow"] = _coordination_flow_summary(flow)
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
        for key, value in dict(payload.get("coordination_latest_merge_results") or {}).items():
            if value:
                self._write_index_value("coordination_latest_merge_results", str(key), str(value))
        if not dict(payload.get("coordination_latest_merge_results") or {}):
            latest_by_run: dict[str, dict[str, Any]] = {}
            for result_id, value in dict(payload.get("coordination_merge_results") or {}).items():
                if not isinstance(value, dict):
                    continue
                coordination_run_id = str(value.get("coordination_run_id") or "")
                if not coordination_run_id:
                    continue
                current = latest_by_run.get(coordination_run_id)
                created_at = float(value.get("created_at") or 0.0)
                if current is None or created_at >= float(current.get("created_at") or 0.0):
                    latest_by_run[coordination_run_id] = {"merge_result_id": str(result_id), "created_at": created_at}
            for coordination_run_id, value in latest_by_run.items():
                self._write_index_value(
                    "coordination_latest_merge_results",
                    coordination_run_id,
                    str(value.get("merge_result_id") or ""),
                )
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
        if not dict(payload.get("task_latest_coordination_runs") or {}):
            latest_by_task: dict[str, dict[str, Any]] = {}
            latest_session_coordination_tasks: dict[str, dict[str, Any]] = {}
            task_runs = {
                str(item.get("task_run_id") or ""): dict(item)
                for item in dict(payload.get("task_runs") or {}).values()
                if isinstance(item, dict)
            }
            for value in dict(payload.get("coordination_runs") or {}).values():
                if not isinstance(value, dict):
                    continue
                task_run_id = str(value.get("task_run_id") or "")
                coordination_run_id = str(value.get("coordination_run_id") or "")
                if not task_run_id or not coordination_run_id:
                    continue
                created = float(value.get("updated_at") or 0.0)
                current = latest_by_task.get(task_run_id)
                if current is None or created >= float(current.get("updated_at") or 0.0):
                    latest_by_task[task_run_id] = {"coordination_run_id": coordination_run_id, "updated_at": created}
                session_id = str(task_runs.get(task_run_id, {}).get("session_id") or "")
                if session_id:
                    current_session = latest_session_coordination_tasks.get(session_id)
                    if current_session is None or created >= float(current_session.get("updated_at") or 0.0):
                        latest_session_coordination_tasks[session_id] = {
                            "task_run_id": task_run_id,
                            "updated_at": created,
                        }
            for task_run_id, value in latest_by_task.items():
                self._write_index_value(
                    "task_latest_coordination_runs",
                    task_run_id,
                    str(value.get("coordination_run_id") or ""),
                )
            for session_id, value in latest_session_coordination_tasks.items():
                self._write_index_value(
                    "session_latest_coordination_task_runs",
                    session_id,
                    str(value.get("task_run_id") or ""),
                )

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
            current_payload = self._read_record("task_runs", current_id) if bucket.startswith("session_") else {}
            if bucket == "task_latest_coordination_runs":
                current_payload = self._read_record("coordination_runs", current_id)
            elif bucket == "session_latest_coordination_task_runs":
                current_payload = self._read_record("task_runs", current_id)
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
        coordination_run_id: str = "",
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
        latest_coordination_task_run_id = str(
            (task_run_id if coordination_run_id else "")
            or current.get("latest_coordination_task_run_id")
            or self._read_index_value("session_latest_coordination_task_runs", session_id)
            or ""
        )
        latest_coordination_run_id = str(
            coordination_run_id
            or current.get("latest_coordination_run_id")
            or (
                self._read_index_value("task_latest_coordination_runs", latest_coordination_task_run_id)
                if latest_coordination_task_run_id
                else ""
            )
            or ""
        )
        payload = {
            "session_id": session_id,
            "task_run_count": task_run_count,
            "latest_task_run_id": latest_task_run_id,
            "latest_coordination_task_run_id": latest_coordination_task_run_id,
            "latest_coordination_run_id": latest_coordination_run_id,
            "updated_at": float(updated_at or current.get("updated_at") or time.time()),
            "authority": "orchestration.runtime_state_index.session_live_view",
        }
        self._atomic_write_path(self._session_live_view_path(session_id), payload)

    def _touch_session_live_view_by_coordination(self, *, coordination_run_id: str, updated_at: float) -> None:
        coordination_run = self._read_record("coordination_runs", coordination_run_id)
        task_run_id = str(coordination_run.get("task_run_id") or "")
        if not task_run_id:
            return
        task_run = self._read_record("task_runs", task_run_id)
        session_id = str(task_run.get("session_id") or "")
        if not session_id:
            return
        current = self._read_session_live_view(session_id)
        payload = {
            "session_id": session_id,
            "task_run_count": int(current.get("task_run_count") or len(self._read_index_ids("sessions", session_id))),
            "latest_task_run_id": str(
                current.get("latest_task_run_id")
                or self._read_index_value("session_latest_task_runs", session_id)
                or task_run_id
            ),
            "latest_coordination_task_run_id": str(
                current.get("latest_coordination_task_run_id")
                or self._read_index_value("session_latest_coordination_task_runs", session_id)
                or task_run_id
            ),
            "latest_coordination_run_id": str(
                current.get("latest_coordination_run_id")
                or self._read_index_value("task_latest_coordination_runs", task_run_id)
                or coordination_run_id
            ),
            "updated_at": float(updated_at or current.get("updated_at") or time.time()),
            "authority": "orchestration.runtime_state_index.session_live_view",
        }
        self._atomic_write_path(self._session_live_view_path(session_id), payload)

    @staticmethod
    def _record_identity(bucket: str, payload: dict[str, Any], fallback: str) -> str:
        key_field_by_bucket = {
            "conversation_turns": "turn_id",
            "task_intent_decisions": "decision_id",
            "task_order_drafts": "draft_id",
            "task_orders": "order_id",
            "task_order_runs": "run_id",
            "execution_channels": "channel_id",
            "task_execution_envelopes": "envelope_id",
            "task_runs": "task_run_id",
            "agent_runs": "agent_run_id",
            "agent_run_results": "agent_run_result_id",
            "coordination_runs": "coordination_run_id",
            "coordination_node_runs": "node_run_id",
            "handoff_envelopes": "handoff_id",
            "coordination_merge_results": "merge_result_id",
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
            "conversation_turns",
            "task_intent_decisions",
            "task_order_drafts",
            "task_orders",
            "task_order_runs",
            "execution_channels",
            "task_execution_envelopes",
            "task_runs",
            "agent_runs",
            "agent_run_results",
            "coordination_runs",
            "coordination_node_runs",
            "handoff_envelopes",
            "coordination_merge_results",
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
            "conversation_turns_by_session",
            "intent_decisions_by_turn",
            "task_order_drafts_by_turn",
            "task_order_drafts_by_session",
            "task_orders_by_session",
            "task_orders_by_task",
            "task_order_runs_by_order",
            "task_order_runs_by_session",
            "execution_channels_by_order",
            "execution_channels_by_session",
            "task_execution_envelopes_by_order",
            "sessions",
            "task_agent_runs",
            "task_agent_run_results",
            "task_coordination_runs",
            "coordination_node_run_index",
            "coordination_handoffs",
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
            "order_by_turn",
            "turn_by_order",
            "intent_decision_by_order",
            "order_run_by_task_run",
            "channel_by_order_run",
            "channel_by_task_run",
            "task_execution_envelope_by_order_run",
            "coordination_latest_merge_results",
            "session_latest_task_runs",
            "session_latest_coordination_task_runs",
            "task_latest_coordination_runs",
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
            "conversation_turns": {},
            "conversation_turns_by_session": {},
            "task_intent_decisions": {},
            "intent_decisions_by_turn": {},
            "task_order_drafts": {},
            "task_order_drafts_by_turn": {},
            "task_order_drafts_by_session": {},
            "task_orders": {},
            "task_orders_by_session": {},
            "task_orders_by_task": {},
            "task_order_runs": {},
            "task_order_runs_by_order": {},
            "task_order_runs_by_session": {},
            "execution_channels": {},
            "execution_channels_by_order": {},
            "execution_channels_by_session": {},
            "task_execution_envelopes": {},
            "task_execution_envelopes_by_order": {},
            "task_runs": {},
            "sessions": {},
            "agent_runs": {},
            "task_agent_runs": {},
            "agent_run_results": {},
            "task_agent_run_results": {},
            "coordination_runs": {},
            "task_coordination_runs": {},
            "coordination_node_runs": {},
            "coordination_node_run_index": {},
            "handoff_envelopes": {},
            "coordination_handoffs": {},
            "coordination_merge_results": {},
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
            "order_by_turn": {},
            "turn_by_order": {},
            "intent_decision_by_order": {},
            "order_run_by_task_run": {},
            "channel_by_order_run": {},
            "channel_by_task_run": {},
            "task_execution_envelope_by_order_run": {},
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
        runtime_lane=str(payload.get("runtime_lane") or "full_interactive"),
        status=payload.get("status", "created"),
        created_at=float(payload.get("created_at") or 0.0),
        updated_at=float(payload.get("updated_at") or 0.0),
        latest_event_offset=int(payload.get("latest_event_offset", -1)),
        latest_checkpoint_ref=str(payload.get("latest_checkpoint_ref") or ""),
        terminal_reason=payload.get("terminal_reason", ""),
        diagnostics=dict(payload.get("diagnostics") or {}),
    )


def _dispatch_plan_summary(payload: dict[str, Any]) -> dict[str, Any]:
    records = list(payload.get("records") or [])
    barriers = list(payload.get("barrier_states") or [])
    notifications = list(payload.get("queued_notifications") or [])
    return {
        "dispatch_plan_id": str(payload.get("dispatch_plan_id") or ""),
        "record_count": len(records),
        "barrier_count": len(barriers),
        "queued_notification_count": len(notifications),
        "ready_node_ids": list(payload.get("ready_node_ids") or []),
        "blocked_node_ids": list(payload.get("blocked_node_ids") or []),
        "background_node_ids": list(payload.get("background_node_ids") or []),
    }


def _langgraph_runtime_state_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "active_stage_id": str(payload.get("active_stage_id") or ""),
        "active_task_ref": str(payload.get("active_task_ref") or ""),
        "terminal_status": str(payload.get("terminal_status") or ""),
        "ready_nodes": list(payload.get("ready_nodes") or []),
        "running_nodes": list(payload.get("running_nodes") or []),
        "completed_node_count": len(list(payload.get("completed_nodes") or [])),
        "failed_node_count": len(list(payload.get("failed_nodes") or [])),
        "blocked_node_count": len(list(payload.get("blocked_nodes") or [])),
        "artifact_ref_count": len(list(payload.get("artifact_refs") or [])),
        "working_memory_operation_count": int(
            payload.get("working_memory_operation_count")
            or len(list(payload.get("working_memory_operations") or []))
            or 0
        ),
    }


def _coordination_graph_spec_summary(payload: dict[str, Any]) -> dict[str, Any]:
    nodes = list(payload.get("nodes") or [])
    edges = list(payload.get("edges") or [])
    return {
        "graph_id": str(payload.get("graph_id") or payload.get("graph_ref") or ""),
        "graph_ref": str(payload.get("graph_ref") or payload.get("graph_id") or ""),
        "coordination_task_id": str(payload.get("coordination_task_id") or ""),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "valid": bool(payload.get("valid") is True),
    }


def _scheduler_state_summary(payload: dict[str, Any]) -> dict[str, Any]:
    node_statuses = dict(payload.get("node_statuses") or {})
    return {
        "node_count": len(node_statuses),
        "ready_nodes": list(payload.get("ready_nodes") or []),
        "running_nodes": list(payload.get("running_nodes") or []),
        "completed_node_count": len(list(payload.get("completed_nodes") or [])),
        "failed_node_count": len(list(payload.get("failed_nodes") or [])),
        "blocked_node_count": len(list(payload.get("blocked_nodes") or [])),
    }


def _coordination_flow_summary(payload: dict[str, Any]) -> dict[str, Any]:
    stages = [dict(item) for item in list(payload.get("stages") or []) if isinstance(item, dict)]
    return {
        "coordination_mode": str(payload.get("coordination_mode") or ""),
        "current_stage_id": str(payload.get("current_stage_id") or ""),
        "next_stage_id": str(payload.get("next_stage_id") or ""),
        "next_task_ref": str(payload.get("next_task_ref") or ""),
        "terminal_status": str(payload.get("terminal_status") or ""),
        "ready_nodes": list(payload.get("ready_nodes") or []),
        "running_nodes": list(payload.get("running_nodes") or []),
        "completed_nodes": list(payload.get("completed_nodes") or []),
        "failed_nodes": list(payload.get("failed_nodes") or []),
        "blocked_nodes": list(payload.get("blocked_nodes") or []),
        "stage_count": len(stages),
        "stages": [
            {
                "stage_id": str(stage.get("stage_id") or ""),
                "node_id": str(stage.get("node_id") or ""),
                "task_ref": str(stage.get("task_ref") or ""),
                "status": str(stage.get("status") or ""),
                "artifact_refs": [
                    ref for ref in list(stage.get("artifact_refs") or []) if str(ref).startswith("artifact:")
                ],
                "working_memory_refs": list(stage.get("working_memory_refs") or []),
            }
            for stage in stages
        ],
        "working_memory_operation_count": int(payload.get("working_memory_operation_count") or 0),
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
        runtime_lane=str(payload.get("runtime_lane") or "full_interactive"),
        parent_agent_run_ref=str(payload.get("parent_agent_run_ref") or ""),
        coordination_run_ref=str(payload.get("coordination_run_ref") or ""),
        status=payload.get("status", "pending"),
        latest_checkpoint_ref=str(payload.get("latest_checkpoint_ref") or ""),
        result_ref=str(payload.get("result_ref") or ""),
        created_at=float(payload.get("created_at") or 0.0),
        updated_at=float(payload.get("updated_at") or 0.0),
        diagnostics=dict(payload.get("diagnostics") or {}),
    )


def _coordination_run_from_payload(payload: dict[str, Any]) -> CoordinationRun:
    return CoordinationRun(
        coordination_run_id=str(payload.get("coordination_run_id") or ""),
        task_run_id=str(payload.get("task_run_id") or ""),
        graph_ref=str(payload.get("graph_ref") or ""),
        coordinator_agent_id=str(payload.get("coordinator_agent_id") or ""),
        topology_template_id=str(payload.get("topology_template_id") or ""),
        communication_protocol_id=str(payload.get("communication_protocol_id") or ""),
        handoff_policy=str(payload.get("handoff_policy") or ""),
        failure_policy=str(payload.get("failure_policy") or ""),
        merge_policy=str(payload.get("merge_policy") or ""),
        status=payload.get("status", "pending"),
        latest_checkpoint_ref=str(payload.get("latest_checkpoint_ref") or ""),
        latest_merge_result_ref=str(payload.get("latest_merge_result_ref") or ""),
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


def _coordination_node_run_from_payload(payload: dict[str, Any]) -> CoordinationNodeRun:
    return CoordinationNodeRun(
        node_run_id=str(payload.get("node_run_id") or ""),
        coordination_run_id=str(payload.get("coordination_run_id") or ""),
        task_run_id=str(payload.get("task_run_id") or ""),
        node_id=str(payload.get("node_id") or ""),
        role=str(payload.get("role") or ""),
        assigned_agent_id=str(payload.get("assigned_agent_id") or ""),
        assigned_agent_run_ref=str(payload.get("assigned_agent_run_ref") or ""),
        status=payload.get("status", "pending"),
        handoff_count=int(payload.get("handoff_count") or 0),
        latest_handoff_ref=str(payload.get("latest_handoff_ref") or ""),
        created_at=float(payload.get("created_at") or 0.0),
        updated_at=float(payload.get("updated_at") or 0.0),
        diagnostics=dict(payload.get("diagnostics") or {}),
    )


def _handoff_from_payload(payload: dict[str, Any]) -> AgentHandoffEnvelope:
    return AgentHandoffEnvelope(
        handoff_id=str(payload.get("handoff_id") or ""),
        task_run_id=str(payload.get("task_run_id") or ""),
        coordination_run_id=str(payload.get("coordination_run_id") or ""),
        source_agent_run_ref=str(payload.get("source_agent_run_ref") or ""),
        target_agent_run_ref=str(payload.get("target_agent_run_ref") or ""),
        protocol_id=str(payload.get("protocol_id") or ""),
        message_type=str(payload.get("message_type") or ""),
        payload_ref=str(payload.get("payload_ref") or ""),
        ack_state=str(payload.get("ack_state") or "pending"),
        created_at=float(payload.get("created_at") or 0.0),
        diagnostics=dict(payload.get("diagnostics") or {}),
    )


def _coordination_merge_result_from_payload(payload: dict[str, Any]) -> CoordinationMergeResult:
    return CoordinationMergeResult(
        merge_result_id=str(payload.get("merge_result_id") or ""),
        coordination_run_id=str(payload.get("coordination_run_id") or ""),
        task_run_id=str(payload.get("task_run_id") or ""),
        merge_policy=str(payload.get("merge_policy") or ""),
        final_result_ref=str(payload.get("final_result_ref") or ""),
        accepted=bool(payload.get("accepted") is True),
        unresolved_issue_refs=tuple(str(item) for item in list(payload.get("unresolved_issue_refs") or []) if str(item)),
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
        observed_coordination_run_id=str(payload.get("observed_coordination_run_id") or ""),
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
        active_coordination_run_id=str(payload.get("active_coordination_run_id") or ""),
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
        runtime_lane=str(payload.get("runtime_lane") or ""),
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
