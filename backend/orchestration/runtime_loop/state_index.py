from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .models import (
    AgentHandoffEnvelope,
    AgentRun,
    AgentRunResult,
    CoordinationMergeResult,
    CoordinationNodeRun,
    CoordinationRun,
    TaskRun,
)
from ..worker_agent_blueprints import WorkerAgentSpawnRequest, WorkerAgentSpawnResult


class RuntimeStateIndex:
    """Fast lookup index for latest runtime formal objects."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.index_path = self.root_dir / "state_index.json"
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def upsert_task_run(self, task_run: TaskRun) -> None:
        payload = self._read()
        task_runs = dict(payload.get("task_runs") or {})
        task_runs[task_run.task_run_id] = task_run.to_dict()
        payload["task_runs"] = task_runs
        sessions = dict(payload.get("sessions") or {})
        session_runs = list(sessions.get(task_run.session_id) or [])
        if task_run.task_run_id not in session_runs:
            session_runs.append(task_run.task_run_id)
        sessions[task_run.session_id] = session_runs
        payload["sessions"] = sessions
        payload["updated_at"] = time.time()
        self._atomic_write(payload)

    def upsert_agent_run(self, agent_run: AgentRun) -> None:
        payload = self._read()
        agent_runs = dict(payload.get("agent_runs") or {})
        agent_runs[agent_run.agent_run_id] = agent_run.to_dict()
        payload["agent_runs"] = agent_runs
        task_agent_runs = dict(payload.get("task_agent_runs") or {})
        agent_run_ids = list(task_agent_runs.get(agent_run.task_run_id) or [])
        if agent_run.agent_run_id not in agent_run_ids:
            agent_run_ids.append(agent_run.agent_run_id)
        task_agent_runs[agent_run.task_run_id] = agent_run_ids
        payload["task_agent_runs"] = task_agent_runs
        payload["updated_at"] = time.time()
        self._atomic_write(payload)

    def upsert_agent_run_result(self, result: AgentRunResult) -> None:
        payload = self._read()
        results = dict(payload.get("agent_run_results") or {})
        results[result.agent_run_result_id] = result.to_dict()
        payload["agent_run_results"] = results
        task_agent_run_results = dict(payload.get("task_agent_run_results") or {})
        result_ids = list(task_agent_run_results.get(result.task_run_id) or [])
        if result.agent_run_result_id not in result_ids:
            result_ids.append(result.agent_run_result_id)
        task_agent_run_results[result.task_run_id] = result_ids
        payload["task_agent_run_results"] = task_agent_run_results
        payload["updated_at"] = time.time()
        self._atomic_write(payload)

    def upsert_coordination_run(self, coordination_run: CoordinationRun) -> None:
        payload = self._read()
        coordination_runs = dict(payload.get("coordination_runs") or {})
        coordination_runs[coordination_run.coordination_run_id] = coordination_run.to_dict()
        payload["coordination_runs"] = coordination_runs
        task_coordination_runs = dict(payload.get("task_coordination_runs") or {})
        run_ids = list(task_coordination_runs.get(coordination_run.task_run_id) or [])
        if coordination_run.coordination_run_id not in run_ids:
            run_ids.append(coordination_run.coordination_run_id)
        task_coordination_runs[coordination_run.task_run_id] = run_ids
        payload["task_coordination_runs"] = task_coordination_runs
        payload["updated_at"] = time.time()
        self._atomic_write(payload)

    def upsert_coordination_node_run(self, node_run: CoordinationNodeRun) -> None:
        payload = self._read()
        node_runs = dict(payload.get("coordination_node_runs") or {})
        node_runs[node_run.node_run_id] = node_run.to_dict()
        payload["coordination_node_runs"] = node_runs
        coordination_node_runs = dict(payload.get("coordination_node_run_index") or {})
        node_ids = list(coordination_node_runs.get(node_run.coordination_run_id) or [])
        if node_run.node_run_id not in node_ids:
            node_ids.append(node_run.node_run_id)
        coordination_node_runs[node_run.coordination_run_id] = node_ids
        payload["coordination_node_run_index"] = coordination_node_runs
        payload["updated_at"] = time.time()
        self._atomic_write(payload)

    def upsert_handoff_envelope(self, handoff: AgentHandoffEnvelope) -> None:
        payload = self._read()
        handoffs = dict(payload.get("handoff_envelopes") or {})
        handoffs[handoff.handoff_id] = handoff.to_dict()
        payload["handoff_envelopes"] = handoffs
        coordination_handoffs = dict(payload.get("coordination_handoffs") or {})
        handoff_ids = list(coordination_handoffs.get(handoff.coordination_run_id) or [])
        if handoff.handoff_id not in handoff_ids:
            handoff_ids.append(handoff.handoff_id)
        coordination_handoffs[handoff.coordination_run_id] = handoff_ids
        payload["coordination_handoffs"] = coordination_handoffs
        payload["updated_at"] = time.time()
        self._atomic_write(payload)

    def upsert_coordination_merge_result(self, result: CoordinationMergeResult) -> None:
        payload = self._read()
        results = dict(payload.get("coordination_merge_results") or {})
        results[result.merge_result_id] = result.to_dict()
        payload["coordination_merge_results"] = results
        payload["updated_at"] = time.time()
        self._atomic_write(payload)

    def upsert_worker_spawn_request(self, request: WorkerAgentSpawnRequest) -> None:
        payload = self._read()
        requests = dict(payload.get("worker_spawn_requests") or {})
        requests[request.spawn_request_id] = request.to_dict()
        payload["worker_spawn_requests"] = requests
        task_index = dict(payload.get("task_worker_spawn_requests") or {})
        request_ids = list(task_index.get(request.task_run_id) or [])
        if request.spawn_request_id not in request_ids:
            request_ids.append(request.spawn_request_id)
        task_index[request.task_run_id] = request_ids
        payload["task_worker_spawn_requests"] = task_index
        payload["updated_at"] = time.time()
        self._atomic_write(payload)

    def upsert_worker_spawn_result(self, result: WorkerAgentSpawnResult) -> None:
        payload = self._read()
        results = dict(payload.get("worker_spawn_results") or {})
        results[result.spawn_result_id] = result.to_dict()
        payload["worker_spawn_results"] = results
        task_index = dict(payload.get("task_worker_spawn_results") or {})
        result_ids = list(task_index.get(result.task_run_id) or [])
        if result.spawn_result_id not in result_ids:
            result_ids.append(result.spawn_result_id)
        task_index[result.task_run_id] = result_ids
        payload["task_worker_spawn_results"] = task_index
        payload["updated_at"] = time.time()
        self._atomic_write(payload)

    def get_task_run(self, task_run_id: str) -> TaskRun | None:
        task_run = dict((self._read().get("task_runs") or {}).get(task_run_id) or {})
        if not task_run:
            return None
        return _task_run_from_payload(task_run)

    def list_session_task_runs(self, session_id: str) -> list[TaskRun]:
        payload = self._read()
        task_runs = dict(payload.get("task_runs") or {})
        ids = list((payload.get("sessions") or {}).get(session_id) or [])
        return [_task_run_from_payload(task_runs[item]) for item in ids if item in task_runs]

    def list_task_agent_runs(self, task_run_id: str) -> list[AgentRun]:
        payload = self._read()
        agent_runs = dict(payload.get("agent_runs") or {})
        ids = list((payload.get("task_agent_runs") or {}).get(task_run_id) or [])
        return [_agent_run_from_payload(agent_runs[item]) for item in ids if item in agent_runs]

    def list_task_coordination_runs(self, task_run_id: str) -> list[CoordinationRun]:
        payload = self._read()
        coordination_runs = dict(payload.get("coordination_runs") or {})
        ids = list((payload.get("task_coordination_runs") or {}).get(task_run_id) or [])
        return [_coordination_run_from_payload(coordination_runs[item]) for item in ids if item in coordination_runs]

    def list_task_agent_run_results(self, task_run_id: str) -> list[AgentRunResult]:
        payload = self._read()
        results = dict(payload.get("agent_run_results") or {})
        ids = list((payload.get("task_agent_run_results") or {}).get(task_run_id) or [])
        return [_agent_run_result_from_payload(results[item]) for item in ids if item in results]

    def list_coordination_node_runs(self, coordination_run_id: str) -> list[CoordinationNodeRun]:
        payload = self._read()
        node_runs = dict(payload.get("coordination_node_runs") or {})
        ids = list((payload.get("coordination_node_run_index") or {}).get(coordination_run_id) or [])
        return [_coordination_node_run_from_payload(node_runs[item]) for item in ids if item in node_runs]

    def list_coordination_handoffs(self, coordination_run_id: str) -> list[AgentHandoffEnvelope]:
        payload = self._read()
        handoffs = dict(payload.get("handoff_envelopes") or {})
        ids = list((payload.get("coordination_handoffs") or {}).get(coordination_run_id) or [])
        return [_handoff_from_payload(handoffs[item]) for item in ids if item in handoffs]

    def get_latest_coordination_merge_result(self, coordination_run_id: str) -> CoordinationMergeResult | None:
        payload = self._read()
        results = dict(payload.get("coordination_merge_results") or {})
        matches = [
            _coordination_merge_result_from_payload(item)
            for item in results.values()
            if isinstance(item, dict) and str(item.get("coordination_run_id") or "") == coordination_run_id
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.created_at, reverse=True)[0]

    def list_task_worker_spawn_requests(self, task_run_id: str) -> list[WorkerAgentSpawnRequest]:
        payload = self._read()
        requests = dict(payload.get("worker_spawn_requests") or {})
        ids = list((payload.get("task_worker_spawn_requests") or {}).get(task_run_id) or [])
        return [_worker_spawn_request_from_payload(requests[item]) for item in ids if item in requests]

    def list_task_worker_spawn_results(self, task_run_id: str) -> list[WorkerAgentSpawnResult]:
        payload = self._read()
        results = dict(payload.get("worker_spawn_results") or {})
        ids = list((payload.get("task_worker_spawn_results") or {}).get(task_run_id) or [])
        return [_worker_spawn_result_from_payload(results[item]) for item in ids if item in results]

    def _read(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return {
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
                "updated_at": 0.0,
            }
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def _atomic_write(self, payload: dict[str, Any]) -> None:
        tmp = self.index_path.with_suffix(f"{self.index_path.suffix}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.index_path)


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


def _agent_run_from_payload(payload: dict[str, Any]) -> AgentRun:
    return AgentRun(
        agent_run_id=str(payload.get("agent_run_id") or ""),
        task_run_id=str(payload.get("task_run_id") or ""),
        agent_id=str(payload.get("agent_id") or ""),
        agent_profile_id=str(payload.get("agent_profile_id") or ""),
        role=str(payload.get("role") or "main_executor"),
        spawn_mode=str(payload.get("spawn_mode") or "adopt_existing"),
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
        coordination_task_ref=str(payload.get("coordination_task_ref") or ""),
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
