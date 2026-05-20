from __future__ import annotations

from pathlib import Path
from typing import Any

from health_system.maintenance.experiments.artifacts import read_json_file
from health_system.evidence_extractor import build_runtime_trace_evidence_packet, build_turn_artifact_evidence_packet
from orchestration import summarize_runtime_loop_events, summarize_runtime_loop_trace


def runtime_events_from_sse_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runtime_events: list[dict[str, Any]] = []
    for item in events:
        if not isinstance(item, dict):
            continue
        if str(item.get("event") or "") != "runtime_loop_event":
            continue
        data = dict(item.get("data") or {})
        event = dict(data.get("event") or data)
        if not event:
            continue
        runtime_events.append(event)
    return runtime_events


def runtime_events_from_turn_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    direct = list(payload.get("runtime_loop_events") or [])
    if direct:
        return [dict(item) for item in direct if isinstance(item, dict)]
    return runtime_events_from_sse_events([dict(item) for item in list(payload.get("events") or []) if isinstance(item, dict)])


def runtime_loop_summary_from_turn_payload(payload: dict[str, Any]) -> dict[str, Any]:
    events = runtime_events_from_turn_payload(payload)
    task_run_id = ""
    for item in events:
        task_run_id = str(item.get("task_run_id") or "")
        if task_run_id:
            break
    return summarize_runtime_loop_events(events, task_run_id=task_run_id)


def runtime_loop_summary_from_turn_artifact(path: str | Path) -> dict[str, Any]:
    payload = read_json_file(Path(path), {})
    if not isinstance(payload, dict):
        return summarize_runtime_loop_trace(None)
    return runtime_loop_summary_from_turn_payload(payload)


def runtime_loop_evidence_packet_from_turn_payload(payload: dict[str, Any], *, question: str) -> dict[str, Any]:
    events = runtime_events_from_turn_payload(payload)
    runtime_trace = dict(payload.get("runtime_trace") or {})
    coordination_runs = list(payload.get("coordination_runs") or runtime_trace.get("coordination_runs") or [])
    if not coordination_runs and int(runtime_trace.get("coordination_run_count") or 0) > 0:
        coordination_runs = [
            {
                "coordination_run_id": str(runtime_trace.get("coordination_run_id") or ""),
                "status": str(runtime_trace.get("coordination_status") or ""),
                "graph_ref": str(runtime_trace.get("graph_ref") or ""),
                "latest_checkpoint_ref": str(runtime_trace.get("coordination_checkpoint_ref") or ""),
                "diagnostics": {
                    "coordination_flow": dict(runtime_trace.get("coordination_flow") or {}),
                    "task_graph_scheduler_state": dict(runtime_trace.get("task_graph_scheduler_state") or {}),
                },
            }
        ]
    trace = {
        "task_run": {"task_run_id": _task_run_id_from_events(events)},
        "events": events,
        "latest_checkpoint": dict(payload.get("latest_checkpoint") or payload.get("checkpoint") or {}),
        "coordination_runs": coordination_runs,
    }
    return build_runtime_trace_evidence_packet(trace, question=question)


def runtime_loop_evidence_packet_from_turn_artifact(path: str | Path, *, question: str) -> dict[str, Any]:
    payload = read_json_file(Path(path), {})
    if not isinstance(payload, dict):
        return build_runtime_trace_evidence_packet(None, question=question)
    return build_turn_artifact_evidence_packet(path, question=question)


def runtime_loop_events_by_type(payload: dict[str, Any], event_type: str) -> list[dict[str, Any]]:
    return [
        item
        for item in runtime_events_from_turn_payload(payload)
        if str(item.get("event_type") or "") == event_type
    ]


def runtime_loop_tool_names(payload: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in runtime_events_by_type(payload, "tool_call_requested"):
        summary = dict(item.get("payload_summary") or {})
        if summary.get("tool_name"):
            names.append(str(summary.get("tool_name")))
            continue
        action = dict(dict(item.get("payload") or {}).get("action_request") or {})
        action_payload = dict(action.get("payload") or {})
        tool_name = str(action_payload.get("tool_name") or "")
        if tool_name:
            names.append(tool_name)
    return names


def _task_run_id_from_events(events: list[dict[str, Any]]) -> str:
    for item in events:
        task_run_id = str(item.get("task_run_id") or "")
        if task_run_id:
            return task_run_id
    return ""
