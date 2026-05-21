from __future__ import annotations

from collections import Counter
from typing import Any


RUNTIME_STAGE_ORDER = (
    "task_run_started",
    "task_contract_built",
    "memory_runtime_view_built",
    "stage_projection_built",
    "context_snapshot_built",
    "context_invariant_checked",
    "runtime_directive_issued",
    "operation_gate_checked",
    "executor_started",
    "tool_call_requested",
    "execution_record_created",
    "execution_dispatch_started",
    "tool_result_received",
    "execution_result_recorded",
    "executor_observation_received",
    "output_boundary_applied",
    "commit_gate_checked",
    "loop_terminal",
)


def summarize_runtime_loop_trace(trace: dict[str, Any] | None) -> dict[str, Any]:
    """Build the orchestration-owned monitor view for one TaskRun trace."""

    if not trace:
        return _empty_summary()
    task_run = dict(trace.get("task_run") or {})
    events = [_event_dict(item) for item in list(trace.get("events") or [])]
    checkpoint = dict(trace.get("latest_checkpoint") or {})
    loop_state = dict(checkpoint.get("loop_state") or {})
    commit_state = dict(loop_state.get("commit_state") or checkpoint.get("commit_state") or {})
    event_counts = Counter(str(item.get("event_type") or "") for item in events)
    gate_events = [item for item in events if str(item.get("event_type") or "") == "operation_gate_checked"]
    tool_call_events = [item for item in events if str(item.get("event_type") or "") == "tool_call_requested"]
    tool_result_events = [item for item in events if str(item.get("event_type") or "") == "tool_result_received"]
    execution_events = [
        item
        for item in events
        if str(item.get("event_type") or "")
        in {
            "execution_record_created",
            "execution_dispatch_started",
            "execution_result_recorded",
            "execution_result_reused",
            "replay_guard_triggered",
            "recovery_replay_decided",
        }
    ]
    commit_events = [item for item in events if str(item.get("event_type") or "") == "commit_gate_checked"]
    terminal = next((item for item in reversed(events) if str(item.get("event_type") or "") == "loop_terminal"), {})
    terminal_summary = _summary(terminal)
    return {
        "task_run_id": str(task_run.get("task_run_id") or ""),
        "status": str(task_run.get("status") or terminal_summary.get("status") or "unknown"),
        "terminal_reason": str(task_run.get("terminal_reason") or terminal_summary.get("terminal_reason") or ""),
        "event_count": len(events),
        "latest_event_type": str(events[-1].get("event_type") if events else ""),
        "event_type_counts": dict(sorted(event_counts.items())),
        "operation_gate": {
            "check_count": len(gate_events),
            "allowed_count": sum(1 for item in gate_events if bool(_summary(item).get("allowed") is True)),
            "denied_count": sum(1 for item in gate_events if bool(_summary(item).get("allowed") is False)),
            "operations": [_summary(item).get("operation_id") for item in gate_events if _summary(item).get("operation_id")],
        },
        "tools": {
            "call_count": len(tool_call_events),
            "result_count": len(tool_result_events),
            "requested": [_summary(item).get("tool_name") for item in tool_call_events if _summary(item).get("tool_name")],
            "pairing_ok": len(tool_call_events) == len(tool_result_events),
        },
        "executions": {
            "event_count": len(execution_events),
            "reused_count": sum(
                1 for item in execution_events if str(item.get("event_type") or "") == "execution_result_reused"
            ),
            "suppressed_count": sum(
                1 for item in execution_events if str(item.get("event_type") or "") == "replay_guard_triggered"
            ),
        },
        "commits": {
            "check_count": len(commit_events),
            "assistant_session_write_allowed": bool(commit_state.get("assistant_session_write_allowed") is True),
            "assistant_session_write_applied": bool(commit_state.get("assistant_session_write_applied") is True),
            "task_result_final": bool(commit_state.get("task_result_final")),
            "artifact_write_allowed": bool(commit_state.get("artifact_write_allowed") is True),
        },
        "memory": {
            "memory_write_allowed": bool(commit_state.get("memory_write_allowed") is True),
            "session_memory_refresh_applied": bool(commit_state.get("session_memory_refresh_applied") is True),
            "durable_memory_commit_applied": bool(commit_state.get("durable_memory_commit_applied") is True),
            "session_memory_chars": int(commit_state.get("session_memory_chars") or 0),
            "durable_saved_count": int(commit_state.get("durable_saved_count") or 0),
        },
        "checkpoints": {
            "latest_checkpoint_id": str(checkpoint.get("checkpoint_id") or ""),
            "event_offset": int(checkpoint.get("event_offset") or -1),
            "status": str(loop_state.get("status") or ""),
            "turn_count": int(loop_state.get("turn_count") or 0),
            "step_count": int(loop_state.get("step_count") or 0),
        },
        "stages": [
            {
                "event_type": event_type,
                "seen": event_counts.get(event_type, 0) > 0,
                "count": int(event_counts.get(event_type, 0)),
            }
            for event_type in RUNTIME_STAGE_ORDER
        ],
        "authority": "runtime_monitor",
    }


def summarize_runtime_loop_events(events: list[dict[str, Any]], *, task_run_id: str = "") -> dict[str, Any]:
    trace = {
        "task_run": {"task_run_id": task_run_id, "status": _status_from_events(events)},
        "events": events,
        "latest_checkpoint": _latest_checkpoint_from_events(events),
    }
    return summarize_runtime_loop_trace(trace)


def _empty_summary() -> dict[str, Any]:
    return {
        "task_run_id": "",
        "status": "unknown",
        "terminal_reason": "",
        "event_count": 0,
        "latest_event_type": "",
        "event_type_counts": {},
        "operation_gate": {"check_count": 0, "allowed_count": 0, "denied_count": 0, "operations": []},
        "tools": {"call_count": 0, "result_count": 0, "requested": [], "pairing_ok": True},
        "executions": {"event_count": 0, "reused_count": 0, "suppressed_count": 0},
        "commits": {
            "check_count": 0,
            "assistant_session_write_allowed": False,
            "assistant_session_write_applied": False,
            "task_result_final": False,
            "artifact_write_allowed": False,
        },
        "memory": {
            "memory_write_allowed": False,
            "session_memory_refresh_applied": False,
            "durable_memory_commit_applied": False,
            "session_memory_chars": 0,
            "durable_saved_count": 0,
        },
        "checkpoints": {"latest_checkpoint_id": "", "event_offset": -1, "status": "", "turn_count": 0, "step_count": 0},
        "stages": [],
        "authority": "runtime_monitor",
    }


def _event_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    return {}


def _summary(item: dict[str, Any]) -> dict[str, Any]:
    return dict(item.get("payload_summary") or item.get("summary") or _payload_summary_from_payload(item))


def _payload_summary_from_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload = dict(item.get("payload") or {})
    event_type = str(item.get("event_type") or "")
    if event_type == "operation_gate_checked":
        gate = dict(payload.get("gate") or {})
        return {
            "operation_id": str(gate.get("operation_id") or ""),
            "allowed": bool(gate.get("allowed") is True),
            "reason": str(gate.get("reason") or ""),
        }
    if event_type == "tool_call_requested":
        action = dict(payload.get("action_request") or {})
        action_payload = dict(action.get("payload") or {})
        return {"tool_name": str(action_payload.get("tool_name") or "")}
    if event_type == "loop_terminal":
        return {
            "status": str(payload.get("status") or ""),
            "terminal_reason": str(payload.get("terminal_reason") or ""),
        }
    return {}


def _latest_checkpoint_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    for item in reversed(events):
        if str(item.get("event_type") or "") != "checkpoint_written":
            continue
        payload = dict(item.get("payload") or {})
        return {
            "checkpoint_id": str(payload.get("checkpoint_id") or ""),
            "event_offset": int(payload.get("event_offset") or item.get("offset") or -1),
            "loop_state": dict(payload.get("loop_state") or {}),
            "commit_state": dict(payload.get("commit_state") or {}),
        }
    return {}


def _status_from_events(events: list[dict[str, Any]]) -> str:
    for item in reversed(events):
        if str(item.get("event_type") or "") != "loop_terminal":
            continue
        return str(_summary(item).get("status") or "unknown")
    return "unknown"
