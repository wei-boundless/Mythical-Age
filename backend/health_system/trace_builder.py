from __future__ import annotations

from typing import Any

from .models import HealthAgentRun, HealthIssue


def build_agent_run_trace_report_payload(
    *,
    run: HealthAgentRun,
    issue: HealthIssue | None,
    result: dict[str, Any] | None,
    trace: dict[str, Any],
) -> dict[str, Any]:
    events = list(trace.get("events") or [])
    event_type_counts: dict[str, int] = {}
    problem_events: list[dict[str, Any]] = []
    for event in events:
        payload = dict(dict(event).get("payload") or {})
        event_type = str(dict(event).get("event_type") or "")
        event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
        if event_type in {"loop_error", "operation_gate_checked", "loop_terminal"}:
            problem_events.append(
                {
                    "event_id": str(dict(event).get("event_id") or ""),
                    "event_type": event_type,
                    "offset": int(dict(event).get("offset") or 0),
                    "summary": summarize_health_event(event_type, payload),
                    "refs": dict(dict(event).get("refs") or {}),
                }
            )
    return {
        "authority": "health_system.trace_report",
        "run": run.to_dict(),
        "issue": issue.to_dict() if issue is not None else None,
        "result": result,
        "event_count": len(events),
        "event_type_counts": event_type_counts,
        "problem_events": problem_events,
        "prompt_manifest_ref": run.prompt_manifest_id,
        "projection_ref": run.projection_id,
        "task_run_trace": trace,
    }


def summarize_health_event(event_type: str, payload: dict[str, Any]) -> str:
    if event_type == "operation_gate_checked":
        gate = dict(payload.get("gate") or {})
        return f"{gate.get('operation_id') or ''}: {gate.get('decision') or ''} / {gate.get('reason') or ''}"
    if event_type == "loop_terminal":
        return f"{payload.get('status') or ''}: {payload.get('terminal_reason') or ''}"
    if event_type == "loop_error":
        return str(payload.get("error") or payload.get("content") or "loop error")
    return event_type


