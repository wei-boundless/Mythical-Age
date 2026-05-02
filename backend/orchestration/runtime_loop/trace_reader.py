from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .checkpoint import RuntimeCheckpointStore
from .event_log import RuntimeEventLog
from .events import RuntimeEvent
from .models import TaskRun
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
        return {
            "task_run": task_run.to_dict(),
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
        return {
            "task_run": task_run.to_dict(),
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
        template = dict(payload.get("selected_template") or {})
        task_spec = dict(payload.get("task_spec") or {})
        task_run_ledger = dict(payload.get("task_run_ledger") or {})
        summary.update(
            {
                "task_id": str(contract.get("task_id") or ""),
                "session_id": str(contract.get("session_id") or ""),
                "template_id": str(contract.get("template_id") or template.get("template_id") or ""),
                "task_spec_ref": str(contract.get("task_spec_ref") or task_spec.get("task_spec_ref") or ""),
                "requested_outputs": list(task_spec.get("requested_outputs") or []),
                "step_count": len(list(task_run_ledger.get("step_runs") or [])),
                "user_goal_chars": len(str(contract.get("user_goal") or "")),
                "source": str(payload.get("source") or ""),
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
