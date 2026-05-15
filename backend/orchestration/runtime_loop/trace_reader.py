from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .checkpoint import RuntimeCheckpointStore
from .event_log import RuntimeEventLog
from .events import RuntimeEvent
from .models import CoordinationRun, TaskRun
from .state_index import RuntimeStateIndex


@dataclass(frozen=True, slots=True)
class RuntimeLoopTraceReader:
    """Read-only view over TaskRunLoop event/checkpoint traces."""

    state_index: RuntimeStateIndex
    event_log: RuntimeEventLog
    checkpoints: RuntimeCheckpointStore

    def list_session_task_runs(self, session_id: str) -> dict[str, Any]:
        task_runs = sorted(
            self.state_index.list_session_task_runs(session_id),
            key=lambda item: item.updated_at,
            reverse=True,
        )
        return {
            "session_id": session_id,
            "task_run_count": len(task_runs),
            "task_runs": [self._task_run_summary(item) for item in task_runs],
            "authority": "orchestration.runtime_loop_trace_reader",
        }

    def get_session_live_monitor(self, session_id: str) -> dict[str, Any]:
        task_runs = sorted(
            self.state_index.list_session_task_runs(session_id),
            key=lambda item: item.updated_at,
            reverse=True,
        )
        latest = task_runs[0] if task_runs else None
        return {
            "session_id": session_id,
            "task_run_count": len(task_runs),
            "latest_task_run_id": latest.task_run_id if latest is not None else "",
            "monitor": self.get_task_run_live_monitor(latest.task_run_id) if latest is not None else None,
            "authority": "orchestration.runtime_loop_live_monitor",
        }

    def get_task_run_live_monitor(self, task_run_id: str) -> dict[str, Any] | None:
        task_run = self.state_index.get_task_run(task_run_id)
        if task_run is None:
            return None
        checkpoint = self.checkpoints.load_latest(task_run_id)
        coordination_runs = sorted(
            self.state_index.list_task_coordination_runs(task_run_id),
            key=lambda item: item.updated_at,
            reverse=True,
        )
        active_coordination_run = _pick_coordination_run(coordination_runs)
        coordination_view = None
        if active_coordination_run is not None:
            node_runs = sorted(
                self.state_index.list_coordination_node_runs(active_coordination_run.coordination_run_id),
                key=lambda item: (item.updated_at, item.node_id),
                reverse=False,
            )
            handoffs = sorted(
                self.state_index.list_coordination_handoffs(active_coordination_run.coordination_run_id),
                key=lambda item: item.created_at,
                reverse=False,
            )
            merge_result = self.state_index.get_latest_coordination_merge_result(active_coordination_run.coordination_run_id)
            diagnostics = dict(active_coordination_run.diagnostics or {})
            coordination_view = {
                **active_coordination_run.to_dict(),
                "coordination_flow": dict(diagnostics.get("coordination_flow") or {}),
                "langgraph_runtime_state": dict(diagnostics.get("langgraph_runtime_state") or {}),
                "task_graph_scheduler_state": dict(diagnostics.get("task_graph_scheduler_state") or {}),
                "coordination_graph_spec": dict(diagnostics.get("coordination_graph_spec") or {}),
                "node_runs": [item.to_dict() for item in node_runs],
                "handoff_envelopes": [item.to_dict() for item in handoffs],
                "latest_merge_result": merge_result.to_dict() if merge_result is not None else None,
            }
        loop_state = checkpoint.loop_state.to_dict() if checkpoint is not None else {}
        return {
            "task_run": task_run.to_dict(),
            "latest_checkpoint": checkpoint.to_dict() if checkpoint is not None else None,
            "loop_state": loop_state,
            "coordination_run": coordination_view,
            "has_coordination": coordination_view is not None,
            "status": str(task_run.status or loop_state.get("status") or "unknown"),
            "terminal_reason": str(task_run.terminal_reason or loop_state.get("terminal_reason") or ""),
            "updated_at": float(
                max(
                    task_run.updated_at or 0.0,
                    checkpoint.created_at if checkpoint is not None else 0.0,
                    active_coordination_run.updated_at if active_coordination_run is not None else 0.0,
                )
            ),
            "authority": "orchestration.runtime_loop_live_monitor",
        }

    def get_task_run_trace(
        self,
        task_run_id: str,
        *,
        include_payloads: bool = False,
        include_model_messages: bool = False,
    ) -> dict[str, Any] | None:
        task_run = self.state_index.get_task_run(task_run_id)
        if task_run is None:
            return None
        events = self.event_log.list_events(task_run_id)
        checkpoint = self.checkpoints.load_latest(task_run_id)
        agent_runs = self.state_index.list_task_agent_runs(task_run_id)
        coordination_runs = self.state_index.list_task_coordination_runs(task_run_id)
        return {
            "task_run": task_run.to_dict(),
            "agent_runs": [item.to_dict() for item in agent_runs],
            "agent_run_results": [item.to_dict() for item in self.state_index.list_task_agent_run_results(task_run_id)],
            "agent_delegation_requests": [
                item.to_dict() for item in self.state_index.list_task_agent_delegation_requests(task_run_id)
            ],
            "agent_delegation_results": [
                item.to_dict() for item in self.state_index.list_task_agent_delegation_results(task_run_id)
            ],
            "worker_spawn_requests": [
                item.to_dict() for item in self.state_index.list_task_worker_spawn_requests(task_run_id)
            ],
            "worker_spawn_results": [
                item.to_dict() for item in self.state_index.list_task_worker_spawn_results(task_run_id)
            ],
            "coordination_runs": [
                {
                    **item.to_dict(),
                    "node_runs": [node.to_dict() for node in self.state_index.list_coordination_node_runs(item.coordination_run_id)],
                    "handoff_envelopes": [
                        handoff.to_dict()
                        for handoff in self.state_index.list_coordination_handoffs(item.coordination_run_id)
                    ],
                    "latest_merge_result": (
                        self.state_index.get_latest_coordination_merge_result(item.coordination_run_id).to_dict()
                        if self.state_index.get_latest_coordination_merge_result(item.coordination_run_id) is not None
                        else None
                    ),
                }
                for item in coordination_runs
            ],
            "event_count": len(events),
            "events": [
                _event_view(
                    event,
                    include_payloads=include_payloads,
                    include_model_messages=include_model_messages,
                )
                for event in events
            ],
            "latest_checkpoint": checkpoint.to_dict() if checkpoint is not None else None,
            "trace_policy": {
                "payloads_included": include_payloads,
                "model_messages_included": include_model_messages,
                "default_redaction": "model_messages_and_section_content_are_summarized",
            },
            "authority": "orchestration.runtime_loop_trace_reader",
        }

    def _task_run_summary(self, task_run: TaskRun) -> dict[str, Any]:
        events = self.event_log.list_events(task_run.task_run_id)
        checkpoint = self.checkpoints.load_latest(task_run.task_run_id)
        agent_runs = self.state_index.list_task_agent_runs(task_run.task_run_id)
        coordination_runs = self.state_index.list_task_coordination_runs(task_run.task_run_id)
        return {
            "task_run": task_run.to_dict(),
            "agent_run_count": len(agent_runs),
            "coordination_run_count": len(coordination_runs),
            "event_count": len(events),
            "latest_event_type": events[-1].event_type if events else "",
            "latest_checkpoint": checkpoint.to_dict() if checkpoint is not None else None,
        }


def _event_view(
    event: RuntimeEvent,
    *,
    include_payloads: bool,
    include_model_messages: bool,
) -> dict[str, Any]:
    payload = dict(event.payload or {})
    view = {
        "event_id": event.event_id,
        "task_run_id": event.task_run_id,
        "event_type": event.event_type,
        "offset": event.offset,
        "created_at": event.created_at,
        "refs": dict(event.refs or {}),
    }
    if include_payloads:
        view["payload"] = _sanitize_payload(payload, include_model_messages=include_model_messages)
    else:
        view["payload_summary"] = _payload_summary(event.event_type, payload)
    return view


def _pick_coordination_run(coordination_runs: list[CoordinationRun]) -> CoordinationRun | None:
    if not coordination_runs:
        return None
    for status in ("running", "waiting", "pending"):
        for item in coordination_runs:
            if item.status == status:
                return item
    return coordination_runs[0]


def _payload_summary(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"keys": sorted(str(key) for key in payload.keys())}
    if event_type == "context_snapshot_built":
        snapshot = dict(payload.get("context_snapshot") or {})
        summary.update(
            {
                "snapshot_id": str(snapshot.get("snapshot_id") or ""),
                "model_message_count": len(list(snapshot.get("model_messages") or [])),
                "history_message_count": int(snapshot.get("history_message_count") or 0),
                "pending_user_message_chars": int(snapshot.get("pending_user_message_chars") or 0),
                "system_prompt_chars": int(snapshot.get("system_prompt_chars") or 0),
                "context_policy_ref": str(snapshot.get("context_policy_ref") or ""),
                "memory_runtime_view_ref": str(snapshot.get("memory_runtime_view_ref") or ""),
                "projection_ref": str(snapshot.get("projection_ref") or ""),
                "prompt_manifest_ref": str(snapshot.get("prompt_manifest_ref") or ""),
                "token_pressure": dict(snapshot.get("token_pressure") or {}),
            }
        )
    elif event_type == "stage_projection_built":
        projection = dict(payload.get("stage_projection") or {})
        summary.update(
            {
                "snapshot_id": str(projection.get("snapshot_id") or ""),
                "projection_ref": str(projection.get("projection_ref") or ""),
                "prompt_manifest_ref": str(projection.get("prompt_manifest_ref") or ""),
                "visible_tool_ids": list(projection.get("visible_tool_ids") or []),
                "visible_skill_ids": list(projection.get("visible_skill_ids") or []),
                "visible_section_count": int(projection.get("visible_section_count") or 0),
            }
        )
    elif event_type == "context_invariant_checked":
        report = dict(payload.get("invariant_report") or {})
        summary.update(
            {
                "report_id": str(report.get("report_id") or ""),
                "snapshot_ref": str(report.get("snapshot_ref") or ""),
                "tool_result_pairing_ok": bool(report.get("tool_result_pairing_ok") is True),
                "needs_compaction": bool(report.get("needs_compaction") is True),
                "compaction_reason": str(report.get("compaction_reason") or ""),
                "token_pressure": dict(report.get("token_pressure") or {}),
            }
        )
    elif event_type == "task_contract_built":
        contract = dict(payload.get("task_contract") or {})
        recipe = dict(payload.get("selected_recipe") or {})
        task_spec = dict(payload.get("task_spec") or {})
        task_run_ledger = dict(payload.get("task_run_ledger") or {})
        summary.update(
            {
                "task_id": str(contract.get("task_id") or ""),
                "session_id": str(contract.get("session_id") or ""),
                "template_id": str(contract.get("template_id") or recipe.get("template_id") or ""),
                "task_spec_ref": str(contract.get("task_spec_ref") or task_spec.get("task_spec_ref") or ""),
                "requested_outputs": list(task_spec.get("requested_outputs") or []),
                "step_count": len(list(task_run_ledger.get("step_runs") or [])),
                "user_goal_chars": len(str(contract.get("user_goal") or "")),
                "adoption_plan_ref": str(dict(payload.get("task_agent_adoption_plan") or {}).get("plan_id") or ""),
                "graph_ref": str(
                    dict(payload.get("task_graph_record") or {}).get("graph_id")
                    or dict(payload.get("graph_record") or {}).get("graph_id")
                    or ""
                ),
                "source": str(payload.get("source") or ""),
            }
        )
    elif event_type == "agent_run_created":
        agent_run = dict(payload.get("agent_run") or {})
        summary.update(
            {
                "agent_run_id": str(agent_run.get("agent_run_id") or ""),
                "agent_id": str(agent_run.get("agent_id") or ""),
                "role": str(agent_run.get("role") or ""),
                "spawn_mode": str(agent_run.get("spawn_mode") or ""),
                "status": str(agent_run.get("status") or ""),
            }
        )
    elif event_type == "coordination_run_created":
        coordination_run = dict(payload.get("coordination_run") or {})
        summary.update(
            {
                "coordination_run_id": str(coordination_run.get("coordination_run_id") or ""),
                "graph_ref": str(coordination_run.get("graph_ref") or ""),
                "coordinator_agent_id": str(coordination_run.get("coordinator_agent_id") or ""),
                "topology_template_id": str(coordination_run.get("topology_template_id") or ""),
                "communication_protocol_id": str(coordination_run.get("communication_protocol_id") or ""),
                "status": str(coordination_run.get("status") or ""),
            }
        )
    elif event_type == "worker_agent_spawn_requested":
        request = dict(payload.get("worker_spawn_request") or {})
        summary.update(
            {
                "spawn_request_id": str(request.get("spawn_request_id") or ""),
                "blueprint_id": str(request.get("blueprint_id") or ""),
                "requested_agent_name": str(request.get("requested_agent_name") or ""),
                "runtime_lane": str(request.get("runtime_lane") or ""),
                "requested_by_agent_id": str(request.get("requested_by_agent_id") or ""),
            }
        )
    elif event_type == "worker_agent_spawn_completed":
        result = dict(payload.get("worker_spawn_result") or {})
        summary.update(
            {
                "spawn_result_id": str(result.get("spawn_result_id") or ""),
                "spawn_request_id": str(result.get("spawn_request_id") or ""),
                "spawned_agent_id": str(result.get("spawned_agent_id") or ""),
                "spawned_agent_run_ref": str(result.get("spawned_agent_run_ref") or ""),
                "status": str(result.get("status") or ""),
            }
        )
    elif event_type == "agent_delegation_requested":
        request = dict(payload.get("agent_delegation_request") or {})
        summary.update(
            {
                "request_id": str(request.get("request_id") or ""),
                "source_agent_id": str(request.get("source_agent_id") or ""),
                "target_agent_id": str(request.get("target_agent_id") or ""),
                "delegation_kind": str(request.get("delegation_kind") or ""),
            }
        )
    elif event_type == "agent_delegation_result_created":
        result = dict(payload.get("agent_delegation_result") or {})
        summary.update(
            {
                "result_id": str(result.get("result_id") or ""),
                "request_id": str(result.get("request_id") or ""),
                "target_agent_id": str(result.get("target_agent_id") or ""),
                "status": str(result.get("status") or ""),
            }
        )
    elif event_type == "coordination_node_run_created":
        node_run = dict(payload.get("coordination_node_run") or {})
        summary.update(
            {
                "node_run_id": str(node_run.get("node_run_id") or ""),
                "node_id": str(node_run.get("node_id") or ""),
                "assigned_agent_id": str(node_run.get("assigned_agent_id") or ""),
                "assigned_agent_run_ref": str(node_run.get("assigned_agent_run_ref") or ""),
                "status": str(node_run.get("status") or ""),
            }
        )
    elif event_type == "coordination_node_run_updated":
        node_run = dict(payload.get("coordination_node_run") or {})
        summary.update(
            {
                "node_run_id": str(node_run.get("node_run_id") or ""),
                "node_id": str(node_run.get("node_id") or ""),
                "status": str(node_run.get("status") or ""),
                "assigned_agent_run_ref": str(node_run.get("assigned_agent_run_ref") or ""),
            }
        )
    elif event_type == "handoff_envelope_created":
        handoff = dict(payload.get("handoff_envelope") or {})
        summary.update(
            {
                "handoff_id": str(handoff.get("handoff_id") or ""),
                "source_agent_run_ref": str(handoff.get("source_agent_run_ref") or ""),
                "target_agent_run_ref": str(handoff.get("target_agent_run_ref") or ""),
                "protocol_id": str(handoff.get("protocol_id") or ""),
                "message_type": str(handoff.get("message_type") or ""),
                "ack_state": str(handoff.get("ack_state") or ""),
            }
        )
    elif event_type == "coordination_merge_result_created":
        merge_result = dict(payload.get("coordination_merge_result") or {})
        summary.update(
            {
                "merge_result_id": str(merge_result.get("merge_result_id") or ""),
                "merge_policy": str(merge_result.get("merge_policy") or ""),
                "accepted": bool(merge_result.get("accepted") is True),
                "final_result_ref": str(merge_result.get("final_result_ref") or ""),
            }
        )
    elif event_type in {"coordination_flow_registered", "coordination_flow_finalized"}:
        flow = dict(payload.get("coordination_flow") or {})
        summary.update(
            {
                "current_stage_id": str(flow.get("current_stage_id") or ""),
                "stage_count": len(list(flow.get("stages") or [])),
                "revision_loop_enabled": bool(flow.get("revision_loop_enabled") is True),
                "completed_revision_cycles": int(flow.get("completed_revision_cycles") or 0),
                "accepted": bool(flow.get("accepted") is True),
            }
        )
    elif event_type == "coordination_stage_updated":
        stage = dict(payload.get("stage") or {})
        summary.update(
            {
                "stage_id": str(stage.get("stage_id") or ""),
                "node_id": str(stage.get("node_id") or ""),
                "message_type": str(stage.get("message_type") or ""),
                "status": str(stage.get("status") or ""),
            }
        )
    elif event_type == "memory_runtime_view_built":
        summary.update(
            {
                "memory_runtime_view_ref": str(payload.get("memory_runtime_view_ref") or ""),
                "conversation_candidate_count": int(payload.get("conversation_candidate_count") or 0),
                "state_candidate_count": int(payload.get("state_candidate_count") or 0),
                "long_term_candidate_count": int(payload.get("long_term_candidate_count") or 0),
            }
        )
    elif event_type == "runtime_directive_issued":
        directive = dict(payload.get("directive") or {})
        policy = dict(payload.get("resource_policy") or {})
        summary.update(
            {
                "directive_id": str(directive.get("directive_id") or ""),
                "directive_kind": str(directive.get("kind") or directive.get("directive_type") or ""),
                "resource_policy_id": str(policy.get("policy_id") or ""),
            }
        )
    elif event_type == "operation_gate_checked":
        gate = dict(payload.get("gate") or {})
        summary.update(
            {
                "operation_id": str(gate.get("operation_id") or ""),
                "allowed": bool(gate.get("allowed") is True),
                "reason": str(gate.get("reason") or ""),
            }
        )
    elif event_type == "loop_control_checked":
        control = dict(payload.get("control") or {})
        snapshot = dict(control.get("snapshot") or {})
        summary.update(
            {
                "allowed": bool(control.get("allowed") is True),
                "reason": str(control.get("reason") or ""),
                "turn_count": int(snapshot.get("turn_count") or 0),
                "model_call_count": int(snapshot.get("model_call_count") or 0),
                "event_count": int(snapshot.get("event_count") or 0),
                "elapsed_seconds": float(snapshot.get("elapsed_seconds") or 0.0),
            }
        )
    elif event_type == "executor_observation_received":
        observation = dict(payload.get("observation") or {})
        context_record = dict(payload.get("context_record") or {})
        summary.update(
            {
                "observation_id": str(observation.get("observation_id") or ""),
                "observation_type": str(observation.get("observation_type") or ""),
                "source": str(payload.get("source") or observation.get("source") or ""),
                "content_chars": int(payload.get("content_chars") or observation.get("content_chars") or 0),
                "needs_model_followup": bool(observation.get("needs_model_followup") is True),
                "context_record_id": str(context_record.get("record_id") or ""),
                "context_update_mode": str(dict(context_record.get("context_update") or {}).get("mode") or ""),
            }
        )
    elif event_type == "tool_call_requested":
        action_request = dict(payload.get("action_request") or {})
        request_payload = dict(action_request.get("payload") or {})
        summary.update(
            {
                "request_id": str(action_request.get("request_id") or ""),
                "request_type": str(action_request.get("request_type") or ""),
                "tool_name": str(request_payload.get("tool_name") or ""),
                "execution_state": str(request_payload.get("execution_state") or ""),
            }
        )
    elif event_type in {
        "execution_record_created",
        "execution_dispatch_started",
        "execution_result_recorded",
        "execution_result_reused",
        "replay_guard_triggered",
        "recovery_replay_decided",
    }:
        record = dict(payload.get("execution_record") or {})
        summary.update(
            {
                "execution_id": str(record.get("execution_id") or ""),
                "step_id": str(record.get("step_id") or ""),
                "operation_id": str(record.get("operation_id") or ""),
                "status": str(record.get("status") or ""),
                "replay_policy": str(record.get("replay_policy") or ""),
                "request_ref": str(record.get("request_ref") or ""),
                "result_ref": str(record.get("result_ref") or ""),
                "reason": str(payload.get("reason") or ""),
            }
        )
    elif event_type in {"step_entered", "step_completed", "step_failed", "step_skipped"}:
        step_run = dict(payload.get("step_run") or {})
        summary.update(
            {
                "step_id": str(step_run.get("step_id") or ""),
                "step_kind": str(step_run.get("step_kind") or ""),
                "executor_type": str(step_run.get("executor_type") or ""),
                "status": str(step_run.get("status") or ""),
                "attempt_count": int(step_run.get("attempt_count") or 0),
                "failure_reason": str(step_run.get("failure_reason") or ""),
                "reason": str(payload.get("reason") or ""),
            }
        )
    elif event_type == "task_run_ledger_updated":
        ledger = dict(payload.get("task_run_ledger") or {})
        step_runs = list(ledger.get("step_runs") or [])
        summary.update(
            {
                "ledger_id": str(ledger.get("ledger_id") or ""),
                "status": str(ledger.get("status") or ""),
                "current_step_id": str(ledger.get("current_step_id") or ""),
                "step_count": len(step_runs),
                "completed_step_count": sum(
                    1 for item in step_runs if str(dict(item).get("status") or "") in {"completed", "failed", "skipped"}
                ),
                "reason": str(payload.get("reason") or ""),
            }
        )
    elif event_type == "commit_gate_checked":
        decision = dict(payload.get("commit_decision") or payload.get("commit_gate") or {})
        candidate_payload = dict(dict(decision.get("commit_candidate") or {}).get("payload") or {})
        task_result = dict(candidate_payload.get("task_result") or {})
        summary.update(
            {
                "gate_id": str(decision.get("gate_id") or ""),
                "commit_type": str(decision.get("commit_type") or ""),
                "commit_allowed": bool(decision.get("commit_allowed") is True),
                "reason": str(decision.get("reason") or ""),
                "task_spec_ref": str(candidate_payload.get("task_spec_ref") or task_result.get("task_spec_ref") or ""),
                "template_id": str(candidate_payload.get("template_id") or task_result.get("template_id") or ""),
            }
        )
    elif event_type == "loop_terminal":
        task_result = dict(payload.get("task_result") or {})
        summary.update(
            {
                "status": str(payload.get("status") or ""),
                "terminal_reason": str(payload.get("terminal_reason") or ""),
                "final_content_chars": int(payload.get("final_content_chars") or 0),
                "task_result_ref": str(task_result.get("result_id") or ""),
                "template_id": str(task_result.get("template_id") or ""),
                "requested_outputs": list(task_result.get("requested_outputs") or []),
            }
        )
    elif event_type == "checkpoint_written":
        execution_summary = dict(payload.get("execution_summary") or {})
        runtime_objects_summary = dict(payload.get("runtime_objects_summary") or {})
        summary.update(
            {
                "checkpoint_id": str(payload.get("checkpoint_id") or ""),
                "event_offset": int(payload.get("event_offset") or 0),
                "execution_count": int(execution_summary.get("execution_count") or 0),
                "completed_count": int(execution_summary.get("completed_count") or 0),
                "reused_count": int(execution_summary.get("reused_count") or 0),
                "suppressed_count": int(execution_summary.get("suppressed_count") or 0),
                "agent_run_count": int(runtime_objects_summary.get("agent_run_count") or 0),
                "coordination_run_count": int(runtime_objects_summary.get("coordination_run_count") or 0),
            }
        )
    return summary


def _sanitize_payload(payload: Any, *, include_model_messages: bool) -> Any:
    if isinstance(payload, dict):
        sanitized: dict[str, Any] = {}
        for key, value in payload.items():
            key_text = str(key)
            if key_text == "model_messages" and not include_model_messages:
                sanitized[key_text] = _message_summaries(value)
                continue
            if key_text == "content":
                sanitized[key_text] = {"content_chars": len(str(value or ""))}
                continue
            sanitized[key_text] = _sanitize_payload(value, include_model_messages=include_model_messages)
        return sanitized
    if isinstance(payload, list):
        return [_sanitize_payload(item, include_model_messages=include_model_messages) for item in payload]
    if isinstance(payload, tuple):
        return [_sanitize_payload(item, include_model_messages=include_model_messages) for item in payload]
    return payload


def _message_summaries(value: Any) -> list[dict[str, Any]]:
    messages = []
    for item in list(value or []):
        if not isinstance(item, dict):
            continue
        messages.append(
            {
                "role": str(item.get("role") or ""),
                "content_chars": len(str(item.get("content") or "")),
            }
        )
    return messages
